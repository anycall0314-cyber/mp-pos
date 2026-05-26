import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  // build 時 asset 路徑前綴改成 /static/,跟 Django STATIC_URL 對齊
  // (Django collectstatic 後,WhiteNoise 從 /static/* serve dist 內的 JS/CSS)。
  // dev 時維持 / 給 Vite dev server。
  base: command === "build" ? "/static/" : "/",
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
