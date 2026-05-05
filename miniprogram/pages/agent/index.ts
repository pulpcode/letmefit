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
    // 胶囊按钮安全右边距（rpx），动态计算，默认留足空间
    capsuleSafeRight: 220,
  },

  // 标记：是否是本页主动发起的 navigateTo（用于区分 onShow 是 Tab 切换还是从子页返回）
  _justNavigatedToChat: false,

  onLoad() {
    this._calcCapsuleSafeRight();
  },

  /** 计算胶囊按钮左边缘到屏幕右侧的距离，换算为 rpx 作为 header 的 padding-right */
  _calcCapsuleSafeRight() {
    try {
      const menuBtn = wx.getMenuButtonBoundingClientRect();
      const sysInfo = wx.getSystemInfoSync();
      const ratio = 750 / sysInfo.windowWidth; // px → rpx 换算比
      // 从屏幕右侧到胶囊左边缘的距离，再加 16rpx 间距
      const safeRight = Math.ceil((sysInfo.windowWidth - menuBtn.left) * ratio) + 16;
      this.setData({ capsuleSafeRight: safeRight });
    } catch (_) {
      // 获取失败时保留默认值 220rpx
    }
  },

  onShow() {
    // ── 情况1：从子页（聊天页）返回，不再自动跳转，只刷新列表 ──
    if (this._justNavigatedToChat) {
      this._justNavigatedToChat = false;
      this.loadConversations();
      return;
    }

    // ── 情况2：来自首页快捷入口的 prefill_mode，新建会话后跳转 ──
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

    // ── 情况3：Tab 切换进来，有缓存会话则直接跳转到最近的那条 ──
    const cached = this.data.conversations;
    if (cached.length > 0) {
      this._justNavigatedToChat = true;
      wx.navigateTo({
        url: `/pages/agent/chat/index?conversationId=${cached[0].id}&title=${encodeURIComponent(cached[0].title || "对话")}`
      });
      // 后台静默刷新，下次返回时列表数据是最新的
      this.loadConversations();
      return;
    }

    // ── 情况4：首次进入或无会话，加载列表 ──
    this.loadConversations();
  },

  async createAndOpenSession(placeholder: string) {
    try {
      const res = await createConversation("新对话");
      const conv = res.conversation;
      this._justNavigatedToChat = true;
      wx.navigateTo({
        url: `/pages/agent/chat/index?conversationId=${conv.id}&title=${encodeURIComponent(conv.title || "新对话")}&placeholder=${encodeURIComponent(placeholder)}`
      });
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

      const items = await Promise.all(
        list.map(async (conv: Conversation, idx: number) => {
          let preview = "";
          try {
            const msgRes = await listMessages(conv.id);
            const msgs = msgRes.messages || [];
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
    this._justNavigatedToChat = true;
    wx.navigateTo({
      url: `/pages/agent/chat/index?conversationId=${id}&title=${encodeURIComponent(title || "对话")}`
    });
  },

  async onNewSession() {
    try {
      const res = await createConversation("新对话");
      const conv = res.conversation;
      this._justNavigatedToChat = true;
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
    this._justNavigatedToChat = true;
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
