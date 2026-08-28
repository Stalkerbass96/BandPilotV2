import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Dialog,
  DialogContent,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  TextField,
  Typography,
} from "@mui/material";
import { BoltIcon } from "../icons";
import { palette } from "../styles/tokens";

export interface EditorCommand {
  id: string;
  label: string;
  group: "Edit" | "Navigate" | "Playback" | "Project";
  description?: string;
  shortcut?: string;
  keywords?: string[];
  hiddenUntilSearch?: boolean;
  disabled?: boolean;
  run(): void;
}

export function filterEditorCommands(
  commands: readonly EditorCommand[],
  query: string,
): EditorCommand[] {
  const tokens = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) {
    return commands.filter((command) => !command.hiddenUntilSearch);
  }
  return commands.filter((command) => {
    const searchable = [
      command.label,
      command.group,
      command.description,
      command.shortcut,
      ...(command.keywords ?? []),
    ].filter(Boolean).join(" ").toLocaleLowerCase();
    return tokens.every((token) => searchable.includes(token));
  });
}

export function moveCommandIndex(
  commands: readonly EditorCommand[],
  currentIndex: number,
  direction: -1 | 1,
): number {
  if (commands.length === 0 || commands.every((command) => command.disabled)) return -1;
  let index = currentIndex;
  for (let offset = 0; offset < commands.length; offset += 1) {
    index = (index + direction + commands.length) % commands.length;
    if (!commands[index]?.disabled) return index;
  }
  return -1;
}

interface CommandPaletteProps {
  commands: readonly EditorCommand[];
  open: boolean;
  onClose(): void;
}

export function CommandPalette({ commands, open, onClose }: CommandPaletteProps): JSX.Element {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const filtered = useMemo(
    () => filterEditorCommands(commands, query),
    [commands, query],
  );

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(-1);
  }, [open]);

  useEffect(() => {
    if (open) setActiveIndex(moveCommandIndex(filtered, -1, 1));
  }, [filtered, open]);

  const execute = (command: EditorCommand | undefined): void => {
    if (!command || command.disabled) return;
    onClose();
    command.run();
  };

  return (
    <Dialog
      aria-labelledby="editor-command-palette-title"
      fullWidth
      maxWidth="sm"
      onClose={onClose}
      open={open}
      PaperProps={{ sx: { borderRadius: 2.5, overflow: "hidden" } }}
    >
      <DialogContent sx={{ p: 0 }}>
        <Typography id="editor-command-palette-title" className="sr-only">
          Editor commands
        </Typography>
        <TextField
          autoFocus
          fullWidth
          inputProps={{ "aria-label": "Search editor commands" }}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((current) => moveCommandIndex(filtered, current, 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((current) => moveCommandIndex(filtered, current, -1));
            } else if (event.key === "Enter") {
              event.preventDefault();
              execute(filtered[activeIndex]);
            }
          }}
          placeholder="Search commands, shortcuts or actions…"
          InputProps={{
            startAdornment: (
              <InputAdornment position="start"><BoltIcon fontSize="small" /></InputAdornment>
            ),
            sx: { borderRadius: 0, px: 1, py: 0.5 },
          }}
          value={query}
        />
        <List aria-label="Editor command results" disablePadding sx={{ maxHeight: 420, overflowY: "auto", py: 0.75 }}>
          {filtered.map((command, index) => (
            <ListItemButton
              aria-current={index === activeIndex ? "true" : undefined}
              disabled={command.disabled}
              key={command.id}
              onClick={() => execute(command)}
              onMouseMove={() => {
                if (!command.disabled) setActiveIndex(index);
              }}
              selected={index === activeIndex}
              sx={{ mx: 0.75, borderRadius: 1.5, py: 0.75 }}
            >
              <ListItemText
                primary={command.label}
                primaryTypographyProps={{ fontSize: 13, fontWeight: 750 }}
                secondary={command.description}
                secondaryTypographyProps={{ fontSize: 11 }}
              />
              <Box className="flex items-center gap-2 pl-3">
                <Typography sx={{ color: palette.textTertiary, fontSize: 10 }}>
                  {command.group}
                </Typography>
                {command.shortcut && (
                  <Box
                    component="kbd"
                    sx={{
                      background: "#F4F1EB",
                      border: `1px solid ${palette.borderDefault}`,
                      borderRadius: 1,
                      color: palette.textSecondary,
                      fontFamily: "inherit",
                      fontSize: 10,
                      px: 0.75,
                      py: 0.25,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {command.shortcut}
                  </Box>
                )}
              </Box>
            </ListItemButton>
          ))}
          {filtered.length === 0 && (
            <Box sx={{ px: 3, py: 5, textAlign: "center" }}>
              <Typography sx={{ color: palette.textSecondary, fontSize: 13 }}>
                No matching editor command.
              </Typography>
            </Box>
          )}
        </List>
        <Box className="flex items-center gap-3" sx={{ borderTop: `1px solid ${palette.borderDefault}`, color: palette.textTertiary, px: 2, py: 0.75 }}>
          <Typography sx={{ fontSize: 10 }}>↑↓ navigate</Typography>
          <Typography sx={{ fontSize: 10 }}>Enter run</Typography>
          <Typography sx={{ fontSize: 10 }}>Esc close</Typography>
        </Box>
      </DialogContent>
    </Dialog>
  );
}
