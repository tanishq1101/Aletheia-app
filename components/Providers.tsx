"use client";

import { ClerkProvider } from "@clerk/nextjs";
import { useEffect, useState, type ReactNode } from "react";
import { useTheme } from "@/lib/theme";

/** Clerk is optional at build time. A checkout without keys must still build
 *  and run — see the sign-in page, which says so plainly. */
const authConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

/** The Clerk palette, read from the stylesheet rather than written twice.
 *
 * Clerk parses these values to derive shades — alpha variants for borders and
 * dividers, hover states for buttons — so they have to be real colours, not
 * `var(--token)` references it cannot compute on. Reading the resolved custom
 * properties off `<html>` keeps `globals.css` the only place a hex is written,
 * and means the hosted form re-themes with everything else. */
const CLERK_TOKENS = {
  colorBackground: "--bg-surface",
  colorForeground: "--text-primary",
  colorMutedForeground: "--text-secondary",
  colorMuted: "--bg-surface-raised",
  colorInput: "--bg-base",
  colorInputForeground: "--text-primary",
  colorBorder: "--border-hairline",
  colorPrimary: "--accent-oxblood",
  colorPrimaryForeground: "--text-on-accent",
  colorRing: "--focus-ring",
  colorDanger: "--status-error",
  colorSuccess: "--status-success",
  colorWarning: "--status-warning",
  /** The bug this whole map exists for.
   *
   * `colorNeutral` defaults to black, and Clerk derives the social-button
   * label, the "or" divider and several borders from it at low alpha. On a
   * dark card that made "Continue with Google" `rgba(0,0,0,0.62)` on `#1c1712`
   * — present in the DOM, invisible on screen, which is exactly what a
   * transparency glitch looks like. It has to follow the text colour. */
  colorNeutral: "--text-primary",
} as const;

type ClerkVariables = Record<keyof typeof CLERK_TOKENS, string>;

function readClerkVariables(): ClerkVariables | null {
  if (typeof window === "undefined") return null;
  const computed = window.getComputedStyle(document.documentElement);
  const entries = Object.entries(CLERK_TOKENS).map(([variable, token]) => [
    variable,
    computed.getPropertyValue(token).trim(),
  ]);
  // Before the stylesheet resolves there is nothing to read, and handing Clerk
  // empty strings is worse than letting it use its own defaults for one frame.
  if (entries.some(([, value]) => !value)) return null;
  return Object.fromEntries(entries) as ClerkVariables;
}

function ThemedClerkProvider({ children }: { children: ReactNode }) {
  const { theme } = useTheme();
  const [variables, setVariables] = useState<ClerkVariables | null>(null);

  // Read on the next frame, not in this effect body, so the read cannot
  // outrun the `data-theme` write it depends on. An earlier version read
  // directly here, from inside a child of the component that owned the
  // attribute; React runs effects child-first, so it got the palette being
  // switched *away* from and left the sign-in card dark on a light page.
  useEffect(() => {
    const frame = requestAnimationFrame(() => setVariables(readClerkVariables()));
    return () => cancelAnimationFrame(frame);
  }, [theme]);

  return (
    <ClerkProvider
      afterSignOutUrl="/sign-in"
      appearance={{
        variables: {
          ...(variables ?? {}),
          borderRadius: "0.375rem",
          fontFamily: "var(--font-ui)",
        },
        elements: {
          // Clerk's own shadow is tuned for a white card on a grey page and
          // disappears on either of ours. A hairline is what every other panel
          // in this app uses to separate itself from the background.
          card: "border border-hairline-subtle shadow-none",
          cardBox: "border border-hairline-subtle shadow-none",
          headerTitle: "font-display",
          socialButtonsBlockButton: "border border-hairline",
          // Clerk colours links with `colorPrimary`, which here has to be a
          // button *fill* — oxblood — and is too dark to read as text on
          // either surface. Links get the accent that was designed to be read.
          footerActionLink: "text-brass hover:text-brass-bright",
          identityPreviewEditButton: "text-brass hover:text-brass-bright",
          formResendCodeLink: "text-brass hover:text-brass-bright",
        },
      }}
    >
      {children}
    </ClerkProvider>
  );
}

/** Everything client-side that has to wrap the whole document.
 *
 * `ClerkProvider` lives here rather than in the root layout because its
 * appearance is a JavaScript value that has to follow the active theme, and
 * the theme is only known in the browser. The theme itself needs no provider:
 * it is external state, read through `useTheme` wherever it is wanted. */
export default function Providers({ children }: { children: ReactNode }) {
  if (!authConfigured) return <>{children}</>;
  return <ThemedClerkProvider>{children}</ThemedClerkProvider>;
}
