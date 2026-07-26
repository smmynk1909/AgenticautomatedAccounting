import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// doc 12 §2: web/ targets the gateway (doc 11 §5) at :8000 in dev compose.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
