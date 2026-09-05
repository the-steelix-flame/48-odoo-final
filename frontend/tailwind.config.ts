import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F8FAFC",
        surface: "#ffffff",
        edge: "#E2E8F0",
        brand: "#0891B2",
        sidebar: "#24354c",
        "sidebar-active": "rgba(34,211,238,0.22)",
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        heading: ['"Space Grotesk"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "monospace"],
      },
      keyframes: {
        dfIn: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'none' },
        },
        dfToast: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'none' },
        },
        dfPulse: {
          '0%, 100%': { opacity: '0.35' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        dfIn: 'dfIn 0.4s ease both',
        dfToast: 'dfToast 0.25s ease both',
        dfPulse: 'dfPulse 2s infinite',
      },
    },
  },
  plugins: [],
};

export default config;
