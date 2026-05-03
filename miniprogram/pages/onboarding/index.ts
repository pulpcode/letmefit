import { profileApi } from "../../services/api";
import type { UserProfile } from "../../types/api";

const goalOptions = [
  { value: "fat_loss", label: "减脂" },
  { value: "muscle_gain", label: "增肌" },
  { value: "maintenance", label: "维持健康" },
  { value: "fitness", label: "建立记录习惯" }
];

const sexOptions = [
  { value: "male", label: "男" },
  { value: "female", label: "女" },
  { value: "other", label: "其他" },
  { value: "unspecified", label: "不透露" }
];

const activityOptions = [
  { value: "sedentary", label: "久坐", desc: "日常活动较少" },
  { value: "light", label: "轻度活动", desc: "每周少量运动" },
  { value: "moderate", label: "中等活动", desc: "规律运动" },
  { value: "active", label: "经常运动", desc: "多数天有训练" },
  { value: "very_active", label: "高强度运动", desc: "训练量较高" }
];

Page({
  data: {
    step: 0,
    saving: false,
    goalOptions,
    sexOptions,
    activityOptions,
    profile: {
      goal_type: "fat_loss",
      sex: "unspecified",
      activity_level: "moderate"
    } as UserProfile
  },

  onGoalTap(event) {
    this.setData({ "profile.goal_type": event.currentTarget.dataset.value });
  },

  onSexTap(event) {
    this.setData({ "profile.sex": event.currentTarget.dataset.value });
  },

  onActivityTap(event) {
    this.setData({ "profile.activity_level": event.currentTarget.dataset.value });
  },

  onNumberInput(event) {
    const field = event.currentTarget.dataset.field;
    const value = event.detail.value;
    this.setData({
      [`profile.${field}`]: value === "" ? null : Number(value)
    });
  },

  onNext() {
    if (this.data.step === 1 && !validateBodyInfo(this.data.profile)) {
      return;
    }
    this.setData({ step: Math.min(2, Number(this.data.step) + 1) });
  },

  onPrev() {
    this.setData({ step: Math.max(0, Number(this.data.step) - 1) });
  },

  async onComplete() {
    if (!validateBodyInfo(this.data.profile)) {
      this.setData({ step: 1 });
      return;
    }

    this.setData({ saving: true });
    try {
      const result = await profileApi.saveProfile(cleanProfile(this.data.profile));
      getApp<IAppOption>().setProfile(result.profile);
      const app = getApp<IAppOption>();
      if (app.globalData.auth) {
        app.globalData.auth.user.profile_completed = result.profile_completed;
        app.setAuth(app.globalData.auth);
      }
      wx.switchTab({ url: "/pages/home/index" });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "保存失败", icon: "none" });
    } finally {
      this.setData({ saving: false });
    }
  },

  onSkip() {
    wx.switchTab({ url: "/pages/home/index" });
  }
});

function cleanProfile(profile: UserProfile): UserProfile {
  return {
    age: profile.age ? Number(profile.age) : undefined,
    sex: profile.sex,
    height_cm: profile.height_cm ? Number(profile.height_cm) : undefined,
    current_weight_kg: profile.current_weight_kg ? Number(profile.current_weight_kg) : undefined,
    target_weight_kg: profile.target_weight_kg ? Number(profile.target_weight_kg) : null,
    activity_level: profile.activity_level,
    goal_type: profile.goal_type
  };
}

function validateBodyInfo(profile: UserProfile): boolean {
  if (!profile.age || !profile.height_cm || !profile.current_weight_kg) {
    wx.showToast({ title: "请填写年龄、身高和当前体重", icon: "none" });
    return false;
  }
  if (Number(profile.age) < 18) {
    wx.showToast({ title: "V1 暂不支持未成年人", icon: "none" });
    return false;
  }
  return true;
}
