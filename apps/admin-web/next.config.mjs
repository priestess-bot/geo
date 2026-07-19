import path from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    serverActions: {
      bodySizeLimit: "6mb"
    }
  },
  output: "standalone",
  outputFileTracingRoot: path.join(appRoot, "../..")
};

export default nextConfig;
