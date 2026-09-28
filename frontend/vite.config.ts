import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8000; requests to /api are forwarded there, so the
// browser only ever talks to one origin. The Docker image does the same with nginx.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.SENTINEL_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
