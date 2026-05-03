declare const wx: WechatMiniprogram.Wx;
declare function App<T extends WechatMiniprogram.App.Option>(options: T): void;
declare function Page<T extends WechatMiniprogram.Page.Options>(options: T): void;
declare function Component<T extends WechatMiniprogram.Component.Options>(options: T): void;
declare function getApp<T = IAppOption>(): T;

declare namespace WechatMiniprogram {
  interface GeneralCallbackResult {
    errMsg: string;
  }

  namespace App {
    interface Option {
      globalData?: Record<string, unknown>;
      [key: string]: unknown;
    }
  }

  namespace Page {
    interface Options {
      data?: Record<string, unknown>;
      onLoad?(query?: Record<string, string>): void;
      onShow?(): void;
      setData(data: Record<string, unknown>, callback?: () => void): void;
      [key: string]: unknown;
    }
  }

  namespace Component {
    interface Options {
      properties?: Record<string, unknown>;
      data?: Record<string, unknown>;
      observers?: Record<string, (...args: unknown[]) => void>;
      methods?: Record<string, (...args: unknown[]) => void>;
      [key: string]: unknown;
    }
  }

  interface RequestSuccessCallbackResult<T = unknown> {
    data: T;
    statusCode: number;
    header: Record<string, string>;
    errMsg: string;
  }

  interface RequestOption<T = unknown> {
    url: string;
    method?: string;
    data?: unknown;
    header?: Record<string, string>;
    success?(res: RequestSuccessCallbackResult<T>): void;
    fail?(err: GeneralCallbackResult): void;
    complete?(): void;
  }

  interface StorageGetOption<T = unknown> {
    key: string;
    success?(res: { data: T }): void;
    fail?(err: GeneralCallbackResult): void;
  }

  interface StorageSetOption {
    key: string;
    data: unknown;
  }

  interface NavigateOption {
    url: string;
  }

  interface SwitchTabOption {
    url: string;
  }

  interface ToastOption {
    title: string;
    icon?: "success" | "error" | "loading" | "none";
    duration?: number;
  }

  interface ModalOption {
    title?: string;
    content?: string;
    showCancel?: boolean;
    confirmText?: string;
    cancelText?: string;
    success?(res: { confirm: boolean; cancel: boolean }): void;
  }

  interface ChooseMediaOption {
    count?: number;
    mediaType?: string[];
    sourceType?: string[];
    maxDuration?: number;
    camera?: "back" | "front";
    success?(res: { tempFiles: Array<{ tempFilePath: string; size: number; duration?: number }> }): void;
    fail?(err: GeneralCallbackResult): void;
  }

  interface RecorderManager {
    start(options?: Record<string, unknown>): void;
    stop(): void;
    onStop(callback: (res: { tempFilePath: string; duration: number; fileSize: number }) => void): void;
    onError(callback: (res: GeneralCallbackResult) => void): void;
  }

  interface Wx {
    request<T = unknown>(option: RequestOption<T>): void;
    getStorageSync<T = unknown>(key: string): T;
    setStorageSync(key: string, data: unknown): void;
    removeStorageSync(key: string): void;
    navigateTo(option: NavigateOption): void;
    redirectTo(option: NavigateOption): void;
    reLaunch(option: NavigateOption): void;
    switchTab(option: SwitchTabOption): void;
    showToast(option: ToastOption): void;
    showModal(option: ModalOption): void;
    chooseMedia(option: ChooseMediaOption): void;
    getRecorderManager(): RecorderManager;
    stopPullDownRefresh(): void;
  }
}
