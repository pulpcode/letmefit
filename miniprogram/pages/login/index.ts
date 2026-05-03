import { sendSmsCode, verifySmsCode } from "../../services/auth";
import { showApiError } from "../../utils/request";

function normalizePhone(phone: string): string {
  const trimmed = phone.trim();
  if (trimmed.startsWith("+")) {
    return trimmed;
  }
  return trimmed.length === 11 ? `+86${trimmed}` : trimmed;
}

Page({
  data: {
    phone: "",
    code: "",
    cooldown: 0,
    sending: false,
    loggingIn: false
  },

  timer: 0 as any,

  onUnload() {
    if (this.timer) {
      clearInterval(this.timer);
    }
  },

  onPhoneInput(event: any) {
    this.setData({ phone: event.detail.value });
  },

  onCodeInput(event: any) {
    this.setData({ code: event.detail.value });
  },

  async onSendCode() {
    if (!this.data.phone || this.data.cooldown > 0 || this.data.sending) return;
    this.setData({ sending: true });
    try {
      const data = await sendSmsCode(normalizePhone(this.data.phone));
      this.setData({ cooldown: data.cooldown_seconds || 60 });
      this.timer = setInterval(() => {
        const next = Math.max(0, this.data.cooldown - 1);
        this.setData({ cooldown: next });
        if (next === 0) clearInterval(this.timer);
      }, 1000);
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ sending: false });
    }
  },

  async onLogin() {
    if (!this.data.phone || !this.data.code || this.data.loggingIn) return;
    this.setData({ loggingIn: true });
    try {
      const data = await verifySmsCode(normalizePhone(this.data.phone), this.data.code);
      if (data.user.profile_completed) {
        wx.switchTab({ url: "/pages/home/index" });
      } else {
        wx.navigateTo({ url: "/pages/onboarding/index" });
      }
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ loggingIn: false });
    }
  }
});
