import { recordsApi } from "../../services/api";
import type { BodyMetricRecord, MealRecord } from "../../types/api";
import { todayLocalDate } from "../../utils/date";

Page({
  data: {
    date: todayLocalDate(),
    meals: [] as MealRecord[],
    bodyMetrics: [] as BodyMetricRecord[],
    loading: false
  },

  onShow() {
    if (!getApp<IAppOption>().globalData.auth?.accessToken) {
      wx.reLaunch({ url: "/pages/login/index" });
      return;
    }
    this.loadRecords();
  },

  onPullDownRefresh() {
    this.loadRecords().finally(() => wx.stopPullDownRefresh?.());
  },

  async loadRecords() {
    const date = this.data.date;
    this.setData({ loading: true });
    try {
      const [mealsRes, metricsRes] = await Promise.all([
        recordsApi.getMeals(date),
        recordsApi.getBodyMetrics(date, date)
      ]);
      this.setData({
        meals: mealsRes.meals || [],
        bodyMetrics: metricsRes.body_metrics || []
      });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "记录加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  goChat() {
    wx.switchTab({ url: "/pages/chat/index" });
  },

  goSummary() {
    wx.navigateTo({ url: `/pages/summary/index?date=${this.data.date}` });
  }
});

