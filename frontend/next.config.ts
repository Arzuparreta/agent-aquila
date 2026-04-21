import fs from "fs";
import path from "path";

import type { NextConfig } from "next";

const pkgPath = path.join(process.cwd(), "package.json");
const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8")) as { version: string };

// Server-side proxy target (Docker: http://backend:8000; local dev: http://127.0.0.1:8000).
// Keeps browser on same origin as the UI so login/data fetches avoid CORS and NetworkError.
const backendInternal =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_APP_VERSION: pkg.version,
    NEXT_PUBLIC_APP_BUILD_ID: process.env.NEXT_PUBLIC_APP_BUILD_ID?.trim() ?? "",
  },
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
