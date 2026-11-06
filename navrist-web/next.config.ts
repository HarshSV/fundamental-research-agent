import type { NextConfig } from "next";

const BACKEND_URL = process.env.NAVRIST_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The production build goes to its own folder (NEXT_DIST_DIR=.next-prod) so building never disturbs a running dev server.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  // The dev server is published at ai.navrist.com via a Cloudflare Tunnel; without this
  // Next.js blocks the dev client (hydration/HMR) for any non-localhost origin.
  allowedDevOrigins: ["ai.navrist.com"],
  // Hide the round "N" dev badge (a development-only indicator; a production build never shows it).
  devIndicators: false,
  // Same-origin proxy to the Navrist FastAPI backend.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
