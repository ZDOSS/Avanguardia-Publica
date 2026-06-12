import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // Optional: Add a trailing slash to all paths
  // trailingSlash: true,
  // Optional: Disable image optimization since it's a static export
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
