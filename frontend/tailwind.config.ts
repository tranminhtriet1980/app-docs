import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        navy: { 50: "#eef2ff", 900: "#0f172a", 950: "#020617" },
        // Tone đỏ đậm thống nhất toàn app (theo logo ImmiPath).
        accent: { DEFAULT: "#b91c1c", light: "#dc2626" },
        brand: {
          50: "#fef2f2",
          100: "#fee2e2",
          600: "#b91c1c",
          700: "#991b1b",
          900: "#7f1d1d",
        },
      },
    },
  },
  plugins: [],
};
export default config;
