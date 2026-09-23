"use client";

import { useEffect, useState } from "react";

import { applyTheme, getInitialTheme, type Theme } from "@/lib/theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    setTheme(getInitialTheme());
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      className="flex items-center gap-2 rounded px-3 py-2 text-sm text-text-secondary hover:bg-surface-raised hover:text-text-primary"
    >
      <span aria-hidden>{theme === "dark" ? "☀️" : "🌙"}</span>
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}
