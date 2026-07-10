/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        // Surfaces neutres et sobres (produit pro).
        canvas: "#0a0b0f",
        surface: "#111219",
        raised: "#161822",
        overlay: "#1b1e2a",
        line: "#242736",
        line2: "#2f3345",
        brand: {
          DEFAULT: "#6366f1",
          soft: "#818cf8",
          faint: "rgba(99,102,241,0.12)",
        },
      },
      boxShadow: {
        panel: "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px rgba(0,0,0,0.25)",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.15s ease-out",
      },
    },
  },
  plugins: [],
};
