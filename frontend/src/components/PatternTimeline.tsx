/**
 * PatternTimeline — SVG timeline showing beat vs fill regions across measures.
 *
 * X axis = measures, Y axis = pattern type (beat / fill / transition).
 * Beat regions rendered in brand color, fill regions in warning color,
 * transition regions in lead color.
 *
 * Props: { patterns: { measure, type, duration }[]; totalMeasures }
 */

import { Box, Typography, Tooltip } from "@mui/material";
import { motion } from "framer-motion";
import { palette } from "../styles/tokens";

export interface PatternData {
  measure: number;
  type: string;
  duration: number;
}

interface PatternTimelineProps {
  patterns: PatternData[];
  totalMeasures: number;
}

/** Color for a given pattern type. */
function patternColor(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("fill")) return palette.warning;
  if (t.includes("transition")) return palette.leadColor;
  return palette.brandPrimary; // beat
}

/** Y position (row) for a given pattern type. */
function patternRow(type: string): number {
  const t = type.toLowerCase();
  if (t.includes("fill")) return 1;
  if (t.includes("transition")) return 2;
  return 0; // beat
}

const ROW_LABELS = ["Beat", "Fill", "Transition"];
const SVG_WIDTH = 520;
const SVG_HEIGHT = 160;
const PADDING_LEFT = 70;
const PADDING_RIGHT = 16;
const PADDING_TOP = 16;
const PADDING_BOTTOM = 28;
const ROW_HEIGHT = (SVG_HEIGHT - PADDING_TOP - PADDING_BOTTOM) / 3;

export default function PatternTimeline({
  patterns,
  totalMeasures,
}: PatternTimelineProps): JSX.Element {
  const measures = Math.max(totalMeasures, 1);
  const plotWidth = SVG_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const measureWidth = plotWidth / measures;

  return (
    <Box
      className="rounded-xl p-5"
      sx={{ backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}` }}
    >
      <Box className="flex items-center justify-between mb-3">
        <Typography variant="subtitle1" fontWeight={700} sx={{ color: palette.textPrimary }}>
          🥁 Pattern Timeline
        </Typography>
        <Typography variant="caption" sx={{ color: palette.textTertiary }}>
          {measures} measures · {patterns.length} patterns
        </Typography>
      </Box>

      <Box sx={{ display: "flex", justifyContent: "center" }}>
        <svg
          width={SVG_WIDTH}
          height={SVG_HEIGHT}
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          style={{ maxWidth: "100%", height: "auto" }}
        >
          {/* Background */}
          <rect
            x={0}
            y={0}
            width={SVG_WIDTH}
            height={SVG_HEIGHT}
            fill={palette.canvas}
            rx={8}
          />

          {/* Row labels + horizontal grid lines */}
          {ROW_LABELS.map((label, rowIdx) => {
            const y = PADDING_TOP + rowIdx * ROW_HEIGHT + ROW_HEIGHT / 2;
            return (
              <g key={label}>
                <line
                  x1={PADDING_LEFT}
                  y1={y}
                  x2={SVG_WIDTH - PADDING_RIGHT}
                  y2={y}
                  stroke={palette.borderDefault}
                  strokeWidth={0.5}
                  strokeDasharray="2 3"
                  opacity={0.5}
                />
                <text
                  x={PADDING_LEFT - 8}
                  y={y + 3}
                  textAnchor="end"
                  fill={palette.textTertiary}
                  fontSize={10}
                  fontWeight={500}
                >
                  {label}
                </text>
              </g>
            );
          })}

          {/* Measure grid lines (every 4 measures or every measure if few) */}
          {Array.from({ length: measures + 1 }, (_, i) => i).filter((m) => measures <= 16 || m % 4 === 0).map((m) => {
            const x = PADDING_LEFT + m * measureWidth;
            return (
              <g key={`grid-${m}`}>
                <line
                  x1={x}
                  y1={PADDING_TOP}
                  x2={x}
                  y2={SVG_HEIGHT - PADDING_BOTTOM}
                  stroke={palette.borderDefault}
                  strokeWidth={0.5}
                  opacity={0.3}
                />
                {(measures <= 16 || m % 4 === 0) && m > 0 && (
                  <text
                    x={x}
                    y={SVG_HEIGHT - PADDING_BOTTOM + 14}
                    textAnchor="middle"
                    fill={palette.textTertiary}
                    fontSize={9}
                  >
                    {m}
                  </text>
                )}
              </g>
            );
          })}

          {/* Pattern regions */}
          {patterns.map((pat, idx) => {
            const row = patternRow(pat.type);
            const color = patternColor(pat.type);
            const x = PADDING_LEFT + (pat.measure - 1) * measureWidth;
            const w = Math.max(pat.duration * measureWidth - 2, 4);
            const y = PADDING_TOP + row * ROW_HEIGHT + 6;
            const h = ROW_HEIGHT - 12;

            return (
              <Tooltip
                key={`pat-${idx}`}
                title={`Measure ${pat.measure}: ${pat.type} (${pat.duration} bars)`}
                arrow
              >
                <motion.rect
                  initial={{ opacity: 0, scaleX: 0 }}
                  animate={{ opacity: 1, scaleX: 1 }}
                  transition={{ duration: 0.25, delay: idx * 0.03 }}
                  x={x + 1}
                  y={y}
                  width={w}
                  height={h}
                  rx={4}
                  fill={color}
                  opacity={0.8}
                  style={{ transformOrigin: `${x + 1}px ${y + h / 2}px` }}
                />
              </Tooltip>
            );
          })}

          {/* X axis label */}
          <text
            x={PADDING_LEFT + plotWidth / 2}
            y={SVG_HEIGHT - 2}
            textAnchor="middle"
            fill={palette.textTertiary}
            fontSize={10}
            fontWeight={500}
          >
            Measures
          </text>
        </svg>
      </Box>

      {/* Legend */}
      <Box className="flex items-center justify-center gap-4 mt-3">
        <Box className="flex items-center gap-1.5">
          <Box sx={{ width: 12, height: 8, borderRadius: 1, backgroundColor: palette.brandPrimary }} />
          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>Beat</Typography>
        </Box>
        <Box className="flex items-center gap-1.5">
          <Box sx={{ width: 12, height: 8, borderRadius: 1, backgroundColor: palette.warning }} />
          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>Fill</Typography>
        </Box>
        <Box className="flex items-center gap-1.5">
          <Box sx={{ width: 12, height: 8, borderRadius: 1, backgroundColor: palette.leadColor }} />
          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>Transition</Typography>
        </Box>
      </Box>
    </Box>
  );
}
