import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    host: true,            // bind 0.0.0.0 so Codespaces/remote can forward it
    allowedHosts: true,    // accept the *.app.github.dev forwarded hostname
    proxy: {
      // Proxy API calls to the FastAPI backend during dev so the browser
      // talks to one origin (and SSE works without CORS friction).
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
