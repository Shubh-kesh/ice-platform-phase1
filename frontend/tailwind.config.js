/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // Cyanotype blueprint palette — the whole app is toned like an
        // actual architectural blueprint print, not a neutral gray SaaS shell.
        ink: {
          DEFAULT: "#0A1628",   // base background — deep Prussian blue
          surface: "#101F35",   // card / panel surface
          raised: "#16294A",    // hovered / elevated surface
          border: "#1F3554",    // hairline borders
        },
        blueprint: {
          50: "#EAF4FD",
          200: "#B8DCF7",
          400: "#4FA8E8",  // primary accent — cyanotype linework blue
          500: "#3D8FDB",
          600: "#2C6DA3",  // dimmer secondary blue
          700: "#1F4E78",
        },
        // Health status colors — reserved exclusively for timeline / budget
        // / safety indicators. Never reused as decoration or brand color.
        status: {
          green: "#34C77B",
          amber: "#F0A83B",
          red: "#E5484D",
        },
        paper: {
          DEFAULT: "#EAF2FB",  // primary text — blueprint linework white
          muted: "#7E97B5",    // secondary text — faded blueprint gray-blue
          faint: "#4C617D",    // tertiary / disabled text
        },
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      backgroundImage: {
        // The signature element: a faint drafting grid, like blueprint paper.
        "blueprint-grid":
          "linear-gradient(rgba(79, 168, 232, 0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(79, 168, 232, 0.06) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "24px 24px",
      },
      boxShadow: {
        panel: "0 1px 0 rgba(79, 168, 232, 0.08), 0 8px 24px rgba(0,0,0,0.35)",
      },
    },
  },
  plugins: [],
};
