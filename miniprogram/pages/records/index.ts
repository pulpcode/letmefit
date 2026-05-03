import { getBodyMetrics } from "../../services/bodyMetrics";
import { getMeals } from "../../services/meals";
import { shortTime, todayCn, toDateString } from "../../utils/date";
import { mealTitle, metricTitle } from "../../utils/format";
import { showApiError } from "../../utils/request";

Page({
  data: {
    date: toDateString(),
    todayText: todayCn(),
    meals: [] as any[],
    metrics: [] as any[],
    loading: false
  },

  onShow() {
    this.loadData();
  },

  async loadData() {
    this.setData({ loading: true });
    try {
      const [mealData, metricData] = await Promise.all([getMeals(this.data.date), getBodyMetrics(this.data.date)]);
      this.setData({
        meals: (mealData.meals || []).map((meal) => ({
          ...meal,
          title: mealTitle(meal),
          time: shortTime(meal.recorded_at),
          caloriesText: meal.total_calories ? `${Math.round(meal.total_calories)} kcal` : "-"
        })),
        metrics: (metricData.body_metrics || []).map((metric) => ({
          ...metric,
          title: metricTitle(metric),
          time: shortTime(metric.recorded_at),
          weightText: metric.weight_kg ? `${metric.weight_kg} kg` : "-"
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
