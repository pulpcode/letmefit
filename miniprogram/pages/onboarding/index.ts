import { updateProfile } from "../../services/profile";
import { showApiError } from "../../utils/request";
import type { Profile } from "../../types/api";

const goalOptions = [
  { value: "fat_loss", label: "减脂", desc: "" },
  { value: "muscle_gain", label: "增肌", desc: "" },
  { value: "maintenance", label: "维持健康", desc: "" },
  { value: "fitness", label: "建立记录习惯", desc: "" }
];

const sexOptions = [
  { value: "male", label: "男" },
  { value: "female", label: "女" },
  { value: "other", label: "其他" },
  { value: "unspecified", label: "不透露" }
];

const activityOptions = [
  { value: "sedentary", label: "久坐", desc: "很少运动" },
  { value: "light", label: "轻度活动", desc: "每周1-2次" },
  { value: "moderate", label: "中等活动", desc: "每周3-4次" },
  { value: "active", label: "经常运动", desc: "每周5-6次" },
  { value: "very_active", label: "高强度运动", desc: "每天训练" }
];

Page({
  data: {
    step: 1,
    goalOptions,
    sexOptions,
    activityOptions,
    form: {
      goal_type: "",
      sex: "",
      age: "",
      height_cm: "",
      current_weight_kg: "",
      target_weight_kg: "",
      activity_level: ""
    },
    submitting: false
  },

  selectGoal(event: any) {
    this.setData({ "form.goal_type": event.currentTarget.dataset.value });
  },

  selectSex(event: any) {
    this.setData({ "form.sex": event.currentTarget.dataset.value });
  },

  selectActivity(event: any) {
    this.setData({ "form.activity_level": event.currentTarget.dataset.value });
  },

  onInput(event: any) {
    const field = event.currentTarget.dataset.field;
    this.setData({ [`form.${field}`]: event.detail.value });
  },

  canContinue(): boolean {
    const form: any = this.data.form;
    if (this.data.step === 1) return Boolean(form.goal_type);
    if (this.data.step === 2) return Boolean(form.sex && form.age && form.height_cm && form.current_weight_kg);
    return Boolean(form.activity_level);
  },

  onNext() {
    if (!this.canContinue()) return;
    if (this.data.step < 3) {
      this.setData({ step: this.data.step + 1 });
      return;
    }
    this.onComplete();
  },

  async onComplete() {
    if (!this.canContinue() || this.data.submitting) return;
    const form: any = this.data.form;
    const profile: Profile = {
      goal_type: form.goal_type,
      sex: form.sex,
      age: Number(form.age),
      height_cm: Number(form.height_cm),
      current_weight_kg: Number(form.current_weight_kg),
      target_weight_kg: form.target_weight_kg ? Number(form.target_weight_kg) : null,
      activity_level: form.activity_level
    };
    this.setData({ submitting: true });
    try {
      await updateProfile(profile);
      wx.switchTab({ url: "/pages/home/index" });
    } catch (error) {
      showApiError(error);
    } finally {
      this.setData({ submitting: false });
    }
  },

  onSkip() {
    wx.switchTab({ url: "/pages/home/index" });
  }
});
