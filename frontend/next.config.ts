import type { NextConfig } from "next";

// Server-side proxy target (Docker: http://backend:8000; local dev: http://127.0.0.1:8000).
// Keeps browser on same origin as the UI so login/data fetches avoid CORS and NetworkError.
const backendInternal =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendInternal}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
