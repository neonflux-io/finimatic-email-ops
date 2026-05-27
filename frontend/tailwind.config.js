/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#10131a",
        muted: "#5c6676",
        line: "#d8dde6",
        field: "#f6f8fb",
        accent: "#0f766e"
      },
      boxShadow: {
        soft: "0 8px 24px rgba(16, 19, 26, 0.08)"
      }
    }
  },
  plugins: []
};
