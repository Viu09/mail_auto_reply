/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0b0f1a",
          900: "#0f1626",
          800: "#17203a",
          700: "#1f2b4d",
          600: "#2b3a63",
        },
      },
    },
  },
  plugins: [],
};
