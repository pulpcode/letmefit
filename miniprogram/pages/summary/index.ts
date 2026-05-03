import { getBodyMetrics } from "../../services/bodyMetrics";
import { getMeals } from "../../services/meals";
import { generateSummary } from "../../services/summaries";
import { shortTime, toDateString } from "../../utils/date";
import { mealTypeLabels } from "../../utils/format";
import { showApiError } from "../../utils/request";

Page({
  data: {
    date: toDateString(),
    summary: {
      calorie_total: 0,
      protein_total_g: 0,
      carbs_total_g: 0,
      fat_total_g: 0,
      meal_count: 0,
      body_metric_count: 0,
      suggestions: [],
      completeness_score: 0
    } as any,
    meals: [] as any[],
    metrics: [] as any[],
    bars: [] as any[],
    loading: false
  },

  onLoad(query: any) {
    if (query.date) {
      this.setData({ date: query.date });
    }
    this.loadData();
  },

  async loadData() {
    this.setData({ loading: true });
    try {
      const [summaryData, mealData, metricData] = await Promise.all([
        generateSummary(this.data.date),
        getMeals(this.data.date).catch(() => ({ meals: [] })),
        getBodyMetrics(this.data.date).catch(() => ({ body_metrics: [] }))
      ]);
      const summary = summaryData.summary;
      this.setData({
        summary,
        bars: [
          { label: "蛋白质", value: `${summary.protein_total_g || 0}g`, width: "75%", color: "green" },
          { label: "碳水化合物", value: `${summary.carbs_total_g || 0}g`, width: "85%", color: "blue" },
          { label: "脂肪", value: `${summary.fat_total_g || 0}g`, width: "60%", color: "orange" }
        ],
        meals: (mealData.meals || []).map((meal) => ({
          ...meal,
          mealTypeText: mealTypeLabels[meal.meal_type || "unknown"],
          time: shortTime(meal.recorded_at),
          foods: (meal.items || []).map((item: any) => item.name).join("、"),
          caloriesText: meal.total_calories ? `${Math.round(meal.total_calories)} kcal` : "-"
        })),
        metrics: (metricData.body_metrics || []).map((metric) => ({
          ...metric,
          time: shortTime(metric.recorded_at),
          valueText: `${metric.weight_kg || "-"} kg${metric.body_fat_percentage ? ` · 体脂 ${metric.body_fat_percentage}%` : ""}`
        }))
      });
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ loading: false });
    }
  },

  goAgent() {
    wx.switchTab({ url: "/pages/agent/index" });
  }
});
