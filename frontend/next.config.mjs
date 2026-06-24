/** @type {import('next').NextConfig} */
const backendInternalUrl =
  process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendInternalUrl}/api/:path*` },
      { source: "/health", destination: `${backendInternalUrl}/health` },
      { source: "/docs", destination: `${backendInternalUrl}/docs` },
      { source: "/docs/:path*", destination: `${backendInternalUrl}/docs/:path*` },
      { source: "/openapi.json", destination: `${backendInternalUrl}/openapi.json` },
      { source: "/redoc", destination: `${backendInternalUrl}/redoc` },
      { source: "/redoc/:path*", destination: `${backendInternalUrl}/redoc/:path*` },
    ];
  },
};

export default nextConfig;
