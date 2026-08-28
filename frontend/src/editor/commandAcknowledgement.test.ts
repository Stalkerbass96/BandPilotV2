import { describe, expect, it } from "vitest";
import type { ScoreCommandResult, ScoreDocument } from "../api/types";
import { acknowledgeOptimisticCommand } from "./commandAcknowledgement";

const document = { id: "document:1" } as ScoreDocument;
const accepted: ScoreCommandResult = {
  command_id: "command:1",
  revision_id: "revision:1",
  revision: 1,
  document_hash: "hash:1",
  rebased: false,
  idempotent_replay: false,
};

describe("acknowledgeOptimisticCommand", () => {
  it("promotes a non-rebased optimistic document to the accepted revision", () => {
    expect(acknowledgeOptimisticCommand(document, accepted)).toEqual({
      document,
      revision: {
        id: "revision:1",
        number: 1,
        hash: "hash:1",
        is_current: true,
      },
    });
  });

  it("requires an authoritative snapshot for rebases and idempotent replays", () => {
    expect(acknowledgeOptimisticCommand(document, { ...accepted, rebased: true })).toBeNull();
    expect(acknowledgeOptimisticCommand(document, {
      ...accepted,
      idempotent_replay: true,
    })).toBeNull();
  });
});
