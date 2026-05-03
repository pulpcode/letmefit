import { request } from "../utils/request";
import { clearAuth, getTokens, setTokens, setUser } from "../utils/storage";
import type { AuthVerifyResponse } from "../types/api";

export function sendSmsCode(phoneNumber: string) {
  return request<{ cooldown_seconds: number; expires_in_seconds: number }>({
    path: "/auth/sms/send",
    method: "POST",
    auth: false,
    data: {
      phone_number: phoneNumber,
      purpose: "login"
    }
  });
}

export async function verifySmsCode(phoneNumber: string, code: string) {
  const data = await request<AuthVerifyResponse>({
    path: "/auth/sms/verify",
    method: "POST",
    auth: false,
    data: {
      phone_number: phoneNumber,
      code
    }
  });
  setTokens({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_in_seconds: data.expires_in_seconds
  });
  setUser(data.user);
  return data;
}

export async function logout() {
  const tokens = getTokens();
  if (tokens?.refresh_token) {
    try {
      await request<{ success: boolean }>({
        path: "/auth/logout",
        method: "POST",
        data: { refresh_token: tokens.refresh_token }
      });
    } catch (error) {
      // Local logout should still proceed if the session is already invalid.
    }
  }
  clearAuth();
}
