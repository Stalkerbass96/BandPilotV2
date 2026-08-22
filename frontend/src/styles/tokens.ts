/**
 * FretPilot v2 Design Tokens — Dark-first「录音棚」美学 v3.
 *
 * 层次：canvas (sidebar) < surface (main) < elevated (card) < subtle (hover)
 * 品牌：琥珀/铜色 #E8A24B（琴弦金属 + 音孔玫瑰木）
 * 声部：Lead = 冷青 / Rhythm = 琥珀
 */

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
    canvas: "#FFFFFF",
    surface: "#F9FAFB",
    elevated: "#FFFFFF",
    subtle: "#F3F4F6",

    textPrimary: "#111827",
    textSecondary: "#6B7280",
    textTertiary: "#9CA3AF",

    brandPrimary: "#D4882E",
    brandHover: "#B36F1E",
    brandAccent: "#C97A35",

    leadColor: "#0D9488",
    rhythmColor: "#D4882E",

    success: "#10B981",
    warning: "#F59E0B",
    error: "#EF4444",
    info: "#3B82F6",

    borderDefault: "#E5E7EB",
    borderHover: "#D1D5DB",
    borderActive: "#D4882E",
  },
} as const;

export const palette = tokens.dark;

export const streamColors = {
  lead: palette.leadColor,
  rhythm: palette.rhythmColor,
} as const;

export type Palette = typeof palette;
