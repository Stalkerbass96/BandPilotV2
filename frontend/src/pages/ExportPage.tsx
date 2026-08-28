/**
 * Export page — choose notation or performance formats, export, and download.
 *
 * Redesign:
 *  - Export format cards with hover micro-interactions.
 *  - Export history list with download buttons.
 *  - alphaTab preview button that renders the latest GP5 export inline.
 */

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Typography,
} from "@mui/material";
import {
  AudioFileIcon,
  DescriptionIcon,
  DownloadIcon,
  VisibilityIcon as PreviewIcon,
} from "../icons";
import { motion } from "framer-motion";
import { exportsApi, projectsApi } from "../api/client";
import type { ExportRecord, ProjectDetail } from "../api/types";
import TabViewer from "../components/TabViewer";
import JourneyStepper from "../components/JourneyStepper";
import { ExportSkeleton } from "../components/Skeletons";
import { palette } from "../styles/tokens";
import { canExportProject } from "../utils/projectStatus";
import { apiErrorMessage } from "../utils/apiError";
import {
  canExportFormat,
  exportUnavailableReason,
} from "../utils/exportCapabilities";

interface FormatOption {
  id: string;
  label: string;
  shortLabel: string;
  description: string;
  icon: JSX.Element;
}

const FORMATS: FormatOption[] = [
  {
    id: "gp5",
    label: "Guitar Pro 5 (.gp5)",
    shortLabel: "GP5",
    description: "Best for rehearsal and performance. Opens in Guitar Pro and compatible score apps.",
    icon: <DescriptionIcon sx={{ fontSize: 40, color: palette.brandPrimary }} />,
  },
  {
    id: "musicxml",
    label: "MusicXML 4.0 (.musicxml)",
    shortLabel: "MusicXML",
    description: "Move the score into MuseScore, Dorico, Sibelius and other notation software.",
    icon: <DescriptionIcon sx={{ fontSize: 40, color: palette.brandPrimary }} />,
  },
  {
    id: "humanized_midi",
    label: "Humanized Band MIDI (.mid)",
    shortLabel: "Human MIDI",
    description: "Continue producing in your DAW with more natural timing, dynamics and note lengths.",
    icon: <AudioFileIcon sx={{ fontSize: 40, color: palette.brandAccent }} />,
  },
  {
    id: "ample_midi",
    label: "Ample Guitar MIDI (.mid)",
    shortLabel: "MIDI",
    description: "Advanced MIDI prepared with keyswitches for Ample Guitar Eclipse.",
    icon: <AudioFileIcon sx={{ fontSize: 40, color: palette.brandAccent }} />,
  },
  {
    id: "humanized_ample_eclipse_midi",
    label: "Humanized Ample Eclipse (.mid)",
    shortLabel: "Ample Human",
    description: "Natural performance timing plus Ample Guitar Eclipse articulation mapping.",
    icon: <AudioFileIcon sx={{ fontSize: 40, color: palette.brandAccent }} />,
  },
];

const FORMAT_LABELS: Record<string, string> = Object.fromEntries(
  FORMATS.map((format) => [format.id, format.shortLabel]),
);

const FORMAT_FILENAMES: Record<string, string> = {
  gp5: "output.gp5",
  musicxml: "output.musicxml",
  humanized_midi: "output_humanized.mid",
  ample_midi: "output_ample.mid",
  humanized_ample_eclipse_midi: "output_humanized_ample.mid",
};

export default function ExportPage(): JSX.Element {
  const { id } = useParams();
  const projectId = id;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);

  // alphaTab preview state
  const [previewData, setPreviewData] = useState<ArrayBuffer | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    if (projectId) {
      void loadData(Number(projectId));
    }
  }, [projectId]);

  const loadData = async (pid: number): Promise<void> => {
    setLoading(true);
    try {
      const [detail, exportList] = await Promise.all([
        projectsApi.get(pid),
        exportsApi.list(pid),
      ]);
      setProject(detail);
      setExports(exportList.items);
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Failed to load project or exports."));
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async (format: string): Promise<void> => {
    if (!project) return;
    setExporting(format);
    setError("");
    setSuccess("");
    try {
      await exportsApi.export(project.id, format);
      setSuccess(`${FORMAT_LABELS[format] ?? format} export completed.`);
      const exportList = await exportsApi.list(project.id);
      setExports(exportList.items);
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Export failed. Make sure repair was run first."));
    } finally {
      setExporting(null);
    }
  };

  const handleDownload = async (exp: ExportRecord): Promise<void> => {
    if (!projectId) return;
    setError("");
    setSuccess("");
    try {
      const fallbackFilename =
        FORMAT_FILENAMES[exp.format_id] ?? "bandpilot-export.bin";
      const { blob, filename } = await exportsApi.download(
        Number(projectId),
        exp.id,
        fallbackFilename,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Download failed."));
    }
  };

  const handlePreview = async (): Promise<void> => {
    if (!project) return;
    setPreviewing(true);
    setError("");
    try {
      // Fetch the latest GP5 export as a blob and convert to ArrayBuffer
      // for alphaTab rendering.
      const existing = await exportsApi.downloadLatest(project.id, "gp5");
      const { blob } = existing ?? await exportsApi.exportAndDownload(project.id, "gp5");
      const arrayBuffer = await blob.arrayBuffer();
      setPreviewData(arrayBuffer);
      setShowPreview(true);
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Preview failed. Make sure repair was run first."));
    } finally {
      setPreviewing(false);
    }
  };

  if (!projectId) {
    return (
      <Alert severity="info">
        No project selected. Import a MIDI file and run the repair pipeline
        first.
      </Alert>
    );
  }

  if (loading) {
    return <ExportSkeleton />;
  }

  const canExport = canExportProject(project?.status);

  return (
    <Box className="flex flex-col gap-6">
      <JourneyStepper activeStep={2} />
      <Box
        sx={{ mt: 2 }}
      >
        <Typography className="bp-eyebrow">Ready to play</Typography>
        <Typography variant="h4" fontWeight={800} sx={{ color: palette.textPrimary, mt: 1, mb: 1, letterSpacing: "-.035em" }}>
          Choose where your score goes next
        </Typography>
        <Typography variant="body2" sx={{ color: palette.textSecondary, lineHeight: 1.6 }}>
          {project
            ? canExport
              ? `${project.title} is ready. Guitar Pro is the best default for rehearsal and performance.`
              : `${project.title} is still a draft. Finish making it playable before choosing an export.`
            : "Loading project..."}
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ borderRadius: 2 }}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert severity="success" sx={{ borderRadius: 2 }}>
          {success}
        </Alert>
      )}

      {project && !canExport && (
        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          This score is still a draft. Return to “Make playable” and create the score before exporting.
        </Alert>
      )}
      {project?.status === "partial" && (
        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          Repair completed partially. Review the validation issues and unresolved
          source events before treating the export as final.
        </Alert>
      )}

      <Box className="flex items-center justify-between mt-2">
        <Box><Typography className="bp-eyebrow">Download</Typography><Typography sx={{ color: palette.textPrimary, fontSize: 20, fontWeight: 800, mt: .5 }}>Pick a format</Typography></Box>
        <Typography sx={{ color: palette.textTertiary, fontSize: 11 }}>You can export again at any time</Typography>
      </Box>

      <Box className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {FORMATS.filter((fmt) => !fmt.id.includes("ample")).map((fmt, index) => {
          const formatAvailable = canExportFormat(fmt.id, project?.tracks);
          const unavailableReason = exportUnavailableReason(fmt.id, project?.tracks);
          return (
          <motion.div
            key={fmt.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.08 }}
            whileHover={{ y: -4 }}
          >
            <Box
              className="rounded-xl p-5 transition-shadow duration-200"
              sx={{
                backgroundColor: palette.elevated,
                border: `1px solid ${fmt.id === "gp5" ? palette.brandPrimary : palette.borderDefault}`,
                height: "100%",
                position: "relative",
                "&:hover": {
                  borderColor: palette.brandPrimary,
                  boxShadow: "0 4px 20px rgba(232, 162, 75, 0.12)",
                },
              }}
            >
              {fmt.id === "gp5" && (
                <Chip label="Recommended" size="small" sx={{ position: "absolute", top: 14, right: 14, background: `${palette.brandPrimary}14`, color: palette.brandPrimary, fontWeight: 800, fontSize: 10 }} />
              )}
              <Box className="flex items-center gap-3 mb-3">
                <Box className="flex items-center justify-center" sx={{ width: 44, height: 44, borderRadius: 2.5, background: palette.subtle }}>{fmt.icon}</Box>
                <Typography
                  variant="h6"
                  fontWeight={600}
                  sx={{ color: palette.textPrimary }}
                >
                  {fmt.label}
                </Typography>
              </Box>
              <Typography
                variant="body2"
                sx={{ color: palette.textSecondary, mb: 3, minHeight: 40 }}
              >
                {fmt.description}
              </Typography>
              <Button
                variant="contained"
                fullWidth
                startIcon={
                  exporting === fmt.id ? (
                    <CircularProgress size={18} color="inherit" />
                  ) : (
                    <DownloadIcon />
                  )
                }
                onClick={() => handleExport(fmt.id)}
                disabled={
                  exporting !== null || !canExport || !formatAvailable
                }
                sx={{
                  textTransform: "none",
                  backgroundColor: fmt.id === "gp5" ? palette.brandPrimary : "transparent",
                  color: fmt.id === "gp5" ? "#fff" : palette.textPrimary,
                  border: fmt.id === "gp5" ? "none" : `1px solid ${palette.borderHover}`,
                  "&:hover": { backgroundColor: palette.brandHover },
                }}
              >
                {exporting === fmt.id
                  ? "Exporting..."
                  : `Export ${fmt.shortLabel}`}
              </Button>
              {unavailableReason && (
                <Typography
                  variant="caption"
                  sx={{ color: palette.textTertiary, display: "block", mt: 1.25 }}
                >
                  {unavailableReason}
                </Typography>
              )}
            </Box>
          </motion.div>
          );
        })}
      </Box>

      <Box component="details" className="bp-card" sx={{ p: 2.5 }}>
        <Box component="summary" sx={{ color: palette.textPrimary, fontSize: 13, fontWeight: 750, cursor: "pointer", listStylePosition: "inside" }}>
          Sound-library MIDI <span style={{ color: palette.textTertiary, fontWeight: 500 }}>· advanced</span>
        </Box>
        <Typography sx={{ color: palette.textSecondary, fontSize: 12, mt: 1, ml: 2.5 }}>Use these only when your DAW session includes Ample Guitar Eclipse.</Typography>
        <Box className="flex flex-col mt-3">
          {FORMATS.filter((fmt) => fmt.id.includes("ample")).map((fmt) => {
            const formatAvailable = canExportFormat(fmt.id, project?.tracks);
            const unavailableReason = exportUnavailableReason(fmt.id, project?.tracks);
            return (
              <Box key={fmt.id} className="flex items-center gap-4 py-3" sx={{ borderTop: `1px solid ${palette.borderDefault}` }}>
                <Box className="flex-1 min-w-0"><Typography sx={{ color: palette.textPrimary, fontSize: 13, fontWeight: 700 }}>{fmt.label}</Typography><Typography sx={{ color: palette.textTertiary, fontSize: 11, mt: .25 }}>{unavailableReason || fmt.description}</Typography></Box>
                <Button size="small" variant="outlined" startIcon={exporting === fmt.id ? <CircularProgress size={16} /> : <DownloadIcon />} onClick={() => handleExport(fmt.id)} disabled={exporting !== null || !canExport || !formatAvailable}>Export</Button>
              </Box>
            );
          })}
        </Box>
      </Box>

      {/* ── alphaTab preview ── */}
      {canExport && (
        <Box
          className="rounded-xl p-5"
          sx={{
            backgroundColor: palette.elevated,
            border: `1px solid ${palette.borderDefault}`,
          }}
        >
          <Box className="flex items-center justify-between mb-4">
            <Typography
              variant="h6"
              fontWeight={600}
              sx={{ color: palette.textPrimary }}
            >
              Score Preview
            </Typography>
            <Button
              variant="outlined"
              startIcon={
                previewing ? (
                  <CircularProgress size={18} color="inherit" />
                ) : (
                  <PreviewIcon />
                )
              }
              onClick={handlePreview}
              disabled={previewing}
              sx={{
                textTransform: "none",
                borderColor: palette.brandPrimary,
                color: palette.brandPrimary,
              }}
            >
              {previewing ? "Loading preview…" : "Preview GP5"}
            </Button>
          </Box>
          {showPreview && <TabViewer scoreData={previewData} />}
        </Box>
      )}

      {/* ── Export history ── */}
      {exports.length > 0 && (
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
            sx={{ color: palette.textPrimary, mb: 2 }}
          >
            Export History
          </Typography>
          <Divider sx={{ mb: 2, borderColor: palette.borderDefault }} />
          <Box className="flex flex-col gap-2">
            {exports.map((exp) => (
              <Box
                key={exp.id}
                className="flex items-center justify-between gap-3 py-2"
              >
                <Box className="flex items-center gap-3 flex-1 min-w-0">
                  {exp.format_id === "gp5" || exp.format_id === "musicxml" ? (
                    <DescriptionIcon
                      sx={{ color: palette.brandPrimary, flexShrink: 0 }}
                    />
                  ) : (
                    <AudioFileIcon
                      sx={{ color: palette.brandAccent, flexShrink: 0 }}
                    />
                  )}
                  <Box className="flex items-center gap-2 flex-wrap">
                    <Typography
                      fontWeight={500}
                      sx={{ color: palette.textPrimary }}
                    >
                      {exp.format_id}
                    </Typography>
                    <Chip
                      label={`${exp.note_count} notes`}
                      size="small"
                      sx={{
                        backgroundColor: palette.subtle,
                        color: palette.textSecondary,
                        border: "none",
                      }}
                    />
                    {exp.created_at && (
                      <Typography
                        variant="caption"
                        sx={{ color: palette.textTertiary }}
                      >
                        {new Date(exp.created_at).toLocaleString()}
                      </Typography>
                    )}
                  </Box>
                </Box>
                <Button
                  startIcon={<DownloadIcon />}
                  size="small"
                  variant="outlined"
                  onClick={() => handleDownload(exp)}
                  sx={{
                    textTransform: "none",
                    borderColor: palette.borderDefault,
                    color: palette.textPrimary,
                    "&:hover": {
                      borderColor: palette.brandPrimary,
                      backgroundColor: "rgba(232, 162, 75, 0.06)",
                    },
                  }}
                >
                  Download
                </Button>
              </Box>
            ))}
          </Box>
        </Box>
      )}
    </Box>
  );
}
