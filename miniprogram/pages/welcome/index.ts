Page({
  onStart() {
    wx.navigateTo({ url: "/pages/login/index" });
  },

  onDemo() {
    wx.switchTab({ url: "/pages/home/index" });
  }
});
