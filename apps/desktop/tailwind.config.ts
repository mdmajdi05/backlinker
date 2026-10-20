import type { Config } from "tailwindcss";

// The design system lives in packages/ui and is shared with the web client.
// The preset is plain CommonJS, so it is pulled in with `require` (Tailwind
// loads this file through jiti, which provides a CommonJS `require`).
const sharedPreset = require("@autobacklinker/ui/tailwind-preset");

export default {
  presets: [sharedPreset],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    "../../packages/ui/src/**/*.{ts,tsx}",
  ],
} satisfies Config;
