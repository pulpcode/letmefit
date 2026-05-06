import { createConversation, listMessages, listPendingActions, sendMessage } from "../../../services/conversations";
import { confirmPendingAction, discardPendingAction } from "../../../services/pendingActions";
import { createClientLocalUpload, transcribeUploadFile, uploadLocalFile } from "../../../services/uploads";
import { showApiError } from "../../../utils/request";
import { getAgentAvatar } from "../../../utils/storage";
import type { ConversationMessage, MessagePart, PendingAction } from "../../../types/api";

const VOICE_MAX_SECONDS = 20;
const VOICE_MIN_DURATION_MS = 800;
const VOICE_MIN_BYTES = 4 * 1024;
const VOICE_TICK_MS = 200; // 进度刷新间隔

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
}

/** 解析一条服务端消息，提取文字内容 */
function parseMessage(message: ConversationMessage): string {
  const parts = message.content || [];
  const texts: string[] = [];

  for (const part of parts as any[]) {
    if (part.type === "text") {
      const text = part.source === "asr" ? stripAsrPrefix(part.text) : part.text;
      texts.push(text);
    } else if (part.type === "audio") {
      // 服务端 ASR 结果放在 content 中附加的 text 部分，不在 audio 块
      // audio 块本身不含文字，跳过（文字由 normalize 追加的 text 部分携带）
    } else if (part.type === "image") {
      texts.push("📷 图片");
    } else if (part.type === "event") {
      texts.push(part.text || "");
    }
  }

  return texts.join("\n");
}

function stripAsrPrefix(text: string): string {
  return (text || "").replace(/^语音转写[:：]\s*/, "");
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
    // 录音状态
    recording: false,
    voiceRemain: VOICE_MAX_SECONDS,
    voiceProgress: 100,
    voiceCancelling: false,
    scrollIntoView: "bottom-anchor"
  },

  recorder: null as any,
  _voiceTimer: null as any,
  _voiceStartY: 0,
  _voiceTouchActive: false,
  _voiceElapsedMs: 0,

  onLoad(options: any) {
    const { conversationId, title, placeholder } = options || {};
    this.recorder = wx.getRecorderManager();

    this.recorder.onStop((res: any) => {
      this._clearVoiceTimer();
      this.setData({ recording: false, voiceCancelling: false });
      if (res.tempFilePath && !this.data.voiceCancelling) {
        this.sendAudio(res.tempFilePath, res.duration || 0);
      }
    });

    this.recorder.onError(() => {
      this._clearVoiceTimer();
      this.setData({ recording: false, voiceCancelling: false });
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
    this._stopRecordingIfActive();
  },

  onUnload() {
    wx.showTabBar({ animation: false });
    this._stopRecordingIfActive();
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
      this.setData({ conversationId: res.conversation_id });
      return res.conversation_id;
    } catch (error) {
      showApiError(error);
      return "";
    }
  },

  async refreshConversation(conversationId?: string) {
    const cid = conversationId || this.data.conversationId;
    if (!cid) return;
    try {
      const [messageData, pendingData] = await Promise.all([
        listMessages(cid),
        listPendingActions(cid)
      ]);
      const messages = (messageData.messages || [])
        .map((msg) => ({
          id: msg.id,
          role: msg.role,
          text: parseMessage(msg)
        }))
        .filter((msg) => msg.text);
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
      const res = await wx.showActionSheet({ itemList: ["拍照", "从相册选择"] });
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
        source === "camera" ? "📷 拍照" : "📷 图片"
      );
    } catch (error) {
      if ((error as any)?.errMsg?.includes("cancel")) return;
      showApiError(error);
    }
  },

  // ========== 语音录制：按住触发 ==========

  onVoiceTouchStart(event: any) {
    if (this.data.recording || this.data.sending) return;
    this._voiceTouchActive = true;
    this._voiceStartY = event.touches?.[0]?.clientY ?? 0;
    wx.authorize({
      scope: "scope.record",
      success: () => {
        if (this._voiceTouchActive && !this.data.recording) {
          this._startRecording();
        }
      },
      fail: () => {
        this._voiceTouchActive = false;
        wx.showToast({ title: "请允许麦克风权限", icon: "none" });
      }
    });
  },

  onVoiceTouchEnd(event: any) {
    if (!this._voiceTouchActive && !this.data.recording) return;
    this._voiceTouchActive = false;
    if (!this.data.recording) return;
    const endY = event.changedTouches?.[0]?.clientY ?? this._voiceStartY;
    const cancelled = (this._voiceStartY - endY) > 80; // 上滑 80px 取消
    this._stopRecording(cancelled);
  },

  onVoiceTouchCancel() {
    this._voiceTouchActive = false;
    if (this.data.recording) {
      this._stopRecording(true);
    }
  },

  _startRecording() {
    this._voiceElapsedMs = 0;
    this.setData({
      recording: true,
      voiceCancelling: false,
      voiceRemain: VOICE_MAX_SECONDS,
      voiceProgress: 100
    });
    this.recorder.start({
      duration: VOICE_MAX_SECONDS * 1000,
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: "mp3"
    });
    this._startVoiceTimer();
    wx.vibrateShort({ type: "medium" });
  },

  _startVoiceTimer() {
    this._clearVoiceTimer();
    this._voiceTimer = setInterval(() => {
      this._voiceElapsedMs += VOICE_TICK_MS;
      const elapsed = this._voiceElapsedMs / 1000;
      const remain = Math.max(0, VOICE_MAX_SECONDS - elapsed);
      const progress = (remain / VOICE_MAX_SECONDS) * 100;
      this.setData({ voiceRemain: Math.ceil(remain), voiceProgress: progress });
      if (remain <= 0) {
        this._stopRecording(false);
      }
    }, VOICE_TICK_MS);
  },

  _clearVoiceTimer() {
    if (this._voiceTimer) {
      clearInterval(this._voiceTimer);
      this._voiceTimer = null;
    }
  },

  _stopRecording(cancel: boolean) {
    this._clearVoiceTimer();
    this._voiceTouchActive = false;
    this.setData({ voiceCancelling: cancel });
    this.recorder.stop();
  },

  _stopRecordingIfActive() {
    if (this.data.recording) {
      this._stopRecording(true);
    }
  },

  async sendAudio(tempFilePath: string, duration: number) {
    const valid = await this._validateAudioFile(tempFilePath, duration);
    if (!valid) {
      return;
    }
    const conversationId = await this.ensureConversation();
    if (!conversationId) return;

    const localUserMessage: ChatMessage = {
      id: `local_user_voice_${Date.now()}`,
      role: "user",
      text: "正在识别..."
    };
    this.setData({
      sending: true,
      messages: [...this.data.messages, localUserMessage]
    });
    this.scrollToBottom();

    let transcriptShown = false;
    try {
      // 必须用 uploadLocalFile 将音频文件上传到服务端，
      // 后端 ASR（paraformer）需要一个公网可访问的 HTTP URL，
      // client_local 模式只保存本地引用，后端无法访问音频文件。
      const mimeType = await this._audioMimeType(tempFilePath);
      const upload = await uploadLocalFile({
        filePath: tempFilePath,
        mime_type: mimeType,
        source: "microphone"
      });
      const transcription = await transcribeUploadFile(upload.file.id);
      const transcript = stripAsrPrefix(transcription.transcript || "").trim();
      if (!transcript) {
        this._removeMessage(localUserMessage.id);
        wx.showToast({ title: "语音识别失败", icon: "none" });
        return;
      }

      this._updateMessageText(localUserMessage.id, transcript);
      transcriptShown = true;
      const data = await sendMessage(conversationId, [
        { type: "audio", file_id: upload.file.id, duration_seconds: Math.round(duration / 1000) },
        { type: "text", text: `语音转写: ${transcript}`, source: "asr" }
      ]);
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
      if (!transcriptShown) {
        this._removeMessage(localUserMessage.id);
      }
      showApiError(error);
    } finally {
      this.setData({ sending: false });
    }
  },

  _updateMessageText(messageId: string, text: string) {
    this.setData({
      messages: this.data.messages.map((message) =>
        message.id === messageId ? { ...message, text } : message
      )
    });
    this.scrollToBottom();
  },

  _removeMessage(messageId: string) {
    this.setData({
      messages: this.data.messages.filter((message) => message.id !== messageId)
    });
  },

  async _validateAudioFile(filePath: string, duration: number): Promise<boolean> {
    if (duration < VOICE_MIN_DURATION_MS) {
      this._showInvalidAudioTip();
      return false;
    }

    try {
      const size = await this._audioFileSize(filePath);
      if (size < VOICE_MIN_BYTES) {
        this._showInvalidAudioTip();
        return false;
      }
    } catch (_) {
      wx.showToast({ title: "读取录音失败", icon: "none" });
      return false;
    }

    return true;
  },

  _audioFileSize(filePath: string): Promise<number> {
    return new Promise((resolve, reject) => {
      wx.getFileInfo({
        filePath,
        success: (res: any) => resolve(Number(res.size || 0)),
        fail: reject
      });
    });
  },

  _showInvalidAudioTip() {
    if (this._isDevtools()) {
      wx.showModal({
        title: "录音无效",
        content: "录音文件太短或几乎为空。开发者工具录音不稳定，建议用真机预览测试。",
        showCancel: false
      });
      return;
    }
    wx.showToast({ title: "说话时间太短", icon: "none" });
  },

  _isDevtools(): boolean {
    try {
      const info = wx.getSystemInfoSync();
      return info?.platform === "devtools";
    } catch (_) {
      return false;
    }
  },

  async _audioMimeType(filePath: string): Promise<string> {
    if (await this._isWebmAudio(filePath)) return "audio/webm";
    const lower = (filePath || "").toLowerCase();
    if (lower.endsWith(".m4a") || lower.endsWith(".mp4")) return "audio/mp4";
    if (lower.endsWith(".aac")) return "audio/aac";
    if (lower.endsWith(".wav")) return "audio/wav";
    return "audio/mpeg";
  },

  _isWebmAudio(filePath: string): Promise<boolean> {
    return new Promise((resolve) => {
      try {
        wx.getFileSystemManager().readFile({
          filePath,
          position: 0,
          length: 4,
          success: (res: any) => {
            const bytes = new Uint8Array(res.data as ArrayBuffer);
            resolve(bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3);
          },
          fail: () => resolve(false)
        });
      } catch (_) {
        resolve(false);
      }
    });
  },

  // ========== PendingAction ==========

  async onConfirmAction(event: any) {
    if (this.data.sending) return;
    const pendingActionId = event.detail.pendingActionId;
    try {
      this.setData({ sending: true });
      await confirmPendingAction(pendingActionId, true);
      wx.showToast({ title: "已保存", icon: "success" });
      await this.refreshConversation();
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ sending: false });
    }
  },

  async onDiscardAction(event: any) {
    if (this.data.sending) return;
    const pendingActionId = event.detail.pendingActionId;
    try {
      this.setData({ sending: true });
      await discardPendingAction(pendingActionId, true);
      wx.showToast({ title: "已放弃", icon: "success" });
      await this.refreshConversation();
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ sending: false });
    }
  },

  onEditAction() {
    wx.showModal({
      title: "修改待确认内容",
      editable: true,
      placeholderText: "例如：鸡胸肉改为180g",
      confirmText: "提交修改",
      success: async (res: any) => {
        if (!res.confirm || !res.content) return;
        await this.sendContent([{ type: "text", text: res.content }], res.content);
      }
    });
  },

  scrollToBottom() {
    setTimeout(() => {
      this.setData({ scrollIntoView: "bottom-anchor" });
    }, 50);
  }
});
