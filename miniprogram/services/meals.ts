import { request } from "../utils/request";
import type { MealRecord } from "../types/api";

export function getMeals(date: string) {
  return request<{ meals: MealRecord[] }>({
    path: `/meals?date=${encodeURIComponent(date)}`
  });
}

export function createMeal(meal: MealRecord) {
  return request<MealRecord>({
    path: "/meals",
    method: "POST",
    data: meal
  });
}
