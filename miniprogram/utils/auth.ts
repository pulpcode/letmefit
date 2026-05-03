import type { AuthState } from "../types/api";

const AUTH_KEY = "letmefit.auth";
const CONVERSATION_KEY = "letmefit.activeConversationId";

export function getStoredAuth(): AuthState | null {
  try {
    return wx.getStorageSync<AuthState | null>(AUTH_KEY) || null;
  } catch (_error) {
    return null;
  }
}

export function setStoredAuth(auth: AuthState): void {
  wx.setStorageSync(AUTH_KEY, auth);
}

export function clearStoredAuth(): void {
  wx.removeStorageSync(AUTH_KEY);
  wx.removeStorageSync(CONVERSATION_KEY);
}

export function getActiveConversationId(): string | null {
  return wx.getStorageSync<string | null>(CONVERSATION_KEY) || null;
}

export function setActiveConversationId(conversationId: string): void {
  wx.setStorageSync(CONVERSATION_KEY, conversationId);
}

