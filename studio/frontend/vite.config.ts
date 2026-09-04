import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const backend = "http://localhost:8002";

// Dev-server only: Vite's default SPA fallback always serves index.html for
// unmatched navigations. The admin app lives under /admin/* with its own
// entry (admin.html) and its own client-side router, so rewrite those
// requests to admin.html before Vite's own fallback kicks in. Production
// serving does the equivalent rewrite in the FastAPI backend.
function adminFallback(): Plugin {
  return {
    name: "studio-admin-fallback",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (
          req.url &&
          (req.url === "/admin" || req.url.startsWith("/admin/")) &&
          !req.url.startsWith("/admin/assets")
        ) {
          req.url = "/admin.html";
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), adminFallback()],
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        admin: fileURLToPath(new URL("./admin.html", import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      "/api": backend,
      "/ingest": backend,
      "/static": backend,
      "/metrics": backend,
      "/health": backend,
    },
  },
});
