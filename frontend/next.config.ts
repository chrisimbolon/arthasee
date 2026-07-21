import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Static export — the whole reason this change exists. Produces
  // pure HTML/CSS/JS with zero running Node process, served directly
  // by Caddy exactly like kla's Vite frontend already is. Only
  // possible because every page in this app is "use client" with no
  // server-side rendering or API routes — worth remembering if a
  // future feature ever needs real server-side work, since that
  // would break this.
  output: "export",
  // Next's built-in Image Optimization API needs a running server,
  // which static export doesn't have. Not currently used anywhere in
  // this app, but set defensively so a future next/image usage fails
  // loudly at build time instead of silently at runtime.
  images: { unoptimized: true },
};

export default nextConfig;
