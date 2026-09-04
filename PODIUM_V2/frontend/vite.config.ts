import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const backend = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        topology: fileURLToPath(new URL("./topology.html", import.meta.url)),
        replay: fileURLToPath(new URL("./replay.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      "/ws": { target: backend.replace("http", "ws"), ws: true },
      "/state": backend,
      "/audit": backend,
      "/agents": backend,
      "/users": backend,
      "/recordings": backend,
    },
  },
});
