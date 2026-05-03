import { API_BASE_URL } from "../config/env";
import type { ApiEnvelope, ApiMethod, AuthState } from "../types/api";
import { getStoredAuth, setStoredAuth, clearStoredAuth } from "./auth";

interface RequestOptions {
  method?: ApiMethod;
  path: string;
  data?: unknown;
  auth?: boolean;
  retryOnUnauthorized?: boolean;
}

export class ApiError extends Error {
  code: string;
  statusCode: number;
  details?: Record<string, unknown>;

  constructor(message: string, code: string, statusCode: number, details?: Record<string, unknown>) {
    super(message);
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

export async function request<T>(options: RequestOptions): Promise<T> {
  const auth = getStoredAuth();
  const header: Record<string, string> = {
    "content-type": "application/json"
  };

  if (options.auth !== false && auth?.accessToken) {
    header.Authorization = `Bearer ${auth.accessToken}`;
  }

  const response = await rawRequest<ApiEnvelope<T>>({
    url: `${API_BASE_URL}${options.path}`,
    method: options.method || "GET",
    data: options.data,
    header
  });

  if (response.statusCode === 401 && options.auth !== false && options.retryOnUnauthorized !== false) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request<T>({ ...options, retryOnUnauthorized: false });
    }
  }

  const envelope = response.data;
  if (response.statusCode < 200 || response.statusCode >= 300 || envelope?.error) {
    const error = envelope?.error;
    throw new ApiError(
      error?.message || "请求失败",
      error?.code || `HTTP_${response.statusCode}`,
      response.statusCode,
      error?.details
    );
  }

  return envelope.data as T;
}

async function refreshAccessToken(): Promise<boolean> {
  const auth = getStoredAuth();
  if (!auth?.refreshToken) {
    clearStoredAuth();
    return false;
  }

  try {
    const data = await request<{ access_token: string; expires_in_seconds: number }>({
      method: "POST",
      path: "/auth/refresh",
      auth: false,
      retryOnUnauthorized: false,
      data: {
        refresh_token: auth.refreshToken
      }
    });
    const nextAuth: AuthState = {
      ...auth,
      accessToken: data.access_token,
      expiresAt: Date.now() + data.expires_in_seconds * 1000
    };
    setStoredAuth(nextAuth);
    getApp<IAppOption>().globalData.auth = nextAuth;
    return true;
  } catch (_error) {
    clearStoredAuth();
    getApp<IAppOption>().globalData.auth = null;
    wx.reLaunch({ url: "/pages/login/index" });
    return false;
  }
}

function rawRequest<T>(option: WechatMiniprogram.RequestOption<T>): Promise<WechatMiniprogram.RequestSuccessCallbackResult<T>> {
  return new Promise((resolve, reject) => {
    wx.request<T>({
      ...option,
      success: resolve,
      fail: reject
    });
  });
}

