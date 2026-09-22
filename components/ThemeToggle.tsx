"use client";

import { useTheme } from "@/lib/theme";

/** Light/dark switch.
 *
 * Which glyph shows is decided by CSS from `html[data-theme]`, not by React
 * state. That matters: the theme is chosen by an inline script before the first
 * paint, so a state-driven icon would render the server's guess, then correct
 * itself — a visible flip on every page load, and a hydration mismatch. The
 * accessible name is written to be true of both states for the same reason. */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const { toggle } = useTheme();

  return (
    <button
      type="button"
      onClick={toggle}
      title="Switch between the light and dark theme"
      aria-label="Switch between the light and dark theme"
      className={`group flex size-8 shrink-0 items-center justify-center rounded-md border border-hairline bg-surface text-secondary transition-colors hover:border-brass hover:text-brass ${className}`}
    >
      {/* Shown in dark mode: the control that takes you to light. */}
      <svg
        viewBox="0 0 20 20"
        aria-hidden="true"
        className="theme-when-dark size-[15px] transition-transform duration-300 group-hover:rotate-45"
      >
        <circle cx="10" cy="10" r="3.6" fill="currentColor" />
        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
          <line
            key={angle}
            x1="10"
            y1="1.6"
            x2="10"
            y2="4"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            transform={`rotate(${angle} 10 10)`}
          />
        ))}
      </svg>

      {/* Shown in light mode: the control that takes you to dark. */}
      <svg
        viewBox="0 0 20 20"
        aria-hidden="true"
        className="theme-when-light size-[15px] transition-transform duration-300 group-hover:-rotate-12"
      >
        <path
          d="M16.2 12.4A6.9 6.9 0 0 1 7.6 3.8a6.9 6.9 0 1 0 8.6 8.6Z"
          fill="currentColor"
        />
      </svg>
    </button>
  );
}
