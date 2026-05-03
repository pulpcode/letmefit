/// <reference path="./wx.d.ts" />

interface IAppOption {
  globalData: {
    auth: import("./api").AuthState | null;
    profile: import("./api").UserProfile | null;
  };
  setAuth(auth: import("./api").AuthState | null): void;
  setProfile(profile: import("./api").UserProfile | null): void;
}

