import { getApiBaseUrl } from "../config/env";
import { clearAuth, getTokens, setAccessToken } from "./storage";
import type { ApiEnvelope } from "../types/api";

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

type RequestOptions = {
  path: string;
  method?: HttpMethod;
  data?: unknown;
  auth?: boolean;
  skipRefresh?: boolean;
};

type UploadFileOptions = {
  path: string;
  filePath: string;
  name?: string;
  formData?: Record<string, string | number | boolean>;
  auth?: boolean;
  skipRefresh?: boolean;
};

export class ApiError extends Error {
  code: string;
  statusCode: number;
  requestId?: string;

  constructor(message: string, code = "NETWORK_ERROR", statusCode = 0, requestId?: string) {
    super(message);
    this.code = code;
    this.statusCode = statusCode;
    this.requestId = requestId;
  }
}

function buildUrl(path: string): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  return `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

function shouldRefresh(error: ApiError): boolean {
  return error.statusCode === 401 || error.code === "AUTH_EXPIRED_TOKEN" || error.code === "AUTH_INVALID_TOKEN";
}

async function requestOnce<T>(options: RequestOptions): Promise<T> {
  const tokens = getTokens();
  const header: Record<string, string> = {
    "content-type": "application/json"
  };
  if (options.auth !== false && tokens?.access_token) {
    header.Authorization = `Bearer ${tokens.access_token}`;
  }

  return new Promise<T>((resolve, reject) => {
    wx.request({
      url: buildUrl(options.path),
      method: options.method || "GET",
      data: options.data as WechatMiniprogram.IAnyObject,
      header,
      success: (res: any) => {
        const envelope = (res.data || {}) as ApiEnvelope<T>;
        if (res.statusCode >= 200 && res.statusCode < 300 && !envelope.error) {
          resolve(envelope.data as T);
          return;
        }
        reject(
          new ApiError(
            envelope.error?.message || "请求失败",
            envelope.error?.code || `HTTP_${res.statusCode}`,
            res.statusCode,
            envelope.request_id
          )
        );
      },
      fail: () => {
        reject(new ApiError("网络不可用，请稍后重试"));
      }
    });
  });
}

async function uploadOnce<T>(options: UploadFileOptions): Promise<T> {
  const tokens = getTokens();
  const header: Record<string, string> = {};
  if (options.auth !== false && tokens?.access_token) {
    header.Authorization = `Bearer ${tokens.access_token}`;
  }

  return new Promise<T>((resolve, reject) => {
    wx.uploadFile({
      url: buildUrl(options.path),
      filePath: options.filePath,
      name: options.name || "file",
      formData: options.formData || {},
      header,
      success: (res: any) => {
        let envelope: ApiEnvelope<T> = {};
        try {
          envelope = JSON.parse(res.data || "{}") as ApiEnvelope<T>;
        } catch (_) {
          reject(new ApiError("响应解析失败", "INVALID_RESPONSE", res.statusCode));
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300 && !envelope.error) {
          resolve(envelope.data as T);
          return;
        }
        reject(
          new ApiError(
            envelope.error?.message || "上传失败",
            envelope.error?.code || `HTTP_${res.statusCode}`,
            res.statusCode,
            envelope.request_id
          )
        );
      },
      fail: () => {
        reject(new ApiError("网络不可用，请稍后重试"));
      }
    });
  });
}

async function refreshAccessToken(): Promise<string | null> {
  const tokens = getTokens();
  if (!tokens?.refresh_token) {
    return null;
  }
  try {
    const data = await requestOnce<{ access_token: string; expires_in_seconds: number }>({
      path: "/auth/refresh",
      method: "POST",
      data: { refresh_token: tokens.refresh_token },
      auth: false,
      skipRefresh: true
    });
    setAccessToken(data.access_token);
    return data.access_token;
  } catch (error) {
    clearAuth();
    return null;
  }
}

export async function request<T>(options: RequestOptions): Promise<T> {
  try {
    return await requestOnce<T>(options);
  } catch (error) {
    if (error instanceof ApiError && options.auth !== false && !options.skipRefresh && shouldRefresh(error)) {
      const token = await refreshAccessToken();
      if (token) {
        return requestOnce<T>({ ...options, skipRefresh: true });
      }
      wx.reLaunch({ url: "/pages/login/index" });
    }
    throw error;
  }
}

export async function uploadFile<T>(options: UploadFileOptions): Promise<T> {
  try {
    return await uploadOnce<T>(options);
  } catch (error) {
    if (error instanceof ApiError && options.auth !== false && !options.skipRefresh && shouldRefresh(error)) {
      const token = await refreshAccessToken();
      if (token) {
        return uploadOnce<T>({ ...options, skipRefresh: true });
      }
      wx.reLaunch({ url: "/pages/login/index" });
    }
    throw error;
  }
}

export function showApiError(error: unknown) {
  const message = error instanceof ApiError ? error.message : "操作失败";
  wx.showToast({ title: message, icon: "none" });
}
