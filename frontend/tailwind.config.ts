import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          base: "var(--surface-base)",
          elevated: "var(--surface-elevated)",
          muted: "var(--surface-muted)",
          inset: "var(--surface-inset)"
        },
        fg: {
          DEFAULT: "var(--text-primary)",
          muted: "var(--text-secondary)",
          subtle: "var(--text-tertiary)"
        },
        border: {
          DEFAULT: "var(--border-default)",
          subtle: "var(--border-subtle)"
        },
        primary: {
          DEFAULT: "var(--primary)",
          fg: "var(--primary-fg)"
        },
        ring: "var(--ring)",
        scrim: "var(--overlay-scrim)",
        interactive: {
          hover: "var(--interactive-hover)",
          "hover-strong": "var(--interactive-hover-strong)"
        }
      }
    }
  },
  plugins: []
};

export default config;
