import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Geliştirme: `npm run dev` (5173) API isteklerini FastAPI'ye (8000) yönlendirir.
// Üretim: `npm run build` → dist/, FastAPI tarafından sunulur (python run_app.py).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});
