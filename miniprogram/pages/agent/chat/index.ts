import { createConversation, listMessages, listPendingActions, sendMessageStream } from "../../../services/conversations";
import { confirmPendingAction, discardPendingAction } from "../../../services/pendingActions";
import { transcribeUploadFile, uploadLocalFile } from "../../../services/uploads";
import { showApiError } from "../../../utils/request";
import { getAgentAvatar } from "../../../utils/storage";
import type { AgentContinuation, ConversationMessage, MessagePart, PendingAction } from "../../../types/api";

const VOICE_MAX_SECONDS = 20;
const VOICE_MIN_DURATION_MS = 800;
const VOICE_MIN_BYTES = 4 * 1024;
const VOICE_TICK_MS = 200;

type ChatItem =
  | {
      kind: "message";
      id: string;
      role: "user" | "assistant";
      text: string;
      images: ChatImage[];
      imageUrls: string[];
      createdAt: string;
    }
  | { kind: "vision_reasoning"; id: string; text: string; createdAt: string }
  | { kind: "pending_action"; id: string; action: PendingAction; createdAt: string }
  | { kind: "pending_action_superseded"; id: string; pendingActionId: string; createdAt: string };

type ChatImage = {
  fileId: string;
  url: string;
  source?: string;
};

interface ParsedMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  images: ChatImage[];
  visionText: string;
  createdAt: string;
}

function createMessageItem(input: {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  images?: ChatImage[];
}): ChatItem {
  const images = input.images || [];
  return {
    kind: "message",
    id: input.id,
    role: input.role,
    text: input.text,
    images,
    imageUrls: images.map((image) => image.url).filter(Boolean),
    createdAt: input.createdAt,
  };
}

function parseConversationMessage(message: ConversationMessage): ParsedMessage {
  const parts = message.content || [];
  const texts: string[] = [];
  const visionTexts: string[] = [];
  const images: ChatImage[] = [];

  for (const part of parts as any[]) {
    if (part.type === "text") {
      if (part.source === "vision") {
        visionTexts.push(stripVisionPrefix(part.text));
      } else {
        const text = part.source === "asr" ? stripAsrPrefix(part.text) : part.text;
        texts.push(text);
      }
    } else if (part.type === "image") {
      if (part.url) {
        images.push({
          fileId: part.file_id || "",
          url: part.url,
          source: part.source,
        });
      } else {
        texts.push("📷 图片");
      }
    } else if (part.type === "event") {
      texts.push(part.text || "");
    }
  }

  return {
    id: message.id,
    role: message.role,
    text: texts.filter(Boolean).join("\n"),
    images,
    visionText: visionTexts.filter(Boolean).join("\n"),
    createdAt: message.created_at
  };
}

function stripAsrPrefix(text: string): string {
  return (text || "").replace(/^语音转写[:：]\s*/, "");
}

function stripVisionPrefix(text: string): string {
  return (text || "").replace(/^图片理解[:：]\s*/, "");
}

function visionTextFromContent(content?: any[]): string {
  if (!content) return "";
  return (content as any[])
    .filter((part) => part.type === "text" && part.source === "vision")
    .map((part) => stripVisionPrefix(part.text || ""))
    .filter(Boolean)
    .join("\n");
}

function buildChatItems(messages: ParsedMessage[], pendingActions: PendingAction[]): ChatItem[] {
  const items: ChatItem[] = [];
  for (const msg of messages) {
    if (msg.text || msg.images.length) {
      items.push(createMessageItem({
        id: msg.id,
        role: msg.role,
        text: msg.text,
        images: msg.images,
        createdAt: msg.createdAt
      }));
    }
    if (msg.visionText) {
      items.push({
        kind: "vision_reasoning",
        id: `${msg.id}_vision`,
        text: msg.visionText,
        createdAt: msg.createdAt
      });
    }
  }
  for (const pa of pendingActions) {
    if (pa.status === "pending_confirmation") {
      items.push({ kind: "pending_action", id: pa.pending_action_id, action: pa, createdAt: pa.created_at || "" });
    }
  }
  items.sort((a, b) => {
    const byTime = a.createdAt.localeCompare(b.createdAt);
    if (byTime !== 0) return byTime;
    return chatItemOrder(a) - chatItemOrder(b);
  });
  return items;
}

function chatItemOrder(item: ChatItem): number {
  if (item.kind === "message") return item.role === "user" ? 0 : 2;
  if (item.kind === "vision_reasoning") return 1;
  if (item.kind === "pending_action") return 3;
  return 4;
}

Page({
  data: {
    conversationId: "",
    pageTitle: "对话",
    chatItems: [] as ChatItem[],
    inputValue: "",
    inputPlaceholder: "告诉我今天吃了什么...",
    avatar: "female",
    avatarSrc: "/assets/female-fit-agent.png",
    sending: false,
    streamingActive: false,
    summaryPending: false,
    recording: false,
    voiceRemain: VOICE_MAX_SECONDS,
    voiceProgress: 100,
    voiceCancelling: false,
    scrollIntoView: "bottom-anchor",
    scrollStyle: "",
    inputBarStyle: "",
    voiceCardStyle: "",
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
    wx.onKeyboardHeightChange((res: any) => this._updateLayoutForKeyboard(res.height));
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
    wx.offKeyboardHeightChange();
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
      const messages: ParsedMessage[] = (messageData.messages || [])
        .map((msg) => parseConversationMessage(msg))
        .filter((msg) => msg.text || msg.images.length || msg.visionText);
      this.setData({
        chatItems: buildChatItems(messages, pendingData.pending_actions || [])
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

  sendContent(content: MessagePart[], userPreview: string, options?: { userImages?: ChatImage[] }) {
    (async () => {
      const conversationId = await this.ensureConversation();
      if (!conversationId) return;

      const now = new Date().toISOString();
      const localUserItem = createMessageItem({
        id: `local_user_${Date.now()}`,
        role: "user",
        text: userPreview,
        images: options?.userImages || [],
        createdAt: now
      });
      const streamingId = `streaming_${Date.now()}`;
      const streamingItem = createMessageItem({
        id: streamingId,
        role: "assistant",
        text: "",
        createdAt: now
      });
      this.setData({
        sending: true,
        streamingActive: true,
        chatItems: [...this.data.chatItems, localUserItem, streamingItem]
      });
      this.scrollToBottom();

      let pendingText = "";
      let flushTimer: ReturnType<typeof setTimeout> | null = null;

      const flushText = () => {
        if (!pendingText) return;
        const toAdd = pendingText;
        pendingText = "";
        this.setData({
          chatItems: this.data.chatItems.map((item) =>
            item.id === streamingId && item.kind === "message"
              ? { ...item, text: item.text + toAdd }
              : item
          )
        });
        this.scrollToBottom();
      };

      sendMessageStream(
        conversationId,
        content,
        (delta) => {
          if (delta.type === "text" && delta.text) {
            pendingText += delta.text;
            if (!flushTimer) {
              flushTimer = setTimeout(() => {
                flushTimer = null;
                flushText();
              }, 50);
            }
          }
        },
        (data) => {
          if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
          const responseNow = new Date().toISOString();
          let nextItems = this.data.chatItems.filter((item) => item.id !== streamingId);
          const visionText = visionTextFromContent(data.normalized_content as any);
          if (visionText) {
            nextItems.push({
              kind: "vision_reasoning",
              id: `${data.message_id}_vision`,
              text: visionText,
              createdAt: responseNow
            });
          }
          if (data.assistant_text) {
            nextItems.push(createMessageItem({
              id: data.assistant_message_id || `local_assistant_${Date.now()}`,
              role: "assistant",
              text: data.assistant_text,
              createdAt: responseNow
            }));
          }
          const existingPendingMap = new Map<string, ChatItem>(
            this.data.chatItems
              .filter(i => i.kind === "pending_action")
              .map(i => [i.id, i as ChatItem])
          );
          for (const pa of data.pending_actions || []) {
            if (pa.status === "pending_confirmation") {
              if (existingPendingMap.has(pa.pending_action_id)) {
                const oldIdx = nextItems.findIndex(
                  i => i.id === pa.pending_action_id && i.kind === "pending_action"
                );
                if (oldIdx !== -1) {
                  const old = nextItems[oldIdx];
                  nextItems[oldIdx] = {
                    kind: "pending_action_superseded",
                    id: "superseded-" + pa.pending_action_id,
                    pendingActionId: pa.pending_action_id,
                    createdAt: old.createdAt,
                  };
                }
                nextItems.push({
                  kind: "pending_action",
                  id: pa.pending_action_id,
                  action: pa,
                  createdAt: responseNow,
                });
              } else {
                nextItems.push({
                  kind: "pending_action",
                  id: pa.pending_action_id,
                  action: pa,
                  createdAt: pa.created_at || responseNow,
                });
              }
            }
          }
          this.setData({ chatItems: nextItems, sending: false, streamingActive: false, summaryPending: data.summary_pending === true });
          if (data.committed_records?.length) {
            wx.showToast({ title: "已保存", icon: "success" });
          }
          this.scrollToBottom();
          // Only sync if stream didn't include pending action data — avoid overwriting correct state
          if (!(data.pending_actions?.length)) {
            this._syncPendingActions(conversationId);
          }
        },
        (error) => {
          if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
          this._removeChatItem(streamingId);
          this.setData({ sending: false, streamingActive: false });
          showApiError(error);
        },
        () => {
          // SSE 未送达（微信 enableChunked 下 onChunkReceived 未触发），从服务端拉取最新结果
          if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
          this._removeChatItem(streamingId);
          this.setData({ sending: false, streamingActive: false });
          this.refreshConversation(conversationId);
        }
      );
    })();
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

  previewChatImage(event: any) {
    const current = event.currentTarget?.dataset?.src;
    const urls = event.currentTarget?.dataset?.urls || [];
    if (!current) return;
    wx.previewImage({
      current,
      urls: Array.isArray(urls) && urls.length ? urls : [current]
    });
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
      const upload = await uploadLocalFile({
        filePath: file.tempFilePath,
        mime_type: "image/jpeg",
        source
      });
      await this.sendContent(
        [{ type: "image", file_id: upload.file.id, source }],
        "",
        {
          userImages: [{
            fileId: upload.file.id,
            url: file.tempFilePath || upload.file.object_key || "",
            source
          }].filter((image) => image.url)
        }
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
    const cancelled = (this._voiceStartY - endY) > 80;
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
    if (!valid) return;
    const conversationId = await this.ensureConversation();
    if (!conversationId) return;

    const now = new Date().toISOString();
    const localUserItem = createMessageItem({
      id: `local_user_voice_${Date.now()}`,
      role: "user",
      text: "正在识别...",
      createdAt: now
    });
    this.setData({
      sending: true,
      chatItems: [...this.data.chatItems, localUserItem]
    });
    this.scrollToBottom();

    let transcriptShown = false;
    try {
      const mimeType = await this._audioMimeType(tempFilePath);
      const upload = await uploadLocalFile({
        filePath: tempFilePath,
        mime_type: mimeType,
        source: "microphone"
      });
      const transcription = await transcribeUploadFile(upload.file.id);
      const transcript = stripAsrPrefix(transcription.transcript || "").trim();
      if (!transcript) {
        this._removeChatItem(localUserItem.id);
        this.setData({ sending: false });
        wx.showToast({ title: "语音识别失败", icon: "none" });
        return;
      }

      this._updateChatItemText(localUserItem.id, transcript);
      transcriptShown = true;

      const streamingId = `streaming_voice_${Date.now()}`;
      const streamingNow = new Date().toISOString();
      this.setData({
        streamingActive: true,
        chatItems: [...this.data.chatItems, createMessageItem({
          id: streamingId,
          role: "assistant",
          text: "",
          createdAt: streamingNow
        })]
      });
      this.scrollToBottom();

      let pendingText = "";
      let flushTimer: ReturnType<typeof setTimeout> | null = null;
      const flushText = () => {
        if (!pendingText) return;
        const toAdd = pendingText;
        pendingText = "";
        this.setData({
          chatItems: this.data.chatItems.map((item) =>
            item.id === streamingId && item.kind === "message"
              ? { ...item, text: item.text + toAdd }
              : item
          )
        });
        this.scrollToBottom();
      };

      sendMessageStream(
        conversationId,
        [
          { type: "audio", file_id: upload.file.id, duration_seconds: Math.round(duration / 1000) },
          { type: "text", text: `语音转写: ${transcript}`, source: "asr" }
        ],
        (delta) => {
          if (delta.type === "text" && delta.text) {
            pendingText += delta.text;
            if (!flushTimer) {
              flushTimer = setTimeout(() => { flushTimer = null; flushText(); }, 50);
            }
          }
        },
        (data) => {
          if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
          const responseNow = new Date().toISOString();
          let nextItems = this.data.chatItems.filter((item) => item.id !== streamingId);
          if (data.assistant_text) {
            nextItems.push(createMessageItem({
              id: data.assistant_message_id || `local_assistant_${Date.now()}`,
              role: "assistant",
              text: data.assistant_text,
              createdAt: responseNow
            }));
          }
          const existingPendingMap = new Map<string, ChatItem>(
            this.data.chatItems
              .filter(i => i.kind === "pending_action")
              .map(i => [i.id, i as ChatItem])
          );
          for (const pa of data.pending_actions || []) {
            if (pa.status === "pending_confirmation") {
              if (existingPendingMap.has(pa.pending_action_id)) {
                const oldIdx = nextItems.findIndex(
                  i => i.id === pa.pending_action_id && i.kind === "pending_action"
                );
                if (oldIdx !== -1) {
                  const old = nextItems[oldIdx];
                  nextItems[oldIdx] = {
                    kind: "pending_action_superseded",
                    id: "superseded-" + pa.pending_action_id,
                    pendingActionId: pa.pending_action_id,
                    createdAt: old.createdAt,
                  };
                }
                nextItems.push({
                  kind: "pending_action",
                  id: pa.pending_action_id,
                  action: pa,
                  createdAt: responseNow,
                });
              } else {
                nextItems.push({
                  kind: "pending_action",
                  id: pa.pending_action_id,
                  action: pa,
                  createdAt: pa.created_at || responseNow,
                });
              }
            }
          }
          this.setData({ chatItems: nextItems, sending: false, streamingActive: false, summaryPending: data.summary_pending === true });
          if (data.committed_records?.length) {
            wx.showToast({ title: "已保存", icon: "success" });
          }
          this.scrollToBottom();
          if (!(data.pending_actions?.length)) {
            this._syncPendingActions(conversationId);
          }
        },
        (error) => {
          if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
          this._removeChatItem(streamingId);
          this.setData({ sending: false, streamingActive: false });
          showApiError(error);
        },
        () => {
          if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
          this._removeChatItem(streamingId);
          this.setData({ sending: false, streamingActive: false });
          this.refreshConversation(conversationId);
        }
      );
      return; // streaming callbacks handle the rest
    } catch (error) {
      if (!transcriptShown) {
        this._removeChatItem(localUserItem.id);
      }
      showApiError(error);
      this.setData({ sending: false, streamingActive: false });
    }
  },

  _updateChatItemText(itemId: string, text: string) {
    this.setData({
      chatItems: this.data.chatItems.map((item) =>
        item.id === itemId && item.kind === "message" ? { ...item, text } : item
      )
    });
    this.scrollToBottom();
  },

  _removeChatItem(itemId: string) {
    this.setData({
      chatItems: this.data.chatItems.filter((item) => item.id !== itemId)
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
        resolve(false)
      }
    });
  },

  // ========== PendingAction ==========

  _pendingActionChanged(fresh: PendingAction, existing: PendingAction): boolean {
    if (fresh.updated_at !== existing.updated_at) return true;
    if (fresh.status !== existing.status) return true;
    if (JSON.stringify(fresh.draft_payload) !== JSON.stringify(existing.draft_payload)) return true;
    return false;
  },

  _syncPendingActions(conversationId: string) {
    listPendingActions(conversationId)
      .then(pendingData => {
        const active = (pendingData.pending_actions || []).filter(
          pa => pa.status === "pending_confirmation"
        );
        const freshById = new Map(active.map(pa => [pa.pending_action_id, pa]));
        const now = new Date().toISOString();
        const existingCardIds = new Set<string>();

        // Pass 1: transform existing chatItems
        const result: ChatItem[] = [];
        for (const item of this.data.chatItems) {
          if (item.kind === "pending_action") {
            existingCardIds.add(item.id);
            const fresh = freshById.get(item.id);
            if (!fresh) {
              continue; // committed or discarded — remove
            }
            if (this._pendingActionChanged(fresh, item.action)) {
              // Updated — replace with superseded placeholder at original position
              result.push({
                kind: "pending_action_superseded",
                id: "superseded-" + item.id,
                pendingActionId: item.id,
                createdAt: item.createdAt,
              });
            } else {
              result.push(item); // unchanged
            }
          } else {
            result.push(item); // message or existing superseded
          }
        }

        // Pass 2: add new or updated cards at the bottom
        for (const pa of active) {
          if (!existingCardIds.has(pa.pending_action_id)) {
            // Brand new card
            result.push({
              kind: "pending_action",
              id: pa.pending_action_id,
              action: pa,
              createdAt: pa.created_at || now,
            });
          } else {
            const existing = this.data.chatItems.find(
              i => i.kind === "pending_action" && i.id === pa.pending_action_id
            ) as { kind: "pending_action"; action: PendingAction } | undefined;
            if (existing && this._pendingActionChanged(pa, existing.action)) {
              // Updated card — float to bottom
              result.push({
                kind: "pending_action",
                id: pa.pending_action_id,
                action: pa,
                createdAt: now,
              });
            }
          }
        }

        result.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
        this.setData({ chatItems: result });
      })
      .catch(() => {});
  },

  _updateLayoutForKeyboard(kh: number) {
    if (kh > 0) {
      const info = wx.getWindowInfo();
      const r = info.windowWidth / 750;
      const inputBarPx = Math.ceil(134 * r);
      const gapPx = Math.ceil(16 * r);
      this.setData({
        scrollStyle: `bottom: ${inputBarPx + kh}px`,
        inputBarStyle: `bottom: ${kh}px`,
        voiceCardStyle: `bottom: ${inputBarPx + kh + gapPx}px`,
      });
    } else {
      this.setData({ scrollStyle: "", inputBarStyle: "", voiceCardStyle: "" });
    }
  },

  _applyContinuation(chatItems: ChatItem[], continuation: AgentContinuation): ChatItem[] {
    const now = new Date().toISOString();
    const result: ChatItem[] = [
      ...chatItems,
      createMessageItem({
        id: continuation.assistant_message_id,
        role: "assistant",
        text: continuation.assistant_text,
        createdAt: now
      })
    ];
    for (const pa of continuation.pending_actions || []) {
      if (pa.status === "pending_confirmation") {
        result.push({ kind: "pending_action", id: pa.pending_action_id, action: pa, createdAt: pa.created_at || now });
      }
    }
    return result;
  },

  async onConfirmAction(event: any) {
    if (this.data.sending) return;
    const pendingActionId = event.detail.pendingActionId;
    this.setData({ sending: true });
    try {
      const res = await confirmPendingAction(pendingActionId);
      wx.showToast({ title: "已保存", icon: "success" });
      let chatItems = this.data.chatItems.filter(item =>
        item.id !== pendingActionId &&
        !(item.kind === "pending_action_superseded" && item.pendingActionId === pendingActionId)
      );
      if (res.continuation) {
        chatItems = this._applyContinuation(chatItems, res.continuation);
      }
      this.setData({ chatItems });
      this.scrollToBottom();
    } catch (error) {
      showApiError(error);
      await this.refreshConversation();
    } finally {
      this.setData({ sending: false });
    }
  },

  async onDiscardAction(event: any) {
    if (this.data.sending) return;
    const pendingActionId = event.detail.pendingActionId;
    this.setData({ sending: true });
    try {
      const res = await discardPendingAction(pendingActionId);
      wx.showToast({ title: "已放弃", icon: "none" });
      let chatItems = this.data.chatItems.filter(item =>
        item.id !== pendingActionId &&
        !(item.kind === "pending_action_superseded" && item.pendingActionId === pendingActionId)
      );
      if (res.continuation) {
        chatItems = this._applyContinuation(chatItems, res.continuation);
      }
      this.setData({ chatItems });
      this.scrollToBottom();
    } catch (error) {
      showApiError(error);
      await this.refreshConversation();
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
