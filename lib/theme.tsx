"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
/** What the reader chose. `system` means "keep following the OS". */
export type ThemePreference = Theme | "system";

export const THEME_STORAGE_KEY = "aletheia-theme";

/** Runs before first paint, inlined into the document head.
 *
 * The theme has to be on `<html>` *before* the browser paints, or every
 * visitor whose preference is light gets a dark flash on every navigation.
 * That rules out doing it in React: an effect is too late, and the server does
 * not know the answer. Kept as one exported string so the script and the store
 * below read the same key and apply the same fallback.
 *
 * `data-theme-ready` is set at the same time; the stylesheet uses it to enable
 * colour transitions, so the very first paint cannot animate. */
export const THEME_BOOTSTRAP_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    var theme =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia("(prefers-color-scheme: light)").matches
          ? "light"
          : "dark";
    document.documentElement.dataset.theme = theme;
  } catch (error) {
    document.documentElement.dataset.theme = "dark";
  }
  document.documentElement.dataset.themeReady = "";
})();
`.trim();

/* --------------------------------------------------------------------------
 * The theme is external state — it lives in `localStorage`, in the OS setting
 * and on the `<html>` element — so it is read through `useSyncExternalStore`
 * rather than mirrored into React state by an effect. That is not pedantry:
 * the effect version wrote `data-theme` *after* its children's effects had
 * already read the old value, which left the hosted sign-in form on the
 * previous theme every time the toggle was pressed.
 * ----------------------------------------------------------------------- */

const listeners = new Set<() => void>();

function announce() {
  for (const listener of listeners) listener();
}

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function readPreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    // Private browsing, or storage denied. Following the OS is the right
    // fallback, and is what the bootstrap script above will have done.
    return "system";
  }
}

function resolve(): Theme {
  const preference = readPreference();
  return preference === "system" ? systemTheme() : preference;
}

/** `"light"`, `"dark"`, `"system:light"` or `"system:dark"` — one string, so
 *  `useSyncExternalStore` can compare snapshots without allocating. */
function snapshot(): string {
  const preference = readPreference();
  return preference === "system" ? `system:${systemTheme()}` : preference;
}

function subscribe(listener: () => void) {
  listeners.add(listener);

  // The OS preference, for as long as the reader has not overridden it.
  const query = window.matchMedia("(prefers-color-scheme: light)");
  const onSystemChange = () => {
    if (readPreference() !== "system") return;
    apply(systemTheme());
    announce();
  };
  query.addEventListener("change", onSystemChange);

  // Another tab of the same app. Without this, two open tabs disagree until
  // one of them is reloaded.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== THEME_STORAGE_KEY) return;
    apply(resolve());
    announce();
  };
  window.addEventListener("storage", onStorage);

  return () => {
    listeners.delete(listener);
    query.removeEventListener("change", onSystemChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** The document is what is actually painted, so it is written first and
 *  synchronously — before React re-renders, and before anything downstream
 *  reads a computed colour off `<html>`. */
function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

export function setThemePreference(next: ThemePreference) {
  try {
    if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // The theme still applies to this tab; it just will not be remembered.
  }
  apply(next === "system" ? systemTheme() : next);
  announce();
}

// Rendered on the server, where there is no document to ask. Dark is the
// app's default, and the bootstrap script corrects it before the first paint.
const SERVER_SNAPSHOT = "dark";

type ThemeValue = {
  /** The theme actually applied to the document. */
  theme: Theme;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  toggle: () => void;
};

export function useTheme(): ThemeValue {
  const state = useSyncExternalStore(subscribe, snapshot, () => SERVER_SNAPSHOT);

  const preference: ThemePreference = state.startsWith("system")
    ? "system"
    : (state as Theme);
  const theme: Theme = state.endsWith("light") ? "light" : "dark";

  // Toggle against what is on screen, not against the stored preference:
  // "system" has no opposite, and the reader is looking at a colour.
  const toggle = useCallback(
    () => setThemePreference(theme === "light" ? "dark" : "light"),
    [theme],
  );

  return useMemo(
    () => ({ theme, preference, setPreference: setThemePreference, toggle }),
    [theme, preference, toggle],
  );
}
