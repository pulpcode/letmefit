import { DEFAULT_TIMEZONE } from "../config/env";
import type {
  AuthState,
  AuthUser,
  BodyMetricRecord,
  Conversation,
  ConversationMessage,
  DailyArchive,
  DailySummary,
  MessageContentItem,
  MealRecord,
  PendingAction,
  UploadedFile,
  UserProfile
} from "../types/api";
import { request } from "../utils/request";

export const authApi = {
  sendSms(phoneNumber: string) {
    return request<{ cooldown_seconds: number; expires_in_seconds: number }>({
      method: "POST",
      path: "/auth/sms/send",
      auth: false,
      data: {
        phone_number: phoneNumber,
        purpose: "login"
      }
    });
  },

  async verifySms(phoneNumber: string, code: string): Promise<AuthState> {
    const data = await request<{
      access_token: string;
      refresh_token: string;
      token_type: string;
      expires_in_seconds: number;
      user: AuthUser;
    }>({
      method: "POST",
      path: "/auth/sms/verify",
      auth: false,
      data: {
        phone_number: phoneNumber,
        code
      }
    });

    return {
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresAt: Date.now() + data.expires_in_seconds * 1000,
      user: data.user
    };
  },

  logout(refreshToken: string) {
    return request<{ success: boolean }>({
      method: "POST",
      path: "/auth/logout",
      data: {
        refresh_token: refreshToken
      }
    });
  }
};

export const profileApi = {
  getProfile() {
    return request<{ profile: UserProfile | null; profile_completed: boolean }>({
      path: "/profile"
    });
  },

  saveProfile(profile: UserProfile) {
    return request<{ profile: UserProfile | null; profile_completed: boolean }>({
      method: "PUT",
      path: "/profile",
      data: profile
    });
  }
};

export const recordsApi = {
  getMeals(date: string) {
    return request<{ meals: MealRecord[] }>({
      path: `/meals?date=${encodeURIComponent(date)}`
    });
  },

  getBodyMetrics(dateFrom: string, dateTo: string) {
    return request<{ body_metrics: BodyMetricRecord[] }>({
      path: `/body-metrics?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`
    });
  },

  getDailyArchive(date: string) {
    return request<{ archive: DailyArchive }>({
      path: `/daily-archives/${encodeURIComponent(date)}`
    });
  },

  generateSummary(date: string, timezone = DEFAULT_TIMEZONE) {
    return request<{ summary: DailySummary }>({
      method: "POST",
      path: "/summaries/generate",
      data: {
        date,
        timezone
      }
    });
  }
};

export const conversationApi = {
  createConversation(title = "今天记录") {
    return request<{ conversation_id: string; conversation: Conversation }>({
      method: "POST",
      path: "/conversations",
      data: {
        title
      }
    });
  },

  listConversations() {
    return request<{ conversations: Conversation[] }>({
      path: "/conversations"
    });
  },

  listMessages(conversationId: string) {
    return request<{ messages: ConversationMessage[] }>({
      path: `/conversations/${conversationId}/messages`
    });
  },

  sendMessage(conversationId: string, content: MessageContentItem[]) {
    return request<{
      message_id: string;
      assistant_message_id: string;
      assistant_text: string;
      intent: string;
      requires_review: boolean;
      pending_actions: PendingAction[];
    }>({
      method: "POST",
      path: `/conversations/${conversationId}/messages`,
      data: {
        content
      }
    });
  },

  listPendingActions(conversationId: string) {
    return request<{ pending_actions: PendingAction[] }>({
      path: `/conversations/${conversationId}/pending-actions`
    });
  }
};

export const pendingActionApi = {
  update(pendingActionId: string, draftPayload: Record<string, unknown>, userNote?: string) {
    return request<PendingAction>({
      method: "PATCH",
      path: `/agent/pending-actions/${pendingActionId}`,
      data: {
        draft_payload: draftPayload,
        user_note: userNote
      }
    });
  },

  confirm(pendingActionId: string) {
    return request<{
      pending_action_id: string;
      status: string;
      record_type: string;
      record_id: string;
    }>({
      method: "POST",
      path: `/agent/pending-actions/${pendingActionId}/confirm`
    });
  },

  discard(pendingActionId: string) {
    return request<{ pending_action_id: string; status: string }>({
      method: "POST",
      path: `/agent/pending-actions/${pendingActionId}/discard`
    });
  }
};

export const uploadApi = {
  createClientLocalFile(input: {
    clientLocalRef: string;
    mimeType: string;
    sizeBytes?: number | null;
    source: "camera" | "album" | "microphone" | "upload";
  }) {
    return request<{ file: UploadedFile; upload_url: string | null; upload_headers: Record<string, string> }>({
      method: "POST",
      path: "/uploads",
      data: {
        storage_provider: "client_local",
        client_local_ref: input.clientLocalRef,
        mime_type: input.mimeType,
        size_bytes: input.sizeBytes || null,
        source: input.source,
        retention_policy: "transient"
      }
    });
  }
};

