/**
 * Learning page — v3 dark-first design.
 *
 *  Upload GP tabs / zip archives; the server runs the full
 *  learning loop (parse → statistics → empirical priors → versioned KB).
 *
 *  Sections:
 *   1. Hero header
 *   2. Upload zone (drag & drop; .gp3/.gp4/.gp5/.zip)
 *   3. Learn options (style override, auto-promote)
 *   4. Results: summary chips, per-style stats, derived priors
 *   5. KB version management: version list, active badge, rollback, diff
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
import { motion } from "framer-motion";
import { elearningApi } from "../api/client";
import type {
  DrumLearnResponse,
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
  { value: "jazz", label: "Jazz" },
];

/** Which learning loop to run: FretPilot (guitar) or StickPilot (drums). */
type LearnMode = "guitar" | "drums";

const ACCEPT = ".gp3,.gp4,.gp5,.zip";

export default function LearningPage(): JSX.Element {
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const [style, setStyle] = useState("auto");
  const [promote, setPromote] = useState(true);
  const [mode, setMode] = useState<LearnMode>("guitar");

  const [learning, setLearning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LearnResponse | DrumLearnResponse | null>(null);

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
      console.error("Failed to load versions", err);
    } finally {
      setVersionsLoading(false);
    }
  }

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const list = Array.from(incoming).filter((f) => {
      const lower = f.name.toLowerCase();
      return (
        lower.endsWith(".gp3") ||
        lower.endsWith(".gp4") ||
        lower.endsWith(".gp5") ||
        lower.endsWith(".zip")
      );
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
      const styleArg = style === "auto" ? undefined : style;
      const data =
        mode === "drums"
          ? await elearningApi.learnDrum(files, styleArg, promote)
          : await elearningApi.learn(files, styleArg, promote);
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
      {/* ── Hero ── */}
      <Box
        className="rounded-2xl px-6 py-7 sm:px-8"
        sx={{
          background: `linear-gradient(135deg, ${palette.elevated} 0%, ${palette.surface} 100%)`,
          border: `1px solid ${palette.borderDefault}`,
        }}
      >
        <Box className="flex items-center gap-2.5 mb-2">
          <Box
            sx={{
              width: 32,
              height: 32,
              borderRadius: 2,
              backgroundColor: `${palette.brandPrimary}15`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <SchoolIcon sx={{ color: palette.brandPrimary, fontSize: 18 }} />
          </Box>
          <Typography variant="h5" fontWeight={700} sx={{ color: palette.textPrimary, letterSpacing: "-0.01em" }}>
            Learning Center
          </Typography>
        </Box>
        <Typography variant="body2" sx={{ color: palette.textSecondary, lineHeight: 1.6, maxWidth: 560 }}>
          Upload professional GP tabs (.gp3/.gp4/.gp5) or zip archives.
          FretPilot parses guitar tracks and extracts fingering statistics;
          StickPilot parses percussion tracks and extracts sticking statistics.
          Either way, empirical priors are derived and written to a new
          versioned knowledge base snapshot.
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {/* ── Upload zone ── */}
      <Box
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
        className="cursor-pointer text-center transition-all duration-200"
        sx={{
          p: 5,
          border: `2px dashed ${dragOver ? palette.brandPrimary : palette.borderDefault}`,
          borderRadius: 3,
          backgroundColor: dragOver ? `${palette.brandPrimary}08` : palette.canvas,
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
        <UploadFileIcon sx={{ fontSize: 40, color: dragOver ? palette.brandPrimary : palette.textTertiary, mb: 1 }} />
        <Typography variant="body1" fontWeight={600} sx={{ color: palette.textPrimary }}>
          {dragOver ? "Drop files here" : "Drag & drop GP tabs or zip archives"}
        </Typography>
        <Typography variant="body2" sx={{ color: palette.textSecondary, mt: 0.5 }}>
          or click to browse — .gp3 / .gp4 / .gp5 / .zip
        </Typography>
        {files.length > 0 && (
          <Box className="flex flex-wrap gap-1 justify-center mt-3">
            {files.slice(0, 12).map((f, i) => (
              <Chip
                key={`${f.name}-${i}`}
                label={f.name}
                size="small"
                sx={{ backgroundColor: palette.subtle, color: palette.textSecondary, border: "none" }}
              />
            ))}
            {files.length > 12 && (
              <Chip label={`+${files.length - 12} more`} size="small" sx={{ backgroundColor: palette.subtle, color: palette.textTertiary, border: "none" }} />
            )}
          </Box>
        )}
      </Box>

      {/* ── Options + action ── */}
      <Box className="flex flex-wrap items-center gap-4">
        <Box
          className="flex rounded-lg p-0.5"
          sx={{ backgroundColor: palette.subtle, border: `1px solid ${palette.borderDefault}` }}
        >
          {(["guitar", "drums"] as LearnMode[]).map((m) => {
            const active = mode === m;
            return (
              <Button
                key={m}
                size="small"
                onClick={() => {
                  setMode(m);
                  setResult(null);
                }}
                sx={{
                  textTransform: "none",
                  fontSize: 13,
                  fontWeight: active ? 600 : 400,
                  borderRadius: 1.5,
                  px: 2,
                  color: active ? palette.textPrimary : palette.textTertiary,
                  backgroundColor: active ? palette.elevated : "transparent",
                  boxShadow: active ? "0 1px 3px rgba(0,0,0,0.35)" : "none",
                  "&:hover": { backgroundColor: active ? palette.elevated : palette.canvas },
                }}
              >
                {m === "guitar" ? "Guitar" : "Drums"}
              </Button>
            );
          })}
        </Box>
        <Select
          size="small"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          sx={{ minWidth: 200, fontSize: 13 }}
        >
          {STYLE_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </Select>
        <FormControlLabel
          control={<Switch checked={promote} onChange={(e) => setPromote(e.target.checked)} />}
          label="Promote to active"
          sx={{ "& .MuiFormControlLabel-label": { color: palette.textSecondary, fontSize: 13 } }}
        />
        <Box className="flex-1" />
        {files.length > 0 && (
          <Button size="small" onClick={() => setFiles([])} sx={{ color: palette.textTertiary, textTransform: "none" }}>
            Clear
          </Button>
        )}
        <Button
          variant="contained"
          disabled={files.length === 0 || learning}
          startIcon={learning ? <CircularProgress size={16} color="inherit" /> : <SchoolIcon />}
          onClick={() => void handleLearn()}
          sx={{
            textTransform: "none",
            backgroundColor: palette.brandPrimary,
            color: "#1A1208",
            fontWeight: 600,
            "&:hover": { backgroundColor: palette.brandHover },
            "&.Mui-disabled": { backgroundColor: palette.subtle, color: palette.textTertiary },
          }}
        >
          {learning ? "Learning…" : `Learn from ${files.length} file${files.length > 1 ? "s" : ""}`}
        </Button>
      </Box>

      {/* ── Results ── */}
      {result && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <Box className="flex flex-col gap-4">
            <Box className="flex flex-wrap gap-2">
              <Chip color="success" label={`Parsed ${result.parsed_files}/${result.total_files} files`} />
              <Chip label={`${result.total_notes.toLocaleString()} notes`} sx={{ backgroundColor: palette.subtle, color: palette.textSecondary, border: "none" }} />
              <Chip label={`KB ${result.new_version}`} sx={{ backgroundColor: `${palette.brandPrimary}12`, color: palette.brandPrimary, border: "none", fontWeight: 600 }} />
              {result.promoted ? (
                <Chip color="primary" label="Promoted" />
              ) : (
                <Chip label="Candidate" sx={{ backgroundColor: palette.subtle, color: palette.textTertiary, border: "none" }} />
              )}
              {result.failed_files.length > 0 && (
                <Tooltip title={result.failed_files.map((f) => `${f.file}: ${f.error}`).join("\n")}>
                  <Chip color="warning" label={`${result.failed_files.length} skipped`} />
                </Tooltip>
              )}
            </Box>

            {/* Per-style stats — guitar vs drum column sets */}
            {result.style_stats.map((s) => {
              const isDrum = "hand_switch_pattern" in s;
              return (
                <TableContainer
                  key={s.style}
                  sx={{
                    backgroundColor: palette.elevated,
                    border: `1px solid ${palette.borderDefault}`,
                    borderRadius: 2,
                    overflow: "hidden",
                  }}
                >
                  <Table size="small">
                    {isDrum ? (
                      <>
                        <TableHead>
                          <TableRow sx={{ backgroundColor: palette.subtle }}>
                            <TableCell sx={{ color: palette.textPrimary, fontWeight: 700 }}><strong>{s.style}</strong></TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Files</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Notes</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Hit/bar</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Gap</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Accent</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Ghost</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Flam</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Dbl str</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>R-hand</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Pattern</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Top pieces</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          <TableRow>
                            <TableCell sx={{ color: palette.textSecondary }}>Stats</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.sample_count}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.total_notes.toLocaleString()}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.hit_density.toFixed(2)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.avg_inter_hit_gap_beats.toFixed(2)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.accent_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.ghost_note_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.flam_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.double_stroke_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.right_hand_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary, fontFamily: "monospace", fontWeight: 600 }}>{s.hand_switch_pattern}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary, fontSize: 12 }}>
                              {Object.entries(s.top_pieces ?? {}).slice(0, 3).map(([piece, count]) => `${piece} ×${count}`).join(", ") || "—"}
                            </TableCell>
                          </TableRow>
                        </TableBody>
                      </>
                    ) : (
                      <>
                        <TableHead>
                          <TableRow sx={{ backgroundColor: palette.subtle }}>
                            <TableCell sx={{ color: palette.textPrimary, fontWeight: 700 }}><strong>{s.style}</strong></TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Files</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Notes</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Open str</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Skip</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Overlap</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Staccato</TableCell>
                            <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Top chords</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          <TableRow>
                            <TableCell sx={{ color: palette.textSecondary }}>Stats</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.sample_count}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.total_notes.toLocaleString()}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.open_string_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{s.avg_string_skip.toFixed(2)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.note_overlap_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(s.staccato_rate)}</TableCell>
                            <TableCell align="right" sx={{ color: palette.textSecondary, fontSize: 12 }}>
                              {Object.entries(s.top_chord_shapes ?? {}).slice(0, 3).map(([shape, count]) => `${shape} ×${count}`).join(", ") || "—"}
                            </TableCell>
                          </TableRow>
                        </TableBody>
                      </>
                    )}
                  </Table>
                </TableContainer>
              );
            })}

            {/* Derived priors */}
            {result.derived_priors.map((p) => (
              <Box
                key={p.knowledge_id}
                sx={{
                  p: 3,
                  backgroundColor: palette.elevated,
                  border: `1px solid ${palette.borderDefault}`,
                  borderRadius: 2,
                }}
              >
                <Box className="flex items-center gap-2 mb-2 flex-wrap">
                  <Typography variant="subtitle2" fontWeight={700} sx={{ color: palette.textPrimary }}>
                    {p.style} priors
                  </Typography>
                  <Chip size="small" label={p.knowledge_id} sx={{ backgroundColor: palette.subtle, color: palette.textSecondary, border: "none" }} />
                  <Chip
                    size="small"
                    label={`conf ${(p.confidence * 100).toFixed(0)}%`}
                    sx={{
                      backgroundColor: p.confidence >= 0.7 ? `${palette.success}15` : palette.subtle,
                      color: p.confidence >= 0.7 ? palette.success : palette.textTertiary,
                      border: "none", fontWeight: 600,
                    }}
                  />
                  <Chip size="small" label={`${p.source_count} sources`} sx={{ backgroundColor: palette.subtle, color: palette.textTertiary, border: "none" }} />
                </Box>
                <Box className="flex flex-wrap gap-2 mt-2">
                  {Object.entries(p.payload).filter(([, v]) => typeof v === "number").map(([k, v]) => (
                    <Chip key={k} variant="outlined" size="small" label={`${k} = ${(v as number).toFixed(3)}`} sx={{ borderColor: palette.borderDefault, color: palette.textSecondary }} />
                  ))}
                </Box>
                {Object.entries(p.payload).filter(([, v]) => typeof v === "object" && v !== null).map(([k, v]) => (
                  <Box key={k} className="flex flex-wrap items-center gap-1 mt-2">
                    <Typography variant="caption" fontWeight={700} sx={{ mr: 0.5, color: palette.textTertiary }}>
                      {k}:
                    </Typography>
                    {Object.entries(v as Record<string, number>).map(([shape, count]) => (
                      <Chip key={shape} size="small" variant="outlined" label={`${shape} ×${count}`} sx={{ borderColor: palette.borderDefault, color: palette.textSecondary }} />
                    ))}
                  </Box>
                ))}
              </Box>
            ))}
          </Box>
        </motion.div>
      )}

      {/* ── Version management ── */}
      <Box className="flex items-center gap-2 mt-2">
        <HistoryIcon sx={{ color: palette.brandPrimary, fontSize: 20 }} />
        <Typography variant="h6" fontWeight={700} sx={{ color: palette.textPrimary }}>
          KB Versions
        </Typography>
        <Box className="flex-1" />
        {(versions?.items.length ?? 0) >= 2 && (
          <Button
            size="small"
            startIcon={diffBusy ? <CircularProgress size={14} color="inherit" /> : <CompareArrowsIcon />}
            onClick={() => void handleDiff()}
            sx={{ textTransform: "none", color: palette.textSecondary }}
          >
            Diff last two
          </Button>
        )}
      </Box>

      {versionsLoading ? (
        <CircularProgress size={24} sx={{ color: palette.brandPrimary }} />
      ) : (versions?.items.length ?? 0) === 0 ? (
        <Box
          className="flex flex-col items-center justify-center py-10 gap-3 rounded-xl"
          sx={{ backgroundColor: palette.elevated, border: `1px dashed ${palette.borderDefault}` }}
        >
          <Typography sx={{ color: palette.textSecondary, fontSize: 14 }}>
            No learned versions yet — upload tabs above to create the first one.
          </Typography>
        </Box>
      ) : (
        <TableContainer
          sx={{
            backgroundColor: palette.elevated,
            border: `1px solid ${palette.borderDefault}`,
            borderRadius: 2,
            overflow: "hidden",
          }}
        >
          <Table size="small">
            <TableHead>
              <TableRow sx={{ backgroundColor: palette.subtle }}>
                <TableCell sx={{ color: palette.textTertiary, fontSize: 12 }}>Version</TableCell>
                <TableCell sx={{ color: palette.textTertiary, fontSize: 12 }}>Created</TableCell>
                <TableCell sx={{ color: palette.textTertiary, fontSize: 12 }}>KB Styles</TableCell>
                <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Sources</TableCell>
                <TableCell align="right" sx={{ color: palette.textTertiary, fontSize: 12 }}>Confidence</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {(versions?.items ?? []).map((v: KbVersion) => {
                const active = v.version === versions?.active_version;
                return (
                  <TableRow key={v.version} hover>
                    <TableCell sx={{ color: palette.textPrimary }}>
                      <Box className="flex items-center gap-1.5">
                        {v.version}
                        {active && <Chip size="small" label="active" sx={{ backgroundColor: `${palette.brandPrimary}15`, color: palette.brandPrimary, border: "none", fontWeight: 600, fontSize: 10 }} />}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ color: palette.textSecondary, fontSize: 12 }}>
                      {v.timestamp ? new Date(v.timestamp).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell sx={{ color: palette.textSecondary, fontSize: 12 }}>{(v.styles_present ?? v.styles_updated ?? []).join(", ") || "—"}</TableCell>
                    <TableCell align="right" sx={{ color: palette.textSecondary }}>{v.total_sources}</TableCell>
                    <TableCell align="right" sx={{ color: palette.textSecondary }}>{pct(v.avg_confidence ?? 0)}</TableCell>
                    <TableCell align="right">
                      {!active && (
                        <Button
                          size="small"
                          disabled={rollbackBusy !== null}
                          onClick={() => void handleRollback(v.version)}
                          sx={{ textTransform: "none", fontSize: 12, color: palette.textTertiary }}
                        >
                          {rollbackBusy === v.version ? "Rolling…" : "Rollback"}
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
          <Typography variant="subtitle2" fontWeight={700} sx={{ color: palette.textPrimary }}>
            Diff: {diff.version_a} → {diff.version_b}
          </Typography>
          {Object.entries(diff.entry_diffs).map(([kid, entry]) => (
            <Box key={kid} sx={{ p: 2, backgroundColor: palette.elevated, border: `1px solid ${palette.borderDefault}`, borderRadius: 2 }}>
              <Box className="flex items-center gap-2 mb-1">
                <Typography variant="body2" fontWeight={600} sx={{ color: palette.textPrimary }}>
                  {kid}
                </Typography>
                <Chip size="small" label={`${entry.source_type_a} → ${entry.source_type_b}`} sx={{ backgroundColor: palette.subtle, color: palette.textTertiary, border: "none" }} />
              </Box>
              {Object.keys(entry.payload_diff).length === 0 ? (
                <Typography variant="body2" sx={{ color: palette.textSecondary }}>
                  No payload changes.
                </Typography>
              ) : (
                Object.entries(entry.payload_diff).map(([key, d]) => (
                  <Typography key={key} variant="body2" fontFamily="monospace" sx={{ color: palette.textSecondary }}>
                    {key}: {fmtDiffVal(d.a)} → {fmtDiffVal(d.b)}
                    {d.delta !== null && (
                      <span style={{ color: d.delta > 0 ? palette.success : palette.error }}>
                        {" "}({d.delta > 0 ? "+" : ""}{d.delta.toFixed(3)})
                      </span>
                    )}
                  </Typography>
                ))
              )}
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}