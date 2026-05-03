import { getTokens, getUser } from "./utils/storage";
import type { AuthUser, TokenPair } from "./types/api";

export type LetMeFitGlobalData = {
  tokens: TokenPair | null;
  user: AuthUser | null;
};

App<LetMeFitGlobalData>({
  globalData: {
    tokens: null,
    user: null
  },

  onLaunch() {
    this.globalData.tokens = getTokens();
    this.globalData.user = getUser();
  }
});
