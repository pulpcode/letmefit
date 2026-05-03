declare const wx: any;

declare function App<T = Record<string, unknown>>(options: any & ThisType<any>): void;

declare function Page(options: any & ThisType<any>): void;

declare function Component(options: any & ThisType<any>): void;

declare namespace WechatMiniprogram {
  interface IAnyObject {
    [key: string]: any;
  }
}
