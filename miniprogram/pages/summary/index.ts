import { recordsApi } from "../../services/api";
import type { DailyArchive, DailySummary } from "../../types/api";
import { todayLocalDate } from "../../utils/date";

Page({
  data: {
    date: todayLocalDate(),
    loading: false,
    archive: null as DailyArchive | null,
    summary: null as DailySummary | null
  },

  onLoad(query) {
    this.setData({ date: query?.date || todayLocalDate() });
    this.loadSummary();
  },

  async loadSummary() {
    this.setData({ loading: true });
    try {
      const [archiveRes, summaryRes] = await Promise.all([
        recordsApi.getDailyArchive(this.data.date),
        recordsApi.generateSummary(this.data.date)
      ]);
      this.setData({
        archive: archiveRes.archive,
        summary: summaryRes.summary
      });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "总结生成失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  goChat() {
    wx.switchTab({ url: "/pages/chat/index" });
  }
});

