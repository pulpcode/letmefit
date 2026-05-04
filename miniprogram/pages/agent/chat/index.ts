import { createConversation, listMessages, listPendingActions, sendMessage } from "../../../services/conversations";
import { confirmPendingAction, discardPendingAction, patchPendingAction } from "../../../services/pendingActions";
import { createClientLocalUpload, uploadLocalFile } from "../../../services/uploads";
import { showApiError } from "../../../utils/request";
import { getAgentAvatar } from "../../../utils/storage";
import type { ConversationMessage, MessagePart, PendingAction } from "../../../types/api";

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
    pageTitle: "对话",
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

  onLoad(options: any) {
    const { conversationId, title, placeholder } = options || {};
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

    if (conversationId) {
      this.setData({
        conversationId,
        pageTitle: title ? decodeURIComponent(title) : "对话",
        inputPlaceholder: placeholder ? decodeURIComponent(placeholder) : "告诉我今天吃了什么..."
      });
    }
  },

  onShow() {
    // 隐藏 tabBar，确保聊天页沉浸式体验
    wx.hideTabBar({ animation: false });

    const avatarType = getAgentAvatar();
    this.setData({
      avatar: avatarType,
      avatarSrc: avatarType === "male" ? "/assets/male-fit-agent.png" : "/assets/female-fit-agent.png"
    });

    const cid = this.data.conversationId;
    if (cid) {
      this.refreshConversation(cid);
    } else {
      this.ensureConversation();
    }
  },

  onHide() {
    wx.showTabBar({ animation: false });
  },

  onUnload() {
    wx.showTabBar({ animation: false });
  },

  onBack() {
    wx.navigateBack();
  },

  async onMoreOptions() {
    try {
      const res = await wx.showActionSheet({ itemList: ["清空消息", "删除会话"] });
      if (res.tapIndex === 0) {
        wx.showToast({ title: "功能开发中", icon: "none" });
      } else if (res.tapIndex === 1) {
        wx.showToast({ title: "功能开发中", icon: "none" });
      }
    } catch (_) {
      // 取消操作
    }
  },

  async ensureConversation() {
    if (this.data.conversationId) return this.data.conversationId;
    try {
      const res = await createConversation("新对话");
      const conversationId = res.conversation_id;
      this.setData({ conversationId });
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
      const [messageData, pendingData] = await Promise.all([
        listMessages(currentConversationId),
        listPendingActions(currentConversationId)
      ]);
      const messages = (messageData.messages || [])
        .map((message) => ({
          id: message.id,
          role: message.role,
          text: messageText(message)
        }))
        .filter((message) => message.text);
      this.setData({
        messages,
        pendingActions: (pendingData.pending_actions || []).filter(
          (item) => item.status === "pending_confirmation"
        )
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
      await this.sendContent(
        [{ type: "image", file_id: upload.file.id, source }],
        source === "camera" ? "拍照记录" : "上传图片"
      );
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
    if (this.data.sending) return;
    this.setData({ sending: true });
    try {
      const upload = await uploadLocalFile({
        filePath: tempFilePath,
        mime_type: "audio/mpeg",
        source: "microphone"
      });
      this.setData({ sending: false });
      await this.sendContent(
        [{ type: "audio", file_id: upload.file.id, duration_seconds: Math.round(duration / 1000) }],
        "语音记录"
      );
    } catch (error) {
      this.setData({ sending: false });
      showApiError(error);
    }
  },

  async onConfirmAction(event: any) {
    const pendingActionId = event.detail.pendingActionId;
    try {
      await confirmPendingAction(pendingActionId);
      wx.showToast({ title: "已保存", icon: "success" });
      this.setData({
        pendingActions: this.data.pendingActions.filter(
          (item) => item.pending_action_id !== pendingActionId
        ),
        messages: [
          ...this.data.messages,
          {
            id: `confirm_${Date.now()}`,
            role: "assistant",
            text: "已确认保存，可在记录页查看或修改。"
          }
        ]
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
        pendingActions: this.data.pendingActions.filter(
          (item) => item.pending_action_id !== pendingActionId
        )
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
            pendingActions: this.data.pendingActions.map((item) =>
              item.pending_action_id === pendingActionId ? updated : item
            )
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
