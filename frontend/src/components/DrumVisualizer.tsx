/**
 * DrumVisualizer — SVG top-down drum kit visualization.
 *
 * Shows a standard drum kit layout (kick, snare, toms, hi-hat, cymbals)
 * with each piece rendered as a circle/shape. Color intensity encodes the
 * average velocity heatmap: amber for high velocity, dim/gray for low.
 *
 * Props: { pieces: { name, hit_count, avg_velocity }[] }
 */

import { Box, Typography, Tooltip } from "@mui/material";
import { motion } from "framer-motion";
import { palette } from "../styles/tokens";

export interface DrumPieceData {
  name: string;
  hit_count: number;
  avg_velocity: number;
}

interface DrumVisualizerProps {
  pieces: DrumPieceData[];
}

// ─── Kit layout positions (SVG coordinate space: 400 x 320) ───

interface KitLayoutItem {
  /** Canonical piece name matching DrumPieceData.name */
  name: string;
  /** Display label */
  label: string;
  /** Center X */
  cx: number;
  /** Center Y */
  cy: number;
  /** Radius */
  r: number;
  /** Shape type */
  shape: "circle" | "rect";
  /** Optional width/height for rect shapes */
  w?: number;
  h?: number;
}

const KIT_LAYOUT: KitLayoutItem[] = [
  // Kick — large circle at bottom center
  { name: "kick", label: "Kick", cx: 200, cy: 250, r: 52, shape: "circle" },
  // Snare — mid-left
  { name: "snare", label: "Snare", cx: 130, cy: 180, r: 30, shape: "circle" },
  // Hi-hat — left side
  { name: "hihat_closed", label: "Hi-Hat", cx: 60, cy: 150, r: 28, shape: "circle" },
  { name: "hihat_open", label: "Open HH", cx: 60, cy: 150, r: 28, shape: "circle" },
  { name: "hihat_pedal", label: "Pedal HH", cx: 60, cy: 150, r: 28, shape: "circle" },
  // Toms — top center row
  { name: "tom_high", label: "High Tom", cx: 160, cy: 90, r: 24, shape: "circle" },
  { name: "tom_mid", label: "Mid Tom", cx: 220, cy: 80, r: 24, shape: "circle" },
  { name: "tom_low", label: "Low Tom", cx: 280, cy: 90, r: 26, shape: "circle" },
  { name: "tom_floor", label: "Floor Tom", cx: 320, cy: 180, r: 30, shape: "circle" },
  // Cymbals — right side / top
  { name: "crash", label: "Crash", cx: 100, cy: 70, r: 32, shape: "circle" },
  { name: "crash_2", label: "Crash 2", cx: 340, cy: 60, r: 32, shape: "circle" },
  { name: "ride", label: "Ride", cx: 300, cy: 140, r: 34, shape: "circle" },
  { name: "ride_2", label: "Ride 2", cx: 300, cy: 140, r: 34, shape: "circle" },
  { name: "ride_bell", label: "Ride Bell", cx: 300, cy: 140, r: 34, shape: "circle" },
  { name: "china", label: "China", cx: 340, cy: 60, r: 32, shape: "circle" },
  { name: "splash", label: "Splash", cx: 50, cy: 80, r: 24, shape: "circle" },
];

/** Map velocity (0-127) to an amber heatmap color. */
function velocityToColor(avgVelocity: number, hitCount: number): string {
  if (hitCount === 0) return palette.subtle;
  // Normalize velocity to 0..1
  const v = Math.max(0, Math.min(1, avgVelocity / 127));
  // Interpolate from dim (#222B36) to amber (#E8A24B)
  const r = Math.round(0x22 + (0xe8 - 0x22) * v);
  const g = Math.round(0x2b + (0xa2 - 0x2b) * v);
  const b = Math.round(0x36 + (0x4b - 0x36) * v);
  return `rgb(${r}, ${g}, ${b})`;
}

/** Stroke color: brighter border for high-velocity pieces. */
function velocityToStroke(avgVelocity: number, hitCount: number): string {
  if (hitCount === 0) return palette.borderDefault;
  const v = Math.max(0, Math.min(1, avgVelocity / 127));
  if (v > 0.7) return palette.brandPrimary;
  if (v > 0.4) return palette.brandAccent;
  return palette.borderDefault;
}

export default function DrumVisualizer({ pieces }: DrumVisualizerProps): JSX.Element {
  // Build a lookup map from piece name to data
  const pieceMap = new Map<string, DrumPieceData>();
  for (const p of pieces) pieceMap.set(p.name, p);

  // Track which layout positions have been rendered (to avoid duplicates
  // when multiple piece names map to the same position, e.g. hihat variants)
  const renderedPositions = new Set<string>();

  const totalHits = pieces.reduce((sum, p) => sum + p.hit_count, 0);

  return (
    <Box
      className="rounded-xl p-5"
      sx={{ backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}` }}
    >
      <Box className="flex items-center justify-between mb-3">
        <Typography variant="subtitle1" fontWeight={700} sx={{ color: palette.textPrimary }}>
          🥁 Drum Kit Heatmap
        </Typography>
        <Typography variant="caption" sx={{ color: palette.textTertiary }}>
          {totalHits.toLocaleString()} total hits · {pieces.length} pieces
        </Typography>
      </Box>

      <Box sx={{ display: "flex", justifyContent: "center" }}>
        <svg
          width="400"
          height="320"
          viewBox="0 0 400 320"
          style={{ maxWidth: "100%", height: "auto" }}
        >
          {/* Subtle grid background */}
          <rect x={0} y={0} width={400} height={320} fill={palette.canvas} rx={8} />

          {KIT_LAYOUT.map((item) => {
            // Skip if this position was already rendered by a higher-priority piece
            const posKey = `${item.cx}-${item.cy}`;
            if (renderedPositions.has(posKey)) return null;

            const data = pieceMap.get(item.name);
            const hitCount = data?.hit_count ?? 0;
            const avgVel = data?.avg_velocity ?? 0;

            // Only render if we have data for this piece, or it's a common piece
            if (!data) return null;

            renderedPositions.add(posKey);

            const fill = velocityToColor(avgVel, hitCount);
            const stroke = velocityToStroke(avgVel, hitCount);
            const opacity = hitCount > 0 ? 1 : 0.3;

            return (
              <Tooltip
                key={item.name}
                title={`${item.label}: ${hitCount} hits, avg vel ${avgVel}`}
                arrow
              >
                <motion.g
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity, scale: 1 }}
                  transition={{ duration: 0.3 }}
                  style={{ transformOrigin: `${item.cx}px ${item.cy}px` }}
                >
                  <circle
                    cx={item.cx}
                    cy={item.cy}
                    r={item.r}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={2}
                    opacity={0.85}
                  />
                  {/* Label */}
                  <text
                    x={item.cx}
                    y={item.cy - 2}
                    textAnchor="middle"
                    fill={hitCount > 0 ? "#0E1116" : palette.textTertiary}
                    fontSize={10}
                    fontWeight={600}
                  >
                    {item.label}
                  </text>
                  {/* Hit count */}
                  <text
                    x={item.cx}
                    y={item.cy + 10}
                    textAnchor="middle"
                    fill={hitCount > 0 ? "#0E1116" : palette.textTertiary}
                    fontSize={9}
                    opacity={0.8}
                  >
                    {hitCount > 0 ? `${hitCount}` : "—"}
                  </text>
                </motion.g>
              </Tooltip>
            );
          })}
        </svg>
      </Box>

      {/* Legend */}
      <Box className="flex items-center justify-center gap-4 mt-3">
        <Box className="flex items-center gap-1.5">
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: palette.subtle, border: `1px solid ${palette.borderDefault}` }} />
          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>No hits</Typography>
        </Box>
        <Box className="flex items-center gap-1.5">
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "rgb(94, 106, 120)", border: `1px solid ${palette.borderDefault}` }} />
          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>Low velocity</Typography>
        </Box>
        <Box className="flex items-center gap-1.5">
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: palette.brandPrimary, border: `1px solid ${palette.brandPrimary}` }} />
          <Typography variant="caption" sx={{ color: palette.textTertiary, fontSize: 11 }}>High velocity</Typography>
        </Box>
      </Box>
    </Box>
  );
}
