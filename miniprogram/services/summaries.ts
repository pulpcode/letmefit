import { request } from "../utils/request";
import type { DailySummary } from "../types/api";

export function generateSummary(date: string, timezone = "Asia/Shanghai") {
  return request<{ summary: DailySummary }>({
    path: "/summaries/generate",
    method: "POST",
    data: { date, timezone }
  });
}
