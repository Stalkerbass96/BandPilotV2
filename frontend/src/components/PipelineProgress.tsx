/**
 * PipelineProgress — visual progress indicator for the 7-stage repair pipeline.
 *
 * Bug fix: the old `isDone` check used `idx < PIPELINE_STAGES.length` which is
 * always true (idx ranges 0-6, length is 7), causing every stage to appear
 * done as soon as the pipeline activated. The new logic uses a three-state
 * model driven by `currentStageIndex`:
 *   - done   : idx < currentStageIndex  (already passed this stage)
 *   - active : idx === currentStageIndex (currently running)
 *   - pending: idx > currentStageIndex  (not yet reached)
 */

import { Box, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import { motion } from "framer-motion";
import { palette } from "../styles/tokens";

const PIPELINE_STAGES = [
  { name: "quantize", label: "Quantize" },
  { name: "measure_split", label: "Measure Split" },
  { name: "tie", label: "Tie / Legato" },
  { name: "voice", label: "Voice" },
  { name: "fingering", label: "Fingering" },
  { name: "articulation", label: "Articulation" },
  { name: "assemble", label: "Assemble IR" },
] as const;

interface PipelineProgressProps {
  /** Whether the pipeline is currently running. */
  active: boolean;
  /** Whether the pipeline has completed (overrides active). */
  completed: boolean;
  /** Index (0-6) of the currently-active stage. */
  currentStageIndex: number;
}

export default function PipelineProgress({
  active,
  completed,
  currentStageIndex,
}: PipelineProgressProps): JSX.Element {
  return (
    <Box sx={{ width: "100%", py: 2 }}>
      <Typography
        variant="subtitle1"
        gutterBottom
        fontWeight={600}
        sx={{ color: palette.textPrimary }}
      >
        Repair Pipeline
      </Typography>
      <Stack
        direction="row"
        spacing={1}
        sx={{ flexWrap: "wrap", gap: 1 }}
      >
        {PIPELINE_STAGES.map((stage, idx) => {
          const isDone = completed || idx < currentStageIndex;
          const isActive = active && !completed && idx === currentStageIndex;
          const isPending = !isDone && !isActive;

          const bgColor = isDone
            ? palette.success
            : isActive
              ? palette.brandPrimary
              : "transparent";
          const fgColor = isDone || isActive ? "#FFFFFF" : palette.textTertiary;
          const borderColor = isDone
            ? palette.success
            : isActive
              ? palette.brandPrimary
              : palette.borderDefault;

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
                  <CheckCircleIcon
                    sx={{ fontSize: 16, color: "#FFFFFF" }}
                  />
                ) : (
                  <RadioButtonUncheckedIcon
                    sx={{ fontSize: 16, color: fgColor }}
                  />
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
          Running repair pipeline — stage {currentStageIndex + 1} /{" "}
          {PIPELINE_STAGES.length}…
        </Typography>
      )}
      {completed && (
        <Typography
          variant="body2"
          sx={{ mt: 2, color: palette.success, fontWeight: 500 }}
        >
          Repair complete!
        </Typography>
      )}
    </Box>
  );
}
