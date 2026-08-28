/** BandPilot design tokens — warm editorial workspace + studio navigation. */

export const tokens = {
  dark: {
    canvas: "#0B0E13",
    surface: "#11161E",
    elevated: "#1A2029",
    subtle: "#222B36",

    textPrimary: "#F0F2F5",
    textSecondary: "#9DA5B4",
    textTertiary: "#6B7280",

    brandPrimary: "#E8A24B",
    brandHover: "#D4882E",
    brandAccent: "#C97A35",

    leadColor: "#4FD1C5",
    rhythmColor: "#E8A24B",

    success: "#34D399",
    warning: "#FBBF24",
    error: "#F87171",
    info: "#60A5FA",

    borderDefault: "#2D3239",
    borderHover: "#3D4451",
    borderActive: "#E8A24B",
  },

  light: {
    canvas: "#F4F1EA",
    surface: "#FAF9F6",
    elevated: "#FFFFFF",
    subtle: "#F0EDE6",

    textPrimary: "#17191D",
    textSecondary: "#5F625F",
    textTertiary: "#8B8E89",

    brandPrimary: "#E8642D",
    brandHover: "#CC4E1C",
    brandAccent: "#F2A65A",

    leadColor: "#4355D8",
    rhythmColor: "#E8642D",

    success: "#10B981",
    warning: "#F59E0B",
    error: "#EF4444",
    info: "#3B82F6",

    borderDefault: "#DEDAD1",
    borderHover: "#C8C2B7",
    borderActive: "#E8642D",
  },
} as const;

export const palette = tokens.light;

export const streamColors = {
  lead: palette.leadColor,
  rhythm: palette.rhythmColor,
} as const;

export type Palette = typeof palette;
