/**
 * CleanupSummary — displays the cleanup-stage traceable summary.
 *
 * Redesign: info-card grid (icon + value + label) instead of a chip row.
 */

import { Box, Typography } from "@mui/material";
import {
  CheckCircleIcon,
  ContentCutIcon as CutIcon,
  MusicOffIcon as NoteOffIcon,
  RepeatIcon,
  SpeedIcon as VelocityIcon,
  TuneIcon,
} from "../icons";
import { motion } from "framer-motion";
import type { CleanupInfo } from "../api/types";
import { palette } from "../styles/tokens";

interface CleanupSummaryProps {
  cleanup: CleanupInfo;
}

interface InfoCard {
  icon: JSX.Element;
  value: string;
  label: string;
}

export default function CleanupSummary({
  cleanup,
}: CleanupSummaryProps): JSX.Element {
  const cards: InfoCard[] = [
    {
      icon: <TuneIcon sx={{ color: palette.brandPrimary }} />,
      value: cleanup.tuning_display_name,
      label: "Detected Tuning",
    },
    {
      icon: <RepeatIcon sx={{ color: palette.warning }} />,
      value: String(cleanup.tempo_dedup_count),
      label: "Tempo Dedup",
    },
    {
      icon: <NoteOffIcon sx={{ color: palette.error }} />,
      value: String(cleanup.out_of_range_count),
      label: "Out of Range",
    },
    {
      icon: <VelocityIcon sx={{ color: palette.info }} />,
      value: cleanup.velocity_remapped ? "Yes" : "No",
      label: "Velocity Remapped",
    },
    {
      icon: <CutIcon sx={{ color: palette.brandAccent }} />,
      value: String(cleanup.overlaps_truncated),
      label: "Overlaps Truncated",
    },
    {
      icon: <CheckCircleIcon sx={{ color: palette.success }} />,
      value: String(cleanup.total_actions),
      label: "Total Actions",
    },
  ];

  return (
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
        sx={{ color: palette.textPrimary, mb: 1 }}
      >
        Cleanup Summary
      </Typography>
      <Typography
        variant="body2"
        sx={{ color: palette.textSecondary, mb: 3 }}
      >
        Auto-detected tuning and the traceable cleanup actions applied before
        the repair pipeline.
      </Typography>
      <Box className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {cards.map((card, index) => (
          <motion.div
            key={card.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: index * 0.06 }}
          >
            <Box
              className="rounded-lg p-3 flex flex-col gap-2"
              sx={{ backgroundColor: palette.subtle }}
            >
              {card.icon}
              <Typography
                variant="body1"
                fontWeight={700}
                sx={{
                  color: palette.textPrimary,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {card.value}
              </Typography>
              <Typography
                variant="caption"
                sx={{ color: palette.textSecondary }}
              >
                {card.label}
              </Typography>
            </Box>
          </motion.div>
        ))}
      </Box>
    </Box>
  );
}
