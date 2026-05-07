export type ApiEnvelope<T> = {
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  request_id?: string;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in_seconds?: number;
};

export type AuthUser = {
  id: string;
  phone_number: string;
  profile_completed: boolean;
};

export type AuthVerifyResponse = TokenPair & {
  token_type: "bearer";
  user: AuthUser;
};

export type Profile = {
  id?: string;
  age?: number;
  sex?: "male" | "female" | "other" | "unspecified";
  height_cm?: number;
  current_weight_kg?: number;
  target_weight_kg?: number | null;
  activity_level?: "sedentary" | "light" | "moderate" | "active" | "very_active";
  goal_type?: "fat_loss" | "muscle_gain" | "maintenance" | "fitness";
  completed_at?: string | null;
};

export type ProfileResponse = {
  profile: Profile | null;
  profile_completed: boolean;
};

export type MealItem = {
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
};

export type MealRecord = {
  id?: string;
  recorded_at?: string;
  recorded_tz?: string;
  local_date?: string;
  source_type?: "photo" | "voice" | "text" | "manual" | "mixed";
  meal_type?: "breakfast" | "lunch" | "dinner" | "snack" | "unknown";
  total_calories?: number | null;
  total_protein_g?: number | null;
  total_carbs_g?: number | null;
  total_fat_g?: number | null;
  confidence?: number | null;
  notes?: string | null;
  items?: MealItem[];
};

export type BodyMetricRecord = {
  id?: string;
  recorded_at?: string;
  recorded_tz?: string;
  local_date?: string;
  source_type?: "scale_photo" | "voice" | "text" | "manual";
  weight_kg?: number | null;
  body_fat_percentage?: number | null;
  bmi?: number | null;
  muscle_mass_kg?: number | null;
  water_percentage?: number | null;
  confidence?: number | null;
};

export type Archive = {
  id?: string;
  date: string;
  timezone: string;
  meal_count: number;
  body_metric_count: number;
  calorie_total?: number | null;
  protein_total_g?: number | null;
  carbs_total_g?: number | null;
  fat_total_g?: number | null;
  completeness_score?: number | null;
};

export type DailySummary = {
  id?: string;
  date: string;
  calorie_total?: number | null;
  protein_total_g?: number | null;
  carbs_total_g?: number | null;
  fat_total_g?: number | null;
  meal_count?: number;
  body_metric_count?: number;
  summary_text?: string;
  suggestions?: string[];
  completeness_score?: number | null;
  generation_status?: string;
};

export type Conversation = {
  id: string;
  title?: string | null;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
};

export type MessagePart =
  | { type: "text"; text: string; source?: string }
  | { type: "image"; file_id: string; source?: "camera" | "album" | "upload" }
  | { type: "audio"; file_id: string; duration_seconds?: number };

export type ConversationMessagePart =
  | MessagePart
  | {
      type: "event";
      event_type: string;
      text?: string;
      pending_action_id?: string;
      record_type?: string;
      record_id?: string;
    };

export type ConversationMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: ConversationMessagePart[];
  intent?: string | null;
  requires_review?: boolean;
  created_at: string;
};

export type PendingActionType = "create_meal_record" | "create_body_metric_record" | "create_workout_record" | "generate_daily_summary" | "answer_fitness_question" | "out_of_scope";

export type PendingAction = {
  pending_action_id: string;
  type: PendingActionType;
  status: "pending_confirmation" | "needs_clarification" | "committed" | "discarded" | "expired";
  confidence?: number | null;
  draft_payload: MealRecord | BodyMetricRecord | Record<string, unknown>;
  warnings?: Array<{ field?: string; reason?: string }>;
  created_at?: string;
  updated_at?: string;
  expires_at?: string;
};

export type SendMessageResponse = {
  message_id: string;
  assistant_message_id?: string;
  assistant_text?: string;
  intent?: string;
  requires_review?: boolean;
  committed_records?: Array<Record<string, unknown>>;
  tool_results?: Array<Record<string, unknown>>;
  agent_trace?: Array<Record<string, unknown>>;
  pending_actions?: PendingAction[];
};

export type AgentContinuation = {
  assistant_message_id: string;
  assistant_text: string;
  intent: string;
  requires_review: boolean;
  committed_records?: Array<Record<string, unknown>>;
  pending_actions?: PendingAction[];
  tool_results?: Array<Record<string, unknown>>;
  agent_trace?: Array<Record<string, unknown>>;
};

export type UploadFile = {
  id: string;
  storage_provider: string;
  client_local_ref?: string | null;
  bucket?: string | null;
  object_key?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  source?: string | null;
  retention_policy?: string | null;
  status?: string | null;
  created_at?: string;
  deleted_at?: string | null;
};

export type UploadTranscriptionResponse = {
  file_id: string;
  status: "transcribed" | "unprocessed";
  transcript?: string | null;
  language?: string | null;
  confidence?: number | null;
  provider?: string | null;
  warnings?: Array<Record<string, unknown>>;
};
