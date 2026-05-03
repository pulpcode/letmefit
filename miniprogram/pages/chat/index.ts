import { conversationApi, pendingActionApi, uploadApi } from "../../services/api";
import type { ConversationMessage, MessageContentItem, PendingAction } from "../../types/api";
import { getActiveConversationId, setActiveConversationId } from "../../utils/auth";

interface ChatMessageView {
  id: string;
  role: "user" | "assistant";
  text: string;
}

let recorder: WechatMiniprogram.RecorderManager | null = null;

Page({
  data: {
    conversationId: "",
    loading: false,
    sending: false,
    recording: false,
    inputText: "",
    messages: [] as ChatMessageView[],
    pendingActions: [] as PendingAction[],
    agentAvatar: "female",
    scrollTarget: ""
  },

  onShow() {
    if (!getApp<IAppOption>().globalData.auth?.accessToken) {
      wx.reLaunch({ url: "/pages/login/index" });
      return;
    }
    this.setData({
      agentAvatar: wx.getStorageSync<string>("letmefit.agentAvatar") || "female"
    });
    this.ensureConversation();
  },

  onLoad() {
    recorder = wx.getRecorderManager();
    recorder.onStop((res) => {
      this.setData({ recording: false });
      this.sendAudio(res.tempFilePath, res.fileSize, Math.round(res.duration / 1000));
    });
    recorder.onError(() => {
      this.setData({ recording: false });
      wx.showToast({ title: "录音失败", icon: "none" });
    });
  },

  async ensureConversation() {
    this.setData({ loading: true });
    try {
      let conversationId = getActiveConversationId();
      if (!conversationId) {
        const result = await conversationApi.createConversation("今天记录");
        conversationId = result.conversation_id;
        setActiveConversationId(conversationId);
      }
      this.setData({ conversationId });
      await this.loadConversation(conversationId);
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "会话加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  async loadConversation(conversationId: string) {
    const [messagesRes, actionsRes] = await Promise.all([
      conversationApi.listMessages(conversationId),
      conversationApi.listPendingActions(conversationId)
    ]);
    this.setData({
      messages: messagesRes.messages.map(toMessageView),
      pendingActions: filterPending(actionsRes.pending_actions),
      scrollTarget: "chat-bottom"
    });
  },

  onInput(event) {
    this.setData({ inputText: event.detail.value });
  },

  async onSendText() {
    const text = String(this.data.inputText || "").trim();
    if (!text) {
      return;
    }
    this.setData({ inputText: "" });
    await this.sendContent([{ type: "text", text }], text);
  },

  async onCamera() {
    await this.chooseAndSendImage("camera");
  },

  async onAlbum() {
    await this.chooseAndSendImage("album");
  },

  async chooseAndSendImage(source: "camera" | "album") {
    try {
      const file = await chooseImage(source);
      const upload = await uploadApi.createClientLocalFile({
        clientLocalRef: file.tempFilePath,
        mimeType: "image/jpeg",
        sizeBytes: file.size,
        source
      });
      await this.sendContent(
        [
          { type: "text", text: source === "camera" ? "这是我刚拍的记录，请帮我识别。" : "这是我选择的图片，请帮我识别。" },
          { type: "image", file_id: upload.file.id, source }
        ],
        source === "camera" ? "[拍照记录]" : "[图片记录]"
      );
    } catch (error) {
      if (error instanceof Error && error.message.includes("cancel")) {
        return;
      }
      wx.showToast({ title: error instanceof Error ? error.message : "图片发送失败", icon: "none" });
    }
  },

  onRecordTap() {
    if (!recorder) {
      return;
    }
    if (this.data.recording) {
      recorder.stop();
      return;
    }
    this.setData({ recording: true });
    recorder.start({
      duration: 60000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: "mp3"
    });
  },

  async sendAudio(tempFilePath: string, fileSize: number, durationSeconds: number) {
    try {
      const upload = await uploadApi.createClientLocalFile({
        clientLocalRef: tempFilePath,
        mimeType: "audio/mpeg",
        sizeBytes: fileSize,
        source: "microphone"
      });
      await this.sendContent(
        [
          { type: "text", text: "这是我的语音记录，请帮我整理。" },
          { type: "audio", file_id: upload.file.id, duration_seconds: durationSeconds }
        ],
        "[语音记录]"
      );
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "语音发送失败", icon: "none" });
    }
  },

  async sendContent(content: MessageContentItem[], displayText: string) {
    const conversationId = this.data.conversationId;
    if (!conversationId || this.data.sending) {
      return;
    }

    const localUserMessage: ChatMessageView = {
      id: `local-user-${Date.now()}`,
      role: "user",
      text: displayText
    };
    this.setData({
      sending: true,
      messages: [...this.data.messages, localUserMessage],
      scrollTarget: "chat-bottom"
    });

    try {
      const result = await conversationApi.sendMessage(conversationId, content);
      const assistantMessage: ChatMessageView = {
        id: result.assistant_message_id,
        role: "assistant",
        text: result.assistant_text
      };
      this.setData({
        messages: [...this.data.messages, assistantMessage],
        pendingActions: mergePending(this.data.pendingActions, result.pending_actions || []),
        scrollTarget: "chat-bottom"
      });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "发送失败", icon: "none" });
    } finally {
      this.setData({ sending: false });
    }
  },

  async onPendingUpdate(event) {
    const { pending_action_id, draft_payload } = event.detail;
    try {
      const updated = await pendingActionApi.update(pending_action_id, draft_payload, "用户在确认卡中修改");
      this.replacePendingAction(updated);
      wx.showToast({ title: "已修改", icon: "success" });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "修改失败", icon: "none" });
    }
  },

  async onPendingConfirm(event) {
    const { pending_action_id, draft_payload } = event.detail;
    try {
      await pendingActionApi.update(pending_action_id, draft_payload, "用户确认前提交修改");
      await pendingActionApi.confirm(pending_action_id);
      this.removePendingAction(pending_action_id);
      this.appendAssistantText("已保存到正式记录。");
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "保存失败", icon: "none" });
    }
  },

  async onPendingDiscard(event) {
    const { pending_action_id } = event.detail;
    try {
      await pendingActionApi.discard(pending_action_id);
      this.removePendingAction(pending_action_id);
      this.appendAssistantText("已放弃这条候选记录。");
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "操作失败", icon: "none" });
    }
  },

  replacePendingAction(action: PendingAction) {
    this.setData({
      pendingActions: this.data.pendingActions.map((item) => (item.pending_action_id === action.pending_action_id ? action : item))
    });
  },

  removePendingAction(pendingActionId: string) {
    this.setData({
      pendingActions: this.data.pendingActions.filter((item) => item.pending_action_id !== pendingActionId)
    });
  },

  appendAssistantText(text: string) {
    const message: ChatMessageView = {
      id: `local-assistant-${Date.now()}`,
      role: "assistant",
      text
    };
    this.setData({
      messages: [...this.data.messages, message],
      scrollTarget: "chat-bottom"
    });
  }
});

function toMessageView(message: ConversationMessage): ChatMessageView {
  return {
    id: message.id,
    role: message.role,
    text: extractText(message.content as Array<Record<string, unknown>>)
  };
}

function extractText(content: Array<Record<string, unknown>>): string {
  const parts = content.map((item) => {
    if (item.type === "text") {
      return String(item.text || "");
    }
    if (item.type === "image") {
      return "[图片]";
    }
    if (item.type === "audio") {
      return "[语音]";
    }
    return "";
  });
  return parts.filter(Boolean).join(" ");
}

function filterPending(actions: PendingAction[]): PendingAction[] {
  return (actions || []).filter((action) => action.status === "pending_confirmation");
}

function mergePending(current: PendingAction[], incoming: PendingAction[]): PendingAction[] {
  const map = new Map<string, PendingAction>();
  current.forEach((item) => {
    if (item.status === "pending_confirmation") {
      map.set(item.pending_action_id, item);
    }
  });
  incoming.forEach((item) => {
    if (item.status === "pending_confirmation") {
      map.set(item.pending_action_id, item);
    }
  });
  return Array.from(map.values());
}

function chooseImage(source: "camera" | "album"): Promise<{ tempFilePath: string; size: number }> {
  return new Promise((resolve, reject) => {
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: [source],
      camera: "back",
      success: (res) => {
        const file = res.tempFiles[0];
        if (!file) {
          reject(new Error("未选择图片"));
          return;
        }
        resolve({
          tempFilePath: file.tempFilePath,
          size: file.size
        });
      },
      fail: (error) => reject(new Error(error.errMsg || "cancel"))
    });
  });
}
