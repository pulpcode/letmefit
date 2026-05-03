import { logout } from "../../services/auth";
import { getProfile } from "../../services/profile";
import { activityLabels, goalLabels, profileRows, sexLabels } from "../../utils/format";
import { showApiError } from "../../utils/request";
import { getAgentAvatar, setAgentAvatar } from "../../utils/storage";

Page({
  data: {
    avatar: getAgentAvatar(),
    profile: null as any,
    rows: [] as any[]
  },

  onShow() {
    this.loadProfile();
  },

  async loadProfile() {
    try {
      const data = await getProfile();
      this.setData({
        profile: data.profile,
        rows: profileRows(data.profile)
      });
    } catch (error) {
      showApiError(error);
    }
  },

  selectAvatar(event: any) {
    const avatar = event.currentTarget.dataset.avatar;
    setAgentAvatar(avatar);
    this.setData({ avatar });
  },

  goEdit() {
    wx.navigateTo({ url: "/pages/onboarding/index" });
  },

  async onLogout() {
    await logout();
    wx.reLaunch({ url: "/pages/login/index" });
  },

  labels() {
    return { activityLabels, goalLabels, sexLabels };
  }
});
