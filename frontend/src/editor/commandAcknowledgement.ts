import type {
  ScoreCommandResult,
  ScoreDocument,
  ScoreDocumentEnvelope,
} from "../api/types";

/**
 * Confirm an optimistic edit without downloading the full document again.
 *
 * A rebased or replayed command may include authoritative state the client has
 * not projected, so those cases deliberately return null and require a fresh
 * snapshot.
 */
export function acknowledgeOptimisticCommand(
  optimisticDocument: ScoreDocument,
  result: ScoreCommandResult,
): ScoreDocumentEnvelope | null {
  if (result.rebased || result.idempotent_replay) return null;
  return {
    document: optimisticDocument,
    revision: {
      id: result.revision_id,
      number: result.revision,
      hash: result.document_hash,
      is_current: true,
    },
  };
}
