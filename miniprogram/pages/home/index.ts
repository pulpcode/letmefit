import { profileApi, recordsApi } from "../../services/api";
import type { BodyMetricRecord, DailyArchive, MealRecord, UserProfile } from "../../types/api";
import { todayLabel, todayLocalDate } from "../../utils/date";
import { numberText } from "../../utils/format";

Page({
  data: {
    loading: false,
    date: todayLocalDate(),
    dateLabel: todayLabel(),
    profile: null as UserProfile | null,
    profileCompleted: false,
    archive: null as DailyArchive | null,
    meals: [] as MealRecord[],
    bodyMetrics: [] as BodyMetricRecord[],
    latestWeight: "--",
    suggestion: "今天可以先记录一餐或一次体重，保持节奏比追求完美更重要。"
  },

  onShow() {
    if (!ensureAuth()) {
      return;
    }
    this.loadHome();
  },

  onPullDownRefresh() {
    this.loadHome().finally(() => wx.stopPullDownRefresh?.());
  },

  async loadHome() {
    const date = todayLocalDate();
    this.setData({ loading: true, date, dateLabel: todayLabel() });
    try {
      const [profileRes, archiveRes, mealsRes, metricsRes] = await Promise.all([
        profileApi.getProfile(),
        recordsApi.getDailyArchive(date),
        recordsApi.getMeals(date),
        recordsApi.getBodyMetrics(date, date)
      ]);
      const metrics = metricsRes.body_metrics || [];
      const latestMetric = metrics[0];
      this.setData({
        profile: profileRes.profile,
        profileCompleted: profileRes.profile_completed,
        archive: archiveRes.archive,
        meals: mealsRes.meals || [],
        bodyMetrics: metrics,
        latestWeight: latestMetric?.weight_kg ? `${numberText(latestMetric.weight_kg)} kg` : "--",
        suggestion: buildSuggestion(archiveRes.archive, mealsRes.meals || [], metrics)
      });
      getApp<IAppOption>().setProfile(profileRes.profile);
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "今日数据加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  goOnboarding() {
    wx.navigateTo({ url: "/pages/onboarding/index" });
  },

  goChat() {
    wx.switchTab({ url: "/pages/chat/index" });
  },

  goRecords() {
    wx.switchTab({ url: "/pages/records/index" });
  },

  goSummary() {
    wx.navigateTo({ url: `/pages/summary/index?date=${this.data.date}` });
  }
});

function ensureAuth(): boolean {
  if (!getApp<IAppOption>().globalData.auth?.accessToken) {
    wx.reLaunch({ url: "/pages/login/index" });
    return false;
  }
  return true;
}

function buildSuggestion(archive: DailyArchive, meals: MealRecord[], metrics: BodyMetricRecord[]): string {
  if (!meals.length && !metrics.length) {
    return "今天还没有记录，可以先从一餐或一次体重开始。";
  }
  if (meals.length < 2) {
    return "今天餐食记录还不完整，下一餐可以继续补充。";
  }
  if (!metrics.length) {
    return "今天还没有身体指标记录，可以补充一次体重。";
  }
  if ((archive.protein_total_g || 0) > 80) {
    return "今天蛋白质记录较完整，晚餐继续保持清淡和稳定。";
  }
  return "今天记录节奏不错，下一餐可以留意蛋白质来源。";
}

