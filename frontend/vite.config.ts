import { execSync } from "node:child_process";
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// build 時把當下 git 短 hash + 時間注入 __APP_VERSION__,
// 讓頁面右下角能顯示「現在跑的是哪個版本」,Mac mini 部署完一眼可確認
function gitShortRev(): string {
  try {
    return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    return "dev";
  }
}
const APP_VERSION = `${gitShortRev()} · ${new Date().toLocaleString("sv-SE")}`;

export default defineConfig(({ command }) => ({
  // build 時 asset 路徑前綴改成 /static/,跟 Django STATIC_URL 對齊
  // (Django collectstatic 後,WhiteNoise 從 /static/* serve dist 內的 JS/CSS)。
  // dev 時維持 / 給 Vite dev server。
  base: command === "build" ? "/static/" : "/",
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
}));
