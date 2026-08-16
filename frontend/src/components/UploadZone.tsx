/**
 * UploadZone — large drag-and-drop MIDI file upload component.
 *
 * Design:
 *  - Large drop area with brand-colored border.
 *  - On drag-over the background tints brand-primary and the border solidifies.
 *  - Selected file shows a compact summary card.
 */

import { useCallback, useRef, useState } from "react";
import { Box, Typography } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import AudioFileIcon from "@mui/icons-material/AudioFile";
import { motion } from "framer-motion";
import { palette } from "../styles/tokens";

interface UploadZoneProps {
  onFileSelected: (file: File) => void;
  accept?: string;
  disabled?: boolean;
}

export default function UploadZone({
  onFileSelected,
  accept = ".mid,.midi",
  disabled = false,
}: UploadZoneProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled) return;
      const file = e.dataTransfer.files[0];
      if (file && file.name.match(/\.(mid|midi)$/i)) {
        setSelectedFile(file);
        onFileSelected(file);
      }
    },
    [onFileSelected, disabled],
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      onFileSelected(file);
    }
  };

  return (
    <motion.div
      whileHover={{ scale: disabled ? 1 : 1.005 }}
      whileTap={{ scale: disabled ? 1 : 0.995 }}
      transition={{ duration: 0.15 }}
    >
      <Box
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className="flex flex-col items-center justify-center gap-3 text-center cursor-pointer transition-all duration-200"
        sx={{
          border: `2px dashed ${isDragging ? palette.brandPrimary : palette.borderDefault}`,
          borderRadius: 3,
          p: 6,
          minHeight: 200,
          opacity: disabled ? 0.6 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
          backgroundColor: isDragging
            ? "rgba(99, 102, 241, 0.06)"
            : palette.canvas,
          transition: "all 0.2s ease",
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          hidden
          onChange={handleFileInput}
        />
        {selectedFile ? (
          <Box className="flex flex-col items-center gap-2">
            <AudioFileIcon
              sx={{ fontSize: 56, color: palette.brandPrimary }}
            />
            <Typography
              variant="body1"
              fontWeight={600}
              sx={{ color: palette.textPrimary }}
            >
              {selectedFile.name}
            </Typography>
            <Typography variant="caption" sx={{ color: palette.textSecondary }}>
              {(selectedFile.size / 1024).toFixed(1)} KB — click to change
            </Typography>
          </Box>
        ) : (
          <Box className="flex flex-col items-center gap-2">
            <CloudUploadIcon
              sx={{
                fontSize: 56,
                color: isDragging ? palette.brandPrimary : palette.textTertiary,
                transition: "color 0.2s ease",
              }}
            />
            <Typography
              variant="body1"
              fontWeight={500}
              sx={{ color: palette.textSecondary }}
            >
              {isDragging
                ? "Drop your MIDI file here"
                : "Drag & drop a MIDI file here, or click to browse"}
            </Typography>
            <Typography variant="caption" sx={{ color: palette.textTertiary }}>
              Supports .mid and .midi files (max 20 MB)
            </Typography>
          </Box>
        )}
      </Box>
    </motion.div>
  );
}
