/**
 * Light/dark mode — an explicit user choice persisted to localStorage,
 * falling back to the OS preference when nothing's been chosen yet.
 * Dark stays the default look (brand's "dark-first" decision) whenever
 * the OS itself has no preference either.
 */

export type Theme = "dark" | "light";

const STORAGE_KEY = "ditsala-conference-theme";

export function getStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : null;
}

export function getSystemTheme(): Theme {
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function getInitialTheme(): Theme {
  return getStoredTheme() ?? getSystemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem(STORAGE_KEY, theme);
}

/** Inlined into a <script> tag in the root layout, run before paint, so
 * the page never flashes the wrong theme while React hydrates. Must stay
 * a plain string (not imported) since it executes before any bundle. */
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = window.localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
    var theme = stored === "light" || stored === "dark"
      ? stored
      : (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = theme;
  } catch (e) {}
})();
`;
