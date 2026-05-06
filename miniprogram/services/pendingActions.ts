import { request } from "../utils/request";
import type { AgentContinuation, PendingAction } from "../types/api";

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

export function confirmPendingAction(
  pendingActionId: string,
  continueAgent = true,
  includeAgentTrace = false
) {
  return request<{
    pending_action_id: string;
    status: "committed";
    record_type: string;
    record_id: string;
    continuation?: AgentContinuation;
  }>({
    path: `/agent/pending-actions/${pendingActionId}/confirm`,
    method: "POST",
    data: { continue_agent: continueAgent, include_agent_trace: includeAgentTrace }
  });
}

export function discardPendingAction(
  pendingActionId: string,
  continueAgent = true,
  includeAgentTrace = false
) {
  return request<{
    pending_action_id: string;
    status: "discarded";
    continuation?: AgentContinuation;
  }>({
    path: `/agent/pending-actions/${pendingActionId}/discard`,
    method: "POST",
    data: { continue_agent: continueAgent, include_agent_trace: includeAgentTrace }
  });
}
