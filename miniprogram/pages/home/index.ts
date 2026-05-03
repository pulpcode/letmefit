import { getDailyArchive } from "../../services/archives";
import { getBodyMetrics } from "../../services/bodyMetrics";
import { getMeals } from "../../services/meals";
import { getProfile } from "../../services/profile";
import { greeting, shortTime, todayCn, toDateString } from "../../utils/date";
import { mealTitle, metricTitle } from "../../utils/format";
import { showApiError } from "../../utils/request";
import type { Archive, BodyMetricRecord, MealRecord, Profile } from "../../types/api";

Page({
  data: {
    loading: false,
    today: toDateString(),
    greetingText: greeting(),
    todayText: todayCn(),
    profileCompleted: true,
    profile: null as Profile | null,
    stats: {
      mealCount: 0,
      bodyMetricCount: 0,
      calories: "-",
      protein: "-"
    },
    isEmpty: true,
    recentRecords: [] as Array<Record<string, unknown>>,
    suggestion: "今天还没有记录，可以先记录一餐或补充一次身体指标。"
  },

  onShow() {
    this.loadData();
  },

  async loadData() {
    const date = toDateString();
    this.setData({ loading: true, today: date, greetingText: greeting(), todayText: todayCn() });
    try {
      const [profileData, mealsData, metricsData, archiveData] = await Promise.all([
        getProfile(),
        getMeals(date).catch(() => ({ meals: [] })),
        getBodyMetrics(date).catch(() => ({ body_metrics: [] })),
        getDailyArchive(date).catch(() => ({ archive: null as any }))
      ]);
      const archive = archiveData.archive as Archive | null;
      const meals = mealsData.meals || [];
      const metrics = metricsData.body_metrics || [];
      this.setData({
        profileCompleted: profileData.profile_completed,
        profile: profileData.profile,
        stats: this.buildStats(meals, metrics, archive),
        isEmpty: meals.length === 0 && metrics.length === 0,
        recentRecords: this.buildRecentRecords(meals, metrics),
        suggestion: meals.length || metrics.length
          ? "今天蛋白质记录较完整，晚餐可以继续保持清淡。建议补充一些绿叶蔬菜。"
          : "从一条记录开始，今天的总结会更准确。"
      });
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ loading: false });
    }
  },

  buildStats(meals: MealRecord[], metrics: BodyMetricRecord[], archive: Archive | null) {
    const calorieTotal = archive?.calorie_total ?? meals.reduce((sum, meal) => sum + (Number(meal.total_calories) || 0), 0);
    const proteinTotal = archive?.protein_total_g ?? meals.reduce((sum, meal) => sum + (Number(meal.total_protein_g) || 0), 0);
    return {
      mealCount: archive?.meal_count ?? meals.length,
      bodyMetricCount: archive?.body_metric_count ?? metrics.length,
      calories: calorieTotal ? `${Math.round(calorieTotal)}` : "-",
      protein: proteinTotal ? `${Math.round(proteinTotal)}g` : "-"
    };
  },

  buildRecentRecords(meals: MealRecord[], metrics: BodyMetricRecord[]) {
    const mealRows = meals.map((meal) => ({
      id: meal.id,
      type: "meal",
      title: mealTitle(meal),
      time: shortTime(meal.recorded_at),
      value: meal.total_calories ? `${Math.round(meal.total_calories)} kcal` : "",
      tone: "green"
    }));
    const metricRows = metrics.map((metric) => ({
      id: metric.id,
      type: "metric",
      title: metricTitle(metric),
      time: shortTime(metric.recorded_at),
      value: metric.weight_kg ? `${metric.weight_kg}kg` : "",
      tone: "blue"
    }));
    return [...mealRows, ...metricRows].slice(0, 3);
  },

  goProfile() {
    wx.switchTab({ url: "/pages/profile/index" });
  },

  goAgent(event: any) {
    const mode = event.currentTarget.dataset.mode || "";
    if (mode) {
      wx.setStorageSync("letmefit.agent_prefill_mode", mode);
    }
    wx.switchTab({ url: "/pages/agent/index" });
  },

  goSummary() {
    wx.navigateTo({ url: `/pages/summary/index?date=${this.data.today}` });
  },

  goRecords() {
    wx.switchTab({ url: "/pages/records/index" });
  }
});
