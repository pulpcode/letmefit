import { createConversation, listConversations, listMessages, listPendingActions, sendMessage } from "../../services/conversations";
import { confirmPendingAction, discardPendingAction, patchPendingAction } from "../../services/pendingActions";
import { createClientLocalUpload } from "../../services/uploads";
import { showApiError } from "../../utils/request";
import { getAgentAvatar } from "../../utils/storage";
import type { ConversationMessage, MessagePart, PendingAction } from "../../types/api";

const MODE_KEY = "letmefit.agent_prefill_mode";

function messageText(message: ConversationMessage): string {
  return (message.content || [])
    .map((part: any) => {
      if (part.type === "text") return part.text;
      if (part.type === "image") return "发送了一张图片";
      if (part.type === "audio") return "发送了一段语音";
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

Page({
  data: {
    conversationId: "",
    messages: [] as Array<{ id: string; role: "user" | "assistant"; text: string }>,
    pendingActions: [] as PendingAction[],
    inputValue: "",
    inputPlaceholder: "告诉我今天吃了什么...",
    avatar: "female",
    avatarSrc: "/assets/female-fit-agent.png",
    sending: false,
    recording: false,
    scrollIntoView: "bottom-anchor"
  },

  recorder: null as any,

  onLoad() {
    this.recorder = wx.getRecorderManager();
    this.recorder.onStop((res: any) => {
      this.setData({ recording: false });
      if (res.tempFilePath) {
        this.sendAudio(res.tempFilePath, res.duration || 0);
      }
    });
    this.recorder.onError(() => {
      this.setData({ recording: false });
      wx.showToast({ title: "录音失败", icon: "none" });
    });
  },

  onShow() {
    const mode = wx.getStorageSync(MODE_KEY);
    wx.removeStorageSync(MODE_KEY);
    const placeholderMap: Record<string, string> = {
      meal: "描述刚吃的食物，或拍照记录",
      weight: "输入体重、体脂，或拍体脂秤"
    };
    this.setData({
      avatar: getAgentAvatar(),
      avatarSrc: getAgentAvatar() === "male" ? "/assets/male-fit-agent.png" : "/assets/female-fit-agent.png",
      inputPlaceholder: placeholderMap[mode] || "告诉我今天吃了什么..."
    });
    this.ensureConversation();
  },

  async ensureConversation() {
    if (this.data.conversationId) return this.data.conversationId;
    try {
      const list = await listConversations();
      const active = (list.conversations || []).find((item) => item.status === "active");
      const conversationId = active?.id || (await createConversation()).conversation_id;
      this.setData({ conversationId });
      await this.refreshConversation(conversationId);
      return conversationId;
    } catch (error) {
      showApiError(error);
      return "";
    }
  },

  async refreshConversation(conversationId?: string) {
    const currentConversationId = conversationId || this.data.conversationId;
    if (!currentConversationId) return;
    try {
      const [messageData, pendingData] = await Promise.all([listMessages(currentConversationId), listPendingActions(currentConversationId)]);
      const messages = (messageData.messages || []).map((message) => ({
        id: message.id,
        role: message.role,
        text: messageText(message)
      })).filter((message) => message.text);
      this.setData({
        messages,
        pendingActions: (pendingData.pending_actions || []).filter((item) => item.status === "pending_confirmation")
      });
      this.scrollToBottom();
    } catch (error) {
      showApiError(error);
    }
  },

  onInput(event: any) {
    this.setData({ inputValue: event.detail.value });
  },

  async onSend() {
    const text = this.data.inputValue.trim();
    if (!text || this.data.sending) return;
    this.setData({ inputValue: "" });
    await this.sendContent([{ type: "text", text }], text);
  },

  async sendContent(content: MessagePart[], userPreview: string) {
    const conversationId = await this.ensureConversation();
    if (!conversationId) return;

    const localUserMessage = {
      id: `local_user_${Date.now()}`,
      role: "user" as const,
      text: userPreview
    };
    this.setData({
      sending: true,
      messages: [...this.data.messages, localUserMessage]
    });
    this.scrollToBottom();

    try {
      const data = await sendMessage(conversationId, content);
      const nextMessages = [...this.data.messages];
      if (data.assistant_text) {
        nextMessages.push({
          id: data.assistant_message_id || `local_assistant_${Date.now()}`,
          role: "assistant",
          text: data.assistant_text
        });
      }
      this.setData({
        messages: nextMessages,
        pendingActions: data.pending_actions || this.data.pendingActions
      });
      if (data.committed_records?.length) {
        wx.showToast({ title: "已自动保存", icon: "success" });
      }
      this.scrollToBottom();
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ sending: false });
    }
  },

  async chooseImageSource() {
    try {
      const res = await wx.showActionSheet({
        itemList: ["拍照", "从相册选择"]
      });
      await this.chooseImage(res.tapIndex === 0 ? "camera" : "album");
    } catch (error) {
      if ((error as any)?.errMsg?.includes("cancel")) return;
      showApiError(error);
    }
  },

  async chooseImage(source: "camera" | "album") {
    try {
      const res = await wx.chooseMedia({
        count: 1,
        mediaType: ["image"],
        sourceType: [source],
        sizeType: ["compressed"]
      });
      const file = res.tempFiles[0];
      const upload = await createClientLocalUpload({
        client_local_ref: file.tempFilePath,
        mime_type: "image/jpeg",
        size_bytes: file.size,
        source
      });
      await this.sendContent([{ type: "image", file_id: upload.file.id, source }], source === "camera" ? "拍照记录" : "上传图片");
    } catch (error) {
      if ((error as any)?.errMsg?.includes("cancel")) return;
      showApiError(error);
    }
  },

  onVoiceTap() {
    if (this.data.recording) {
      this.recorder.stop();
      return;
    }
    wx.authorize({
      scope: "scope.record",
      success: () => {
        this.setData({ recording: true });
        this.recorder.start({
          duration: 60000,
          sampleRate: 16000,
          numberOfChannels: 1,
          encodeBitRate: 48000,
          format: "mp3"
        });
      },
      fail: () => wx.showToast({ title: "请允许麦克风权限", icon: "none" })
    });
  },

  async sendAudio(tempFilePath: string, duration: number) {
    try {
      const upload = await createClientLocalUpload({
        client_local_ref: tempFilePath,
        mime_type: "audio/mpeg",
        source: "microphone"
      });
      await this.sendContent([{ type: "audio", file_id: upload.file.id, duration_seconds: Math.round(duration / 1000) }], "语音记录");
    } catch (error) {
      showApiError(error);
    }
  },

  async onConfirmAction(event: any) {
    const pendingActionId = event.detail.pendingActionId;
    try {
      await confirmPendingAction(pendingActionId);
      wx.showToast({ title: "已保存", icon: "success" });
      this.setData({
        pendingActions: this.data.pendingActions.filter((item) => item.pending_action_id !== pendingActionId),
        messages: [...this.data.messages, { id: `confirm_${Date.now()}`, role: "assistant", text: "已确认保存，可在记录页查看或修改。" }]
      });
      this.scrollToBottom();
    } catch (error) {
      showApiError(error);
    }
  },

  async onDiscardAction(event: any) {
    const pendingActionId = event.detail.pendingActionId;
    try {
      await discardPendingAction(pendingActionId);
      this.setData({
        pendingActions: this.data.pendingActions.filter((item) => item.pending_action_id !== pendingActionId)
      });
      wx.showToast({ title: "已放弃", icon: "success" });
    } catch (error) {
      showApiError(error);
    }
  },

  onEditAction(event: any) {
    const { pendingActionId, action } = event.detail;
    wx.showModal({
      title: "修改待确认内容",
      editable: true,
      placeholderText: "例如：鸡胸肉改为180g",
      confirmText: "提交修改",
      success: async (res: any) => {
        if (!res.confirm || !res.content) return;
        try {
          const updated = await patchPendingAction(pendingActionId, action.draft_payload, res.content);
          this.setData({
            pendingActions: this.data.pendingActions.map((item) => item.pending_action_id === pendingActionId ? updated : item)
          });
          wx.showToast({ title: "已提交修改", icon: "success" });
        } catch (error) {
          showApiError(error);
        }
      }
    });
  },

  scrollToBottom() {
    setTimeout(() => {
      this.setData({ scrollIntoView: "bottom-anchor" });
    }, 50);
  }
});
