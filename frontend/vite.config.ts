import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev запросы к /api проксируются на FastAPI (127.0.0.1:8000),
// поэтому CORS в разработке не мешает, а прод-сборка ходит на тот же origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
