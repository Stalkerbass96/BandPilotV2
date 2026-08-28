import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import type { ScoreRational } from "../api/types";
import {
  AddIcon,
  ContentCopyIcon,
  ContentCutIcon,
  ContentPasteIcon,
  DeleteIcon,
  MusicNoteIcon,
  RemoveIcon,
} from "../icons";
import { palette } from "../styles/tokens";
import {
  equalRational,
  isFretted,
  WRITTEN_DURATIONS,
  type BeatContext,
  type NoteContext,
} from "./scoreEditing";

interface SelectionInspectorProps {
  beatContext: BeatContext | null;
  noteContext: NoteContext | null;
  disabled: boolean;
  canAddFirst: boolean;
  canPaste: boolean;
  selectionCount: number;
  techniqueLabels: string[];
  onAddFirst(kind: "notes" | "rest"): void;
  onInsertAfter(kind: "notes" | "rest"): void;
  onDuration(duration: ScoreRational): void;
  onDelete(): void;
  onCopy(): void;
  onCut(): void;
  onPaste(): void;
  onPitch(pitch: number): void;
  onString(stringNumber: number): void;
}

function noteName(pitch: number): string {
  const names = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];
  return `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}

export function SelectionInspector({
  beatContext,
  noteContext,
  disabled,
  canAddFirst,
  canPaste,
  selectionCount,
  techniqueLabels,
  onAddFirst,
  onInsertAfter,
  onDuration,
  onDelete,
  onCopy,
  onCut,
  onPaste,
  onPitch,
  onString,
}: SelectionInspectorProps): JSX.Element {
  const [pitchDraft, setPitchDraft] = useState("");
  useEffect(
    () => setPitchDraft(noteContext ? String(noteContext.note.pitch) : ""),
    [noteContext],
  );

  if (!beatContext) {
    return (
      <Box className="flex flex-col items-center text-center px-5 py-12">
        <MusicNoteIcon sx={{ color: palette.textTertiary, fontSize: 28 }} />
        <Typography sx={{ color: palette.textPrimary, fontWeight: 750, mt: 2 }}>
          Select a beat
        </Typography>
        <Typography sx={{ color: palette.textSecondary, fontSize: 12, lineHeight: 1.55, mt: 0.75 }}>
          Click a note, tab number or explicit rest to edit the musical event.
        </Typography>
        {canAddFirst && (
          <Box className="flex flex-col gap-2 mt-5 w-full">
            <Button
              onClick={() => onAddFirst("notes")}
              disabled={disabled}
              variant="contained"
              startIcon={<AddIcon />}
            >
              Add first note
            </Button>
            <Button onClick={() => onAddFirst("rest")} disabled={disabled} variant="outlined">
              Add first rest
            </Button>
          </Box>
        )}
      </Box>
    );
  }

  if (selectionCount > 1) {
    return (
      <Box className="flex flex-col min-h-0">
        <Box className="px-5 py-4">
          <Typography className="bp-eyebrow">Inspector</Typography>
          <Typography sx={{ color: palette.textPrimary, fontSize: 19, fontWeight: 820, mt: 0.75 }}>
            {selectionCount} beats selected
          </Typography>
          <Typography sx={{ color: palette.textSecondary, fontSize: 11.5, lineHeight: 1.55, mt: 1 }}>
            Shift + arrow extends the range. Range-safe commands appear in the edition toolbar.
          </Typography>
        </Box>
        <Divider />
        <Box className="px-5 py-5">
          <Typography sx={{ color: palette.textSecondary, fontSize: 11.5, lineHeight: 1.55 }}>
            Make rest and transpose are atomic for the complete range. Copy/paste and
            multi-beat rhythm rewriting remain disabled until their transaction semantics
            are implemented.
          </Typography>
        </Box>
      </Box>
    );
  }

  const fretted = Boolean(noteContext && isFretted(noteContext));
  const isDrum = beatContext.track.family === "drums";
  const tuning = Array.isArray(beatContext.track.instrument.tuning)
    ? beatContext.track.instrument.tuning.filter(
        (value): value is number => typeof value === "number",
      )
    : [];
  const commitPitch = (): void => {
    const next = Number(pitchDraft);
    if (noteContext && Number.isInteger(next) && next !== noteContext.note.pitch) {
      onPitch(next);
    } else {
      setPitchDraft(noteContext ? String(noteContext.note.pitch) : "");
    }
  };
  const title = noteContext
    ? isDrum
      ? String(noteContext.note.realization.piece ?? "Drum hit")
      : noteName(noteContext.note.pitch)
    : beatContext.beat.kind === "rest"
      ? "Rest"
      : `${beatContext.beat.notes.length}-note chord`;

  return (
    <Box className="flex flex-col min-h-0">
      <Box className="px-5 py-4">
        <Typography className="bp-eyebrow">Inspector</Typography>
        <Typography sx={{ color: palette.textPrimary, fontSize: 19, fontWeight: 820, mt: 0.75 }}>
          {title}
        </Typography>
        <Typography
          className="truncate"
          title={noteContext?.note.id ?? beatContext.beat.id}
          sx={{ color: palette.textTertiary, fontFamily: "monospace", fontSize: 10.5, mt: 0.5 }}
        >
          {noteContext?.note.id ?? beatContext.beat.id}
        </Typography>
      </Box>
      <Divider />
      <Box className="px-5 py-5 flex flex-col gap-5">
        {noteContext && (
          <Box>
            <Typography sx={{ color: palette.textPrimary, fontSize: 12, fontWeight: 750, mb: 1 }}>
              Pitch
            </Typography>
            {isDrum ? (
              <Box sx={{ background: palette.subtle, borderRadius: 2.5, p: 1.5 }}>
                <Typography sx={{ color: palette.textPrimary, fontSize: 12.5, fontWeight: 700 }}>
                  MIDI {noteContext.note.pitch}
                </Typography>
                <Typography sx={{ color: palette.textSecondary, fontSize: 11, mt: 0.4 }}>
                  Drum piece changes require a kit-aware operation.
                </Typography>
              </Box>
            ) : (
              <Box className="flex items-center gap-2">
                <Tooltip title="Down one semitone">
                  <span>
                    <IconButton
                      disabled={disabled || noteContext.note.pitch <= 0}
                      onClick={() => onPitch(noteContext.note.pitch - 1)}
                      size="small"
                      sx={{ border: `1px solid ${palette.borderDefault}` }}
                    >
                      <RemoveIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <TextField
                  value={pitchDraft}
                  onChange={(event) => setPitchDraft(event.target.value)}
                  onBlur={commitPitch}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") commitPitch();
                  }}
                  disabled={disabled}
                  inputProps={{ min: 0, max: 127, inputMode: "numeric", "aria-label": "MIDI pitch" }}
                  size="small"
                  sx={{ width: 88, "& input": { textAlign: "center", fontWeight: 800 } }}
                />
                <Tooltip title="Up one semitone">
                  <span>
                    <IconButton
                      disabled={disabled || noteContext.note.pitch >= 127}
                      onClick={() => onPitch(noteContext.note.pitch + 1)}
                      size="small"
                      sx={{ border: `1px solid ${palette.borderDefault}` }}
                    >
                      <AddIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
            )}
          </Box>
        )}

        {fretted && noteContext && (
          <Box>
            <Typography sx={{ color: palette.textPrimary, fontSize: 12, fontWeight: 750, mb: 1 }}>
              String & fret
            </Typography>
            <Box className="flex flex-wrap gap-1.5">
              {tuning.map((_pitch, index) => {
                const stringNumber = tuning.length - index;
                const fret = noteContext.note.pitch - tuning[index] - Number(beatContext.track.instrument.capo ?? 0);
                const available = fret >= 0 && fret <= Number(noteContext.track.instrument.fret_count ?? 24);
                const active = noteContext.note.realization.string === stringNumber;
                return (
                  <Button
                    key={stringNumber}
                    disabled={disabled || !available}
                    onClick={() => onString(stringNumber)}
                    size="small"
                    variant={active ? "contained" : "outlined"}
                    sx={{ minWidth: 44, px: 1, fontSize: 11 }}
                  >
                    {stringNumber} · {available ? fret : "—"}
                  </Button>
                );
              })}
            </Box>
            <Typography sx={{ color: palette.textTertiary, fontSize: 10.5, lineHeight: 1.5, mt: 1 }}>
              Each option shows string · fret. Unplayable positions are disabled.
            </Typography>
          </Box>
        )}

        <Box>
          <Typography sx={{ color: palette.textPrimary, fontSize: 12, fontWeight: 750, mb: 1 }}>
            Written duration
          </Typography>
          <Box className="grid grid-cols-3 gap-1.5">
            {WRITTEN_DURATIONS.map((duration) => (
              <Button
                key={duration.shortLabel}
                disabled={disabled}
                onClick={() => onDuration(duration.value)}
                size="small"
                variant={equalRational(beatContext.beat.duration, duration.value) ? "contained" : "outlined"}
                title={`${duration.label} note`}
                sx={{ minWidth: 0, fontSize: 10.5 }}
              >
                {duration.shortLabel}
              </Button>
            ))}
          </Box>
          <Box className="flex flex-wrap gap-1.5 mt-2.5">
            <Chip size="small" label={`Voice ${beatContext.beat.voice}`} />
            <Chip size="small" label={`Bar ${beatContext.measure.number}`} />
            {typeof beatContext.beat.properties.dynamic === "string" && (
              <Chip
                size="small"
                color="secondary"
                variant="outlined"
                label={`Dynamic ${beatContext.beat.properties.dynamic}`}
              />
            )}
            {(beatContext.beat.tie_in || beatContext.beat.tie_out) && (
              <Chip
                size="small"
                color="secondary"
                variant="outlined"
                label={beatContext.beat.tie_in && beatContext.beat.tie_out
                  ? "Tie continuation"
                  : beatContext.beat.tie_in ? "Tie destination" : "Tie origin"}
              />
            )}
            {techniqueLabels.map((technique) => (
              <Chip
                key={technique}
                size="small"
                color="primary"
                variant="outlined"
                label={technique}
              />
            ))}
          </Box>
        </Box>

        <Divider />
        <Box>
          <Typography sx={{ color: palette.textPrimary, fontSize: 12, fontWeight: 750, mb: 1 }}>
            Edit rhythm
          </Typography>
          <Box className="grid grid-cols-2 gap-1.5">
            <Button
              disabled={disabled}
              onClick={() => onInsertAfter("notes")}
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
            >
              Note after
            </Button>
            <Button disabled={disabled} onClick={() => onInsertAfter("rest")} size="small" variant="outlined">
              Rest after
            </Button>
            <Button disabled={disabled} onClick={onCopy} size="small" color="inherit" startIcon={<ContentCopyIcon />}>
              Copy beat
            </Button>
            <Button disabled={disabled || !canPaste} onClick={onPaste} size="small" color="inherit" startIcon={<ContentPasteIcon />}>
              Paste after
            </Button>
          </Box>
          <Box className="flex items-center gap-1.5 mt-1">
            <Button
              disabled={disabled}
              onClick={onCut}
              size="small"
              color="inherit"
              startIcon={<ContentCutIcon />}
            >
              Cut beat
            </Button>
            <Button
              disabled={disabled}
              onClick={onDelete}
              size="small"
              color="error"
              startIcon={<DeleteIcon />}
            >
              {noteContext ? "Delete note" : "Delete beat"}
            </Button>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
