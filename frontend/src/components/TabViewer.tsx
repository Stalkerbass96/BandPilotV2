/**
 * TabViewer — renders a guitar-tab score using alphaTab.
 *
 * Accepts a score file as an ArrayBuffer. When `scoreData` is null a
 * skeleton placeholder is shown. The alphaTab engine is lazily loaded
 * via the `useAlphaTab` hook.
 *
 * IMPORTANT: the container element that carries `containerRef` MUST stay
 * mounted for the whole time `scoreData` is non-null.  alphaTab renders its
 * SVG directly into that element (bypassing React), so if the element were
 * swapped out for a loading skeleton the rendered score would be attached to
 * a detached DOM node and never appear.  Loading / error states are therefore
 * rendered as overlays on top of the (always-mounted) container instead of
 * replacing it.
 */

import { Box, Skeleton, Typography } from "@mui/material";
import { MusicNoteIcon } from "../icons";
import { useAlphaTab } from "../hooks/useAlphaTab";
import { palette } from "../styles/tokens";

interface TabViewerProps {
  /** Score file (.gp5 / .gp4 / .gpx) as an ArrayBuffer, or null. */
  scoreData: ArrayBuffer | null;
}

export default function TabViewer({ scoreData }: TabViewerProps): JSX.Element {
  const { containerRef, isLoading, error } = useAlphaTab(scoreData);

  // ── No data yet: show a skeleton placeholder (no container to mount on) ──
  if (!scoreData) {
    return (
      <Box className="w-full">
        <Skeleton
          variant="rectangular"
          height={200}
          sx={{ borderRadius: 2, bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rectangular"
          height={120}
          sx={{ mt: 1, borderRadius: 2, bgcolor: palette.subtle }}
        />
        <Box className="flex items-center justify-center gap-2 mt-4">
          <MusicNoteIcon sx={{ color: palette.textTertiary }} />
          <Typography variant="body2" sx={{ color: palette.textTertiary }}>
            Score preview will appear here after repair.
          </Typography>
        </Box>
      </Box>
    );
  }

  // ── Container is always mounted once we have data; states are overlays ──
  return (
    <Box className="relative w-full">
      <Box
        ref={containerRef}
        className="w-full overflow-x-auto"
        sx={{
          minHeight: 240,
          "& svg": { maxWidth: "100%" },
        }}
      />

      {isLoading && (
        <Box className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-canvas/80">
          <Skeleton
            variant="rectangular"
            width="100%"
            height={180}
            sx={{ borderRadius: 2, bgcolor: palette.subtle }}
          />
          <Typography variant="body2" sx={{ color: palette.textSecondary }}>
            Rendering score…
          </Typography>
        </Box>
      )}

      {!isLoading && error && (
        <Box className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-canvas/80">
          <Typography
            variant="body2"
            sx={{ color: palette.error, fontWeight: 500 }}
          >
            Score rendering error
          </Typography>
          <Typography variant="caption" sx={{ color: palette.textSecondary }}>
            {error}
          </Typography>
        </Box>
      )}
    </Box>
  );
}
