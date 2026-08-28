import { Box, Button, ButtonGroup, Divider, Tooltip, Typography } from "@mui/material";
import type { ScoreRational } from "../api/types";
import { palette } from "../styles/tokens";
import {
  DRUM_INPUT_PIECES,
  DYNAMIC_INPUTS,
  equalRational,
  PITCH_CLASS_INPUTS,
  WRITTEN_DURATIONS,
} from "./scoreEditing";

interface EditionToolbarProps {
  duration: ScoreRational;
  durationModifier: "dot" | "triplet" | null;
  family: string | null;
  voice: number;
  caretString: number | null;
  activeDrumPiece: string | null;
  pitchOctave: number;
  activePitch: number | null;
  stringCount: number;
  selectionCount: number;
  selectedNoteCount: number;
  activeTechniques: string[];
  activeDynamic: string | null;
  canTie: boolean;
  tieActive: boolean;
  canTranspose: boolean;
  canEditMeasure: boolean;
  canDeleteMeasure: boolean;
  disabled: boolean;
  onDuration(duration: ScoreRational): void;
  onDurationModifier(modifier: "dot" | "triplet"): void;
  onVoice(voice: number): void;
  onString(stringNumber: number): void;
  onDrumPiece(piece: string): void;
  onPitchOctave(octave: number): void;
  onPitchedNote(pitchClass: number): void;
  onInsert(kind: "notes" | "rest"): void;
  onMakeRest(): void;
  onTechnique(type: string): void;
  onDynamic(label: string, velocity: number): void;
  onTie(): void;
  onTranspose(semitones: number): void;
  onInsertMeasure(): void;
  onDuplicateMeasure(): void;
  onDeleteMeasure(): void;
}

export function EditionToolbar({
  duration,
  durationModifier,
  family,
  voice,
  caretString,
  activeDrumPiece,
  pitchOctave,
  activePitch,
  stringCount,
  selectionCount,
  selectedNoteCount,
  activeTechniques,
  activeDynamic,
  canTie,
  tieActive,
  canTranspose,
  canEditMeasure,
  canDeleteMeasure,
  disabled,
  onDuration,
  onDurationModifier,
  onVoice,
  onString,
  onDrumPiece,
  onPitchOctave,
  onPitchedNote,
  onInsert,
  onMakeRest,
  onTechnique,
  onDynamic,
  onTie,
  onTranspose,
  onInsertMeasure,
  onDuplicateMeasure,
  onDeleteMeasure,
}: EditionToolbarProps): JSX.Element {
  const fretted = family === "guitar" || family === "bass";
  const techniqueInputs = [
    { type: "palm_mute", label: "P.M.", title: "Palm mute", frettedOnly: true },
    { type: "let_ring", label: "Let ring", title: "Let ring", frettedOnly: true },
    { type: "staccato", label: "Stacc.", title: "Staccato" },
    { type: "accent", label: "Accent", title: "Accent" },
    { type: "ghost_note", label: "Ghost", title: "Ghost note" },
    { type: "bend", label: "Bend", title: "One-semitone bend", frettedOnly: true },
    { type: "harmonic", label: "Harm.", title: "Natural harmonic", frettedOnly: true },
    { type: "vibrato", label: "Vibr.", title: "Vibrato", pitchedOnly: true },
    { type: "hammer_on", label: "H", title: "Hammer-on · select exactly two notes", linked: true },
    { type: "pull_off", label: "P", title: "Pull-off · select exactly two notes", linked: true },
    { type: "slide", label: "Slide", title: "Shift slide · select exactly two notes", linked: true },
  ];
  return (
    <Box
      data-testid="edition-toolbar"
      className="flex flex-col flex-shrink-0"
      sx={{
        minHeight: 92,
        background: "#F7F7F8",
        borderBottom: `1px solid ${palette.borderDefault}`,
      }}
    >
      <Box
        className="flex items-center gap-3 px-3 overflow-x-auto flex-shrink-0"
        sx={{ minHeight: 46, borderBottom: "1px solid #E9E9EB", scrollbarWidth: "none", "&::-webkit-scrollbar": { display: "none" } }}
      >
        <Box className="flex items-center gap-1 flex-shrink-0">
        <Typography className="bp-eyebrow" sx={{ mr: 0.75 }}>Duration</Typography>
        <ButtonGroup size="small" aria-label="Input duration">
          {WRITTEN_DURATIONS.map((item) => (
            <Tooltip key={item.shortLabel} title={`${item.label} note`}>
              <span className="inline-flex">
                <Button
                  disabled={disabled}
                  onClick={() => onDuration(item.value)}
                  variant={equalRational(duration, item.value) ? "contained" : "outlined"}
                  sx={{ minWidth: 38, px: 0.75, fontSize: 10.5 }}
                >
                  {item.shortLabel.replace("1/", "")}
                </Button>
              </span>
            </Tooltip>
          ))}
        </ButtonGroup>
        <Button
          aria-label="Toggle dotted duration"
          size="small"
          disabled={disabled}
          onClick={() => onDurationModifier("dot")}
          variant={durationModifier === "dot" ? "contained" : "text"}
          color={durationModifier === "dot" ? "primary" : "inherit"}
          sx={{ minWidth: 30, px: 0.5 }}
        >
          ·
        </Button>
        <Button
          aria-label="Toggle triplet duration"
          size="small"
          disabled={disabled}
          onClick={() => onDurationModifier("triplet")}
          variant={durationModifier === "triplet" ? "contained" : "text"}
          color={durationModifier === "triplet" ? "primary" : "inherit"}
          sx={{ minWidth: 30, px: 0.5, fontSize: 10.5 }}
        >
          3
        </Button>
        </Box>
        <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
        <Box className="flex items-center gap-1 flex-shrink-0">
        <Typography className="bp-eyebrow" sx={{ mr: 0.75 }}>Voice</Typography>
        {[1, 2, 3, 4].map((candidate) => (
          <Button
            key={candidate}
            aria-label={`Voice ${candidate}`}
            size="small"
            color={candidate === voice ? "primary" : "inherit"}
            variant={candidate === voice ? "contained" : "text"}
            disabled={disabled}
            onClick={() => onVoice(candidate)}
            sx={{ minWidth: 28, px: 0.5 }}
          >
            {candidate}
          </Button>
        ))}
        </Box>
        {fretted && stringCount > 0 && (
          <>
            <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
            <Box className="flex items-center gap-1 flex-shrink-0">
            <Typography className="bp-eyebrow" sx={{ mr: 0.75 }}>String</Typography>
            {Array.from({ length: stringCount }, (_, index) => index + 1).map((stringNumber) => (
              <Button
                key={stringNumber}
                aria-label={`String ${stringNumber}`}
                size="small"
                disabled={disabled}
                onClick={() => onString(stringNumber)}
                variant={caretString === stringNumber ? "contained" : "text"}
                color={caretString === stringNumber ? "primary" : "inherit"}
                sx={{ minWidth: 28, px: 0.5 }}
              >
                {stringNumber}
              </Button>
            ))}
            </Box>
          </>
        )}
        {family === "drums" && (
          <>
            <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
            <Box className="flex items-center gap-1 flex-shrink-0">
              <Typography className="bp-eyebrow" sx={{ mr: 0.75 }}>Kit</Typography>
              {DRUM_INPUT_PIECES.map((item) => (
                <Tooltip key={item.piece} title={`${item.label} · Voice ${item.voice}`}>
                  <span className="inline-flex">
                    <Button
                      aria-label={`Drum ${item.label}`}
                      size="small"
                      disabled={disabled}
                      onClick={() => onDrumPiece(item.piece)}
                      variant={activeDrumPiece === item.piece ? "contained" : "text"}
                      color={activeDrumPiece === item.piece ? "primary" : "inherit"}
                      sx={{ minWidth: 0, px: 0.65, fontSize: 10.5 }}
                    >
                      {item.label}
                    </Button>
                  </span>
                </Tooltip>
              ))}
            </Box>
          </>
        )}
        {(family === "keys" || family === "generic") && (
          <>
            <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
            <Box className="flex items-center gap-0.5 flex-shrink-0">
              <Typography className="bp-eyebrow" sx={{ mr: 0.5 }}>Pitch</Typography>
              <Button
                aria-label="Previous octave"
                size="small"
                disabled={disabled || pitchOctave <= -1}
                onClick={() => onPitchOctave(pitchOctave - 1)}
                color="inherit"
                sx={{ minWidth: 24, px: 0.25 }}
              >−</Button>
              <Typography sx={{ color: palette.textSecondary, fontSize: 10.5, minWidth: 28, textAlign: "center" }}>
                O{pitchOctave}
              </Typography>
              <Button
                aria-label="Next octave"
                size="small"
                disabled={disabled || pitchOctave >= 9}
                onClick={() => onPitchOctave(pitchOctave + 1)}
                color="inherit"
                sx={{ minWidth: 24, px: 0.25 }}
              >+</Button>
              {PITCH_CLASS_INPUTS.map((item) => {
                const pitch = (pitchOctave + 1) * 12 + item.pitchClass;
                return (
                  <Button
                    key={item.pitchClass}
                    aria-label={`Enter ${item.label}${pitchOctave}`}
                    size="small"
                    disabled={disabled || pitch > 127}
                    onClick={() => onPitchedNote(item.pitchClass)}
                    variant={activePitch === pitch ? "contained" : "text"}
                    color={activePitch === pitch ? "primary" : "inherit"}
                    sx={{ minWidth: 27, px: 0.35, fontSize: 10.5 }}
                  >
                    {item.label}
                  </Button>
                );
              })}
            </Box>
          </>
        )}
      </Box>
      <Box
        className="flex items-center gap-3 px-3 overflow-x-auto flex-shrink-0"
        sx={{ minHeight: 46, scrollbarWidth: "none", "&::-webkit-scrollbar": { display: "none" } }}
      >
        <Box className="flex items-center gap-1 flex-shrink-0">
        <Typography className="bp-eyebrow" sx={{ mr: 0.5 }}>Dynamics</Typography>
        {DYNAMIC_INPUTS.map((item) => (
          <Button
            key={item.label}
            aria-label={`Dynamic ${item.label}`}
            size="small"
            disabled={disabled || selectedNoteCount === 0}
            onClick={() => onDynamic(item.label, item.velocity)}
            variant={activeDynamic === item.label ? "contained" : "text"}
            color={activeDynamic === item.label ? "primary" : "inherit"}
            sx={{ minWidth: 28, px: 0.45, fontSize: 10.5, fontStyle: "italic" }}
          >
            {item.label}
          </Button>
        ))}
        </Box>
        <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
        <Box className="flex items-center gap-1 flex-shrink-0">
        <Typography className="bp-eyebrow" sx={{ mr: 0.75 }}>Technique</Typography>
        <Tooltip title="Tie to the adjacent matching beat">
          <span>
            <Button
              aria-label="Tie adjacent notes"
              size="small"
              disabled={disabled || !canTie}
              onClick={onTie}
              variant={tieActive ? "contained" : "text"}
              color={tieActive ? "primary" : "inherit"}
              sx={{ minWidth: 0, px: 0.75, fontSize: 10.5 }}
            >
              Tie
            </Button>
          </span>
        </Tooltip>
        {techniqueInputs.map((item) => {
          const unavailable = (
            selectedNoteCount === 0 ||
            (item.frettedOnly && !fretted) ||
            (item.pitchedOnly && family === "drums") ||
            (item.linked && (!fretted || selectedNoteCount !== 2))
          );
          return (
            <Tooltip key={item.type} title={item.title}>
              <span>
                <Button
                  aria-label={item.title}
                  size="small"
                  disabled={disabled || unavailable}
                  onClick={() => onTechnique(item.type)}
                  variant={activeTechniques.includes(item.type) ? "contained" : "text"}
                  color={activeTechniques.includes(item.type) ? "primary" : "inherit"}
                  sx={{ minWidth: 0, px: 0.75, fontSize: 10.5 }}
                >
                  {item.label}
                </Button>
              </span>
            </Tooltip>
          );
        })}
        </Box>
        <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
        <Box className="flex items-center gap-1 flex-shrink-0">
        <Typography className="bp-eyebrow" sx={{ mr: 0.5 }}>Transpose</Typography>
        {[-12, -1, 1, 12].map((semitones) => (
          <Button
            key={semitones}
            size="small"
            disabled={disabled || selectedNoteCount === 0 || !canTranspose}
            onClick={() => onTranspose(semitones)}
            color="inherit"
            sx={{ minWidth: 32, px: 0.5, fontSize: 10.5 }}
          >
            {semitones > 0 ? `+${semitones}` : semitones}
          </Button>
        ))}
        </Box>
        <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
        <Box className="flex items-center gap-1.5 flex-shrink-0">
        <Button disabled={disabled} size="small" variant="outlined" onClick={() => onInsert("notes")}>
          Insert beat
        </Button>
        <Button disabled={disabled} size="small" color="inherit" onClick={() => onInsert("rest")}>
          Insert rest
        </Button>
        <Button
          disabled={disabled || selectionCount === 0}
          size="small"
          color="inherit"
          onClick={onMakeRest}
        >
          Make rest
        </Button>
        </Box>
        <Divider orientation="vertical" flexItem sx={{ my: 1.1 }} />
        <Box className="flex items-center gap-1 flex-shrink-0">
        <Typography className="bp-eyebrow" sx={{ mr: 0.5 }}>Bar</Typography>
        <Button
          aria-label="Add bar after"
          disabled={disabled || !canEditMeasure}
          size="small"
          color="inherit"
          onClick={onInsertMeasure}
          sx={{ minWidth: 0, px: 0.75, fontSize: 10.5 }}
        >
          + Bar
        </Button>
        <Button
          aria-label="Duplicate bar"
          disabled={disabled || !canEditMeasure}
          size="small"
          color="inherit"
          onClick={onDuplicateMeasure}
          sx={{ minWidth: 0, px: 0.75, fontSize: 10.5 }}
        >
          Duplicate
        </Button>
        <Button
          aria-label="Delete bar"
          disabled={disabled || !canDeleteMeasure}
          size="small"
          color="error"
          onClick={onDeleteMeasure}
          sx={{ minWidth: 0, px: 0.75, fontSize: 10.5 }}
        >
          Delete
        </Button>
        </Box>
      </Box>
    </Box>
  );
}

interface EditorStatusBarProps {
  trackName: string | null;
  family: string | null;
  measure: number | null;
  voice: number;
  caretString: number | null;
  selectedBeatCount: number;
  fretBuffer: string;
  scoreScale: number;
  scoreLayout: "page" | "horizontal";
}

export function EditorStatusBar({
  trackName,
  family,
  measure,
  voice,
  caretString,
  selectedBeatCount,
  fretBuffer,
  scoreScale,
  scoreLayout,
}: EditorStatusBarProps): JSX.Element {
  return (
    <Box
      data-testid="editor-status-bar"
      className="flex items-center gap-3 px-3 flex-shrink-0"
      sx={{
        minHeight: 28,
        background: "#20242B",
        color: "#D8DADE",
        borderTop: "1px solid #101217",
      }}
    >
      <Typography sx={{ fontSize: 10.5, fontWeight: 750 }}>{trackName ?? "No track"}</Typography>
      <Typography sx={{ color: "#858B95", fontSize: 10.5 }}>
        {family ?? "notation"} · Bar {measure ?? "—"} · Voice {voice}
      </Typography>
      {caretString !== null && (
        <Typography sx={{ color: "#B6BAC1", fontSize: 10.5 }}>String {caretString}</Typography>
      )}
      {selectedBeatCount > 1 && (
        <Typography sx={{ color: "#F4A261", fontSize: 10.5, fontWeight: 750 }}>
          {selectedBeatCount} beats selected
        </Typography>
      )}
      {fretBuffer && (
        <Box
          className="ml-auto px-2 py-0.5"
          sx={{ background: "#E76F3C", borderRadius: 1, color: "#FFFFFF" }}
        >
          <Typography sx={{ fontSize: 10.5, fontWeight: 850 }}>Fret {fretBuffer}</Typography>
        </Box>
      )}
      <Typography className={fretBuffer ? undefined : "ml-auto"} sx={{ color: "#858B95", fontSize: 10, whiteSpace: "nowrap" }}>
        {scoreLayout === "page" ? "Page" : "Horizontal"} · Zoom {Math.round(scoreScale * 100)}%
      </Typography>
      {!fretBuffer && (
        <Typography sx={{ color: "#858B95", fontSize: 10, whiteSpace: "nowrap" }}>
          ⌘K commands · ← → beat · ⇧ select · ↑ ↓ string · type fret
        </Typography>
      )}
    </Box>
  );
}
