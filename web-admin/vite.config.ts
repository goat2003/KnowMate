import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.VITE_DEV_HOST ?? "0.0.0.0",
    port: Number(process.env.VITE_DEV_PORT ?? 5173),
    proxy: {
      "/api/wechat/callback": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8080",
        changeOrigin: true
      },
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8080",
        changeOrigin: true,
        rewrite: (path) => path === "/api/wechat/callback" ? path : path.replace(/^\/api/, "")
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    exclude: ["e2e/**", "dist/**", "node_modules/**"]
  }
});
