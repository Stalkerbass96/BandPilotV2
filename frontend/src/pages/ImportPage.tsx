/**
 * Import page — upload MIDI, list projects as a card grid, navigate to workbench.
 *
 * Redesign:
 *  - Project list replaced with a responsive card grid.
 *  - Loading state uses ProjectListSkeleton.
 *  - Cards have hover micro-interactions (lift + shadow).
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Box, Button, Chip, CircularProgress, Typography } from "@mui/material";
import UploadIcon from "@mui/icons-material/Upload";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import RefreshIcon from "@mui/icons-material/Refresh";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import { motion } from "framer-motion";
import UploadZone from "../components/UploadZone";
import { ProjectListSkeleton } from "../components/Skeletons";
import { projectsApi } from "../api/client";
import type { ProjectItem } from "../api/types";
import { palette } from "../styles/tokens";

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
    <Box className="flex flex-col gap-6">
      <Box>
        <Typography
          variant="h5"
          fontWeight={600}
          sx={{ color: palette.textPrimary, mb: 1 }}
        >
          Import MIDI File
        </Typography>
        <Typography variant="body2" sx={{ color: palette.textSecondary }}>
          Upload an AI-generated guitar MIDI to begin the repair pipeline.
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ borderRadius: 2 }}>
          {error}
        </Alert>
      )}

      {uploading ? (
        <Box
          className="flex items-center gap-3 py-8 rounded-xl"
          sx={{
            backgroundColor: palette.elevated,
            border: `1px solid ${palette.borderDefault}`,
          }}
        >
          <CircularProgress size={24} />
          <Typography sx={{ color: palette.textSecondary }}>
            Uploading and analyzing MIDI…
          </Typography>
        </Box>
      ) : (
        <UploadZone onFileSelected={handleFileSelected} />
      )}

      <Box className="flex items-center justify-between">
        <Typography
          variant="h6"
          fontWeight={600}
          sx={{ color: palette.textPrimary }}
        >
          Your Projects
        </Typography>
        <Button
          startIcon={<RefreshIcon />}
          variant="text"
          onClick={loadProjects}
          sx={{ color: palette.brandPrimary, textTransform: "none" }}
        >
          Refresh
        </Button>
      </Box>

      {loading ? (
        <ProjectListSkeleton />
      ) : projects.length === 0 ? (
        <Box
          className="flex flex-col items-center justify-center py-12 gap-3 rounded-xl"
          sx={{
            backgroundColor: palette.elevated,
            border: `1px dashed ${palette.borderDefault}`,
          }}
        >
          <MusicNoteIcon sx={{ fontSize: 48, color: palette.textTertiary }} />
          <Typography sx={{ color: palette.textSecondary }}>
            No projects yet. Upload a MIDI file to get started.
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
                className="cursor-pointer rounded-xl p-5 transition-shadow duration-200"
                sx={{
                  backgroundColor: palette.elevated,
                  border: `1px solid ${palette.borderDefault}`,
                  "&:hover": {
                    borderColor: palette.brandPrimary,
                    boxShadow: "0 4px 20px rgba(99, 102, 241, 0.12)",
                  },
                }}
              >
                <Box className="flex items-start justify-between gap-2">
                  <Typography
                    fontWeight={600}
                    sx={{
                      color: palette.textPrimary,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      flex: 1,
                    }}
                  >
                    {project.title}
                  </Typography>
                  <ArrowForwardIcon
                    sx={{
                      fontSize: 20,
                      color: palette.textTertiary,
                      flexShrink: 0,
                    }}
                  />
                </Box>
                <Typography
                  variant="body2"
                  sx={{
                    color: palette.textSecondary,
                    mt: 0.5,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {project.source_filename}
                </Typography>
                <Box className="flex items-center gap-2 mt-3 flex-wrap">
                  <Chip
                    size="small"
                    label={project.status}
                    sx={{
                      backgroundColor: `${statusColor(project.status)}20`,
                      color: statusColor(project.status),
                      fontWeight: 500,
                      border: "none",
                    }}
                  />
                  {project.style_label !== "unknown" && (
                    <Chip
                      size="small"
                      label={project.style_label}
                      variant="outlined"
                      sx={{
                        borderColor: palette.borderDefault,
                        color: palette.textSecondary,
                      }}
                    />
                  )}
                  {project.degraded_mode && (
                    <Chip
                      size="small"
                      label="degraded"
                      sx={{
                        backgroundColor: `${palette.warning}20`,
                        color: palette.warning,
                        fontWeight: 500,
                        border: "none",
                      }}
                    />
                  )}
                </Box>
              </Box>
            </motion.div>
          ))}
        </Box>
      )}

      <Box>
        <Button
          startIcon={<UploadIcon />}
          variant="text"
          onClick={loadProjects}
          sx={{ color: palette.brandPrimary, textTransform: "none" }}
        >
          Refresh list
        </Button>
      </Box>
    </Box>
  );
}
