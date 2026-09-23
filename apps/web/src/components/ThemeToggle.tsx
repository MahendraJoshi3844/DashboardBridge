"use client";

import { useEffect, useState } from "react";

import {
  DEFAULT_PREFERENCE,
  THEME_LABELS,
  THEME_PREFERENCES,
  THEME_STORAGE_KEY,
  asPreference,
  resolveTheme,
  themeAnnouncement,
  type ResolvedTheme,
  type ThemePreference,
} from "@/lib/theme";

const QUERY = "(prefers-color-scheme: dark)";

/**
 * System / Light / Dark.
 *
 * A radio group, not a two-state switch and not a cycling button. Three
 * choices need three controls: a toggle cannot express "follow the system",
 * and a button that cycles makes the user press it and watch to find out what
 * it does. `radiogroup` is also what a screen reader already knows how to
 * describe - "3 of 3 selected" - without any custom announcement.
 *
 * The applied value is written by the boot script before first paint. This
 * component reads it back rather than assuming, so a mismatch between what the
 * script decided and what React thinks cannot appear as a flash.
 */
export function ThemeToggle() {
  const [preference, setPreference] = useState<ThemePreference>(DEFAULT_PREFERENCE);
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");

  // Read the stored choice after mount. Reading it during render would differ
  // between the server pass and the browser, which is the classic hydration
  // mismatch - and here it would show as the page changing colour on load.
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    } catch {
      // Storage can be unavailable - a private window, or blocked site data.
      // The control still works for this page; it just will not be remembered.
    }
    setPreference(asPreference(stored));
  }, []);

  // Apply, and keep applying: `system` has to follow the OS while the page is
  // open, not only at load. Without the listener a user changing their OS
  // theme sees a page that disagrees with everything around it.
  useEffect(() => {
    const media = window.matchMedia(QUERY);
    const apply = () => {
      const next = resolveTheme(preference, media.matches);
      document.documentElement.dataset.theme = next;
      setResolved(next);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preference]);

  function choose(next: ThemePreference) {
    setPreference(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // As above: not being remembered is a smaller failure than not working.
    }
  }

  return (
    <div className="theme-toggle">
      <div
        role="radiogroup"
        aria-label="Colour theme"
        className="theme-toggle__group"
      >
        {THEME_PREFERENCES.map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={preference === value}
            className="theme-toggle__option"
            onClick={() => choose(value)}
          >
            {THEME_LABELS[value]}
          </button>
        ))}
      </div>
      {/* Announced on change, not drawn: the buttons already say which is
          chosen, but "System" alone does not say what the system currently is. */}
      <span className="sr-only" aria-live="polite">
        {themeAnnouncement(preference, resolved)}
      </span>
    </div>
  );
}
