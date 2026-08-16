import { createTheme } from "@mui/material/styles";
import { palette } from "./styles/tokens";

/**
 * MUI theme for FretPilot v2.
 *
 * All colors are sourced from `src/styles/tokens.ts` — the same file that
 * drives the Tailwind config — guaranteeing visual consistency between
 * MUI components (Select, Slider, Table, Dialog) and Tailwind utilities.
 */
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: palette.brandPrimary,
      dark: palette.brandHover,
      light: palette.brandAccent,
    },
    secondary: {
      main: palette.brandAccent,
    },
    success: {
      main: palette.success,
    },
    warning: {
      main: palette.warning,
    },
    error: {
      main: palette.error,
    },
    info: {
      main: palette.info,
    },
    background: {
      default: palette.surface,
      paper: palette.elevated,
    },
    text: {
      primary: palette.textPrimary,
      secondary: palette.textSecondary,
      disabled: palette.textTertiary,
    },
    divider: palette.borderDefault,
  },
  typography: {
    fontFamily: [
      "Inter",
      "-apple-system",
      "BlinkMacSystemFont",
      "Segoe UI",
      "Roboto",
      "sans-serif",
    ].join(","),
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        containedPrimary: {
          backgroundColor: palette.brandPrimary,
          "&:hover": { backgroundColor: palette.brandHover },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          "&:hover .MuiOutlinedInput-notchedOutline": {
            borderColor: palette.borderHover,
          },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: palette.borderActive,
          },
        },
      },
    },
  },
});
