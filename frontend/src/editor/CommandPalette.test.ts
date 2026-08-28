import { describe, expect, it, vi } from "vitest";
import {
  filterEditorCommands,
  moveCommandIndex,
  type EditorCommand,
} from "./CommandPalette";

function command(
  id: string,
  label: string,
  options: Partial<EditorCommand> = {},
): EditorCommand {
  return {
    id,
    label,
    group: "Edit",
    run: vi.fn(),
    ...options,
  };
}

describe("editor command palette", () => {
  const commands = [
    command("undo", "Undo last edit", { shortcut: "⌘Z" }),
    command("loop", "Loop selection", {
      description: "Repeat the selected passage",
      group: "Playback",
      keywords: ["practice", "repeat"],
    }),
    command("export-midi", "Export humanized MIDI", { group: "Project" }),
  ];

  it("matches labels, descriptions, groups, shortcuts and explicit keywords", () => {
    expect(filterEditorCommands(commands, "undo").map((item) => item.id)).toEqual(["undo"]);
    expect(filterEditorCommands(commands, "repeat passage").map((item) => item.id)).toEqual(["loop"]);
    expect(filterEditorCommands(commands, "playback practice").map((item) => item.id)).toEqual(["loop"]);
    expect(filterEditorCommands(commands, "⌘z").map((item) => item.id)).toEqual(["undo"]);
  });

  it("preserves declared order for an empty query", () => {
    expect(filterEditorCommands(commands, "  ")).toEqual(commands);
  });

  it("keeps large navigation indexes hidden until the user searches", () => {
    const indexed = [
      ...commands,
      command("bar-104", "Go to bar 104", {
        group: "Navigate",
        hiddenUntilSearch: true,
      }),
    ];
    expect(filterEditorCommands(indexed, "").map((item) => item.id)).not.toContain("bar-104");
    expect(filterEditorCommands(indexed, "bar 104").map((item) => item.id)).toEqual(["bar-104"]);
  });

  it("cycles through enabled commands and skips disabled results", () => {
    const values = [
      command("first", "First", { disabled: true }),
      command("second", "Second"),
      command("third", "Third", { disabled: true }),
      command("fourth", "Fourth"),
    ];
    expect(moveCommandIndex(values, -1, 1)).toBe(1);
    expect(moveCommandIndex(values, 1, 1)).toBe(3);
    expect(moveCommandIndex(values, 3, 1)).toBe(1);
    expect(moveCommandIndex(values, 1, -1)).toBe(3);
    expect(moveCommandIndex(values.map((item) => ({ ...item, disabled: true })), 0, 1)).toBe(-1);
  });
});
