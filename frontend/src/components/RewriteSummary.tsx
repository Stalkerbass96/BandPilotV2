/**
 * RewriteSummary — displays the LLM shadow rewrite results.
 *
 * Redesign: info-card grid + status indicator.
 */

import { Box, Chip, Typography } from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import SwapVertIcon from "@mui/icons-material/SwapVert";
import SummarizeIcon from "@mui/icons-material/Summarize";
import BoltIcon from "@mui/icons-material/Bolt";
import { motion } from "framer-motion";
import type { RewriteInfo } from "../api/types";
import { palette } from "../styles/tokens";

interface RewriteSummaryProps {
  rewrite: RewriteInfo;
}

interface InfoCard {
  icon: JSX.Element;
  value: string;
  label: string;
}

export default function RewriteSummary({
  rewrite,
}: RewriteSummaryProps): JSX.Element {
  const cards: InfoCard[] = [
    {
      icon: <DeleteIcon sx={{ color: palette.error }} />,
      value: String(rewrite.deletions),
      label: "Deletions",
    },
    {
      icon: <SwapVertIcon sx={{ color: palette.warning }} />,
      value: String(rewrite.transpositions),
      label: "Transpositions",
    },
    {
      icon: <SummarizeIcon sx={{ color: palette.info }} />,
      value: String(rewrite.total),
      label: "Total Changes",
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
      <Box className="flex items-center gap-2 mb-1">
        <BoltIcon sx={{ color: palette.brandPrimary, fontSize: 20 }} />
        <Typography
          variant="h6"
          fontWeight={600}
          sx={{ color: palette.textPrimary }}
        >
          LLM Shadow Rewrite
        </Typography>
        <Chip
          size="small"
          label={rewrite.degraded ? "Degraded (no LLM)" : "LLM Active"}
          sx={{
            backgroundColor: rewrite.degraded
              ? `${palette.warning}20`
              : `${palette.success}20`,
            color: rewrite.degraded ? palette.warning : palette.success,
            fontWeight: 600,
            border: "none",
          }}
        />
      </Box>

      {!rewrite.degraded && rewrite.total > 0 && (
        <>
          <Typography
            variant="body2"
            sx={{ color: palette.textSecondary, mb: 3 }}
          >
            The LLM proposed {rewrite.total} note-level change
            {rewrite.total !== 1 ? "s" : ""}, validated and applied before the
            pipeline.
          </Typography>
          <Box className="grid grid-cols-3 gap-3 mb-3">
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
                    sx={{ color: palette.textPrimary }}
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
          {rewrite.reasons.length > 0 && (
            <Box className="mt-3">
              <Typography
                variant="caption"
                fontWeight={600}
                sx={{ color: palette.textSecondary }}
              >
                Reasons:
              </Typography>
              <Box className="flex flex-col gap-1 mt-1">
                {rewrite.reasons.map((reason, i) => (
                  <Typography
                    key={i}
                    variant="caption"
                    sx={{ color: palette.textSecondary }}
                  >
                    • {reason}
                  </Typography>
                ))}
              </Box>
            </Box>
          )}
        </>
      )}

      {!rewrite.degraded && rewrite.total === 0 && (
        <Typography
          variant="body2"
          sx={{ color: palette.textSecondary, mt: 1 }}
        >
          LLM analyzed the track but proposed no changes.
        </Typography>
      )}

      {rewrite.degraded && (
        <Typography
          variant="body2"
          sx={{ color: palette.textSecondary, mt: 1 }}
        >
          Configure BYOK (Bring Your Own Key) in settings to enable LLM-driven
          note rewrite.
        </Typography>
      )}
    </Box>
  );
}
