/**
 * Theme preference: what the user chose, and what that resolves to.
 *
 * Three preferences and *two* palettes, and the distinction is the whole
 * design. `system` is a preference, never a value on the element: the script
 * in `layout.tsx` resolves it before first paint and re-resolves it when the
 * OS setting changes, so `data-theme` on <html> is only ever `dark` or
 * `light`.
 *
 * That is what keeps `tokens.css` to two blocks. The alternative - a
 * `[data-theme]` rule and a `prefers-color-scheme` media query - means writing
 * the same palette twice, and two copies of a palette are two copies that
 * drift the first time somebody adjusts one colour.
 *
 * Pure so it can be tested without a DOM; everything here is called from both
 * the inline boot script and the React control.
 */

export const THEME_PREFERENCES = ["system", "light", "dark"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

/** What actually gets written to the element. `system` is not one of these. */
export type ResolvedTheme = "light" | "dark";

/** Where the choice is remembered. Read by the boot script by this literal. */
export const THEME_STORAGE_KEY = "dbb-theme";

/** The palette with no JavaScript, no stored choice and no OS preference. */
export const DEFAULT_PREFERENCE: ThemePreference = "system";

/**
 * Narrow anything to a preference. Storage is a string the user can edit and a
 * value from an older build can outlive it, so an unrecognised one falls back
 * rather than putting an unknown value on the element.
 */
export function asPreference(value: unknown): ThemePreference {
  return THEME_PREFERENCES.includes(value as ThemePreference)
    ? (value as ThemePreference)
    : DEFAULT_PREFERENCE;
}

/**
 * The palette a preference means right now.
 *
 * `systemPrefersDark` is passed in rather than read here, because this runs in
 * three places - the boot script, a React effect, and a test - and only one of
 * them has a `window`.
 */
export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "dark") return "dark";
  if (preference === "light") return "light";
  return systemPrefersDark ? "dark" : "light";
}

/** How each choice is labelled. Sentence case, like every other control. */
export const THEME_LABELS: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/**
 * What a screen reader announces for the group's current state.
 *
 * "System" alone does not say what the system currently *is*, and that is the
 * one thing a person using this control wants to know.
 */
export function themeAnnouncement(
  preference: ThemePreference,
  resolved: ResolvedTheme,
): string {
  return preference === "system"
    ? `Theme: following the system setting, currently ${resolved}`
    : `Theme: ${THEME_LABELS[preference].toLowerCase()}`;
}
