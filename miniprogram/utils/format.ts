import type { BodyMetricRecord, MealRecord, Profile } from "../types/api";

export const goalLabels: Record<string, string> = {
  fat_loss: "减脂",
  muscle_gain: "增肌",
  maintenance: "维持健康",
  fitness: "建立记录习惯"
};

export const sexLabels: Record<string, string> = {
  male: "男",
  female: "女",
  other: "其他",
  unspecified: "不透露"
};

export const activityLabels: Record<string, string> = {
  sedentary: "久坐",
  light: "轻度活动",
  moderate: "中等活动",
  active: "经常运动",
  very_active: "高强度运动"
};

export const mealTypeLabels: Record<string, string> = {
  breakfast: "早餐",
  lunch: "午餐",
  dinner: "晚餐",
  snack: "加餐",
  unknown: "餐食"
};

export function numberText(value?: number | null, suffix = ""): string {
  return value === null || value === undefined ? "-" : `${value}${suffix}`;
}

export function profileRows(profile: Profile | null) {
  return [
    { key: "sex", label: "性别", value: profile?.sex ? sexLabels[profile.sex] : "未填写" },
    { key: "age", label: "年龄", value: profile?.age ? `${profile.age}岁` : "未填写" },
    { key: "height", label: "身高", value: profile?.height_cm ? `${profile.height_cm}cm` : "未填写" },
    { key: "current_weight", label: "当前体重", value: profile?.current_weight_kg ? `${profile.current_weight_kg}kg` : "未填写" },
    { key: "target_weight", label: "目标体重", value: profile?.target_weight_kg ? `${profile.target_weight_kg}kg` : "未填写" },
    { key: "activity", label: "活动水平", value: profile?.activity_level ? activityLabels[profile.activity_level] : "未填写" },
    { key: "goal", label: "主要目标", value: profile?.goal_type ? goalLabels[profile.goal_type] : "未填写" }
  ];
}

export function mealTitle(meal: MealRecord): string {
  const type = meal.meal_type ? mealTypeLabels[meal.meal_type] : "餐食";
  const first = meal.items?.[0]?.name;
  return first ? `${type}：${first}${meal.items && meal.items.length > 1 ? "等" : ""}` : type;
}

export function metricTitle(metric: BodyMetricRecord): string {
  return metric.weight_kg ? `体重 ${metric.weight_kg}kg` : "身体指标";
}
