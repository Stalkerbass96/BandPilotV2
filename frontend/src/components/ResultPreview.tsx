/**
 * ResultPreview — displays the repair report (transformations + summary).
 *
 * Redesign:
 *  - Before → After comparison with a visual arrow.
 *  - Confidence displayed with a color scale (green / amber / red).
 *  - Stagger animation on table rows.
 */

import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import { motion } from "framer-motion";
import type { RepairReport } from "../api/types";
import { palette } from "../styles/tokens";

interface ResultPreviewProps {
  report: RepairReport | null;
}

/** Map a 0-1 confidence value to a semantic color. */
function confidenceColor(confidence: number): string {
  if (confidence > 0.7) return palette.success;
  if (confidence > 0.4) return palette.warning;
  return palette.error;
}

/** Compact JSON string for display in the table. */
function compactJson(obj: Record<string, unknown>): string {
  const entries = Object.entries(obj);
  if (entries.length === 0) return "{}";
  return entries
    .map(([k, v]) => `${k}:${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
}

export default function ResultPreview({
  report,
}: ResultPreviewProps): JSX.Element {
  if (!report) {
    return (
      <Alert severity="info" sx={{ borderRadius: 2 }}>
        No repair report available. Run the repair pipeline to see results.
      </Alert>
    );
  }

  const { changes, summary } = report;

  return (
    <Stack spacing={2}>
      <Box className="flex gap-2 flex-wrap">
        <Chip
          label={`Style: ${summary.style_label}`}
          sx={{
            backgroundColor: `${palette.brandPrimary}15`,
            color: palette.brandPrimary,
            fontWeight: 500,
            border: "none",
          }}
        />
        <Chip
          label={`Notes: ${summary.note_count}`}
          variant="outlined"
          sx={{ borderColor: palette.borderDefault, color: palette.textSecondary }}
        />
        <Chip
          label={`Changes: ${summary.total_changes}`}
          sx={{
            backgroundColor: `${palette.brandAccent}15`,
            color: palette.brandAccent,
            fontWeight: 500,
            border: "none",
          }}
        />
        <Chip
          label={summary.degraded_mode ? "Degraded Mode" : "LLM Active"}
          sx={{
            backgroundColor: summary.degraded_mode
              ? `${palette.warning}15`
              : `${palette.success}15`,
            color: summary.degraded_mode ? palette.warning : palette.success,
            fontWeight: 500,
            border: "none",
          }}
        />
      </Box>

      {summary.warnings.length > 0 && (
        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          <Typography variant="subtitle2">
            Warnings ({summary.warnings.length}):
          </Typography>
          <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
            {summary.warnings.slice(0, 10).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
            {summary.warnings.length > 10 && (
              <li>... and {summary.warnings.length - 10} more</li>
            )}
          </ul>
        </Alert>
      )}

      <TableContainer
        component={Paper}
        elevation={0}
        sx={{
          border: `1px solid ${palette.borderDefault}`,
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: palette.subtle }}>
              <TableCell sx={{ fontWeight: 600, color: palette.textPrimary }}>
                Stage
              </TableCell>
              <TableCell sx={{ fontWeight: 600, color: palette.textPrimary }}>
                Note #
              </TableCell>
              <TableCell sx={{ fontWeight: 600, color: palette.textPrimary }}>
                Before → After
              </TableCell>
              <TableCell sx={{ fontWeight: 600, color: palette.textPrimary }}>
                Confidence
              </TableCell>
              <TableCell sx={{ fontWeight: 600, color: palette.textPrimary }}>
                Reason
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {changes.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={5}
                  align="center"
                  sx={{ py: 3, color: palette.textSecondary }}
                >
                  No transformations recorded — the MIDI was already clean.
                </TableCell>
              </TableRow>
            ) : (
              changes.slice(0, 50).map((change, index) => (
                <motion.tr
                  key={change.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2, delay: index * 0.02 }}
                  style={{
                    backgroundColor:
                      index % 2 === 0 ? palette.canvas : palette.surface,
                  }}
                >
                  <TableCell>
                    <Chip
                      label={change.stage}
                      size="small"
                      sx={{
                        backgroundColor: palette.subtle,
                        color: palette.textSecondary,
                        border: "none",
                        fontWeight: 500,
                      }}
                    />
                  </TableCell>
                  <TableCell sx={{ color: palette.textSecondary }}>
                    {change.source_note_index}
                  </TableCell>
                  <TableCell>
                    <Box className="flex items-center gap-1">
                      <Typography
                        variant="caption"
                        fontFamily="monospace"
                        sx={{
                          color: palette.error,
                          fontSize: "0.7rem",
                          maxWidth: 120,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {compactJson(change.before)}
                      </Typography>
                      <ArrowForwardIcon
                        sx={{ fontSize: 14, color: palette.textTertiary }}
                      />
                      <Typography
                        variant="caption"
                        fontFamily="monospace"
                        sx={{
                          color: palette.success,
                          fontSize: "0.7rem",
                          maxWidth: 120,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {compactJson(change.after)}
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Box className="flex items-center gap-1.5">
                      <Box
                        sx={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          backgroundColor: confidenceColor(
                            change.confidence,
                          ),
                          flexShrink: 0,
                        }}
                      />
                      <Typography
                        variant="caption"
                        fontWeight={600}
                        sx={{
                          color: confidenceColor(change.confidence),
                        }}
                      >
                        {(change.confidence * 100).toFixed(0)}%
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Typography
                      variant="caption"
                      sx={{ color: palette.textSecondary }}
                    >
                      {change.reason}
                    </Typography>
                  </TableCell>
                </motion.tr>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
      {changes.length > 50 && (
        <Typography variant="caption" sx={{ color: palette.textTertiary }}>
          Showing first 50 of {changes.length} transformations.
        </Typography>
      )}
    </Stack>
  );
}
