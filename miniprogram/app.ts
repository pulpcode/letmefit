import { getStoredAuth, setStoredAuth, clearStoredAuth } from "./utils/auth";
import type { AuthState, UserProfile } from "./types/api";

App<IAppOption>({
  globalData: {
    auth: getStoredAuth(),
    profile: null
  },

  setAuth(auth: AuthState | null) {
    if (auth) {
      setStoredAuth(auth);
    } else {
      clearStoredAuth();
    }
    this.globalData.auth = auth;
  },

  setProfile(profile: UserProfile | null) {
    this.globalData.profile = profile;
  }
});

