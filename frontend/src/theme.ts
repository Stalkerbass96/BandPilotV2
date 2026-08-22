import { createTheme } from "@mui/material/styles";
import { palette } from "./styles/tokens";

/**
 * MUI theme for FretPilot v2 — Dark-first.
 *
 * All colors are sourced from `src/styles/tokens.ts` — the same file that
 * drives the Tailwind config — guaranteeing visual consistency between
 * MUI components and Tailwind utilities.
 */
export const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: palette.brandPrimary,
      dark: palette.brandHover,
      light: palette.brandAccent,
    },
    secondary: {
      main: palette.leadColor,
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
      default: palette.canvas,
      paper: palette.surface,
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
    h5: { fontWeight: 700 },
    h6: { fontWeight: 600 },
  },
  shape: {
    borderRadius: 10,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        containedPrimary: {
          backgroundColor: palette.brandPrimary,
          color: "#1A1208",
          fontWeight: 600,
          "&:hover": { backgroundColor: palette.brandHover },
        },
        outlinedPrimary: {
          borderColor: palette.brandPrimary,
          color: palette.brandPrimary,
          "&:hover": {
            backgroundColor: "rgba(232, 162, 75, 0.08)",
            borderColor: palette.brandHover,
          },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: palette.subtle,
          "& .MuiOutlinedInput-notchedOutline": {
            borderColor: palette.borderDefault,
          },
          "&:hover .MuiOutlinedInput-notchedOutline": {
            borderColor: palette.borderHover,
          },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: palette.borderActive,
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundColor: palette.surface,
          backgroundImage: "none",
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: palette.canvas,
          backgroundImage: "none",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: palette.surface,
          backgroundImage: "none",
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 10,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    MuiSlider: {
      styleOverrides: {
        root: {
          color: palette.brandPrimary,
        },
      },
    },
  },
});
