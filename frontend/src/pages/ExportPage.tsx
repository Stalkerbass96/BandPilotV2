/**
 * Export page — choose gp5 or Ample MIDI format, trigger export, download.
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
import DownloadIcon from "@mui/icons-material/Download";
import DescriptionIcon from "@mui/icons-material/Description";
import AudioFileIcon from "@mui/icons-material/AudioFile";
import PreviewIcon from "@mui/icons-material/Visibility";
import { motion } from "framer-motion";
import { exportsApi, projectsApi } from "../api/client";
import type { ExportRecord, ProjectDetail } from "../api/types";
import TabViewer from "../components/TabViewer";
import { ExportSkeleton } from "../components/Skeletons";
import { palette } from "../styles/tokens";

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
    description:
      "Notation-focused score file. Opens in Guitar Pro, TuxGuitar, MuseScore.",
    icon: <DescriptionIcon sx={{ fontSize: 40, color: palette.brandPrimary }} />,
  },
  {
    id: "ample_midi",
    label: "Ample Guitar MIDI (.mid)",
    shortLabel: "MIDI",
    description:
      "Performance-focused MIDI with keyswitches for Ample Guitar Eclipse.",
    icon: <AudioFileIcon sx={{ fontSize: 40, color: palette.brandAccent }} />,
  },
];

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
    } catch {
      setError("Failed to load project or exports.");
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
      setSuccess(
        `${format === "gp5" ? "Guitar Pro 5" : "Ample MIDI"} export completed.`,
      );
      const exportList = await exportsApi.list(project.id);
      setExports(exportList.items);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Export failed. Make sure repair was run first.";
      setError(detail);
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
        exp.format_id === "gp5" ? "output.gp5" : "output_ample.mid";
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
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Download failed.";
      setError(detail);
    }
  };

  const handlePreview = async (): Promise<void> => {
    if (!project) return;
    setPreviewing(true);
    setError("");
    try {
      // Fetch the latest GP5 export as a blob and convert to ArrayBuffer
      // for alphaTab rendering.
      const { blob } = await exportsApi.exportAndDownload(project.id, "gp5");
      const arrayBuffer = await blob.arrayBuffer();
      setPreviewData(arrayBuffer);
      setShowPreview(true);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Preview failed. Make sure repair was run first.";
      setError(detail);
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

  return (
    <Box className="flex flex-col gap-6">
      <Box>
        <Typography
          variant="h5"
          fontWeight={600}
          sx={{ color: palette.textPrimary, mb: 1 }}
        >
          Export
        </Typography>
        <Typography variant="body2" sx={{ color: palette.textSecondary }}>
          {project
            ? `Export repaired project "${project.title}" to your preferred format.`
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

      {project && project.status !== "repaired" && (
        <Alert severity="warning" sx={{ borderRadius: 2 }}>
          This project has not been repaired yet. Run the repair pipeline in the
          Workbench before exporting.
        </Alert>
      )}

      {/* ── Format cards ── */}
      <Box className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {FORMATS.map((fmt, index) => (
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
                border: `1px solid ${palette.borderDefault}`,
                height: "100%",
                "&:hover": {
                  borderColor: palette.brandPrimary,
                  boxShadow: "0 4px 20px rgba(99, 102, 241, 0.12)",
                },
              }}
            >
              <Box className="flex items-center gap-3 mb-3">
                {fmt.icon}
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
                  exporting !== null || project?.status !== "repaired"
                }
                sx={{
                  textTransform: "none",
                  backgroundColor: palette.brandPrimary,
                  "&:hover": { backgroundColor: palette.brandHover },
                }}
              >
                {exporting === fmt.id
                  ? "Exporting..."
                  : `Export ${fmt.shortLabel}`}
              </Button>
            </Box>
          </motion.div>
        ))}
      </Box>

      {/* ── alphaTab preview ── */}
      {project?.status === "repaired" && (
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
                  {exp.format_id === "gp5" ? (
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
                      backgroundColor: "rgba(99, 102, 241, 0.04)",
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
