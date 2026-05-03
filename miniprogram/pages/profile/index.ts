import { authApi, profileApi } from "../../services/api";
import type { UserProfile } from "../../types/api";

const sexOptions = [
  { value: "male", label: "男" },
  { value: "female", label: "女" },
  { value: "other", label: "其他" },
  { value: "unspecified", label: "不透露" }
];

const goalOptions = [
  { value: "fat_loss", label: "减脂" },
  { value: "muscle_gain", label: "增肌" },
  { value: "maintenance", label: "维持健康" },
  { value: "fitness", label: "建立记录习惯" }
];

const activityOptions = [
  { value: "sedentary", label: "久坐" },
  { value: "light", label: "轻度活动" },
  { value: "moderate", label: "中等活动" },
  { value: "active", label: "经常运动" },
  { value: "very_active", label: "高强度运动" }
];

Page({
  data: {
    loading: false,
    saving: false,
    profileCompleted: false,
    profile: {} as UserProfile,
    sexOptions,
    goalOptions,
    activityOptions,
    sexIndex: 3,
    goalIndex: 0,
    activityIndex: 2,
    agentAvatar: "female"
  },

  onShow() {
    if (!getApp<IAppOption>().globalData.auth?.accessToken) {
      wx.reLaunch({ url: "/pages/login/index" });
      return;
    }
    this.loadProfile();
  },

  async loadProfile() {
    this.setData({ loading: true });
    try {
      const result = await profileApi.getProfile();
      const profile = result.profile || {};
      this.setProfileData(profile, result.profile_completed);
      getApp<IAppOption>().setProfile(result.profile);
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "档案加载失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },

  setProfileData(profile: UserProfile, profileCompleted: boolean) {
    const sexIndex = Math.max(0, sexOptions.findIndex((item) => item.value === (profile.sex || "unspecified")));
    const goalIndex = Math.max(0, goalOptions.findIndex((item) => item.value === (profile.goal_type || "fat_loss")));
    const activityIndex = Math.max(0, activityOptions.findIndex((item) => item.value === (profile.activity_level || "moderate")));
    this.setData({
      profile: {
        sex: "unspecified",
        goal_type: "fat_loss",
        activity_level: "moderate",
        ...profile
      },
      profileCompleted,
      sexIndex,
      goalIndex,
      activityIndex,
      agentAvatar: wx.getStorageSync<string>("letmefit.agentAvatar") || "female"
    });
  },

  onNumberInput(event) {
    const field = event.currentTarget.dataset.field;
    const value = event.detail.value;
    this.setData({
      [`profile.${field}`]: value === "" ? null : Number(value)
    });
  },

  onSexChange(event) {
    const index = Number(event.detail.value);
    this.setData({
      sexIndex: index,
      "profile.sex": sexOptions[index].value
    });
  },

  onGoalChange(event) {
    const index = Number(event.detail.value);
    this.setData({
      goalIndex: index,
      "profile.goal_type": goalOptions[index].value
    });
  },

  onActivityChange(event) {
    const index = Number(event.detail.value);
    this.setData({
      activityIndex: index,
      "profile.activity_level": activityOptions[index].value
    });
  },

  onAgentTap(event) {
    const avatar = event.currentTarget.dataset.value;
    wx.setStorageSync("letmefit.agentAvatar", avatar);
    this.setData({ agentAvatar: avatar });
  },

  async onSave() {
    this.setData({ saving: true });
    try {
      const result = await profileApi.saveProfile(cleanProfile(this.data.profile));
      this.setProfileData(result.profile || {}, result.profile_completed);
      getApp<IAppOption>().setProfile(result.profile);
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (error) {
      wx.showToast({ title: error instanceof Error ? error.message : "保存失败", icon: "none" });
    } finally {
      this.setData({ saving: false });
    }
  },

  onLogout() {
    wx.showModal({
      title: "退出登录",
      content: "退出后需要重新通过短信登录。",
      confirmText: "退出",
      success: async (res) => {
        if (!res.confirm) {
          return;
        }
        const auth = getApp<IAppOption>().globalData.auth;
        try {
          if (auth?.refreshToken) {
            await authApi.logout(auth.refreshToken);
          }
        } finally {
          getApp<IAppOption>().setAuth(null);
          getApp<IAppOption>().setProfile(null);
          wx.reLaunch({ url: "/pages/login/index" });
        }
      }
    });
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

