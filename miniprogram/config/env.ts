// export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/v1";
export const DEFAULT_API_BASE_URL = "http://49.232.156.14/v1";
// export const DEFAULT_API_BASE_URL = "https://www.letmefit.cloud/v1";



export function getApiBaseUrl(): string {
  const override = wx.getStorageSync("LETMEFIT_API_BASE_URL");
  return typeof override === "string" && override ? override : DEFAULT_API_BASE_URL;
}
