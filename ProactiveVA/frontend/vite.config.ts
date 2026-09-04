import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://localhost:8002";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: backend.replace("http", "ws"), ws: true },
      "/data": backend,
      "/audit": backend,
      "/state": backend,
    },
  },
});
