import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://localhost:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: backend.replace("http", "ws"), ws: true },
      "/audit": backend,
      "/log": backend,
    },
  },
});
