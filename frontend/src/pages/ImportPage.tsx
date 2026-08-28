import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, MenuItem, TextField, Tooltip, Typography } from "@mui/material";
import { ArrowForwardIcon, CheckCircleIcon, MusicNoteIcon, RefreshIcon } from "../icons";
import UploadZone from "../components/UploadZone";
import { ProjectListSkeleton } from "../components/Skeletons";
import { projectsApi } from "../api/client";
import type { ProjectItem } from "../api/types";
import { palette } from "../styles/tokens";
import { apiErrorMessage } from "../utils/apiError";

function projectState(status: string): { label: string; color: string; action: string } {
  if (status === "repaired") return { label: "Ready", color: palette.success, action: "Open score" };
  if (status === "partial") return { label: "Review", color: palette.warning, action: "Review" };
  if (status === "processing") return { label: "Working", color: palette.info, action: "View progress" };
  return { label: "Draft", color: palette.textTertiary, action: "Continue" };
}

function instrumentLabel(family: string): string {
  if (family === "mixed") return "Full band";
  if (family === "guitar") return "Guitar";
  if (family === "drums") return "Drums";
  if (family === "keys") return "Keys";
  if (family === "bass") return "Bass";
  return "MIDI";
}

function projectRoute(project: ProjectItem): string {
  return !project.source_filename || project.status === "repaired" || project.status === "partial"
    ? `/projects/${project.id}/editor`
    : `/projects/${project.id}`;
}

export default function ImportPage(): JSX.Element {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [blankOpen, setBlankOpen] = useState(false);
  const [creatingBlank, setCreatingBlank] = useState(false);
  const [blankTitle, setBlankTitle] = useState("Untitled score");
  const [blankFamily, setBlankFamily] = useState<"guitar" | "drums" | "bass" | "keys" | "generic">("guitar");
  const [blankBpm, setBlankBpm] = useState(120);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void loadProjects(); }, []);

  async function loadProjects(): Promise<void> {
    setLoading(true);
    try { setProjects((await projectsApi.list()).items); }
    catch (err: unknown) { setError(apiErrorMessage(err, "We couldn’t load your projects.")); }
    finally { setLoading(false); }
  }

  const handleFileSelected = useCallback(async (file: File): Promise<void> => {
    setUploading(true); setError(null);
    try {
      const project = await projectsApi.create(file, file.name.replace(/\.[^.]+$/, ""));
      navigate(projectRoute(project));
    } catch (err: unknown) { setError(apiErrorMessage(err, "We couldn’t import this MIDI file.")); }
    finally { setUploading(false); }
  }, [navigate]);

  async function createBlankScore(): Promise<void> {
    if (!blankTitle.trim() || blankBpm < 20 || blankBpm > 400) return;
    setCreatingBlank(true); setError(null);
    try {
      const project = await projectsApi.createBlank({
        title: blankTitle.trim(),
        instrument_family: blankFamily,
        bpm: blankBpm,
        numerator: 4,
        denominator: 4,
      });
      navigate(`/projects/${project.id}/editor`);
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "We couldn’t create this blank score."));
      setBlankOpen(false);
    } finally { setCreatingBlank(false); }
  }

  return (
    <Box className="flex flex-col gap-10">
      <Box className="flex flex-col sm:flex-row sm:items-end justify-between gap-5">
        <Box>
          <Typography className="bp-eyebrow">MIDI to playable score</Typography>
          <Typography component="h1" sx={{ color: palette.textPrimary, fontSize: { xs: 34, md: 46 }, fontWeight: 850, letterSpacing: "-.045em", lineHeight: 1.06, mt: 1.5, maxWidth: 760 }}>
            Turn a MIDI into a score<br />you can actually play.
          </Typography>
          <Typography sx={{ color: palette.textSecondary, fontSize: 15, lineHeight: 1.7, mt: 2, maxWidth: 620 }}>
            BandPilot finds the instruments, creates practical fingerings and articulations, and gives you a professional score to review and export.
          </Typography>
        </Box>
        <Button onClick={() => setBlankOpen(true)} variant="outlined" startIcon={<MusicNoteIcon />} sx={{ flexShrink: 0 }}>Blank score</Button>
      </Box>

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

      <Dialog open={blankOpen} onClose={() => { if (!creatingBlank) setBlankOpen(false); }} fullWidth maxWidth="xs">
        <DialogTitle sx={{ fontWeight: 820 }}>Create a blank score</DialogTitle>
        <DialogContent className="flex flex-col gap-4" sx={{ pt: "12px !important" }}>
          <TextField autoFocus label="Score title" value={blankTitle} onChange={(event) => setBlankTitle(event.target.value)} fullWidth />
          <TextField select label="Instrument" value={blankFamily} onChange={(event) => setBlankFamily(event.target.value as typeof blankFamily)} fullWidth>
            <MenuItem value="guitar">Guitar</MenuItem><MenuItem value="bass">Bass</MenuItem><MenuItem value="drums">Drums</MenuItem><MenuItem value="keys">Keys</MenuItem><MenuItem value="generic">Standard notation</MenuItem>
          </TextField>
          <TextField label="Tempo" type="number" value={blankBpm} onChange={(event) => setBlankBpm(Number(event.target.value))} inputProps={{ min: 20, max: 400 }} helperText="4/4 · you can change meter in a later editor slice" fullWidth />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}><Button disabled={creatingBlank} onClick={() => setBlankOpen(false)}>Cancel</Button><Button disabled={creatingBlank || !blankTitle.trim() || blankBpm < 20 || blankBpm > 400} onClick={() => void createBlankScore()} variant="contained">{creatingBlank ? "Creating…" : "Create"}</Button></DialogActions>
      </Dialog>

      <Box className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-stretch">
        <Box className="lg:col-span-2">
          {uploading ? (
            <Box className="bp-card flex flex-col items-center justify-center gap-3 text-center" sx={{ minHeight: 280 }}>
              <CircularProgress size={30} />
              <Typography sx={{ color: palette.textPrimary, fontWeight: 800 }}>Reading your MIDI…</Typography>
              <Typography sx={{ color: palette.textSecondary, fontSize: 13 }}>This usually takes only a moment.</Typography>
            </Box>
          ) : <UploadZone onFileSelected={handleFileSelected} />}
        </Box>
        <Box className="bp-card p-6 sm:p-7 flex flex-col justify-between">
          <Box>
            <Typography sx={{ color: palette.textPrimary, fontWeight: 800, fontSize: 15 }}>What happens next</Typography>
            <Box className="flex flex-col gap-5 mt-6">
              {[
                ["1", "Check the band", "Confirm guitar, drums, bass, keys and other parts."],
                ["2", "Choose your intent", "Keep the original or favor easier, more natural playing."],
                ["3", "Review and export", "Preview the score, then download Guitar Pro, MusicXML or MIDI."],
              ].map(([number, title, body]) => (
                <Box key={number} className="flex gap-3">
                  <Box className="flex-shrink-0 flex items-center justify-center" sx={{ width: 26, height: 26, borderRadius: "50%", background: palette.subtle, color: palette.brandPrimary, fontSize: 11, fontWeight: 800 }}>{number}</Box>
                  <Box><Typography sx={{ color: palette.textPrimary, fontSize: 13, fontWeight: 750 }}>{title}</Typography><Typography sx={{ color: palette.textSecondary, fontSize: 11.5, lineHeight: 1.55, mt: .25 }}>{body}</Typography></Box>
                </Box>
              ))}
            </Box>
          </Box>
          <Box className="flex items-center gap-2 mt-6 pt-5" sx={{ borderTop: `1px solid ${palette.borderDefault}` }}>
            <CheckCircleIcon sx={{ color: palette.success, fontSize: 17 }} />
            <Typography sx={{ color: palette.textTertiary, fontSize: 11 }}>Your original MIDI is always preserved.</Typography>
          </Box>
        </Box>
      </Box>

      <Box>
        <Box className="flex items-end justify-between mb-4">
          <Box><Typography className="bp-eyebrow">Workspace</Typography><Typography sx={{ color: palette.textPrimary, fontSize: 22, fontWeight: 820, letterSpacing: "-.025em", mt: .75 }}>Your music</Typography></Box>
          <Tooltip title="Refresh projects"><IconButton onClick={() => void loadProjects()} size="small" aria-label="Refresh projects"><RefreshIcon fontSize="small" /></IconButton></Tooltip>
        </Box>

        {loading ? <ProjectListSkeleton /> : projects.length === 0 ? (
          <Box className="bp-card flex flex-col items-center text-center px-6 py-12">
            <MusicNoteIcon sx={{ color: palette.textTertiary, fontSize: 28 }} />
            <Typography sx={{ color: palette.textPrimary, fontWeight: 750, mt: 2 }}>Your first score will appear here</Typography>
            <Typography sx={{ color: palette.textSecondary, fontSize: 12.5, mt: .75 }}>Choose a MIDI above to get started.</Typography>
          </Box>
        ) : (
          <Box className="bp-card overflow-hidden">
            {projects.map((project, index) => {
              const state = projectState(project.status);
              return (
                <Box key={project.id} role="button" tabIndex={0} onClick={() => navigate(projectRoute(project))}
                  onKeyDown={(event) => { if (event.key === "Enter") navigate(projectRoute(project)); }}
                  className="flex items-center gap-4 px-5 py-4 cursor-pointer"
                  sx={{ borderTop: index ? `1px solid ${palette.borderDefault}` : "none", transition: "background .15s ease", "&:hover": { background: palette.surface } }}>
                  <Box className="flex items-center justify-center flex-shrink-0" sx={{ width: 42, height: 42, borderRadius: 2.5, background: palette.subtle, color: palette.brandPrimary }}><MusicNoteIcon sx={{ fontSize: 20 }} /></Box>
                  <Box className="flex-1 min-w-0">
                    <Typography className="truncate" sx={{ color: palette.textPrimary, fontSize: 14, fontWeight: 750 }}>{project.title}</Typography>
                    <Typography className="truncate" sx={{ color: palette.textTertiary, fontSize: 11.5, mt: .4 }}>{instrumentLabel(project.instrument_family)}{project.style_label !== "unknown" ? ` · ${project.style_label}` : ""} · {project.source_filename}</Typography>
                  </Box>
                  <Chip size="small" label={state.label} sx={{ background: `${state.color}14`, color: state.color, fontWeight: 750, fontSize: 11 }} />
                  <Button endIcon={<ArrowForwardIcon />} size="small" sx={{ color: palette.textPrimary, display: { xs: "none", sm: "inline-flex" } }}>{state.action}</Button>
                </Box>
              );
            })}
          </Box>
        )}
      </Box>
    </Box>
  );
}
