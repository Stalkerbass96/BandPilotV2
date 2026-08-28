import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { alphaTab } from "@coderline/alphatab-vite";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    // Official worker/worklet integration plus Bravura and SONiVOX assets.
    // Hand-copying only the assets renders notation but leaves playback stuck.
    alphaTab(),
    react(),
  ],
  // MUI v5 icon entry points are CommonJS. Vite 8's dev optimizer preserves
  // their nested `default` wrapper, which React then tries to render as an
  // object. Point subpath imports at MUI's native ESM build instead.
  resolve: {
    alias: [
      {
        find: /^@mui\/icons-material\/(.*)$/,
        replacement: resolve(
          __dirname,
          "node_modules/@mui/icons-material/esm/$1.js",
        ),
      },
    ],
  },
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
