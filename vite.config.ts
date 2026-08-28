import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "web",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 43122,
    proxy: {
      "/api": "http://127.0.0.1:43121",
      "/health": "http://127.0.0.1:43121",
      "/session": "http://127.0.0.1:43121"
    }
  },
  build: {
    outDir: "../dist/web",
    emptyOutDir: true
  }
});
