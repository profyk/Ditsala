import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @ditsala/ui-tokens ships raw TypeScript (no build step) — Next needs
  // to transpile it itself rather than treating it as pre-built JS.
  transpilePackages: ["@ditsala/ui-tokens"],
};

export default nextConfig;
