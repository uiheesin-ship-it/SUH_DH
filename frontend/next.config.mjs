/** @type {import('next').NextConfig} */
// Two build modes:
//   - local dev (default): a Next server with rewrites proxying /api/eai → backend.
//   - deploy (EAI_STATIC_EXPORT=1): a fully static export (frontend/out) that the
//     FastAPI service serves itself at "/", with the API same-origin at /api/eai.
const isExport = process.env.EAI_STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  ...(isExport
    ? { output: "export", trailingSlash: true, images: { unoptimized: true } }
    : {
        async rewrites() {
          const base = process.env.NEXT_PUBLIC_EAI_API_BASE || "http://localhost:8000";
          return [{ source: "/api/eai/:path*", destination: `${base}/api/eai/:path*` }];
        },
      }),
};
export default nextConfig;
