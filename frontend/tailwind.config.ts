import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17202A",
        surface: "#F7F8FA",
        brand: "#5C4DFF",
        ok: "#1E8E5A",
        warn: "#B7791F",
        danger: "#C2413B"
      }
    }
  },
  plugins: []
};

export default config;

