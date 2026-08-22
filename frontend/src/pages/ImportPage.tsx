/**
 * Import page — v3 premium dark-first design.
 *
 *  - Refined hero with gradient mesh + pipeline stage pills
 *  - Upload zone with amber accent border
 *  - Project cards: title, filename, status/style/track badges
 *  - Stagger animation, hover lift + brand glow
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import GuitarIcon from "@mui/icons-material/MusicNote";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import { motion } from "framer-motion";
import UploadZone from "../components/UploadZone";
import { ProjectListSkeleton } from "../components/Skeletons";
import { projectsApi } from "../api/client";
import type { ProjectItem } from "../api/types";
import { palette } from "../styles/tokens";

const STAGE_PILLS = [
  "Quantize",
  "Measure Split",
  "Tie",
  "Voice",
  "Separation",
  "Fingering",
  "Articulation",
  "Assemble",
];

export default function ImportPage(): JSX.Element {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadProjects();
  }, []);

  async function loadProjects(): Promise<void> {
    setLoading(true);
    try {
      const data = await projectsApi.list();
      setProjects(data.items);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const handleFileSelected = useCallback(
    async (file: File): Promise<void> => {
      setUploading(true);
      setError(null);
      try {
        const project = await projectsApi.create(
          file,
          file.name.replace(/\.[^.]+$/, ""),
        );
        navigate(`/projects/${project.id}`);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setUploading(false);
      }
    },
    [navigate],
  );

  const statusColor = (status: string): string => {
    if (status === "repaired") return palette.success;
    if (status === "processing") return palette.warning;
    return palette.textTertiary;
  };

  return (
    <Box className="flex flex-col gap-8">
      {/* ── Hero ── */}
      <Box
        className="rounded-2xl overflow-hidden relative"
        sx={{
          background: `linear-gradient(135deg, ${palette.elevated} 0%, ${palette.surface} 50%, ${palette.canvas} 100%)`,
          border: `1px solid ${palette.borderDefault}`,
        }}
      >
        {/* Glow accent */}
        <Box
          sx={{
            position: "absolute",
            top: -60,
            right: -60,
            width: 200,
            height: 200,
            borderRadius: "50%",
            background: `radial-gradient(circle, ${palette.brandPrimary}15 0%, transparent 70%)`,
            pointerEvents: "none",
          }}
        />
        <Box className="px-6 py-8 sm:px-10 sm:py-12 relative">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <Chip
              size="small"
              label="MIDI → Tablature"
              sx={{
                backgroundColor: `${palette.brandPrimary}15`,
                color: palette.brandPrimary,
                fontWeight: 600,
                border: "none",
                mb: 3,
                fontSize: 12,
              }}
            />
            <Typography
              variant="h3"
              fontWeight={800}
              sx={{
                color: palette.textPrimary,
                mb: 2,
                letterSpacing: "-0.02em",
                lineHeight: 1.15,
              }}
            >
              Drop a MIDI file.
              <br />
              <span style={{ color: palette.brandPrimary }}>
                Get a playable tab.
              </span>
            </Typography>
            <Typography
              variant="body1"
              sx={{
                color: palette.textSecondary,
                maxWidth: 520,
                lineHeight: 1.6,
                fontSize: 15,
              }}
            >
              FretPilot runs an 8-stage repair pipeline — quantize, measure split,
              tie, voice, stream separation, fingering, articulation, assemble —
              to turn AI-generated guitar MIDI into professional six-line tablature.
            </Typography>
            {/* Pipeline pills */}
            <Box className="flex flex-wrap gap-1.5 mt-5">
              {STAGE_PILLS.map((stage, i) => (
                <motion.div
                  key={stage}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.2, delay: 0.3 + i * 0.04 }}
                >
                  <Chip
                    size="small"
                    label={stage}
                    sx={{
                      backgroundColor: palette.subtle,
                      color: palette.textTertiary,
                      border: `1px solid ${palette.borderDefault}`,
                      fontSize: 11,
                      fontWeight: 500,
                    }}
                  />
                </motion.div>
              ))}
            </Box>
          </motion.div>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ borderRadius: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* ── Upload ── */}
      {uploading ? (
        <Box
          className="flex items-center gap-3 py-10 rounded-xl"
          sx={{
            backgroundColor: palette.elevated,
            border: `1px solid ${palette.borderDefault}`,
            justifyContent: "center",
          }}
        >
          <CircularProgress size={24} sx={{ color: palette.brandPrimary }} />
          <Typography sx={{ color: palette.textSecondary, fontSize: 14 }}>
            Uploading and analyzing MIDI…
          </Typography>
        </Box>
      ) : (
        <UploadZone onFileSelected={handleFileSelected} />
      )}

      {/* ── Projects ── */}
      <Box className="flex items-center justify-between">
        <Box className="flex items-center gap-2">
          <Typography
            variant="h6"
            fontWeight={700}
            sx={{ color: palette.textPrimary, letterSpacing: "-0.01em" }}
          >
            Projects
          </Typography>
          {!loading && projects.length > 0 && (
            <Chip
              size="small"
              label={projects.length}
              sx={{
                backgroundColor: palette.subtle,
                color: palette.textTertiary,
                border: "none",
                fontWeight: 600,
                minWidth: 24,
              }}
            />
          )}
        </Box>
        <Button
          startIcon={<RefreshIcon />}
          variant="text"
          onClick={loadProjects}
          sx={{
            color: palette.textSecondary,
            textTransform: "none",
            fontSize: 13,
            "&:hover": { color: palette.brandPrimary },
          }}
        >
          Refresh
        </Button>
      </Box>

      {loading ? (
        <ProjectListSkeleton />
      ) : projects.length === 0 ? (
        <Box
          className="flex flex-col items-center justify-center py-16 gap-4 rounded-xl"
          sx={{
            backgroundColor: palette.elevated,
            border: `1px dashed ${palette.borderDefault}`,
          }}
        >
          <Box
            sx={{
              width: 56,
              height: 56,
              borderRadius: 3,
              backgroundColor: palette.subtle,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <MusicNoteIcon sx={{ fontSize: 28, color: palette.textTertiary }} />
          </Box>
          <Typography sx={{ color: palette.textSecondary, fontSize: 14 }}>
            No projects yet — upload a MIDI file to get started.
          </Typography>
        </Box>
      ) : (
        <Box className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((project, index) => (
            <motion.div
              key={project.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: index * 0.05 }}
              whileHover={{ y: -4 }}
            >
              <Box
                onClick={() => navigate(`/projects/${project.id}`)}
                className="cursor-pointer rounded-xl p-5 transition-all duration-200"
                sx={{
                  backgroundColor: palette.elevated,
                  border: `1px solid ${palette.borderDefault}`,
                  "&:hover": {
                    borderColor: `${palette.brandPrimary}60`,
                    boxShadow: `0 8px 24px rgba(232, 162, 75, 0.08)`,
                  },
                }}
              >
                {/* Top row: icon + title + arrow */}
                <Box className="flex items-start gap-3">
                  <Box
                    sx={{
                      width: 36,
                      height: 36,
                      borderRadius: 2,
                      backgroundColor: palette.subtle,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    <GuitarIcon sx={{ fontSize: 18, color: palette.brandPrimary }} />
                  </Box>
                  <Box className="flex-1 min-w-0">
                    <Typography
                      fontWeight={600}
                      sx={{
                        color: palette.textPrimary,
                        fontSize: 15,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {project.title}
                    </Typography>
                    <Typography
                      sx={{
                        color: palette.textTertiary,
                        fontSize: 12,
                        mt: 0.3,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {project.source_filename}
                    </Typography>
                  </Box>
                  <ArrowForwardIcon
                    sx={{
                      fontSize: 18,
                      color: palette.textTertiary,
                      flexShrink: 0,
                      transition: "color 0.2s",
                      "&:hover": { color: palette.brandPrimary },
                    }}
                  />
                </Box>

                {/* Bottom row: badges */}
                <Box className="flex items-center gap-1.5 mt-4 flex-wrap">
                  {/* Instrument family badge */}
                  {project.instrument_family === "mixed" && (
                    <Chip
                      size="small"
                      label="🎸 🥁"
                      sx={{
                        backgroundColor: `${palette.brandPrimary}15`,
                        color: palette.brandPrimary,
                        fontWeight: 600,
                        border: "none",
                        fontSize: 11,
                      }}
                    />
                  )}
                  {project.instrument_family && project.instrument_family !== "mixed" && (
                    <Chip
                      size="small"
                      label={project.instrument_family === "guitar" ? "🎸 guitar" : project.instrument_family === "drums" ? "🥁 drums" : project.instrument_family}
                      sx={{
                        backgroundColor: palette.subtle,
                        color: palette.textSecondary,
                        fontWeight: 500,
                        border: "none",
                        fontSize: 11,
                      }}
                    />
                  )}
                  <Chip
                    size="small"
                    label={project.status}
                    sx={{
                      backgroundColor: `${statusColor(project.status)}15`,
                      color: statusColor(project.status),
                      fontWeight: 500,
                      border: "none",
                      fontSize: 11,
                      textTransform: "capitalize",
                    }}
                  />
                  {project.style_label !== "unknown" && (
                    <Chip
                      size="small"
                      label={project.style_label}
                      sx={{
                        backgroundColor: `${palette.brandPrimary}12`,
                        color: palette.brandPrimary,
                        fontWeight: 500,
                        border: "none",
                        fontSize: 11,
                      }}
                    />
                  )}
                  {project.degraded_mode && (
                    <Chip
                      size="small"
                      label="degraded"
                      sx={{
                        backgroundColor: `${palette.warning}15`,
                        color: palette.warning,
                        fontWeight: 500,
                        border: "none",
                        fontSize: 11,
                      }}
                    />
                  )}
                </Box>
              </Box>
            </motion.div>
          ))}
        </Box>
      )}
    </Box>
  );
}
