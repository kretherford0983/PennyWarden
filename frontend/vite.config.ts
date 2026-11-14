import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Production build is emitted into the Python package so FastAPI serves UI + API on one port.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/fmpoc/static", emptyOutDir: true, sourcemap: false },
  // 2.4.0 (#473): the dev server may read ../docs (the user guide is bundled with "?raw" imports)
  server: { proxy: { "/api": "http://127.0.0.1:8765" }, fs: { allow: [".."] } },
});
