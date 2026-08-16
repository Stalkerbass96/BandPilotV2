/**
 * Workbench page — repair pipeline execution, progress, result preview.
 *
 * Redesign:
 *  - Left/right split (left 320px params / right flex-1 results with alphaTab).
 *  - The 7×200ms setTimeout loop is replaced by a timer-driven
 *    currentStageIndex that increments every ~400ms (max 5) while the
 *    API call is in flight. When the API resolves, completed=true and
 *    currentStageIndex=6.
 *  - After a successful repair, a GP5 blob is fetched via
 *    exportsApi.exportAndDownload and fed to TabViewer as an ArrayBuffer.
 *  - Below 1024px the two panels stack vertically.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Slider,
  Stack,
  Typography,
} from "@mui/material";
import { motion } from "framer-motion";
import { projectsApi, tuningsApi, exportsApi } from "../api/client";
import CleanupSummary from "../components/CleanupSummary";
import RewriteSummary from "../components/RewriteSummary";
import SeparationSummary from "../components/SeparationSummary";
import PipelineProgress from "../components/PipelineProgress";
import ResultPreview from "../components/ResultPreview";
import TabViewer from "../components/TabViewer";
import { WorkbenchSkeleton } from "../components/Skeletons";
import type {
  CleanupInfo,
  ProjectDetail,
  RepairReport,
  RewriteInfo,
  SeparationInfo,
  TuningInfo,
} from "../api/types";
import { palette } from "../styles/tokens";

/** Total number of pipeline stages (matches PipelineProgress). */
const STAGE_COUNT = 7;

export default function WorkbenchPage(): JSX.Element {
  const navigate = useNavigate();
  const { id } = useParams();
  const projectId = id;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [projectLoading, setProjectLoading] = useState(true);
  const [fidelity, setFidelity] = useState(0.5);
  const [tunings, setTunings] = useState<TuningInfo[]>([]);
  const [tuningId, setTuningId] = useState<string>("");
  const [isRunning, setIsRunning] = useState(false);
  const [currentStageIndex, setCurrentStageIndex] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [repairResult, setRepairResult] = useState<{
    noteCount: number;
    changeCount: number;
    cleanup: CleanupInfo | null;
    rewrite: RewriteInfo | null;
    separation: SeparationInfo | null;
  } | null>(null);
  const [report, setReport] = useState<RepairReport | null>(null);
  const [scoreData, setScoreData] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState("");

  const stageTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (projectId) {
      void loadProject(Number(projectId));
    }
  }, [projectId]);

  useEffect(() => {
    tuningsApi
      .list()
      .then(setTunings)
      .catch(() => setTunings([]));
  }, []);

  // Clean up the stage timer on unmount.
  useEffect(() => {
    return () => {
      if (stageTimerRef.current) {
        clearInterval(stageTimerRef.current);
      }
    };
  }, []);

  const loadProject = async (pid: number): Promise<void> => {
    setProjectLoading(true);
    try {
      const detail = await projectsApi.get(pid);
      setProject(detail);
    } catch {
      setError("Failed to load project. It may not exist.");
    } finally {
      setProjectLoading(false);
    }
  };

  /**
   * Start a timer that increments currentStageIndex every ~400ms up to
   * STAGE_COUNT - 2 (index 5). Stage 6 is reserved for the "complete"
   * state set when the API resolves.
   */
  const startStageTimer = (): void => {
    setCurrentStageIndex(0);
    if (stageTimerRef.current) {
      clearInterval(stageTimerRef.current);
    }
    stageTimerRef.current = setInterval(() => {
      setCurrentStageIndex((prev) => {
        if (prev >= STAGE_COUNT - 2) {
          return prev; // hold at 5 until API completes
        }
        return prev + 1;
      });
    }, 400);
  };

  const stopStageTimer = (): void => {
    if (stageTimerRef.current) {
      clearInterval(stageTimerRef.current);
      stageTimerRef.current = null;
    }
  };

  const handleRepair = async (): Promise<void> => {
    if (!project) return;
    setIsRunning(true);
    setCompleted(false);
    setError("");
    setRepairResult(null);
    setReport(null);
    setScoreData(null);

    startStageTimer();

    try {
      const result = await projectsApi.repair(
        project.id,
        fidelity,
        tuningId || null,
      );

      stopStageTimer();
      setCurrentStageIndex(STAGE_COUNT - 1); // index 6 = all done
      setCompleted(true);
      setIsRunning(false);
      setRepairResult({
        noteCount: result.note_count,
        changeCount: result.change_count,
        cleanup: result.cleanup ?? null,
        rewrite: result.rewrite ?? null,
        separation: result.separation ?? null,
      });

      // Fetch the detailed report.
      const repairReport = await projectsApi.report(project.id);
      setReport(repairReport);

      // Auto-fetch GP5 blob for alphaTab preview.
      try {
        const { blob } = await exportsApi.exportAndDownload(
          project.id,
          "gp5",
        );
        const arrayBuffer = await blob.arrayBuffer();
        setScoreData(arrayBuffer);
      } catch {
        // Preview is non-critical; the user can still export manually.
        // eslint-disable-next-line no-console
        console.warn("Failed to fetch GP5 preview blob.");
      }
    } catch (err: unknown) {
      stopStageTimer();
      setIsRunning(false);
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Repair failed. Please try again.";
      setError(detail);
    }
  };

  // ── Early returns ──

  if (!projectId) {
    return (
      <Alert severity="info" sx={{ borderRadius: 2 }}>
        No project selected. Go to the Import page to upload a MIDI file first.
      </Alert>
    );
  }

  if (projectLoading) {
    return <WorkbenchSkeleton />;
  }

  if (!project) {
    return (
      <Alert severity={error ? "error" : "info"} sx={{ borderRadius: 2 }}>
        {error || "Loading project..."}
      </Alert>
    );
  }

  return (
    <Box className="flex flex-col gap-6">
      {/* ── Header ── */}
      <Box>
        <Typography
          variant="h5"
          fontWeight={600}
          sx={{ color: palette.textPrimary, mb: 0.5 }}
        >
          Repair Workbench
        </Typography>
        <Typography variant="body2" sx={{ color: palette.textSecondary }}>
          Project: {project.title} ({project.source_filename})
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {/* ── Left / Right split ── */}
      <Box className="flex flex-col lg:flex-row gap-6">
        {/* Left panel — settings (320px on desktop) */}
        <Box
          className="w-full lg:w-80 flex-shrink-0 rounded-xl p-5"
          sx={{
            backgroundColor: palette.elevated,
            border: `1px solid ${palette.borderDefault}`,
          }}
        >
          <Stack spacing={2.5}>
            <Typography
              variant="subtitle1"
              fontWeight={600}
              sx={{ color: palette.textPrimary }}
            >
              Repair Settings
            </Typography>
            <Box>
              <Typography
                variant="body2"
                gutterBottom
                sx={{ color: palette.textPrimary }}
              >
                MIDI Fidelity: {fidelity.toFixed(2)}
              </Typography>
              <Slider
                value={fidelity}
                onChange={(_, value) => setFidelity(value as number)}
                min={0}
                max={1}
                step={0.05}
                marks={[
                  { value: 0, label: "Aggressive" },
                  { value: 0.5, label: "Balanced" },
                  { value: 1, label: "Preserve" },
                ]}
                sx={{
                  color: palette.brandPrimary,
                  "& .MuiSlider-thumb": {
                    backgroundColor: palette.brandPrimary,
                  },
                }}
              />
              <Typography
                variant="caption"
                sx={{ color: palette.textSecondary }}
              >
                Higher fidelity = less quantization, fewer LLM rewrites. Lower
                fidelity = more aggressive cleanup.
              </Typography>
            </Box>
            <FormControl fullWidth>
              <InputLabel id="tuning-select-label">Tuning</InputLabel>
              <Select
                labelId="tuning-select-label"
                id="tuning-select"
                value={tuningId}
                label="Tuning"
                onChange={(e) => setTuningId(e.target.value as string)}
              >
                <MenuItem value="">Auto-detect</MenuItem>
                {tunings.map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.display_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              size="large"
              onClick={handleRepair}
              disabled={isRunning}
              sx={{
                textTransform: "none",
                backgroundColor: palette.brandPrimary,
                "&:hover": { backgroundColor: palette.brandHover },
              }}
            >
              {isRunning ? "Repairing..." : "Run Repair Pipeline"}
            </Button>
          </Stack>
        </Box>

        {/* Right panel — results (flex-1) */}
        <Box className="flex-1 flex flex-col gap-4 min-w-0">
          <PipelineProgress
            active={isRunning}
            completed={completed}
            currentStageIndex={currentStageIndex}
          />

          {repairResult?.cleanup && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
            >
              <CleanupSummary cleanup={repairResult.cleanup} />
            </motion.div>
          )}

          {repairResult?.rewrite && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: 0.08 }}
            >
              <RewriteSummary rewrite={repairResult.rewrite} />
            </motion.div>
          )}

          {repairResult?.separation && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: 0.12 }}
            >
              <SeparationSummary separation={repairResult.separation} />
            </motion.div>
          )}

          {repairResult && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: 0.16 }}
            >
              <Box
                className="rounded-xl p-5"
                sx={{
                  backgroundColor: palette.elevated,
                  border: `1px solid ${palette.borderDefault}`,
                }}
              >
                <Typography
                  variant="h6"
                  fontWeight={600}
                  sx={{ color: palette.textPrimary, mb: 2 }}
                >
                  Repair Complete
                </Typography>
                <ResultPreview report={report} />
              </Box>
            </motion.div>
          )}

          {/* alphaTab score preview */}
          {completed && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: 0.24 }}
            >
              <Box
                className="rounded-xl p-5"
                sx={{
                  backgroundColor: palette.elevated,
                  border: `1px solid ${palette.borderDefault}`,
                }}
              >
                <Typography
                  variant="h6"
                  fontWeight={600}
                  sx={{ color: palette.textPrimary, mb: 3 }}
                >
                  Score Preview
                </Typography>
                <TabViewer scoreData={scoreData} />
              </Box>
            </motion.div>
          )}

          {repairResult && (
            <Box>
              <Button
                variant="outlined"
                onClick={() => navigate(`/projects/${project.id}/export`)}
                sx={{
                  textTransform: "none",
                  borderColor: palette.brandPrimary,
                  color: palette.brandPrimary,
                  "&:hover": {
                    backgroundColor: "rgba(99, 102, 241, 0.04)",
                    borderColor: palette.brandHover,
                  },
                }}
              >
                Go to Export →
              </Button>
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}
