import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets land inside the Python package so PyInstaller bundles them.
// A relative base is required: the shell loads index.html from file://, not a server.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/t2pbi/desktop/web",
    emptyOutDir: true,
    assetsInlineLimit: 4096,
  },
});
