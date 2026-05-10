import { getApiBaseUrl } from "../config/env";
import { getTokens } from "../utils/storage";
import { request } from "../utils/request";
import type { Conversation, ConversationMessage, MessagePart, PendingAction, SendMessageResponse } from "../types/api";

class SSEParser {
  private buf = "";
  private decoder = new Utf8StreamDecoder();

  feed(chunk: ArrayBuffer | string): { event: string; data: string }[] {
    this.buf += this.decoder.decode(chunk);
    this.buf = this.buf.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const blocks = this.buf.split("\n\n");
    this.buf = blocks.pop() ?? "";
    return blocks.flatMap((block) => {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      const data = dataLines.join("\n");
      return data ? [{ event, data }] : [];
    });
  }
}

class Utf8StreamDecoder {
  private pending: number[] = [];

  decode(chunk: ArrayBuffer | string): string {
    if (typeof chunk === "string") {
      return chunk;
    }

    const bytes = [...this.pending, ...Array.from(new Uint8Array(chunk))];
    this.pending = [];
    let output = "";

    for (let i = 0; i < bytes.length;) {
      const first = bytes[i];
      let needed = 0;
      let codePoint = 0;

      if (first < 0x80) {
        output += String.fromCharCode(first);
        i += 1;
        continue;
      }
      if ((first & 0xe0) === 0xc0) {
        needed = 1;
        codePoint = first & 0x1f;
      } else if ((first & 0xf0) === 0xe0) {
        needed = 2;
        codePoint = first & 0x0f;
      } else if ((first & 0xf8) === 0xf0) {
        needed = 3;
        codePoint = first & 0x07;
      } else {
        output += "\uFFFD";
        i += 1;
        continue;
      }

      if (i + needed >= bytes.length) {
        this.pending = bytes.slice(i);
        break;
      }

      let valid = true;
      for (let j = 1; j <= needed; j += 1) {
        const next = bytes[i + j];
        if ((next & 0xc0) !== 0x80) {
          valid = false;
          break;
        }
        codePoint = (codePoint << 6) | (next & 0x3f);
      }

      if (!valid) {
        output += "\uFFFD";
        i += 1;
        continue;
      }

      output += codePoint <= 0xffff
        ? String.fromCharCode(codePoint)
        : String.fromCharCode(
            ((codePoint - 0x10000) >> 10) + 0xd800,
            ((codePoint - 0x10000) & 0x3ff) + 0xdc00,
          );
      i += needed + 1;
    }

    return output;
  }
}

function parseSSEText(text: string): { event: string; data: string }[] {
  const parser = new SSEParser();
  return parser.feed(text);
}

function decodeResponseData(data: unknown): string {
  if (typeof data === "string") {
    return data;
  }
  if (data instanceof ArrayBuffer) {
    return new Utf8StreamDecoder().decode(data);
  }
  return "";
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
        for (const { event, data } of parseSSEText(decodeResponseData(res.data))) {
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
  if (typeof task.onChunkReceived === "function") {
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
  }
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
