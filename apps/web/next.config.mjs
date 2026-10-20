import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  images: {
    unoptimized: true,
  },
  transpilePackages: [
    "@autobacklinker/ui",
    "@autobacklinker/shared-types",
    "@autobacklinker/api-client",
  ],
  eslint: {
    ignoreDuringBuilds: true,
  },
  webpack: (config) => {
    // The shared packages are consumed through `file:` links, which npm installs
    // as symlinks. Keeping the symlinked path means module resolution stays
    // inside apps/web/node_modules (otherwise `clsx` / `@autobacklinker/shared-types`
    // cannot be resolved from inside packages/ui and packages/api-client).
    config.resolve.symlinks = false;
    return config;
  },
};

export default nextConfig;
