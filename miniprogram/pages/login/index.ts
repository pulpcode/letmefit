import { authApi, profileApi } from "../../services/api";
import { getStoredAuth } from "../../utils/auth";
import type { AuthState } from "../../types/api";

let countdownTimer: number | null = null;

Page({
  data: {
    phone: "",
    code: "",
    cooldown: 0,
    sending: false,
    loading: false
  },

  async onLoad() {
    const auth = getStoredAuth();
    if (auth?.accessToken) {
      getApp<IAppOption>().setAuth(auth);
      await routeByProfile();
    }
  },

  onUnload() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  },

  onPhoneInput(event) {
    this.setData({ phone: event.detail.value });
  },

  onCodeInput(event) {
    this.setData({ code: event.detail.value });
  },

  async onSendCode() {
    const phoneNumber = normalizePhone(this.data.phone);
    if (!phoneNumber) {
      wx.showToast({ title: "请输入有效手机号", icon: "none" });
      return;
    }

    this.setData({ sending: true });
    try {
      const result = await authApi.sendSms(phoneNumber);
      this.startCountdown(result.cooldown_seconds || 60);
      wx.showToast({ title: "验证码已发送", icon: "success" });
    } catch (error) {
      wx.showToast({ title: getErrorMessage(error), icon: "none" });
    } finally {
      this.setData({ sending: false });
    }
  },

  startCountdown(seconds: number) {
    if (countdownTimer) {
      clearInterval(countdownTimer);
    }
    this.setData({ cooldown: seconds });
    countdownTimer = setInterval(() => {
      const next = Math.max(0, Number(this.data.cooldown) - 1);
      this.setData({ cooldown: next });
      if (next === 0 && countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }, 1000) as unknown as number;
  },

  async onLogin() {
    const phoneNumber = normalizePhone(this.data.phone);
    const code = String(this.data.code || "").trim();
    if (!phoneNumber || code.length < 4) {
      wx.showToast({ title: "请输入手机号和验证码", icon: "none" });
      return;
    }

    this.setData({ loading: true });
    try {
      const auth: AuthState = await authApi.verifySms(phoneNumber, code);
      getApp<IAppOption>().setAuth(auth);
      await routeByProfile();
    } catch (error) {
      wx.showToast({ title: getErrorMessage(error), icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  }
});

async function routeByProfile(): Promise<void> {
  try {
    const profile = await profileApi.getProfile();
    getApp<IAppOption>().setProfile(profile.profile);
    if (profile.profile_completed) {
      wx.switchTab({ url: "/pages/home/index" });
    } else {
      wx.redirectTo({ url: "/pages/onboarding/index" });
    }
  } catch (_error) {
    if (getApp<IAppOption>().globalData.auth?.accessToken) {
      wx.switchTab({ url: "/pages/home/index" });
    } else {
      wx.reLaunch({ url: "/pages/login/index" });
    }
  }
}

function normalizePhone(raw: string): string | null {
  const value = String(raw || "").replace(/\s|-/g, "");
  if (/^\+86\d{11}$/.test(value)) {
    return value;
  }
  if (/^1\d{10}$/.test(value)) {
    return `+86${value}`;
  }
  return null;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败";
}
