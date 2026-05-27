/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// 由 vite.config.ts 在 build / dev 時注入(git short hash + 建構時間)
declare const __APP_VERSION__: string;
