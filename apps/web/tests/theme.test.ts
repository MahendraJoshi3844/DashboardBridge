/**
 * Theme preference and what it resolves to.
 *
 * Three preferences, two palettes. The distinction is the design: `system` is
 * a preference and is never written to the element, because resolving it in
 * JavaScript is what keeps `tokens.css` to two blocks instead of two blocks
 * written twice - once for a selector and once for a media query. Two copies
 * of a palette drift the first time somebody adjusts one colour.
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_PREFERENCE,
  THEME_PREFERENCES,
  asPreference,
  resolveTheme,
  themeAnnouncement,
} from "@/lib/theme";

describe("theme preferences", () => {
  it("offers exactly the three the user asked for", () => {
    expect([...THEME_PREFERENCES]).toEqual(["system", "light", "dark"]);
  });

  it("follows the system when that is the preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("ignores the system when the user has chosen explicitly", () => {
    // The point of an explicit choice: an OS set to dark must not override
    // someone who picked light, or the control does nothing on half the
    // machines it runs on.
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("never resolves to the preference name itself", () => {
    // `system` on the element would match no palette and render unstyled.
    for (const preference of THEME_PREFERENCES) {
      for (const prefersDark of [true, false]) {
        expect(["light", "dark"]).toContain(resolveTheme(preference, prefersDark));
      }
    }
  });
});

describe("reading a stored preference", () => {
  it("accepts the three known values", () => {
    expect(asPreference("system")).toBe("system");
    expect(asPreference("light")).toBe("light");
    expect(asPreference("dark")).toBe("dark");
  });

  it.each([null, undefined, "", "midnight", 42, {}])(
    "falls back rather than trusting %p",
    (value) => {
      // Storage holds a string a user can edit, and a value written by an
      // older build outlives that build. An unrecognised one must not reach
      // the element.
      expect(asPreference(value)).toBe(DEFAULT_PREFERENCE);
    },
  );

  it("defaults to following the system", () => {
    // Not dark: a product that ignores an OS-level preference on first run is
    // making a choice on the user's behalf that they already made elsewhere.
    expect(DEFAULT_PREFERENCE).toBe("system");
  });
});

describe("what is announced", () => {
  it("says what the system currently is, not just that it is being followed", () => {
    // "System" alone is the one label that does not tell a screen-reader user
    // what they are actually getting.
    expect(themeAnnouncement("system", "dark")).toContain("currently dark");
    expect(themeAnnouncement("system", "light")).toContain("currently light");
  });

  it("states an explicit choice plainly", () => {
    expect(themeAnnouncement("light", "light")).toBe("Theme: light");
    expect(themeAnnouncement("dark", "dark")).toBe("Theme: dark");
  });
});
