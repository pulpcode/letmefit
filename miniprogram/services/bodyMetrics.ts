import { request } from "../utils/request";
import type { BodyMetricRecord } from "../types/api";

export function getBodyMetrics(dateFrom: string, dateTo = dateFrom) {
  return request<{ body_metrics: BodyMetricRecord[] }>({
    path: `/body-metrics?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`
  });
}

export function createBodyMetric(metric: BodyMetricRecord) {
  return request<BodyMetricRecord>({
    path: "/body-metrics",
    method: "POST",
    data: metric
  });
}
