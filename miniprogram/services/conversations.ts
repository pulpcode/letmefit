import { getApiBaseUrl } from "../config/env";
import { getTokens } from "../utils/storage";
import { request } from "../utils/request";
import type { Conversation, ConversationMessage, MessagePart, PendingAction, SendMessageResponse } from "../types/api";

class SSEParser {
  private buf = "";
  feed(chunk: ArrayBuffer): { event: string; data: string }[] {
    this.buf += new TextDecoder().decode(chunk);
    const blocks = this.buf.split("\n\n");
    this.buf = blocks.pop() ?? "";
    return blocks.flatMap((block) => {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data = line.slice(6).trim();
      }
      return data ? [{ event, data }] : [];
    });
  }
}

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

export function sendMessageStream(
  conversationId: string,
  content: MessagePart[],
  onDelta: (d: { type: string; text?: string }) => void,
  onDone: (data: SendMessageResponse) => void,
  onError: (err: Error) => void,
  onFallback?: () => void,
): WechatMiniprogram.RequestTask {
  const tokens = getTokens();
  const header: Record<string, string> = { "content-type": "application/json" };
  if (tokens?.access_token) {
    header.Authorization = `Bearer ${tokens.access_token}`;
  }
  const parser = new SSEParser();
  let doneCalled = false;
  const handleDone = (data: SendMessageResponse) => {
    if (!doneCalled) { doneCalled = true; onDone(data); }
  };
  const task = wx.request({
    url: `${getApiBaseUrl()}/conversations/${conversationId}/messages/stream`,
    method: "POST",
    data: { include_debug_context: false, content },
    header,
    enableChunked: true,
    success: (res: any) => {
      if (res.statusCode >= 400) {
        onError(new Error("请求失败"));
        return;
      }
      // 兜底：onChunkReceived 在某些微信版本/网络环境下可能未触发，
      // success.data 包含完整响应体，从中解析 SSE 事件。
      if (!doneCalled && res.data) {
        const sseText: string = typeof res.data === "string"
          ? res.data
          : new TextDecoder().decode(res.data as ArrayBuffer);
        for (const block of sseText.split("\n\n")) {
          let event = "message";
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7).trim();
            else if (line.startsWith("data: ")) data = line.slice(6).trim();
          }
          if (!data) continue;
          try {
            const parsed = JSON.parse(data);
            if (event === "delta") onDelta(parsed);
            else if (event === "done") { handleDone(parsed as SendMessageResponse); break; }
            else if (event === "error") { onError(new Error(parsed.message || "未知错误")); break; }
          } catch (_) {}
        }
      }
      // enableChunked 模式下 success.data 为空是微信的正常行为；
      // 若此时 onChunkReceived 也未触发 done，走 fallback 从 REST API 拉取结果。
      if (!doneCalled) { onFallback?.(); }
    },
    fail: () => onError(new Error("网络不可用")),
  });
  task.onChunkReceived((res: any) => {
    for (const { event, data } of parser.feed(res.data as ArrayBuffer)) {
      try {
        const parsed = JSON.parse(data);
        if (event === "delta") onDelta(parsed);
        else if (event === "done") handleDone(parsed as SendMessageResponse);
        else if (event === "error") onError(new Error(parsed.message || "未知错误"));
      } catch (_) {}
    }
  });
  return task;
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

