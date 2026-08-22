/**
 * SeparationSummary — displays the riff/melody stream-separation result.
 *
 * When a mixed guitar track is detected (low riff + high melody), the backend
 * splits it into two tracks: Lead (melody) + Rhythm (riff).  This card shows
 * the segment count, split ranges, and confidence so the user can verify the
 * separation at a glance.
 */

import { Box, Chip, Typography } from "@mui/material";
import LayersIcon from "@mui/icons-material/Layers";
import StraightenIcon from "@mui/icons-material/Straighten";
import GraphicEqIcon from "@mui/icons-material/GraphicEq";
import { motion } from "framer-motion";
import type { SeparationInfo } from "../api/types";
import { palette, streamColors } from "../styles/tokens";
import SeparationVisualizer from "./SeparationVisualizer";

interface SeparationSummaryProps {
  separation: SeparationInfo;
}

interface InfoCard {
  icon: JSX.Element;
  value: string;
  label: string;
}

export default function SeparationSummary({
  separation,
}: SeparationSummaryProps): JSX.Element {
  const totalLow = separation.segments.reduce(
    (acc, s) => acc + s.low_note_count,
    0,
  );
  const totalHigh = separation.segments.reduce(
    (acc, s) => acc + s.high_note_count,
    0,
  );

  const cards: InfoCard[] = [
    {
      icon: <LayersIcon sx={{ color: palette.brandPrimary }} />,
      value: String(separation.segments.length),
      label: "Mixed Segments",
    },
    {
      icon: <StraightenIcon sx={{ color: streamColors.lead }} />,
      value: String(totalHigh),
      label: "Lead (melody)",
    },
    {
      icon: <GraphicEqIcon sx={{ color: streamColors.rhythm }} />,
      value: String(totalLow),
      label: "Rhythm (riff)",
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
        <LayersIcon sx={{ color: palette.brandPrimary, fontSize: 20 }} />
        <Typography
          variant="h6"
          fontWeight={600}
          sx={{ color: palette.textPrimary }}
        >
          Stream Separation
        </Typography>
        <Chip
          size="small"
          label={separation.detected ? "2 Tracks" : "Single Track"}
          sx={{
            backgroundColor: separation.detected
              ? `${palette.success}20`
              : palette.subtle,
            color: separation.detected ? palette.success : palette.textSecondary,
            fontWeight: 600,
            border: "none",
          }}
        />
      </Box>

      {separation.detected ? (
        <>
          <Typography
            variant="body2"
            sx={{ color: palette.textSecondary, mb: 3 }}
          >
            Detected {separation.segments.length} mixed segment
            {separation.segments.length !== 1 ? "s" : ""} (low riff + high
            melody), split into <strong>Lead</strong> and{" "}
            <strong>Rhythm</strong> tracks in the GP5 export.
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

          {separation.segments.length > 0 && (
            <Box className="mt-4">
              <SeparationVisualizer segments={separation.segments} />
            </Box>
          )}
        </>
      ) : (
        <Typography
          variant="body2"
          sx={{ color: palette.textSecondary, mt: 1 }}
        >
          No mixed riff/melody passages detected — exported as a single track.
        </Typography>
      )}
    </Box>
  );
}
