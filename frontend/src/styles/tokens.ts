/**
 * FretPilot v2 Design Tokens — the single source of truth for all colors.
 *
 * Both the Tailwind config and the MUI theme import these tokens, so a change
 * here propagates to every utility class and component in the app.
 *
 * Only `light` is fully populated today; `dark` is reserved for future use.
 */

export const tokens = {
  light: {
    // ── Background layers (4) ──
    canvas: "#FFFFFF",
    surface: "#F9FAFB",
    elevated: "#FFFFFF",
    subtle: "#F3F4F6",

    // ── Text layers (3) ──
    textPrimary: "#111827",
    textSecondary: "#6B7280",
    textTertiary: "#9CA3AF",

    // ── Brand colors (3) ──
    brandPrimary: "#6366F1",
    brandHover: "#4F46E5",
    brandAccent: "#8B5CF6",

    // ── Semantic colors (4) ──
    success: "#10B981",
    warning: "#F59E0B",
    error: "#EF4444",
    info: "#3B82F6",

    // ── Border states (3) ──
    borderDefault: "#E5E7EB",
    borderHover: "#D1D5DB",
    borderActive: "#6366F1",
  },

  dark: {
    // ── Background layers (4) — reserved ──
    canvas: "#0F172A",
    surface: "#1E293B",
    elevated: "#334155",
    subtle: "#1E293B",

    // ── Text layers (3) ──
    textPrimary: "#F1F5F9",
    textSecondary: "#94A3B8",
    textTertiary: "#64748B",

    // ── Brand colors (3) ──
    brandPrimary: "#818CF8",
    brandHover: "#6366F1",
    brandAccent: "#A78BFA",

    // ── Semantic colors (4) ──
    success: "#34D399",
    warning: "#FBBF24",
    error: "#F87171",
    info: "#60A5FA",

    // ── Border states (3) ──
    borderDefault: "#334155",
    borderHover: "#475569",
    borderActive: "#818CF8",
  },
} as const;

/** The active palette (light mode). */
export const palette = tokens.light;

export type Palette = typeof palette;
