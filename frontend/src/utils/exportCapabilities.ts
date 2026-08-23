import type { TrackSummaryItem } from "../api/types";

const GUITAR_ONLY_FORMATS = new Set([
  "ample_midi",
  "ample_eclipse_midi",
  "humanized_ample_eclipse_midi",
]);

export function canExportFormat(
  format: string,
  tracks: TrackSummaryItem[] | undefined,
): boolean {
  if (!GUITAR_ONLY_FORMATS.has(format)) return true;
  return tracks?.some((track) => track.family === "guitar" || track.is_guitar) ?? false;
}

export function exportUnavailableReason(
  format: string,
  tracks: TrackSummaryItem[] | undefined,
): string | null {
  if (canExportFormat(format, tracks)) return null;
  return "Requires at least one repaired guitar track.";
}
