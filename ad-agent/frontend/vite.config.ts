import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } } },
  // Spectrum CSS uses nesting; target browsers that support :is() so esbuild does not warn
  build: { chunkSizeWarningLimit: 2500, target: "es2022", cssTarget: ["chrome105", "edge105", "firefox104", "safari16"] },
});
