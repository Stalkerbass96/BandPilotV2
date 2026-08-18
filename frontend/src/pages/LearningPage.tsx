/**
 * Learning page — upload GP tabs / zip archives; the server runs the full
 * learning loop (parse → statistics → empirical priors → versioned KB).
 *
 * Sections:
 *  1. Upload zone (drag & drop or file picker; .gp3/.gp4/.gp5/.zip).
 *  2. Learn options (style override, auto-promote).
 *  3. Results: summary chips, per-style stats, derived priors.
 *  4. KB version management: version list, active badge, rollback, diff.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Paper,
  Select,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import SchoolIcon from "@mui/icons-material/School";
import HistoryIcon from "@mui/icons-material/History";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import { elearningApi } from "../api/client";
import type {
  KbVersion,
  LearnResponse,
  PriorValue,
  VersionDiff,
  VersionsResponse,
} from "../api/types";
import { palette } from "../styles/tokens";

const STYLE_OPTIONS = [
  { value: "auto", label: "Auto-detect (filename)" },
  { value: "rock", label: "Rock" },
  { value: "metal", label: "Metal" },
  { value: "pop", label: "Pop" },
  { value: "funk", label: "Funk" },
];

const ACCEPT = ".gp3,.gp4,.gp5,.zip";

export default function LearningPage(): JSX.Element {
  // ── Upload state ──
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // ── Options ──
  const [style, setStyle] = useState("auto");
  const [promote, setPromote] = useState(true);

  // ── Learn state ──
  const [learning, setLearning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LearnResponse | null>(null);

  // ── Versions state ──
  const [versions, setVersions] = useState<VersionsResponse | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [rollbackBusy, setRollbackBusy] = useState<string | null>(null);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [diffBusy, setDiffBusy] = useState(false);

  useEffect(() => {
    void loadVersions();
  }, []);

  async function loadVersions(): Promise<void> {
    setVersionsLoading(true);
    try {
      setVersions(await elearningApi.versions());
    } catch (err) {
      // Non-fatal: version panel just stays empty.
      console.error("Failed to load versions", err);
    } finally {
      setVersionsLoading(false);
    }
  }

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const list = Array.from(incoming).filter((f) => {
      const lower = f.name.toLowerCase();
      return lower.endsWith(".gp3") || lower.endsWith(".gp4") ||
        lower.endsWith(".gp5") || lower.endsWith(".zip");
    });
    setFiles((prev) => [...prev, ...list]);
  }, []);

  async function handleLearn(): Promise<void> {
    if (files.length === 0) return;
    setLearning(true);
    setError(null);
    setResult(null);
    setDiff(null);
    try {
      const data = await elearningApi.learn(
        files,
        style === "auto" ? undefined : style,
        promote,
      );
      setResult(data);
      await loadVersions();
    } catch (err) {
      setError((err as Error).message || "Learning failed");
    } finally {
      setLearning(false);
    }
  }

  async function handleRollback(version: string): Promise<void> {
    setRollbackBusy(version);
    try {
      await elearningApi.rollback(version);
      await loadVersions();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRollbackBusy(null);
    }
  }

  async function handleDiff(): Promise<void> {
    const items = versions?.items ?? [];
    if (items.length < 2) return;
    setDiffBusy(true);
    try {
      setDiff(await elearningApi.diff(items[1].version, items[0].version));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDiffBusy(false);
    }
  }

  const pct = (v: number): string => `${(v * 100).toFixed(1)}%`;

  const fmtDiffVal = (v: PriorValue | null): string =>
    v === null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v);

  return (
    <Box className="flex flex-col gap-6 max-w-4xl">
      {/* ── Header ── */}
      <Box className="flex items-center gap-2">
        <SchoolIcon sx={{ color: palette.brandPrimary }} />
        <Typography variant="h5" fontWeight={700}>
          Learning Center
        </Typography>
      </Box>
      <Typography variant="body2" style={{ color: palette.textSecondary }}>
        Upload professional GP tabs (.gp3/.gp4/.gp5) or zip archives. FretPilot
        parses them, extracts fingering statistics (open-string rate, hand
        positions, chord shapes), derives empirical priors, and writes a new
        versioned knowledge base snapshot.
      </Typography>

      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* ── Upload zone ── */}
      <Paper
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        sx={{
          p: 4,
          textAlign: "center",
          cursor: "pointer",
          border: `2px dashed ${dragOver ? palette.brandPrimary : palette.borderDefault}`,
          bgcolor: dragOver ? "rgba(25,118,210,0.04)" : "transparent",
          transition: "all 0.15s ease",
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <UploadFileIcon
          sx={{ fontSize: 40, color: palette.textSecondary, mb: 1 }}
        />
        <Typography variant="body1" fontWeight={600}>
          Drag &amp; drop GP tabs or zip archives here
        </Typography>
        <Typography variant="body2" style={{ color: palette.textSecondary }}>
          or click to browse — .gp3 / .gp4 / .gp5 / .zip
        </Typography>
        {files.length > 0 && (
          <Box className="flex flex-wrap gap-1 justify-center mt-3">
            {files.slice(0, 12).map((f, i) => (
              <Chip key={`${f.name}-${i}`} label={f.name} size="small" />
            ))}
            {files.length > 12 && (
              <Chip label={`+${files.length - 12} more`} size="small" />
            )}
          </Box>
        )}
      </Paper>

      {/* ── Options + action ── */}
      <Box className="flex flex-wrap items-center gap-4">
        <Select
          size="small"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          sx={{ minWidth: 200 }}
        >
          {STYLE_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </Select>
        <FormControlLabel
          control={
            <Switch checked={promote} onChange={(e) => setPromote(e.target.checked)} />
          }
          label="Promote new KB version to active"
        />
        <Box className="flex-1" />
        {files.length > 0 && (
          <Button size="small" onClick={() => setFiles([])} color="inherit">
            Clear
          </Button>
        )}
        <Button
          variant="contained"
          disabled={files.length === 0 || learning}
          startIcon={learning ? <CircularProgress size={16} color="inherit" /> : <SchoolIcon />}
          onClick={() => void handleLearn()}
        >
          {learning ? "Learning…" : `Learn from ${files.length} file${files.length > 1 ? "s" : ""}`}
        </Button>
      </Box>

      {/* ── Results ── */}
      {result && (
        <Box className="flex flex-col gap-4">
          <Box className="flex flex-wrap gap-2">
            <Chip
              color="success"
              label={`Parsed ${result.parsed_files}/${result.total_files} files`}
            />
            <Chip label={`${result.total_notes.toLocaleString()} notes analyzed`} />
            <Chip label={`New KB version: ${result.new_version}`} />
            {result.promoted ? (
              <Chip color="primary" label="Promoted to active" />
            ) : (
              <Chip label="Saved as candidate" />
            )}
            {result.failed_files.length > 0 && (
              <Tooltip
                title={result.failed_files
                  .map((f) => `${f.file}: ${f.error}`)
                  .join("\n")}
              >
                <Chip color="warning" label={`${result.failed_files.length} skipped`} />
              </Tooltip>
            )}
          </Box>

          {/* Per-style stats */}
          {result.style_stats.map((s) => (
            <TableContainer key={s.style} component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell><strong>{s.style}</strong></TableCell>
                    <TableCell align="right">Files</TableCell>
                    <TableCell align="right">Notes</TableCell>
                    <TableCell align="right">Open strings</TableCell>
                    <TableCell align="right">Avg skip</TableCell>
                    <TableCell align="right">Overlap</TableCell>
                    <TableCell align="right">Staccato</TableCell>
                    <TableCell align="right">Top chord shapes</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  <TableRow>
                    <TableCell>Statistics</TableCell>
                    <TableCell align="right">{s.sample_count}</TableCell>
                    <TableCell align="right">{s.total_notes.toLocaleString()}</TableCell>
                    <TableCell align="right">{pct(s.open_string_rate)}</TableCell>
                    <TableCell align="right">{s.avg_string_skip.toFixed(2)}</TableCell>
                    <TableCell align="right">{pct(s.note_overlap_rate)}</TableCell>
                    <TableCell align="right">{pct(s.staccato_rate)}</TableCell>
                    <TableCell align="right">
                      {Object.entries(s.top_chord_shapes ?? {})
                        .slice(0, 3)
                        .map(([shape, count]) => `${shape} ×${count}`)
                        .join(", ") || "—"}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TableContainer>
          ))}

          {/* Derived priors */}
          {result.derived_priors.map((p) => (
            <Paper key={p.knowledge_id} variant="outlined" sx={{ p: 2 }}>
              <Box className="flex items-center gap-2 mb-1">
                <Typography variant="subtitle2" fontWeight={700}>
                  {p.style} priors
                </Typography>
                <Chip size="small" label={p.knowledge_id} />
                <Chip
                  size="small"
                  color={p.confidence >= 0.7 ? "success" : "default"}
                  label={`confidence ${(p.confidence * 100).toFixed(0)}%`}
                />
                <Chip size="small" label={`${p.source_count} sources`} />
              </Box>
              <Box className="flex flex-wrap gap-2 mt-2">
                {Object.entries(p.payload)
                  .filter(([, v]) => typeof v === "number")
                  .map(([k, v]) => (
                    <Chip
                      key={k}
                      variant="outlined"
                      size="small"
                      label={`${k} = ${(v as number).toFixed(3)}`}
                    />
                  ))}
              </Box>
              {Object.entries(p.payload)
                .filter(([, v]) => typeof v === "object" && v !== null)
                .map(([k, v]) => (
                  <Box key={k} className="flex flex-wrap items-center gap-1 mt-1">
                    <Typography variant="caption" fontWeight={700} sx={{ mr: 0.5 }}>
                      {k}:
                    </Typography>
                    {Object.entries(v as Record<string, number>).map(([shape, count]) => (
                      <Chip
                        key={shape}
                        size="small"
                        variant="outlined"
                        label={`${shape} ×${count}`}
                      />
                    ))}
                  </Box>
                ))}
            </Paper>
          ))}
        </Box>
      )}

      {/* ── Version management ── */}
      <Box className="flex items-center gap-2 mt-4">
        <HistoryIcon sx={{ color: palette.brandPrimary }} />
        <Typography variant="h6" fontWeight={700}>
          Knowledge Base Versions
        </Typography>
        <Box className="flex-1" />
        {(versions?.items.length ?? 0) >= 2 && (
          <Button
            size="small"
            startIcon={
              diffBusy ? <CircularProgress size={14} color="inherit" /> : <CompareArrowsIcon />
            }
            onClick={() => void handleDiff()}
          >
            Diff last two
          </Button>
        )}
      </Box>

      {versionsLoading ? (
        <CircularProgress size={24} />
      ) : (versions?.items.length ?? 0) === 0 ? (
        <Typography variant="body2" style={{ color: palette.textSecondary }}>
          No learned versions yet — upload some tabs above to create the first one.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Version</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Styles</TableCell>
                <TableCell align="right">Sources</TableCell>
                <TableCell align="right">Confidence</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {(versions?.items ?? []).map((v: KbVersion) => {
                const active = v.version === versions?.active_version;
                return (
                  <TableRow key={v.version} hover>
                    <TableCell>
                      <Box className="flex items-center gap-1">
                        {v.version}
                        {active && <Chip size="small" color="primary" label="active" />}
                      </Box>
                    </TableCell>
                    <TableCell>
                      {v.timestamp ? new Date(v.timestamp).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>{(v.styles_updated ?? []).join(", ") || "—"}</TableCell>
                    <TableCell align="right">{v.total_sources}</TableCell>
                    <TableCell align="right">{pct(v.avg_confidence ?? 0)}</TableCell>
                    <TableCell align="right">
                      {!active && (
                        <Button
                          size="small"
                          disabled={rollbackBusy !== null}
                          onClick={() => void handleRollback(v.version)}
                        >
                          {rollbackBusy === v.version ? "Rolling back…" : "Rollback to this"}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* ── Diff view ── */}
      {diff && (
        <Box className="flex flex-col gap-2">
          <Typography variant="subtitle2" fontWeight={700}>
            Diff: {diff.version_a} → {diff.version_b}
          </Typography>
          {Object.entries(diff.entry_diffs).map(([kid, entry]) => (
            <Paper key={kid} variant="outlined" sx={{ p: 2 }}>
              <Typography variant="body2" fontWeight={600}>
                {kid}
                <Chip
                  size="small"
                  sx={{ ml: 1 }}
                  label={`${entry.source_type_a} → ${entry.source_type_b}`}
                />
              </Typography>
              {Object.keys(entry.payload_diff).length === 0 ? (
                <Typography variant="body2" style={{ color: palette.textSecondary }}>
                  No payload changes.
                </Typography>
              ) : (
                Object.entries(entry.payload_diff).map(([key, d]) => (
                  <Typography key={key} variant="body2" fontFamily="monospace">
                    {key}: {fmtDiffVal(d.a)} → {fmtDiffVal(d.b)}
                    {d.delta !== null && (
                      <span style={{ color: d.delta > 0 ? "#2e7d32" : "#c62828" }}>
                        {" "}({d.delta > 0 ? "+" : ""}{d.delta.toFixed(3)})
                      </span>
                    )}
                  </Typography>
                ))
              )}
            </Paper>
          ))}
        </Box>
      )}
    </Box>
  );
}
