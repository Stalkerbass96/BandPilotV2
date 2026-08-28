import { useCallback, useRef, useState } from "react";
import { Box, Button, Typography } from "@mui/material";
import { CloudUploadIcon, MusicNoteIcon } from "../icons";
import { palette } from "../styles/tokens";

interface UploadZoneProps { onFileSelected: (file: File) => void; accept?: string; disabled?: boolean }

export default function UploadZone({ onFileSelected, accept = ".mid,.midi", disabled = false }: UploadZoneProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const useFile = useCallback((file?: File): void => {
    if (!disabled && file && /\.(mid|midi)$/i.test(file.name)) onFileSelected(file);
  }, [disabled, onFileSelected]);

  return (
    <Box role="button" tabIndex={disabled ? -1 : 0} aria-label="Choose a MIDI file"
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") inputRef.current?.click(); }}
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); useFile(event.dataTransfer.files[0]); }}
      className="flex flex-col items-center justify-center text-center cursor-pointer"
      sx={{ minHeight: 280, px: 4, py: 6, borderRadius: 4, border: `1.5px dashed ${dragging ? palette.brandPrimary : palette.borderHover}`,
        background: dragging ? "rgba(232,100,45,.06)" : "linear-gradient(145deg, #fff 0%, #fbfaf7 100%)",
        boxShadow: dragging ? "0 12px 34px rgba(232,100,45,.10)" : "none", transition: "all .18s ease", opacity: disabled ? .6 : 1,
        "&:hover": { borderColor: palette.brandPrimary, transform: disabled ? "none" : "translateY(-2px)" } }}>
      <input ref={inputRef} hidden type="file" accept={accept} onChange={(event) => useFile(event.target.files?.[0])} />
      <Box className="flex items-center justify-center" sx={{ width: 58, height: 58, borderRadius: "50%", background: "rgba(232,100,45,.10)", color: palette.brandPrimary, mb: 2.5 }}>
        {dragging ? <CloudUploadIcon sx={{ fontSize: 28 }} /> : <MusicNoteIcon sx={{ fontSize: 28 }} />}
      </Box>
      <Typography sx={{ color: palette.textPrimary, fontSize: 20, fontWeight: 800, letterSpacing: "-.02em" }}>{dragging ? "Release to start" : "Start with your MIDI"}</Typography>
      <Typography sx={{ color: palette.textSecondary, fontSize: 13, mt: 1, mb: 2.5, maxWidth: 340, lineHeight: 1.6 }}>We’ll identify the instruments and prepare a playable first draft. You stay in control before anything changes.</Typography>
      <Button variant="contained" startIcon={<CloudUploadIcon />} tabIndex={-1} sx={{ px: 3 }}>Choose MIDI file</Button>
      <Typography sx={{ color: palette.textTertiary, fontSize: 11, mt: 1.5 }}>.mid or .midi · up to 20 MB</Typography>
    </Box>
  );
}
