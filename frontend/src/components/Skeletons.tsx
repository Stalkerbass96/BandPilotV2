/**
 * Skeletons — loading placeholders for each major page / section.
 *
 * Uses MUI Skeleton with token colors so the shimmer matches the design system.
 */

import { Box, Skeleton } from "@mui/material";
import { palette } from "../styles/tokens";

/** A single project card skeleton. */
export function CardSkeleton(): JSX.Element {
  return (
    <Box
      className="rounded-xl p-4"
      sx={{
        backgroundColor: palette.elevated,
        border: `1px solid ${palette.borderDefault}`,
      }}
    >
      <Skeleton
        variant="text"
        width="60%"
        height={24}
        sx={{ bgcolor: palette.subtle }}
      />
      <Skeleton
        variant="text"
        width="40%"
        height={20}
        sx={{ bgcolor: palette.subtle }}
      />
      <Box className="flex gap-2 mt-3">
        <Skeleton
          variant="rounded"
          width={60}
          height={24}
          sx={{ bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rounded"
          width={80}
          height={24}
          sx={{ bgcolor: palette.subtle }}
        />
      </Box>
    </Box>
  );
}

/** Skeleton for the ImportPage project list. */
export function ProjectListSkeleton(): JSX.Element {
  return (
    <Box className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </Box>
  );
}

/** Skeleton for the WorkbenchPage. */
export function WorkbenchSkeleton(): JSX.Element {
  return (
    <Box className="flex flex-col lg:flex-row gap-6">
      {/* Left panel (settings) */}
      <Box
        className="w-full lg:w-80 rounded-xl p-5"
        sx={{
          backgroundColor: palette.elevated,
          border: `1px solid ${palette.borderDefault}`,
        }}
      >
        <Skeleton
          variant="text"
          width="50%"
          height={28}
          sx={{ bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rectangular"
          height={40}
          sx={{ mt: 2, borderRadius: 1, bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rectangular"
          height={120}
          sx={{ mt: 2, borderRadius: 1, bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rectangular"
          height={44}
          sx={{ mt: 2, borderRadius: 1, bgcolor: palette.subtle }}
        />
      </Box>
      {/* Right panel (results) */}
      <Box className="flex-1 flex flex-col gap-4">
        <Skeleton
          variant="rectangular"
          height={60}
          sx={{ borderRadius: 1, bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rectangular"
          height={200}
          sx={{ borderRadius: 1, bgcolor: palette.subtle }}
        />
        <Skeleton
          variant="rectangular"
          height={160}
          sx={{ borderRadius: 1, bgcolor: palette.subtle }}
        />
      </Box>
    </Box>
  );
}

/** Skeleton for the ExportPage. */
export function ExportSkeleton(): JSX.Element {
  return (
    <Box className="flex flex-col gap-6">
      <Box className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {Array.from({ length: 2 }).map((_, i) => (
          <Box
            key={i}
            className="rounded-xl p-5"
            sx={{
              backgroundColor: palette.elevated,
              border: `1px solid ${palette.borderDefault}`,
            }}
          >
            <Skeleton
              variant="text"
              width="70%"
              height={24}
              sx={{ bgcolor: palette.subtle }}
            />
            <Skeleton
              variant="text"
              width="100%"
              height={20}
              sx={{ bgcolor: palette.subtle }}
            />
            <Skeleton
              variant="rectangular"
              height={40}
              sx={{ mt: 2, borderRadius: 1, bgcolor: palette.subtle }}
            />
          </Box>
        ))}
      </Box>
      <Skeleton
        variant="rectangular"
        height={200}
        sx={{ borderRadius: 1, bgcolor: palette.subtle }}
      />
    </Box>
  );
}
