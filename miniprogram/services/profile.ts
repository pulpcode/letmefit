import { request } from "../utils/request";
import type { Profile, ProfileResponse } from "../types/api";

export function getProfile() {
  return request<ProfileResponse>({
    path: "/profile"
  });
}

export function updateProfile(profile: Profile) {
  return request<ProfileResponse>({
    path: "/profile",
    method: "PUT",
    data: profile
  });
}
