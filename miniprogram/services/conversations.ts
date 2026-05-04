import { request } from "../utils/request";
import type { Conversation, ConversationMessage, MessagePart, PendingAction, SendMessageResponse } from "../types/api";

export function listConversations() {
  return request<{ conversations: Conversation[] }>({
    path: "/conversations"
  });
}

export function createConversation(title = "今天记录") {
  return request<{ conversation_id: string; conversation: Conversation }>({
    path: "/conversations",
    method: "POST",
    data: { title }
  });
}

export function listMessages(conversationId: string) {
  return request<{ messages: ConversationMessage[] }>({
    path: `/conversations/${conversationId}/messages`
  });
}

export function sendMessage(conversationId: string, content: MessagePart[]) {
  return request<SendMessageResponse>({
    path: `/conversations/${conversationId}/messages`,
    method: "POST",
    data: {
      include_debug_context: false,
      content
    }
  });
}

export function listPendingActions(conversationId: string) {
  return request<{ pending_actions: PendingAction[] }>({
    path: `/conversations/${conversationId}/pending-actions`
  });
}

export function deleteConversation(conversationId: string) {
  return request<{}>({
    path: `/conversations/${conversationId}`,
    method: "DELETE"
  });
}

