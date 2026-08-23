import { describe, expect, it } from "vitest";
import { canExportProject, isTerminalProjectStatus } from "./projectStatus";

describe("project status policy", () => {
  it("allows full and partial repair results to export", () => {
    expect(canExportProject("repaired")).toBe(true);
    expect(canExportProject("partial")).toBe(true);
  });

  it("blocks non-output states", () => {
    expect(canExportProject("imported")).toBe(false);
    expect(canExportProject("processing")).toBe(false);
    expect(canExportProject("failed")).toBe(false);
  });

  it("recognizes terminal outcomes", () => {
    expect(isTerminalProjectStatus("repaired")).toBe(true);
    expect(isTerminalProjectStatus("partial")).toBe(true);
    expect(isTerminalProjectStatus("failed")).toBe(true);
    expect(isTerminalProjectStatus("processing")).toBe(false);
  });
});
