/** Shared project-status policy used by navigation and export surfaces. */

export type ProjectStatus =
  | "imported"
  | "processing"
  | "repaired"
  | "partial"
  | "failed";

export function canExportProject(status: string | undefined): boolean {
  return status === "repaired" || status === "partial";
}

export function isTerminalProjectStatus(status: string): boolean {
  return status === "repaired" || status === "partial" || status === "failed";
}
