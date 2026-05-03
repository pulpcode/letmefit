import { request } from "../utils/request";
import type { Archive } from "../types/api";

export function getDailyArchive(date: string) {
  return request<{ archive: Archive }>({
    path: `/daily-archives/${encodeURIComponent(date)}`
  });
}
