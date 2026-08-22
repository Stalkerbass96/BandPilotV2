/**
 * DrumPipelineProgress — visual progress indicator for the 8-stage drum
 * (StickPilot) repair pipeline.
 *
 * Stages: Quantize → MeasureSplit → DrumMap → PatternDetect → Velocity →
 * Sticking → Notation → Assemble
 *
 * Same three-state visual model as PipelineProgress (done / active / pending)
 * but with drum-specific stage names and icons.
 */

import { Box, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import DrumMapIcon from "@mui/icons-material/Album";
import PatternIcon from "@mui/icons-material/GraphicEq";
import StickingIcon from "@mui/icons-material/SwapHoriz";
import { motion } from "framer-motion";
import { palette } from "../styles/tokens";

const DRUM_PIPELINE_STAGES = [
  { name: "quantize", label: "Quantize" },
  { name: "measure_split", label: "Measure Split" },
  { name: "drum_map", label: "Drum Map" },
  { name: "pattern_detect", label: "Pattern Detect" },
  { name: "velocity", label: "Velocity" },
  { name: "sticking", label: "Sticking" },
  { name: "notation", label: "Notation" },
  { name: "assemble", label: "Assemble IR" },
] as const;

/** Icon to show for a given drum stage (active/pending state). */
function stageIcon(name: string): JSX.Element | null {
  switch (name) {
    case "drum_map":
      return <DrumMapIcon sx={{ fontSize: 14, color: "inherit" }} />;
    case "pattern_detect":
      return <PatternIcon sx={{ fontSize: 14, color: "inherit" }} />;
    case "sticking":
      return <StickingIcon sx={{ fontSize: 14, color: "inherit" }} />;
    default:
      return null;
  }
}

interface DrumPipelineProgressProps {
  /** Whether the drum pipeline is currently running. */
  active: boolean;
  /** Whether the drum pipeline has completed (overrides active). */
  completed: boolean;
  /** Index (0-7) of the currently-active drum stage. */
  currentStageIndex: number;
}

export default function DrumPipelineProgress({
  active,
  completed,
  currentStageIndex,
}: DrumPipelineProgressProps): JSX.Element {
  return (
    <Box sx={{ width: "100%", py: 2 }}>
      <Typography
        variant="subtitle1"
        gutterBottom
        fontWeight={600}
        sx={{ color: palette.textPrimary }}
      >
        🥁 Drum Repair Pipeline
      </Typography>
      <Stack
        direction="row"
        spacing={1}
        sx={{ flexWrap: "wrap", gap: 1 }}
      >
        {DRUM_PIPELINE_STAGES.map((stage, idx) => {
          const isDone = completed || idx < currentStageIndex;
          const isActive = active && !completed && idx === currentStageIndex;
          const isPending = !isDone && !isActive;

          const bgColor = isDone
            ? palette.success
            : isActive
              ? palette.brandPrimary
              : "transparent";
          const fgColor = isDone
            ? "#0E1116"
            : isActive
              ? "#1A1208"
              : palette.textTertiary;
          const borderColor = isDone
            ? palette.success
            : isActive
              ? palette.brandPrimary
              : palette.borderDefault;

          const icon = stageIcon(stage.name);

          return (
            <motion.div
              key={stage.name}
              initial={{ opacity: 0.5, scale: 0.95 }}
              animate={{
                opacity: isPending ? 0.5 : 1,
                scale: isActive ? 1.05 : 1,
              }}
              transition={{ duration: 0.2 }}
            >
              <Box
                className="flex items-center gap-1 px-3 py-1.5 rounded-full"
                sx={{
                  backgroundColor: bgColor,
                  border: `1px solid ${borderColor}`,
                }}
              >
                {isDone ? (
                  <CheckCircleIcon sx={{ fontSize: 16, color: "#0E1116" }} />
                ) : icon ? (
                  <Box sx={{ display: "flex", color: fgColor }}>{icon}</Box>
                ) : (
                  <RadioButtonUncheckedIcon sx={{ fontSize: 16, color: fgColor }} />
                )}
                <Typography
                  variant="caption"
                  fontWeight={isDone || isActive ? 600 : 400}
                  sx={{ color: fgColor }}
                >
                  {stage.label}
                </Typography>
              </Box>
            </motion.div>
          );
        })}
      </Stack>
      {active && !completed && (
        <Typography
          variant="body2"
          sx={{ mt: 2, color: palette.brandPrimary, fontWeight: 500 }}
        >
          Running drum pipeline — stage {currentStageIndex + 1} /{" "}
          {DRUM_PIPELINE_STAGES.length}…
        </Typography>
      )}
      {completed && (
        <Typography
          variant="body2"
          sx={{ mt: 2, color: palette.success, fontWeight: 500 }}
        >
          Drum repair complete!
        </Typography>
      )}
    </Box>
  );
}
