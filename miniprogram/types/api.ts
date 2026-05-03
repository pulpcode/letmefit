export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiEnvelope<T> {
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  request_id?: string;
}

export interface AuthState {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  user: AuthUser;
}

export interface AuthUser {
  id: string;
  phone_number: string;
  profile_completed: boolean;
}

export interface UserProfile {
  id?: string;
  age?: number;
  sex?: "male" | "female" | "other" | "unspecified";
  height_cm?: number;
  current_weight_kg?: number;
  target_weight_kg?: number | null;
  activity_level?: "sedentary" | "light" | "moderate" | "active" | "very_active";
  goal_type?: "fat_loss" | "muscle_gain" | "maintenance" | "fitness";
  completed_at?: string | null;
  agent_avatar?: "female" | "male";
}

export interface MealItemDraft {
  id?: string;
  name: string;
  alias?: string | null;
  portion_text?: string | null;
  portion_grams?: number | null;
  calories?: number | null;
  protein_g?: number | null;
  carbs_g?: number | null;
  fat_g?: number | null;
  confidence?: number | null;
  user_corrected?: boolean;
}

export interface MealRecord {
  id: string;
  recorded_at: string;
  recorded_tz: string;
  local_date: string;
  source_type: string;
  meal_type: string;
  total_calories?: number | null;
  total_protein_g?: number | null;
  total_carbs_g?: number | null;
  total_fat_g?: number | null;
  confidence?: number | null;
  source_pending_action_id?: string | null;
  notes?: string | null;
  items: MealItemDraft[];
}

export interface BodyMetricRecord {
  id: string;
  recorded_at: string;
  recorded_tz: string;
  local_date: string;
  source_type: string;
  weight_kg?: number | null;
  body_fat_percentage?: number | null;
  bmi?: number | null;
  muscle_mass_kg?: number | null;
  water_percentage?: number | null;
  confidence?: number | null;
  source_pending_action_id?: string | null;
}

export interface DailyArchive {
  id: string;
  date: string;
  timezone: string;
  meal_count: number;
  body_metric_count: number;
  calorie_total?: number | null;
  protein_total_g?: number | null;
  carbs_total_g?: number | null;
  fat_total_g?: number | null;
  completeness_score?: number | null;
  last_calculated_at?: string | null;
}

export interface DailySummary {
  id: string;
  date: string;
  archive_id?: string | null;
  calorie_total?: number | null;
  protein_total_g?: number | null;
  carbs_total_g?: number | null;
  fat_total_g?: number | null;
  meal_count: number;
  body_metric_count: number;
  summary_text: string;
  suggestions: string[];
  completeness_score?: number | null;
  generation_status: string;
}

export interface Conversation {
  id: string;
  title?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface MessageContentItem {
  type: "text" | "image" | "audio";
  text?: string;
  file_id?: string;
  source?: string;
  duration_seconds?: number;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: MessageContentItem[] | Record<string, unknown>[];
  intent?: string | null;
  requires_review: boolean;
  created_at: string;
}

export interface PendingActionWarning {
  field?: string;
  reason?: string;
  message?: string;
}

export interface PendingAction {
  pending_action_id: string;
  type: "create_meal_record" | "create_body_metric_record" | string;
  status: "pending_confirmation" | "committed" | "discarded" | string;
  confidence?: number | null;
  draft_payload: Record<string, unknown>;
  warnings: PendingActionWarning[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface UploadedFile {
  id: string;
  storage_provider: string;
  client_local_ref?: string | null;
  mime_type: string;
  size_bytes?: number | null;
  source: string;
  retention_policy: string;
  status: string;
  created_at: string;
}

