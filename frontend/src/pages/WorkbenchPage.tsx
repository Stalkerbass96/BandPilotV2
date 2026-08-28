/**
 * WorkbenchPage — 专业修复工作台（三栏布局）.
 *
 * 左面板：项目信息 + 修复配置（fidelity 语义化 + tuning + 状态）
 * 中间区：Pipeline 进度 + alphaTab 谱面 + 声部分离可视化
 * 右面板：结果摘要 + 变更表格
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Slider,
  Stack,
  Typography,
  IconButton,
  Divider,
} from "@mui/material";
import { BoltIcon, ChevronLeftIcon, ChevronRightIcon } from "../icons";
import { motion } from "framer-motion";
import { projectsApi, tuningsApi, exportsApi, byokApi, tracksApi } from "../api/client";
import CleanupSummary from "../components/CleanupSummary";
import RewriteSummary from "../components/RewriteSummary";
import SeparationSummary from "../components/SeparationSummary";
import PipelineProgress from "../components/PipelineProgress";
import DrumPipelineProgress from "../components/DrumPipelineProgress";
import DrumVisualizer from "../components/DrumVisualizer";
import PatternTimeline from "../components/PatternTimeline";
import ResultPreview from "../components/ResultPreview";
import TabViewer from "../components/TabViewer";
import JourneyStepper from "../components/JourneyStepper";
import { WorkbenchSkeleton } from "../components/Skeletons";
import type {
  CleanupInfo,
  ArrangementMode,
  ProjectDetail,
  RepairResponse,
  RepairReport,
  RewriteInfo,
  SeparationInfo,
  TrackRepairInfo,
  TrackSummaryItem,
  TuningInfo,
  ValidationIssue,
} from "../api/types";
import { palette, streamColors } from "../styles/tokens";
import { apiErrorMessage } from "../utils/apiError";
import { canExportProject } from "../utils/projectStatus";

const STAGE_COUNT = 8;

/** Semantic label for fidelity slider value. */
function fidelityLabel(v: number): { title: string; desc: string } {
  if (v < 0.25) return { title: "Flexible", desc: "More cleanup and stronger rhythm correction." };
  if (v < 0.5) return { title: "Balanced", desc: "A practical balance between cleanup and source detail." };
  if (v < 0.75) return { title: "Source-first", desc: "Keeps the MIDI detail and makes only careful corrections." };
  return { title: "Minimal", desc: "Only fixes notes that are out of range or overlap." };
}

function familyIcon(family: string): string {
  if (family === "guitar") return "🎸";
  if (family === "drums") return "🥁";
  if (family === "bass") return "🎵";
  if (family === "keys") return "🎹";
  return "🎼";
}

export default function WorkbenchPage(): JSX.Element {
  const navigate = useNavigate();
  const { id } = useParams();
  const projectId = id;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [projectLoading, setProjectLoading] = useState(true);
  const [fidelity, setFidelity] = useState(0.5);
  const [arrangementMode, setArrangementMode] = useState<ArrangementMode>("playable_arrangement");
  const [tunings, setTunings] = useState<TuningInfo[]>([]);
  const [tuningId, setTuningId] = useState<string>("");
  const [byokActive, setByokActive] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [drumStageIndex, setDrumStageIndex] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [tracks, setTracks] = useState<TrackSummaryItem[]>([]);
  const [repairResult, setRepairResult] = useState<{
    status: string;
    noteCount: number;
    changeCount: number;
    cleanup: CleanupInfo | null;
    rewrite: RewriteInfo | null;
    separation: SeparationInfo | null;
    tracksRepaired: TrackRepairInfo[] | null;
    hasDrums: boolean;
    arrangementMode: ArrangementMode;
    validationStatus: string;
    validationIssues: ValidationIssue[];
  } | null>(null);
  const [report, setReport] = useState<RepairReport | null>(null);
  const [scoreData, setScoreData] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [rightPanelOpen, setRightPanelOpen] = useState(false);

  const stageTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollGenerationRef = useRef(0);

  useEffect(() => {
    if (projectId) void loadProject(Number(projectId));
  }, [projectId]);

  useEffect(() => {
    tuningsApi.list().then(setTunings).catch(() => setTunings([]));
    byokApi.get().then((c) => setByokActive(!!c)).catch(() => setByokActive(false));
  }, []);

  useEffect(() => {
    return () => {
      pollGenerationRef.current += 1;
      if (stageTimerRef.current) clearInterval(stageTimerRef.current);
    };
  }, []);

  const loadProject = async (pid: number): Promise<void> => {
    setProjectLoading(true);
    try {
      const proj = await projectsApi.get(pid);
      setProject(proj);
      // Fetch detected tracks for multi-instrument support
      let detectedTracks = proj.tracks ?? [];
      try {
        const trackData = await tracksApi.list(pid);
        detectedTracks = trackData.tracks;
      } catch {
        // Project detail is the durable fallback when live classification fails.
      }
      setTracks(detectedTracks);

      if (canExportProject(proj.status)) {
        try {
          const persistedReport = await projectsApi.report(pid);
          setReport(persistedReport);
          setCompleted(true);
          setRepairResult({
            status: proj.status,
            noteCount: persistedReport.summary.note_count,
            changeCount: persistedReport.summary.total_changes,
            cleanup: null,
            rewrite: null,
            separation: null,
            tracksRepaired: null,
            hasDrums: detectedTracks.some((track) => track.family === "drums" || track.is_drum),
            arrangementMode: persistedReport.summary.arrangement_mode ?? "faithful",
            validationStatus: persistedReport.summary.validation_status ?? "not_validated",
            validationIssues: persistedReport.summary.validation_issues ?? [],
          });
          const preview = await exportsApi.downloadLatest(pid, "gp5");
          if (preview) setScoreData(await preview.blob.arrayBuffer());
        } catch (err: unknown) {
          setPreviewError(apiErrorMessage(err, "Saved repair results could not be restored."));
        }
      } else if (proj.status === "processing") {
        try {
          const jobs = await projectsApi.repairJobs(pid);
          const activeJob = jobs.items.find((job) => job.status === "processing");
          if (activeJob) {
            setIsRunning(true);
            startStageTimer();
            void resumeRepair(pid, activeJob.id);
          }
        } catch (err: unknown) {
          setError(apiErrorMessage(err, "Could not restore the active repair job."));
        }
      }
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Failed to load project."));
    } finally {
      setProjectLoading(false);
    }
  };

  const startStageTimer = (): void => {
    setCurrentStageIndex(0);
    setDrumStageIndex(0);
    if (stageTimerRef.current) clearInterval(stageTimerRef.current);
    stageTimerRef.current = setInterval(() => {
      setCurrentStageIndex((prev) => prev >= STAGE_COUNT - 2 ? prev : prev + 1);
      setDrumStageIndex((prev) => prev >= STAGE_COUNT - 2 ? prev : prev + 1);
    }, 400);
  };

  const stopStageTimer = (): void => {
    if (stageTimerRef.current) { clearInterval(stageTimerRef.current); stageTimerRef.current = null; }
  };

  const waitForRepair = async (pid: number, jobId: number): Promise<RepairResponse> => {
    const generation = ++pollGenerationRef.current;
    let transientFailures = 0;
    while (generation === pollGenerationRef.current) {
      try {
        const job = await projectsApi.repairJob(pid, jobId);
        transientFailures = 0;
        if (job.status !== "processing") {
          if (job.result) return job.result;
          throw new Error(job.error_message || `Repair finished with status ${job.status}.`);
        }
      } catch (err: unknown) {
        transientFailures += 1;
        if (transientFailures >= 3) throw err;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
    throw new Error("Repair polling stopped because the page changed.");
  };

  const finishRepair = async (result: RepairResponse, pid: number): Promise<void> => {
    stopStageTimer();
    setCurrentStageIndex(STAGE_COUNT - 1);
    setDrumStageIndex(STAGE_COUNT - 1);
    setCompleted(true);
    setIsRunning(false);
    setRepairResult({
      status: result.status,
      noteCount: result.note_count,
      changeCount: result.change_count,
      cleanup: result.cleanup ?? null,
      rewrite: result.rewrite ?? null,
      separation: result.separation ?? null,
      tracksRepaired: result.tracks_repaired ?? null,
      hasDrums: result.has_drums ?? false,
      arrangementMode: result.arrangement_mode,
      validationStatus: result.validation_status,
      validationIssues: result.validation_issues ?? [],
    });
    setProject((current) => current ? {
      ...current,
      status: result.status,
      style_label: result.style_label,
      degraded_mode: result.degraded_mode,
    } : current);
    setReport(await projectsApi.report(pid));
    try {
      const { blob } = await exportsApi.exportAndDownload(pid, "gp5");
      setScoreData(await blob.arrayBuffer());
    } catch (err: unknown) {
      setPreviewError(apiErrorMessage(
        err,
        "Repair succeeded, but the GP5 preview could not be generated.",
      ));
    }
  };

  const resumeRepair = async (pid: number, jobId: number): Promise<void> => {
    try {
      await finishRepair(await waitForRepair(pid, jobId), pid);
    } catch (err: unknown) {
      stopStageTimer();
      setIsRunning(false);
      setError(apiErrorMessage(err, "Repair failed."));
      void loadProject(pid);
    }
  };

  const handleRepair = async (): Promise<void> => {
    if (!project) return;
    setIsRunning(true); setCompleted(false); setError("");
    setRepairResult(null); setReport(null); setScoreData(null); setPreviewError("");
    startStageTimer();
    try {
      const accepted = await projectsApi.startRepair(
        project.id,
        fidelity,
        tuningId || null,
        arrangementMode,
      );
      setProject((current) => current ? { ...current, status: "processing" } : current);
      await finishRepair(
        await waitForRepair(project.id, accepted.job.id),
        project.id,
      );
    } catch (err: unknown) {
      stopStageTimer(); setIsRunning(false);
      setError(apiErrorMessage(err, "Repair failed."));
    }
  };

  const handleFamilyOverride = async (trackIndex: number, family: string): Promise<void> => {
    if (!project) return;
    try {
      const updated = await tracksApi.overrideFamily(project.id, trackIndex, family);
      setTracks((current) => current.map((track) => (
        track.index === trackIndex ? updated : track
      )));
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Failed to save the track family correction."));
    }
  };

  if (!projectId) return <Alert severity="info" sx={{ borderRadius: 2 }}>No project selected. Import a MIDI file first.</Alert>;
  if (projectLoading) return <WorkbenchSkeleton />;
  if (!project) return <Alert severity={error ? "error" : "info"} sx={{ borderRadius: 2 }}>{error || "Loading..."}</Alert>;

  const fl = fidelityLabel(fidelity);
  const hasGuitar = tracks.some((track) => track.family === "guitar" || track.is_guitar);
  const hasDrums = tracks.some((track) => track.family === "drums" || track.is_drum);

  return (
    <Box className="flex flex-col gap-5">
      <JourneyStepper activeStep={1} />
      <Box className="flex items-end justify-between gap-4 flex-wrap mt-2">
        <Box>
          <Typography className="bp-eyebrow">Prepare your score</Typography>
          <Typography variant="h4" fontWeight={800} sx={{ color: palette.textPrimary, letterSpacing: "-.035em", mt: 1 }}>
            {project.title}
          </Typography>
          <Box className="flex items-center gap-2 mt-1 flex-wrap">
            <Chip
              size="small"
              label={project.source_filename}
              sx={{ backgroundColor: palette.subtle, color: palette.textSecondary, border: "none" }}
            />
            {project.style_label !== "unknown" && <Typography sx={{ color: palette.textTertiary, fontSize: 12 }}>Detected style: {project.style_label}</Typography>}
          </Box>
        </Box>
        {canExportProject(project.status) && <Button
          variant="outlined"
          onClick={() => navigate(`/projects/${project.id}/export`)}
          sx={{ borderColor: palette.borderHover, color: palette.textPrimary }}
        >
          Export score
        </Button>}
      </Box>

      {error && <Alert severity="error" sx={{ borderRadius: 2 }}>{error}</Alert>}
      {isRunning && (
        <Alert severity="info" sx={{ borderRadius: 2 }}>
          We’re building your score in the background. You can safely leave this page and come back later.
        </Alert>
      )}
      {previewError && (
        <Alert severity="warning" sx={{ borderRadius: 2 }} onClose={() => setPreviewError("")}>
          {previewError}
        </Alert>
      )}
      {repairResult?.status === "partial" && (
        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          Repair completed partially. Supported tracks were repaired; skipped or failed tracks are listed in the results.
        </Alert>
      )}
      {repairResult && repairResult.validationStatus !== "passed" && (
        <Alert
          severity={repairResult.validationIssues.some((issue) => issue.severity === "error") ? "error" : "warning"}
          sx={{ borderRadius: 2 }}
        >
          This draft needs a little attention before performance.
          {repairResult.validationIssues.slice(0, 3).map((issue) => ` ${issue.message}`).join("")}
          {repairResult.validationIssues.length > 3
            ? ` (+${repairResult.validationIssues.length - 3} more)`
            : ""}
        </Alert>
      )}

      {/* Three-panel layout */}
      <Box
        className="flex gap-5"
        sx={{ flexDirection: { xs: "column", xl: "row" } }}
      >
        {/* Keep the default decision path together in one clear panel. */}
        <Box
          className="flex-shrink-0 rounded-xl p-5 flex flex-col gap-5"
          sx={{ width: { xs: "100%", xl: 280 }, backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}` }}
        >
          {/* Project info — track list with instrument family icons */}
          {tracks.length > 0 && (
            <Box>
              <Typography variant="caption" fontWeight={600} sx={{ color: palette.textTertiary, textTransform: "uppercase", letterSpacing: 0.5 }}>
                1 · Check the instruments
              </Typography>
              <Box className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-7 gap-y-2" sx={{ mt: 1.5 }}>
                {tracks.map((t) => (
                  <Box key={t.index} className="flex items-center justify-between">
                    <Box className="flex items-center gap-1.5">
                      <Typography sx={{ fontSize: 14, lineHeight: 1 }}>
                        {familyIcon(t.family)}
                      </Typography>
                      <Typography variant="body2" sx={{ color: palette.textPrimary, fontSize: 13 }}>
                        {t.name}
                      </Typography>
                      {t.kit_type && (
                        <Chip size="small" label={t.kit_type} sx={{ height: 16, fontSize: 9, backgroundColor: palette.subtle, color: palette.textTertiary, border: "none" }} />
                      )}
                    </Box>
                    <Select
                      size="small"
                      value={t.family}
                      onChange={(event) => void handleFamilyOverride(t.index, event.target.value)}
                      aria-label={`Instrument family for ${t.name}`}
                      sx={{ height: 24, fontSize: 11, minWidth: 82 }}
                    >
                      <MenuItem value="guitar">Guitar</MenuItem>
                      <MenuItem value="drums">Drums</MenuItem>
                      <MenuItem value="bass">Bass</MenuItem>
                      <MenuItem value="keys">Keys</MenuItem>
                      <MenuItem value="unknown">Other</MenuItem>
                    </Select>
                  </Box>
                ))}
              </Box>
            </Box>
          )}

          <Divider sx={{ borderColor: palette.borderDefault }} />

          {/* Repair config */}
          <Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ color: palette.textPrimary, mb: 2 }}>
              2 · Choose the result
            </Typography>

            <Box component="details" sx={{ mb: 2.5, border: `1px solid ${palette.borderDefault}`, borderRadius: 2.5, p: 1.5, "&[open]": { background: palette.surface } }}>
              <Box component="summary" sx={{ color: palette.textSecondary, fontSize: 12, fontWeight: 700, cursor: "pointer", listStylePosition: "inside" }}>Advanced settings</Box>
            <Box sx={{ mt: 2.5, mb: 3 }}>
              <Box className="flex items-center justify-between mb-1">
                <Typography variant="body2" sx={{ color: palette.textSecondary, fontSize: 13 }}>How much can BandPilot adjust?</Typography>
                <Chip size="small" label={fl.title} sx={{ backgroundColor: `${palette.brandPrimary}15`, color: palette.brandPrimary, fontWeight: 600, border: "none", fontSize: 11 }} />
              </Box>
              <Slider
                value={fidelity}
                onChange={(_, v) => setFidelity(v as number)}
                min={0} max={1} step={0.05}
                sx={{ color: palette.brandPrimary, "& .MuiSlider-thumb": { backgroundColor: palette.brandPrimary } }}
              />
              <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11, display: "block", mt: 0.5 }}>
                {fl.desc}
              </Typography>
            </Box>

            {/* Guitar tuning is not a global song setting. */}
            {hasGuitar ? (
              <FormControl fullWidth size="small" sx={{ mb: 2.5 }}>
              <InputLabel sx={{ color: palette.textSecondary, fontSize: 13 }}>Guitar tuning</InputLabel>
              <Select
                value={tuningId}
                label="Tuning"
                onChange={(e) => setTuningId(e.target.value as string)}
                sx={{ fontSize: 13 }}
              >
                <MenuItem value="">
                  <Box className="flex items-center gap-2">
                    <BoltIcon sx={{ fontSize: 14, color: palette.brandPrimary }} />
                    <span>Let BandPilot choose</span>
                  </Box>
                </MenuItem>
                {tunings.map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    <Box className="flex items-center justify-between w-full">
                      <span>{t.display_name}</span>
                      <Chip size="small" label={`${t.string_count}str`} sx={{ ml: 1, backgroundColor: palette.subtle, color: palette.textTertiary, border: "none", fontSize: 10 }} />
                    </Box>
                  </MenuItem>
                ))}
              </Select>
              </FormControl>
            ) : (
              <Alert severity="info" sx={{ mb: 2.5, borderRadius: 2, fontSize: 12 }}>
                No guitar part was found, so tuning is not needed.
              </Alert>
            )}
            </Box>

            <FormControl fullWidth size="small" sx={{ mb: 2.5 }}>
              <InputLabel sx={{ color: palette.textSecondary, fontSize: 13 }}>Playing goal</InputLabel>
              <Select
                value={arrangementMode}
                label="Playing goal"
                onChange={(event) => setArrangementMode(event.target.value as ArrangementMode)}
                sx={{ fontSize: 13 }}
              >
                <MenuItem value="faithful">Stay close to the original</MenuItem>
                <MenuItem value="playable_arrangement">Make it natural to play</MenuItem>
                <MenuItem value="creative_rewrite">Create a new arrangement</MenuItem>
              </Select>
            </FormControl>
            <Typography variant="caption" sx={{ color: palette.textTertiary, display: "block", mt: -1.5, mb: 2.5, fontSize: 11 }}>
              {arrangementMode === "faithful"
                ? "Keeps the original notes and musical intent with only essential cleanup."
                : arrangementMode === "playable_arrangement"
                  ? "Prioritizes comfortable positions, string choices and natural performance. Recommended for most players."
                  : "Allows broader musical changes while keeping every edit reviewable."}
            </Typography>
            {!byokActive && arrangementMode !== "faithful" && (
              <Alert severity="warning" sx={{ mb: 2.5, borderRadius: 2, fontSize: 12 }}>
                AI enhancement is not connected. BandPilot will still use its built-in playability rules.
              </Alert>
            )}

            {/* Run button */}
            <Button
              variant="contained"
              fullWidth
              size="large"
              onClick={handleRepair}
              disabled={isRunning}
              sx={{
                textTransform: "none", fontWeight: 600,
                backgroundColor: palette.brandPrimary, color: "#1A1208",
                "&:hover": { backgroundColor: palette.brandHover },
                "&.Mui-disabled": { backgroundColor: palette.subtle, color: palette.textTertiary },
              }}
            >
              {isRunning ? "Creating your score…" : completed ? "Create again" : "Create playable score"}
            </Button>
          </Box>
        </Box>

        {/* ── Center: Progress + Score ── */}
        <Box className="flex-1 flex flex-col gap-4 min-w-0">
          {hasGuitar && (isRunning || completed) && (
            <PipelineProgress active={isRunning} completed={completed} currentStageIndex={currentStageIndex} />
          )}

          {/* Drum pipeline progress — shown when drum tracks are detected */}
          {(repairResult?.hasDrums || hasDrums) && (isRunning || completed) && (
            <DrumPipelineProgress active={isRunning} completed={completed} currentStageIndex={drumStageIndex} />
          )}

          {!hasGuitar && !hasDrums && (
            <Alert severity={completed ? "success" : "info"} sx={{ borderRadius: 2 }}>
              {isRunning
                ? "BandPilot is routing the detected bass, keys, and other tracks through their dedicated engines."
                : completed
                  ? "Dedicated instrument repair completed and the validated SongIR is ready."
                  : "Ready to route each detected track through its dedicated instrument engine."}
            </Alert>
          )}

          {completed && scoreData && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
              <Box
                className="rounded-xl p-5"
                sx={{ backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}` }}
              >
                <Box className="flex items-center justify-between gap-3 mb-3 flex-wrap">
                  <Box className="flex items-center gap-2 flex-wrap">
                    <Typography variant="subtitle1" fontWeight={700} sx={{ color: palette.textPrimary }}>
                      Your playable score
                    </Typography>
                  {repairResult?.separation?.detected && (
                    <Chip size="small" label="Lead + Rhythm" sx={{ backgroundColor: `${streamColors.lead}18`, color: streamColors.lead, fontWeight: 600, border: "none" }} />
                  )}
                  {repairResult?.hasDrums && (
                    <Chip size="small" label="Band score" sx={{ backgroundColor: `${palette.brandPrimary}18`, color: palette.brandPrimary, fontWeight: 600, border: "none" }} />
                  )}
                  <Chip
                    size="small"
                    label={`Validation: ${repairResult?.validationStatus ?? "unknown"}`}
                    sx={{
                      backgroundColor: repairResult?.validationStatus === "passed" ? `${palette.success}18` : `${palette.warning}18`,
                      color: repairResult?.validationStatus === "passed" ? palette.success : palette.warning,
                      fontWeight: 600,
                      border: "none",
                    }}
                  />
                  </Box>
                  <Button variant="contained" onClick={() => navigate(`/projects/${project.id}/editor`)}>
                    Open score editor
                  </Button>
                </Box>
                <TabViewer scoreData={scoreData} />
              </Box>
            </motion.div>
          )}

          {/* Drum visualizations — shown when drum repair results are available */}
          {completed && repairResult?.hasDrums && repairResult.tracksRepaired && (() => {
            const drumTrack = repairResult.tracksRepaired.find((t) => t.drum_report);
            if (!drumTrack?.drum_report) return null;
            const drumReport = drumTrack.drum_report;

            const pieceData = drumReport.piece_stats ?? [];

            // Build pattern timeline data from drum_report.patterns
            const patternData = drumReport.patterns.map((type, i) => ({
              measure: i + 1,
              type,
              duration: 1,
            }));

            return (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, delay: 0.1 }}>
                <Box className="flex flex-col gap-4">
                  {pieceData.length > 0 && <DrumVisualizer pieces={pieceData} />}
                  <PatternTimeline patterns={patternData} totalMeasures={Math.max(drumReport.patterns.length, 8)} />
                </Box>
              </motion.div>
            );
          })()}

          {repairResult?.separation && repairResult.separation.detected && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, delay: 0.08 }}>
              <SeparationSummary separation={repairResult.separation} />
            </motion.div>
          )}
        </Box>

        {/* ── Right panel: Results ── */}
        {rightPanelOpen && repairResult && (
          <Box
            className="flex-shrink-0 rounded-xl p-5 flex flex-col gap-4"
            sx={{ width: { xs: "100%", xl: 320 }, backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}`, maxHeight: { xs: "none", xl: "80vh" }, overflowY: "auto" }}
          >
            <Box className="flex items-center justify-between">
              <Typography variant="subtitle2" fontWeight={700} sx={{ color: palette.textPrimary }}>Results</Typography>
              <IconButton size="small" onClick={() => setRightPanelOpen(false)} sx={{ color: palette.textTertiary }}>
                <ChevronRightIcon fontSize="small" />
              </IconButton>
            </Box>

            {repairResult.cleanup && <CleanupSummary cleanup={repairResult.cleanup} />}
            {repairResult.rewrite && <RewriteSummary rewrite={repairResult.rewrite} />}

            {/* Per-track repair reports (BandPilot multi-instrument) */}
            {repairResult.tracksRepaired && repairResult.tracksRepaired.length > 0 && (
              <Box>
                <Typography variant="caption" fontWeight={600} sx={{ color: palette.textTertiary, textTransform: "uppercase", letterSpacing: 0.5, mb: 1, display: "block" }}>
                  Track Repairs
                </Typography>
                <Stack spacing={1.5}>
                  {repairResult.tracksRepaired.map((tr) => {
                    const trackInfo = tracks.find((t) => t.index === tr.track_index);
                    const family = tr.family || trackInfo?.family || "unknown";
                    return (
                      <Box
                        key={tr.track_index}
                        className="rounded-lg p-3"
                        sx={{ backgroundColor: palette.subtle, border: `1px solid ${palette.borderDefault}` }}
                      >
                        <Box className="flex items-center gap-2 mb-1.5">
                          <Typography sx={{ fontSize: 14 }}>{familyIcon(family)}</Typography>
                          <Typography variant="body2" fontWeight={600} sx={{ color: palette.textPrimary, fontSize: 13 }}>
                            {trackInfo?.name ?? `Track ${tr.track_index}`}
                          </Typography>
                          <Chip
                            size="small"
                            label={tr.module}
                            sx={{ height: 16, fontSize: 9, backgroundColor: `${palette.brandPrimary}18`, color: palette.brandPrimary, border: "none", fontWeight: 600 }}
                          />
                        </Box>
                        <Box className="flex items-center gap-3 flex-wrap">
                          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>
                            {tr.stages_completed} stages
                          </Typography>
                          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>
                            {tr.note_count} notes
                          </Typography>
                          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>
                            {tr.change_count} changes
                          </Typography>
                        </Box>
                        {(tr.failed || tr.skipped) && (
                          <Alert severity={tr.failed ? "error" : "warning"} sx={{ mt: 1, py: 0, fontSize: 11 }}>
                            {tr.error ?? (tr.skipped ? "Track was retained but skipped by notation repair." : "Track repair failed.")}
                          </Alert>
                        )}
                        {!tr.failed && tr.warnings?.length > 0 && (
                          <Typography variant="caption" sx={{ color: palette.warning, display: "block", mt: 1, fontSize: 10 }}>
                            {tr.warnings[0]}{tr.warnings.length > 1 ? ` (+${tr.warnings.length - 1} more)` : ""}
                          </Typography>
                        )}
                        {/* Drum-specific report summary */}
                        {tr.drum_report && (
                          <Box className="mt-2 flex flex-wrap gap-1">
                            <Chip size="small" label={tr.drum_report.kit_type} sx={{ height: 16, fontSize: 9, backgroundColor: palette.subtle, color: palette.textSecondary, border: "none" }} />
                            <Chip size="small" label={tr.drum_report.style_detected} sx={{ height: 16, fontSize: 9, backgroundColor: `${palette.brandPrimary}12`, color: palette.brandPrimary, border: "none", fontWeight: 600 }} />
                            {tr.drum_report.sticking_suggested && (
                              <Chip size="small" label="R/L sticking" sx={{ height: 16, fontSize: 9, backgroundColor: `${palette.leadColor}12`, color: palette.leadColor, border: "none" }} />
                            )}
                            {tr.drum_report.velocity_normalized && (
                              <Chip size="small" label="vel normalized" sx={{ height: 16, fontSize: 9, backgroundColor: `${palette.success}12`, color: palette.success, border: "none" }} />
                            )}
                          </Box>
                        )}
                      </Box>
                    );
                  })}
                </Stack>
              </Box>
            )}

            <Box>
              <Typography variant="caption" fontWeight={600} sx={{ color: palette.textTertiary, textTransform: "uppercase", letterSpacing: 0.5, mb: 1, display: "block" }}>
                Changes ({repairResult.changeCount})
              </Typography>
              <ResultPreview report={report} />
            </Box>
          </Box>
        )}

        {!rightPanelOpen && repairResult && (
          <IconButton
            onClick={() => setRightPanelOpen(true)}
            sx={{ alignSelf: "flex-start", color: palette.textSecondary, backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}`, borderRadius: 2 }}
          >
            <ChevronLeftIcon fontSize="small" />
            <Typography variant="caption" sx={{ ml: 0.5, color: palette.textSecondary }}>View technical details</Typography>
          </IconButton>
        )}
      </Box>
    </Box>
  );
}
