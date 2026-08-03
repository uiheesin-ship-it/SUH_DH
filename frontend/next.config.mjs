/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy /api/eai/* to the FastAPI backend so the browser hits one origin.
  async rewrites() {
    const base = process.env.NEXT_PUBLIC_EAI_API_BASE || "http://localhost:8000";
    return [{ source: "/api/eai/:path*", destination: `${base}/api/eai/:path*` }];
  },
};
export default nextConfig;
