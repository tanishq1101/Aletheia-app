import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        base: "var(--bg-base)",
        surface: "var(--bg-surface)",
        "surface-raised": "var(--bg-surface-raised)",

        hairline: "var(--border-hairline)",
        "hairline-subtle": "var(--border-hairline-subtle)",

        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        muted: "var(--text-muted)",

        // Labels drawn on top of a filled accent. Deliberately not `base`:
        // `text-base` is Tailwind's font-size utility and silently wins over a
        // colour of the same name, which is how filled chips ended up with
        // inherited body text at 16px instead of a contrasting colour.
        "on-accent": "var(--text-on-accent)",
        "on-brass": "var(--text-on-brass)",

        brass: "var(--accent-brass)",
        "brass-bright": "var(--accent-brass-bright)",
        oxblood: "var(--accent-oxblood)",
        "oxblood-bright": "var(--accent-oxblood-bright)",
        forest: "var(--accent-forest)",
        "forest-bright": "var(--accent-forest-bright)",

        success: "var(--status-success)",
        warning: "var(--status-warning)",
        error: "var(--status-error)",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        reading: ["var(--font-reading)"],
        ui: ["var(--font-ui)"],
        mono: ["var(--font-mono)"],
      },
    },
  },
};

export default config;
