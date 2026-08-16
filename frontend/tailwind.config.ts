import type { Config } from "tailwindcss";
import { palette } from "./src/styles/tokens";

/**
 * Tailwind config driven by the design-token single source of truth.
 * Every color utility below resolves to a token value, so changing a token
 * in `src/styles/tokens.ts` automatically updates Tailwind classes app-wide.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Background layers ──
        canvas: palette.canvas,
        surface: palette.surface,
        elevated: palette.elevated,
        subtle: palette.subtle,

        // ── Text layers ──
        "text-primary": palette.textPrimary,
        "text-secondary": palette.textSecondary,
        "text-tertiary": palette.textTertiary,

        // ── Brand ──
        brand: {
          DEFAULT: palette.brandPrimary,
          primary: palette.brandPrimary,
          hover: palette.brandHover,
          accent: palette.brandAccent,
        },

        // ── Semantic ──
        success: palette.success,
        warning: palette.warning,
        error: palette.error,
        info: palette.info,

        // ── Borders ──
        "border-default": palette.borderDefault,
        "border-hover": palette.borderHover,
        "border-active": palette.borderActive,
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
  // Disable preflight so MUI baseline styles are not overridden.
  corePlugins: {
    preflight: false,
  },
};

export default config;
