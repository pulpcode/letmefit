import { createConversation, deleteConversation, listConversations, listMessages } from "../../services/conversations";
import { showApiError } from "../../utils/request";
import type { Conversation } from "../../types/api";

/** 将 ISO 时间格式化为 "今天" / "昨天" / "M月D日" */
function formatTimeLabel(isoStr: string): string {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yestStart = new Date(todayStart.getTime() - 86400000);
  if (d >= todayStart) return "今天";
  if (d >= yestStart) return "昨天";
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

const ICON_COLORS = ["icon-green", "icon-blue", "icon-teal", "icon-purple", "icon-orange"];

interface SessionItem {
  id: string;
  title: string;
  timeLabel: string;
  preview: string;
  iconColor: string;
  deleting: boolean;
  status: "active" | "archived";
}

Page({
  data: {
    conversations: [] as SessionItem[],
    loading: true,
    actionSheetVisible: false,
    actionSheetTitle: "",
    actionSheetId: "",
  },

  onShow() {
    // 检测来自首页快捷入口的 prefill_mode，有则自动新建会话
    const mode = wx.getStorageSync("letmefit.agent_prefill_mode");
    if (mode) {
      wx.removeStorageSync("letmefit.agent_prefill_mode");
      const placeholderMap: Record<string, string> = {
        meal: "描述刚吃的食物，或拍照记录",
        weight: "输入体重、体脂，或拍体脂秤"
      };
      this.createAndOpenSession(placeholderMap[mode] || "");
      return;
    }
    this.loadConversations();
  },

  async createAndOpenSession(placeholder: string) {
    try {
      const res = await createConversation("新对话");
      const conv = res.conversation;
      wx.navigateTo({
        url: `/pages/agent/chat/index?conversationId=${conv.id}&title=${encodeURIComponent(conv.title || "新对话")}&placeholder=${encodeURIComponent(placeholder)}`
      });
      // 在跳转后刷新列表（后台）
      this.loadConversations();
    } catch (error) {
      showApiError(error);
    }
  },

  async loadConversations() {
    this.setData({ loading: true });
    try {
      const res = await listConversations();
      const list = (res.conversations || []).sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );

      // 并行加载每个会话的最后一条消息预览
      const items = await Promise.all(
        list.map(async (conv: Conversation, idx: number) => {
          let preview = "";
          try {
            const msgRes = await listMessages(conv.id);
            const msgs = msgRes.messages || [];
            // 取最后一条消息做预览
            for (let i = msgs.length - 1; i >= 0; i--) {
              const parts = msgs[i].content || [];
              const textPart = parts.find((p: any) => p.type === "text");
              if (textPart && (textPart as any).text) {
                preview = (textPart as any).text.slice(0, 40);
                break;
              }
            }
          } catch (_) {
            // 预览加载失败不影响列表展示
          }
          return {
            id: conv.id,
            title: conv.title || "新对话",
            timeLabel: formatTimeLabel(conv.updated_at),
            preview,
            iconColor: ICON_COLORS[idx % ICON_COLORS.length],
            deleting: false,
            status: conv.status,
          } as SessionItem;
        })
      );

      this.setData({ conversations: items, loading: false });
    } catch (error) {
      this.setData({ loading: false });
      showApiError(error);
    }
  },

  onOpenSession(event: any) {
    const { id, title } = event.currentTarget.dataset;
    wx.navigateTo({
      url: `/pages/agent/chat/index?conversationId=${id}&title=${encodeURIComponent(title || "对话")}`
    });
  },

  async onNewSession() {
    try {
      const res = await createConversation("新对话");
      const conv = res.conversation;
      wx.navigateTo({
        url: `/pages/agent/chat/index?conversationId=${conv.id}&title=${encodeURIComponent(conv.title || "新对话")}`
      });
    } catch (error) {
      showApiError(error);
    }
  },

  onLongPressSession(event: any) {
    const { id, title } = event.currentTarget.dataset;
    this.setData({
      actionSheetVisible: true,
      actionSheetId: id,
      actionSheetTitle: title || "对话",
    });
  },

  onActionEnter() {
    const { actionSheetId, actionSheetTitle } = this.data;
    this.setData({ actionSheetVisible: false });
    wx.navigateTo({
      url: `/pages/agent/chat/index?conversationId=${actionSheetId}&title=${encodeURIComponent(actionSheetTitle)}`
    });
  },

  async onActionDelete() {
    const { actionSheetId } = this.data;
    this.setData({ actionSheetVisible: false });
    const confirmed = await new Promise<boolean>((resolve) => {
      wx.showModal({
        title: "删除会话",
        content: "确定要删除这个会话吗？所有消息将被清除。",
        confirmText: "删除",
        confirmColor: "#fb2c36",
        success: (res) => resolve(res.confirm),
        fail: () => resolve(false),
      });
    });
    if (!confirmed) return;
    try {
      await deleteConversation(actionSheetId);
      this.setData({
        conversations: this.data.conversations.filter((c) => c.id !== actionSheetId),
      });
      wx.showToast({ title: "已删除", icon: "success" });
    } catch (error) {
      showApiError(error);
    }
  },

  onCloseActionSheet() {
    this.setData({ actionSheetVisible: false });
  },
});
