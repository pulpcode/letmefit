import { request } from "../utils/request";
import type { PendingAction } from "../types/api";

export function patchPendingAction(pendingActionId: string, draftPayload: Record<string, unknown>, userNote?: string) {
  return request<PendingAction>({
    path: `/agent/pending-actions/${pendingActionId}`,
    method: "PATCH",
    data: {
      draft_payload: draftPayload,
      user_note: userNote
    }
  });
}

export function confirmPendingAction(pendingActionId: string) {
  return request<{ pending_action_id: string; status: "committed"; record_type: string; record_id: string }>({
    path: `/agent/pending-actions/${pendingActionId}/confirm`,
    method: "POST"
  });
}

export function discardPendingAction(pendingActionId: string) {
  return request<{ pending_action_id: string; status: "discarded" }>({
    path: `/agent/pending-actions/${pendingActionId}/discard`,
    method: "POST"
  });
}
