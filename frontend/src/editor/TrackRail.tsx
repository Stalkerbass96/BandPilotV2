import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Select,
  Slider,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import type { ScoreTrack, ScoreTrackMixer } from "../api/types";
import {
  AddIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DeleteIcon,
  SettingsIcon,
} from "../icons";
import { palette } from "../styles/tokens";
import {
  TRACK_FAMILIES,
  TRACK_NOTATION_MODES,
  formatTuning,
  parseTuning,
  type TrackFamily,
  type TrackSetupInput,
} from "./trackEditing";

interface TrackRailProps {
  tracks: ScoreTrack[];
  activeTrackId: string | null;
  disabled: boolean;
  onSelect(trackId: string): void;
  onAdd(family: TrackFamily): void;
  onMove(trackId: string, direction: -1 | 1): void;
  onMixer(trackId: string, mixer: ScoreTrackMixer): void;
  onSetup(trackId: string, input: TrackSetupInput): boolean;
  onDelete(trackId: string): void;
}

function familyOf(track: ScoreTrack): TrackFamily {
  return TRACK_FAMILIES.includes(track.family as TrackFamily)
    ? track.family as TrackFamily
    : "generic";
}

export function TrackRail({
  tracks,
  activeTrackId,
  disabled,
  onSelect,
  onAdd,
  onMove,
  onMixer,
  onSetup,
  onDelete,
}: TrackRailProps): JSX.Element {
  const ordered = [...tracks].sort((left, right) => left.order - right.order);
  const [addOpen, setAddOpen] = useState(false);
  const [setupTrackId, setSetupTrackId] = useState<string | null>(null);
  const setupTrack = ordered.find((track) => track.id === setupTrackId) ?? null;
  const family = setupTrack ? familyOf(setupTrack) : "generic";
  const [name, setName] = useState("");
  const [program, setProgram] = useState(0);
  const [capo, setCapo] = useState(0);
  const [tuning, setTuning] = useState("");
  const [notationMode, setNotationMode] = useState("standard");
  const [setupError, setSetupError] = useState<string | null>(null);

  const openSetup = (track: ScoreTrack): void => {
    setSetupTrackId(track.id);
    setName(track.name);
    setProgram(Number(track.instrument.program ?? 0));
    setCapo(Number(track.instrument.capo ?? 0));
    setTuning(Array.isArray(track.instrument.tuning) ? formatTuning(track.instrument.tuning as number[]) : "");
    setNotationMode(track.notation_mode);
    setSetupError(null);
  };

  return (
    <Box className="flex flex-col min-h-0 h-full">
      <Box className="flex items-center justify-between px-3 pt-3 pb-2">
        <Typography className="bp-eyebrow">Tracks</Typography>
        <Tooltip title="Add instrument track">
          <span>
            <IconButton
              aria-label="Add track"
              disabled={disabled}
              onClick={() => setAddOpen(true)}
              size="small"
            >
              <AddIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>
      <Box className="flex-1 overflow-y-auto px-2 pb-3">
        {ordered.map((track, index) => {
          const active = track.id === activeTrackId;
          const noteCount = track.measures.reduce((total, measure) => (
            total + measure.beats.reduce((count, beat) => count + beat.notes.length, 0)
          ), 0);
          return (
            <Box
              key={track.id}
              sx={{
                background: active ? "#FFFFFF" : "transparent",
                border: active ? `1px solid ${palette.borderDefault}` : "1px solid transparent",
                borderRadius: 2.5,
                mb: 0.75,
                boxShadow: active ? "0 1px 2px rgba(23,25,29,.04)" : "none",
                overflow: "hidden",
              }}
            >
              <Button
                fullWidth
                onClick={() => onSelect(track.id)}
                sx={{
                  color: active ? palette.textPrimary : palette.textSecondary,
                  justifyContent: "flex-start",
                  px: 1.25,
                  py: 1,
                  textAlign: "left",
                  textTransform: "none",
                }}
              >
                <Box className="min-w-0">
                  <Typography className="truncate" sx={{ fontSize: 12.5, fontWeight: active ? 800 : 650 }}>
                    {track.name}
                  </Typography>
                  <Typography sx={{ color: palette.textTertiary, fontSize: 10, mt: 0.2 }}>
                    {familyOf(track)} · {noteCount} notes
                  </Typography>
                </Box>
              </Button>
              {active && (
                <Box sx={{ borderTop: `1px solid ${palette.borderDefault}`, px: 1, pb: 1 }}>
                  <Box className="flex items-center gap-0.5 py-0.5">
                    <Button
                      aria-label="Mute track"
                      color={track.mixer.mute ? "primary" : "inherit"}
                      disabled={disabled}
                      onClick={() => onMixer(track.id, { ...track.mixer, mute: !track.mixer.mute })}
                      size="small"
                      sx={{ minWidth: 27, px: 0.5, fontSize: 10, fontWeight: 900 }}
                    >M</Button>
                    <Button
                      aria-label="Solo track"
                      color={track.mixer.solo ? "primary" : "inherit"}
                      disabled={disabled}
                      onClick={() => onMixer(track.id, { ...track.mixer, solo: !track.mixer.solo })}
                      size="small"
                      sx={{ minWidth: 27, px: 0.5, fontSize: 10, fontWeight: 900 }}
                    >S</Button>
                    <Box className="ml-auto flex items-center">
                      <Tooltip title="Move track up"><span><IconButton aria-label="Move track up" disabled={disabled || index === 0} onClick={() => onMove(track.id, -1)} size="small"><ChevronLeftIcon sx={{ transform: "rotate(90deg)", fontSize: 16 }} /></IconButton></span></Tooltip>
                      <Tooltip title="Move track down"><span><IconButton aria-label="Move track down" disabled={disabled || index === ordered.length - 1} onClick={() => onMove(track.id, 1)} size="small"><ChevronRightIcon sx={{ transform: "rotate(90deg)", fontSize: 16 }} /></IconButton></span></Tooltip>
                      <Tooltip title="Track setup"><span><IconButton aria-label="Track setup" disabled={disabled} onClick={() => openSetup(track)} size="small"><SettingsIcon sx={{ fontSize: 16 }} /></IconButton></span></Tooltip>
                    </Box>
                  </Box>
                  <Box className="grid grid-cols-[24px_1fr] items-center gap-x-1">
                    <Typography sx={{ color: palette.textTertiary, fontSize: 9 }}>VOL</Typography>
                    <Slider
                      aria-label="Track volume"
                      defaultValue={track.mixer.volume}
                      disabled={disabled}
                      key={`${track.id}:volume:${track.mixer.volume}`}
                      max={1}
                      min={0}
                      onChangeCommitted={(_event, value) => onMixer(track.id, { ...track.mixer, volume: value as number })}
                      size="small"
                      step={0.01}
                    />
                    <Typography sx={{ color: palette.textTertiary, fontSize: 9 }}>PAN</Typography>
                    <Slider
                      aria-label="Track pan"
                      defaultValue={track.mixer.pan}
                      disabled={disabled}
                      key={`${track.id}:pan:${track.mixer.pan}`}
                      max={1}
                      min={-1}
                      onChangeCommitted={(_event, value) => onMixer(track.id, { ...track.mixer, pan: value as number })}
                      size="small"
                      step={0.01}
                    />
                  </Box>
                </Box>
              )}
            </Box>
          );
        })}
      </Box>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Add instrument track</DialogTitle>
        <DialogContent>
          <Typography sx={{ color: palette.textSecondary, fontSize: 12, mb: 2 }}>
            The new track uses the current score timeline and starts empty.
          </Typography>
          <Box className="grid grid-cols-2 gap-2">
            {TRACK_FAMILIES.map((value) => (
              <Button key={value} variant="outlined" onClick={() => { onAdd(value); setAddOpen(false); }}>
                {value === "generic" ? "Notation" : value}
              </Button>
            ))}
          </Box>
        </DialogContent>
        <DialogActions><Button onClick={() => setAddOpen(false)}>Cancel</Button></DialogActions>
      </Dialog>

      <Dialog open={Boolean(setupTrack)} onClose={() => setSetupTrackId(null)} fullWidth maxWidth="xs">
        <DialogTitle>Track setup</DialogTitle>
        {setupTrack && (
          <DialogContent className="flex flex-col gap-3" sx={{ pt: "8px !important" }}>
            {setupError && <Alert severity="error">{setupError}</Alert>}
            <TextField label="Track name" size="small" value={name} onChange={(event) => setName(event.target.value)} />
            <TextField label="MIDI program" size="small" type="number" value={program} onChange={(event) => setProgram(Number(event.target.value))} inputProps={{ min: 0, max: 127 }} />
            <Select size="small" value={notationMode} onChange={(event) => setNotationMode(event.target.value)}>
              {TRACK_NOTATION_MODES[family].map((mode) => <MenuItem key={mode.value} value={mode.value}>{mode.label}</MenuItem>)}
            </Select>
            {(family === "guitar" || family === "bass") && (
              <>
                <TextField label="Tuning (low → high)" helperText="Example: E2 A2 D3 G3 B3 E4. Retuning preserves pitch and recalculates frets." size="small" value={tuning} onChange={(event) => setTuning(event.target.value)} />
                <TextField label="Capo" size="small" type="number" value={capo} onChange={(event) => setCapo(Number(event.target.value))} inputProps={{ min: 0, max: 24 }} />
              </>
            )}
          </DialogContent>
        )}
        <DialogActions>
          {setupTrack && tracks.length > 1 && !setupTrack.measures.some((measure) => measure.beats.some((beat) => beat.notes.length > 0)) && (
            <Button color="error" startIcon={<DeleteIcon />} onClick={() => { onDelete(setupTrack.id); setSetupTrackId(null); }}>Delete empty track</Button>
          )}
          <Box className="flex-1" />
          <Button onClick={() => setSetupTrackId(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              if (!setupTrack) return;
              try {
                const accepted = onSetup(setupTrack.id, {
                  name,
                  notationMode,
                  program,
                  capo,
                  tuning: family === "guitar" || family === "bass"
                    ? parseTuning(tuning)
                    : null,
                });
                if (accepted) setSetupTrackId(null);
                else setSetupError("This setup cannot preserve the current playable notation.");
              } catch (caught) {
                setSetupError(caught instanceof Error ? caught.message : "The tuning is invalid.");
              }
            }}
          >Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
