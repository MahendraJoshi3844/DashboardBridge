/**
 * DashboardBridge AI — web shell.
 *
 * Offline by default: no analytics, no remote fonts, no image CDN. The only
 * network the browser touches is the API gateway named by NEXT_PUBLIC_API_URL,
 * which in Local/air-gapped mode is a loopback address (ADR-006, §51).
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Deterministic output: same source in, same bundle out.
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  typescript: {
    // A type error is a build failure. It is never routed around.
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
