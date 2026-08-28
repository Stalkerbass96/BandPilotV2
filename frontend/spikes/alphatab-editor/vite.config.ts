import { defineConfig } from "vite";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const probeRoot = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(probeRoot, "../..");

export default defineConfig({
  root: probeRoot,
  publicDir: resolve(frontendRoot, "node_modules/@coderline/alphatab/dist"),
  optimizeDeps: {
    exclude: ["@coderline/alphatab"],
  },
  server: {
    host: "127.0.0.1",
    port: 4174,
  },
});
