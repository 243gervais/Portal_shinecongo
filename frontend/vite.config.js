import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    modulePreload: false,
    target: "es2018",
    outDir: path.resolve(__dirname, "../frontend_dist/frontend"),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, "index.html"),
      output: {
        entryFileNames: "portal-app.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name?.endsWith(".css")) {
            return "portal-app.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
