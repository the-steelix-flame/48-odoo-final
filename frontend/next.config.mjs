import os from "node:os";

/**
 * Next blocks cross-origin dev requests (HMR, /_next/*) by default. When you
 * open the app from another device on the LAN — a phone, or a second laptop
 * during the demo — the client bundle never hydrates and every page hangs on
 * its loading state.
 *
 * Rather than hardcode one address that changes with DHCP, collect this
 * machine's own IPv4 addresses at startup and trust those.
 */
function localAddresses() {
  const found = new Set();
  for (const iface of Object.values(os.networkInterfaces())) {
    for (const net of iface ?? []) {
      if (net.family === "IPv4" && !net.internal) found.add(net.address);
    }
  }
  return [...found];
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: [...localAddresses(), "localhost", "127.0.0.1"],
  // The dev badge defaults to the bottom-left, which is exactly where the
  // sidebar's Log out sits — it covered the control during the demo.
  devIndicators: { position: "bottom-right" },
};

export default nextConfig;
