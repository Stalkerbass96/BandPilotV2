/**
 * SeparationVisualizer — pitch-vs-measure 可视化 for stream separation.
 *
 * Renders an SVG chart showing each mixed segment as a horizontal band:
 *  - Low region (rhythm, below split_pitch) in amber
 *  - High region (melody, above split_pitch) in cyan
 *  - Split line dashed at split_pitch
 *  - Confidence as opacity
 *
 * This replaces the old text-only segment list in SeparationSummary.
 */

import { Box, Typography, Tooltip } from "@mui/material";
import type { SeparationSegmentInfo } from "../api/types";
import { streamColors, palette } from "../styles/tokens";

interface SeparationVisualizerProps {
  segments: SeparationSegmentInfo[];
  /** Total measures in the piece (for axis scaling). */
  totalMeasures?: number;
}

// Chart dimensions
const CHART_W = 520;
const CHART_H = 200;
const PAD_L = 40;
const PAD_R = 12;
const PAD_T = 16;
const PAD_B = 28;
const PLOT_W = CHART_W - PAD_L - PAD_R;
const PLOT_H = CHART_H - PAD_T - PAD_B;

// Pitch range for Y axis (MIDI notes)
const PITCH_MIN = 28; // E1 — low guitar
const PITCH_MAX = 96; // C7 — high guitar

function pitchToY(pitch: number): number {
  const t = (pitch - PITCH_MIN) / (PITCH_MAX - PITCH_MIN);
  return PAD_T + PLOT_H * (1 - t); // invert: high pitch at top
}

function measureToX(measure: number, totalMeasures: number): number {
  return PAD_L + (PLOT_W * measure) / Math.max(totalMeasures, 1);
}

export default function SeparationVisualizer({
  segments,
  totalMeasures,
}: SeparationVisualizerProps): JSX.Element {
  if (segments.length === 0) return <></>;

  // Derive total measures from segments if not provided
  const maxMeasure = totalMeasures ?? Math.max(...segments.map((s) => s.end_measure), 1);

  // Pitch grid lines
  const pitchTicks: number[] = [];
  for (let p = 40; p <= 84; p += 12) pitchTicks.push(p);

  // Measure grid lines
  const measureTicks: number[] = [];
  const step = Math.max(Math.ceil(maxMeasure / 8), 1);
  for (let m = 0; m <= maxMeasure; m += step) measureTicks.push(m);

  return (
    <Box className="w-full">
      <Typography
        variant="caption"
        fontWeight={600}
        sx={{ color: palette.textSecondary, mb: 1, display: "block" }}
      >
        Pitch vs Measure — Separation Map
      </Typography>
      <Box
        className="w-full rounded-lg"
        sx={{
          backgroundColor: palette.subtle,
          border: `1px solid ${palette.borderDefault}`,
          p: 1,
          overflowX: "auto",
        }}
      >
        <svg
          viewBox={`0 0 ${CHART_W} ${CHART_H}`}
          style={{ width: "100%", minWidth: 400, maxWidth: CHART_W }}
        >
          {/* ── Grid lines ── */}
          {pitchTicks.map((p) => (
            <line
              key={`pg-${p}`}
              x1={PAD_L}
              y1={pitchToY(p)}
              x2={CHART_W - PAD_R}
              y2={pitchToY(p)}
              stroke={palette.borderDefault}
              strokeWidth={0.5}
              opacity={0.5}
            />
          ))}
          {measureTicks.map((m) => (
            <line
              key={`mg-${m}`}
              x1={measureToX(m, maxMeasure)}
              y1={PAD_T}
              x2={measureToX(m, maxMeasure)}
              y2={CHART_H - PAD_B}
              stroke={palette.borderDefault}
              strokeWidth={0.5}
              opacity={0.5}
            />
          ))}

          {/* ── Y axis labels (pitch) ── */}
          {pitchTicks.map((p) => (
            <text
              key={`pl-${p}`}
              x={PAD_L - 6}
              y={pitchToY(p) + 3}
              fill={palette.textTertiary}
              fontSize={9}
              textAnchor="end"
            >
              {p}
            </text>
          ))}

          {/* ── X axis labels (measure) ── */}
          {measureTicks.map((m) => (
            <text
              key={`ml-${m}`}
              x={measureToX(m, maxMeasure)}
              y={CHART_H - PAD_B + 14}
              fill={palette.textTertiary}
              fontSize={9}
              textAnchor="middle"
            >
              {m}
            </text>
          ))}

          {/* ── Axis titles ── */}
          <text
            x={PAD_L - 28}
            y={PAD_T + PLOT_H / 2}
            fill={palette.textSecondary}
            fontSize={9}
            textAnchor="middle"
            transform={`rotate(-90 ${PAD_L - 28} ${PAD_T + PLOT_H / 2})`}
          >
            Pitch (MIDI)
          </text>
          <text
            x={PAD_L + PLOT_W / 2}
            y={CHART_H - 4}
            fill={palette.textSecondary}
            fontSize={9}
            textAnchor="middle"
          >
            Measure
          </text>

          {/* ── Segments ── */}
          {segments.map((seg, i) => {
            const x1 = measureToX(seg.start_measure, maxMeasure);
            const x2 = measureToX(seg.end_measure, maxMeasure);
            const segW = Math.max(x2 - x1, 2);
            const splitY = pitchToY(seg.split_pitch);
            const opacity = 0.25 + seg.confidence * 0.5;

            return (
              <g key={`seg-${i}`}>
                {/* Rhythm region (low pitch, below split) — amber */}
                <Tooltip
                  title={`Bars ${seg.start_measure}–${seg.end_measure}: ${seg.low_note_count} rhythm notes`}
                  placement="top"
                >
                  <rect
                    x={x1}
                    y={splitY}
                    width={segW}
                    height={CHART_H - PAD_B - splitY}
                    fill={streamColors.rhythm}
                    opacity={opacity}
                    rx={2}
                  />
                </Tooltip>

                {/* Lead region (high pitch, above split) — cyan */}
                <Tooltip
                  title={`Bars ${seg.start_measure}–${seg.end_measure}: ${seg.high_note_count} lead notes`}
                  placement="top"
                >
                  <rect
                    x={x1}
                    y={PAD_T}
                    width={segW}
                    height={splitY - PAD_T}
                    fill={streamColors.lead}
                    opacity={opacity}
                    rx={2}
                  />
                </Tooltip>

                {/* Split line */}
                <line
                  x1={x1}
                  y1={splitY}
                  x2={x2}
                  y2={splitY}
                  stroke={palette.textPrimary}
                  strokeWidth={1}
                  strokeDasharray="3 2"
                  opacity={0.8}
                />

                {/* Split pitch label */}
                <text
                  x={x1 + segW / 2}
                  y={splitY - 3}
                  fill={palette.textSecondary}
                  fontSize={8}
                  textAnchor="middle"
                >
                  {seg.split_pitch}
                </text>
              </g>
            );
          })}

          {/* ── Legend ── */}
          <rect x={CHART_W - 110} y={PAD_T} width={10} height={10} fill={streamColors.lead} opacity={0.6} rx={2} />
          <text x={CHART_W - 96} y={PAD_T + 9} fill={palette.textSecondary} fontSize={9}>
            Lead
          </text>
          <rect x={CHART_W - 65} y={PAD_T} width={10} height={10} fill={streamColors.rhythm} opacity={0.6} rx={2} />
          <text x={CHART_W - 51} y={PAD_T + 9} fill={palette.textSecondary} fontSize={9}>
            Rhythm
          </text>
        </svg>
      </Box>
    </Box>
  );
}
