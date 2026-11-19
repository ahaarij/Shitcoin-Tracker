import type { NextConfig } from "next";

// Pure frontend: no API routes, no server logic. All data comes from the Railway backend.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
