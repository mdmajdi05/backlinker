import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Tauri expects a fixed dev port and does not want the dev server to clear
// the terminal (the Rust process owns the stdout).
export default defineConfig({
  plugins: [react()],
  // Do not wipe the terminal - the Rust process owns the stdout.
  clearScreen: false,
  resolve: {
    // The shared packages are symlinked into node_modules. Dedupe makes Vite
    // resolve their peer dependencies (react, clsx, tailwind-merge) from this
    // project instead of walking up from packages/*/src.
    dedupe: ["react", "react-dom", "clsx", "tailwind-merge"],
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  optimizeDeps: {
    // Linked workspace packages ship TypeScript sources - never pre-bundle them.
    exclude: [
      "@autobacklinker/ui",
      "@autobacklinker/api-client",
      "@autobacklinker/shared-types",
    ],
  },
  // Vite 5 style env prefix (TAURI_*) keeps the frontend config out of the
  // regular VITE_ namespace.
  envPrefix: ["TAURI_", "VITE_"],
  server: {
    port: 1420,
    strictPort: true,
    host: "127.0.0.1",
    watch: {
      // The Rust crate is rebuilt by `tauri dev`, not by Vite.
      ignored: ["**/src-tauri/**", "**/binaries/**"],
    },
    fs: {
      // Allow serving the linked shared packages from ../../packages.
      allow: [path.resolve(__dirname, "../..")],
    },
  },
  envDir: path.resolve(__dirname, "../.."),
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2021",
    sourcemap: true,
    chunkSizeWarningLimit: 1500,
  },
});
