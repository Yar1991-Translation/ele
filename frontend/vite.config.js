import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { viteSingleFile } from "vite-plugin-singlefile";

// 构建产物直接输出到 Flask 托管的 gui/dist；dev 模式把 /api 代理到本地后端
export default defineConfig({
  plugins: [vue(), viteSingleFile()],
  build: {
    outDir: "../gui/dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.js"],
  },
});
