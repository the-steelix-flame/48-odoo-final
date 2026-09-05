import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Matches the dark mockup: near-black canvas, blue chrome.
        canvas: "#0d0d0f",
        surface: "#17171b",
        edge: "#2a2a31",
        brand: "#3b9df7",
      },
    },
  },
  plugins: [],
};

export default config;
