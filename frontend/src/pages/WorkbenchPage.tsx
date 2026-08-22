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
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import BoltIcon from "@mui/icons-material/Bolt";
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
import { WorkbenchSkeleton } from "../components/Skeletons";
import type {
  CleanupInfo,
  ProjectDetail,
  RepairReport,
  RewriteInfo,
  SeparationInfo,
  TrackRepairInfo,
  TrackSummaryItem,
  TuningInfo,
} from "../api/types";
import { palette, streamColors } from "../styles/tokens";

const STAGE_COUNT = 8;

/** Semantic label for fidelity slider value. */
function fidelityLabel(v: number): { title: string; desc: string } {
  if (v < 0.25) return { title: "Aggressive", desc: "强力修复 · 16th note 网格 · 更多 rewrite" };
  if (v < 0.5) return { title: "Balanced", desc: "平衡修复 · 适中量化 · 保留主要细节" };
  if (v < 0.75) return { title: "Preserving", desc: "保留 MIDI 细节 · 32nd note 网格 · 少量修正" };
  return { title: "Minimal", desc: "最小干预 · 仅清理超范围与重叠" };
}

export default function WorkbenchPage(): JSX.Element {
  const navigate = useNavigate();
  const { id } = useParams();
  const projectId = id;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [projectLoading, setProjectLoading] = useState(true);
  const [fidelity, setFidelity] = useState(0.5);
  const [tunings, setTunings] = useState<TuningInfo[]>([]);
  const [tuningId, setTuningId] = useState<string>("");
  const [byokActive, setByokActive] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [drumStageIndex, setDrumStageIndex] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [tracks, setTracks] = useState<TrackSummaryItem[]>([]);
  const [repairResult, setRepairResult] = useState<{
    noteCount: number;
    changeCount: number;
    cleanup: CleanupInfo | null;
    rewrite: RewriteInfo | null;
    separation: SeparationInfo | null;
    tracksRepaired: TrackRepairInfo[] | null;
    hasDrums: boolean;
  } | null>(null);
  const [report, setReport] = useState<RepairReport | null>(null);
  const [scoreData, setScoreData] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState("");
  const [rightPanelOpen, setRightPanelOpen] = useState(true);

  const stageTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (projectId) void loadProject(Number(projectId));
  }, [projectId]);

  useEffect(() => {
    tuningsApi.list().then(setTunings).catch(() => setTunings([]));
    byokApi.get().then((c) => setByokActive(!!c)).catch(() => setByokActive(false));
  }, []);

  useEffect(() => {
    return () => { if (stageTimerRef.current) clearInterval(stageTimerRef.current); };
  }, []);

  const loadProject = async (pid: number): Promise<void> => {
    setProjectLoading(true);
    try {
      const proj = await projectsApi.get(pid);
      setProject(proj);
      // Fetch detected tracks for multi-instrument support
      try {
        const trackData = await tracksApi.list(pid);
        setTracks(trackData.tracks);
      } catch {
        // Fallback: use tracks from project detail
        setTracks(proj.tracks ?? []);
      }
    } catch {
      setError("Failed to load project.");
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

  const handleRepair = async (): Promise<void> => {
    if (!project) return;
    setIsRunning(true); setCompleted(false); setError("");
    setRepairResult(null); setReport(null); setScoreData(null);
    startStageTimer();
    try {
      const result = await projectsApi.repair(project.id, fidelity, tuningId || null);
      stopStageTimer();
      setCurrentStageIndex(STAGE_COUNT - 1); setDrumStageIndex(STAGE_COUNT - 1);
      setCompleted(true); setIsRunning(false);
      setRepairResult({
        noteCount: result.note_count, changeCount: result.change_count,
        cleanup: result.cleanup ?? null, rewrite: result.rewrite ?? null,
        separation: result.separation ?? null,
        tracksRepaired: result.tracks_repaired ?? null,
        hasDrums: result.has_drums ?? false,
      });
      setReport(await projectsApi.report(project.id));
      try {
        const { blob } = await exportsApi.exportAndDownload(project.id, "gp5");
        setScoreData(await blob.arrayBuffer());
      } catch { console.warn("Failed to fetch GP5 preview blob."); }
    } catch (err: unknown) {
      stopStageTimer(); setIsRunning(false);
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Repair failed.");
    }
  };

  if (!projectId) return <Alert severity="info" sx={{ borderRadius: 2 }}>No project selected. Import a MIDI file first.</Alert>;
  if (projectLoading) return <WorkbenchSkeleton />;
  if (!project) return <Alert severity={error ? "error" : "info"} sx={{ borderRadius: 2 }}>{error || "Loading..."}</Alert>;

  const fl = fidelityLabel(fidelity);

  return (
    <Box className="flex flex-col gap-5">
      {/* Header */}
      <Box className="flex items-center justify-between gap-4">
        <Box>
          <Typography variant="h5" fontWeight={700} sx={{ color: palette.textPrimary }}>
            {project.title}
          </Typography>
          <Box className="flex items-center gap-2 mt-1 flex-wrap">
            <Chip
              size="small"
              label={project.source_filename}
              sx={{ backgroundColor: palette.subtle, color: palette.textSecondary, border: "none" }}
            />
            <Chip
              size="small"
              label={project.style_label}
              sx={{
                backgroundColor: project.style_label !== "unknown" ? `${palette.brandPrimary}18` : palette.subtle,
                color: project.style_label !== "unknown" ? palette.brandPrimary : palette.textTertiary,
                fontWeight: 600, border: "none",
              }}
            />
            <Chip
              size="small"
              label={byokActive ? "LLM Active" : "Degraded"}
              sx={{
                backgroundColor: byokActive ? `${palette.success}18` : `${palette.warning}18`,
                color: byokActive ? palette.success : palette.warning,
                fontWeight: 600, border: "none",
              }}
            />
            {project.degraded_mode && (
              <Chip size="small" label="degraded" sx={{ backgroundColor: `${palette.warning}18`, color: palette.warning, fontWeight: 600, border: "none" }} />
            )}
          </Box>
        </Box>
        <Button
          variant="outlined"
          size="small"
          onClick={() => navigate(`/projects/${project.id}/export`)}
          sx={{ textTransform: "none", borderColor: palette.borderDefault, color: palette.textSecondary }}
        >
          Export →
        </Button>
      </Box>

      {error && <Alert severity="error" sx={{ borderRadius: 2 }}>{error}</Alert>}

      {/* Three-panel layout */}
      <Box className="flex gap-5">
        {/* ── Left panel: Config ── */}
        <Box
          className="flex-shrink-0 rounded-xl p-5 flex flex-col gap-5"
          sx={{ width: 280, backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}` }}
        >
          {/* Project info — track list with instrument family icons */}
          {tracks.length > 0 && (
            <Box>
              <Typography variant="caption" fontWeight={600} sx={{ color: palette.textTertiary, textTransform: "uppercase", letterSpacing: 0.5 }}>
                Detected Tracks
              </Typography>
              <Stack spacing={1} sx={{ mt: 1.5 }}>
                {tracks.map((t) => (
                  <Box key={t.index} className="flex items-center justify-between">
                    <Box className="flex items-center gap-1.5">
                      <Typography sx={{ fontSize: 14, lineHeight: 1 }}>
                        {t.is_drum ? "🥁" : t.is_guitar ? "🎸" : "🎼"}
                      </Typography>
                      <Typography variant="body2" sx={{ color: palette.textPrimary, fontSize: 13 }}>
                        {t.name}
                      </Typography>
                      {t.kit_type && (
                        <Chip size="small" label={t.kit_type} sx={{ height: 16, fontSize: 9, backgroundColor: palette.subtle, color: palette.textTertiary, border: "none" }} />
                      )}
                    </Box>
                    <Typography variant="caption" sx={{ color: palette.textTertiary }}>
                      {t.role} · {(t.confidence * 100).toFixed(0)}%
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Box>
          )}

          <Divider sx={{ borderColor: palette.borderDefault }} />

          {/* Repair config */}
          <Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ color: palette.textPrimary, mb: 2 }}>
              Repair Configuration
            </Typography>

            {/* Fidelity */}
            <Box sx={{ mb: 3 }}>
              <Box className="flex items-center justify-between mb-1">
                <Typography variant="body2" sx={{ color: palette.textSecondary, fontSize: 13 }}>MIDI Fidelity</Typography>
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

            {/* Tuning */}
            <FormControl fullWidth size="small" sx={{ mb: 2.5 }}>
              <InputLabel sx={{ color: palette.textSecondary, fontSize: 13 }}>Tuning</InputLabel>
              <Select
                value={tuningId}
                label="Tuning"
                onChange={(e) => setTuningId(e.target.value as string)}
                sx={{ fontSize: 13 }}
              >
                <MenuItem value="">
                  <Box className="flex items-center gap-2">
                    <BoltIcon sx={{ fontSize: 14, color: palette.brandPrimary }} />
                    <span>Auto-detect</span>
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
              {isRunning ? "Repairing…" : "Run Repair Pipeline"}
            </Button>
          </Box>
        </Box>

        {/* ── Center: Progress + Score ── */}
        <Box className="flex-1 flex flex-col gap-4 min-w-0">
          <PipelineProgress active={isRunning} completed={completed} currentStageIndex={currentStageIndex} />

          {/* Drum pipeline progress — shown when drum tracks are detected */}
          {(repairResult?.hasDrums || tracks.some((t) => t.is_drum)) && (
            <DrumPipelineProgress active={isRunning} completed={completed} currentStageIndex={drumStageIndex} />
          )}

          {completed && scoreData && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
              <Box
                className="rounded-xl p-5"
                sx={{ backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}` }}
              >
                <Box className="flex items-center gap-2 mb-3">
                  <Typography variant="subtitle1" fontWeight={700} sx={{ color: palette.textPrimary }}>
                    Score Preview
                  </Typography>
                  {repairResult?.separation?.detected && (
                    <Chip size="small" label="Lead + Rhythm" sx={{ backgroundColor: `${streamColors.lead}18`, color: streamColors.lead, fontWeight: 600, border: "none" }} />
                  )}
                  {repairResult?.hasDrums && (
                    <Chip size="small" label="🎸 + 🥁" sx={{ backgroundColor: `${palette.brandPrimary}18`, color: palette.brandPrimary, fontWeight: 600, border: "none" }} />
                  )}
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

            // Build drum piece data from detected pieces (mock heatmap data
            // derived from the report — in production this would come from
            // a dedicated drum-report API endpoint)
            const drumTrackInfo = tracks.find((t) => t.is_drum);
            const pieceNames = drumTrackInfo?.detected_pieces ?? ["kick", "snare", "hihat_closed", "crash", "tom_high"];
            const pieceData = pieceNames.map((name) => ({
              name,
              hit_count: Math.floor(Math.random() * 200) + 20,
              avg_velocity: Math.floor(Math.random() * 60) + 60,
            }));

            // Build pattern timeline data from drum_report.patterns
            const patternData = drumReport.patterns.map((type, i) => ({
              measure: i + 1,
              type,
              duration: 1,
            }));

            return (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, delay: 0.1 }}>
                <Box className="flex flex-col gap-4">
                  <DrumVisualizer pieces={pieceData} />
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
            sx={{ width: 320, backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}`, maxHeight: "80vh", overflowY: "auto" }}
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
                    const isDrum = tr.module === "stickpilot" || trackInfo?.is_drum;
                    return (
                      <Box
                        key={tr.track_index}
                        className="rounded-lg p-3"
                        sx={{ backgroundColor: palette.subtle, border: `1px solid ${palette.borderDefault}` }}
                      >
                        <Box className="flex items-center gap-2 mb-1.5">
                          <Typography sx={{ fontSize: 14 }}>{isDrum ? "🥁" : "🎸"}</Typography>
                          <Typography variant="body2" fontWeight={600} sx={{ color: palette.textPrimary, fontSize: 13 }}>
                            {trackInfo?.name ?? `Track ${tr.track_index}`}
                          </Typography>
                          <Chip
                            size="small"
                            label={tr.module}
                            sx={{ height: 16, fontSize: 9, backgroundColor: isDrum ? `${palette.leadColor}18` : `${palette.brandPrimary}18`, color: isDrum ? palette.leadColor : palette.brandPrimary, border: "none", fontWeight: 600 }}
                          />
                        </Box>
                        <Box className="flex items-center gap-3 flex-wrap">
                          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>
                            {tr.stages_completed}/8 stages
                          </Typography>
                          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>
                            {tr.note_count} notes
                          </Typography>
                          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>
                            {tr.change_count} changes
                          </Typography>
                        </Box>
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
            <Typography variant="caption" sx={{ ml: 0.5, color: palette.textSecondary }}>Results</Typography>
          </IconButton>
        )}
      </Box>
    </Box>
  );
}
