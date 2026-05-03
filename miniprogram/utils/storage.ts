import type { AuthUser, TokenPair } from "../types/api";

const ACCESS_TOKEN_KEY = "letmefit.access_token";
const REFRESH_TOKEN_KEY = "letmefit.refresh_token";
const USER_KEY = "letmefit.user";
const AGENT_AVATAR_KEY = "letmefit.agent_avatar";

export function getTokens(): TokenPair | null {
  const access_token = wx.getStorageSync(ACCESS_TOKEN_KEY);
  const refresh_token = wx.getStorageSync(REFRESH_TOKEN_KEY);
  if (!access_token || !refresh_token) {
    return null;
  }
  return { access_token, refresh_token };
}

export function setTokens(tokens: TokenPair) {
  wx.setStorageSync(ACCESS_TOKEN_KEY, tokens.access_token);
  wx.setStorageSync(REFRESH_TOKEN_KEY, tokens.refresh_token);
}

export function setAccessToken(accessToken: string) {
  wx.setStorageSync(ACCESS_TOKEN_KEY, accessToken);
}

export function getUser(): AuthUser | null {
  const raw = wx.getStorageSync(USER_KEY);
  return raw || null;
}

export function setUser(user: AuthUser) {
  wx.setStorageSync(USER_KEY, user);
}

export function clearAuth() {
  wx.removeStorageSync(ACCESS_TOKEN_KEY);
  wx.removeStorageSync(REFRESH_TOKEN_KEY);
  wx.removeStorageSync(USER_KEY);
}

export function getAgentAvatar(): "female" | "male" {
  const value = wx.getStorageSync(AGENT_AVATAR_KEY);
  return value === "male" ? "male" : "female";
}

export function setAgentAvatar(value: "female" | "male") {
  wx.setStorageSync(AGENT_AVATAR_KEY, value);
}
