import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    watch: { usePolling: true }, // needed for hot reload inside Docker on Windows/Mac
    proxy: {
      "/api": "http://backend:8088",
      "/ws": { target: "ws://backend:8088", ws: true },
    },
  },
});