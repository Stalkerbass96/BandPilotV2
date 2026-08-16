import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Copy alphaTab's Bravura music fonts into /font/ so the alphaTab
    // engine can fetch them at runtime via settings.core.fontDirectory.
    viteStaticCopy({
      targets: [
        {
          src: resolve(
            __dirname,
            "node_modules/@coderline/alphatab/dist/font/*",
          ),
          dest: "font",
        },
      ],
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
