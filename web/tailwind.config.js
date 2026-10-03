/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F7F4EF",
        "bg-subtle": "#F1EDE6",
        surface: "#FFFEFC",
        "surface-raised": "#FFFFFF",
        border: {
          DEFAULT: "#E5E0D8",
          subtle: "#EEEAE4",
        },
        text: {
          primary: "#171716",
          secondary: "#5F5C56",
          tertiary: "#8A867E",
          disabled: "#B4B0A8",
        },
        brand: {
          DEFAULT: "#B85738",
          hover: "#A94C30",
          active: "#963F27",
          soft: "#F4DED5",
          wash: "#FBF1ED",
        },
        success: {
          DEFAULT: "#4D8A6A",
          soft: "#E7F1EB",
          dot: "#22A06B",
          text: "#286348",
        },
        warning: {
          DEFAULT: "#C88732",
          soft: "#F8EDDA",
          text: "#815A1F",
        },
        danger: {
          DEFAULT: "#C94A4A",
          soft: "#F9E3E3",
          text: "#8F3434",
        },
        info: {
          DEFAULT: "#607A96",
          soft: "#E9EEF4",
        },
        provider: {
          aws: "#FF9900",
          "aws-soft": "#FFF4E2",
          azure: "#0078D4",
          "azure-soft": "#E8F3FB",
          gcp: "#4285F4",
          "gcp-soft": "#EDF4FF",
        },
        node: {
          compute: "#C75B3C",
          networking: "#5577A8",
          database: "#3F7FA1",
          storage: "#5B8C68",
          messaging: "#9B6A9C",
          security: "#B07A3A",
          monitoring: "#607A70",
          external: "#767676",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(23, 23, 22, 0.04), 0 4px 16px rgba(23, 23, 22, 0.04)",
        elevated: "0 8px 30px rgba(23, 23, 22, 0.08)",
        "focus-ring": "0 0 0 3px rgba(184, 87, 56, 0.14)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #B85738 0%, #D27856 100%)",
        "hero-wash": "linear-gradient(135deg, rgba(184, 87, 56, 0.10), rgba(77, 138, 106, 0.04))",
      },
    },
  },
  plugins: [],
};
