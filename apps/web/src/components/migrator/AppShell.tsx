"use client";

/**
 * The migrator's frame: a dark icon rail, a section sidebar, and a top bar with
 * breadcrumbs, search, the licence, the theme and the signed-in person.
 *
 * Navigation only. Nothing here reads a workbook or decides anything about a
 * conversion (AGENTS.md rule 8).
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useCurrentUser, useSession } from "@/lib/hooks/useSession";
import { useLicense } from "@/lib/hooks/useLicense";
import { THEME_STORAGE_KEY } from "@/lib/theme";

import {
  IconBell,
  IconGrid,
  IconHome,
  IconJobs,
  IconMoon,
  IconPulse,
  IconSearch,
  IconSun,
  IconSwap,
  IconUpload,
} from "./MgIcons";

export interface Crumb {
  readonly label: string;
  readonly href?: string;
}

interface AppShellProps {
  readonly crumbs: readonly Crumb[];
  readonly children: ReactNode;
}

/** The platforms the sidebar lists, and the migration card each one opens. */
const PLATFORMS: readonly { readonly name: string; readonly opens: string | null }[] = [
  { name: "Tableau", opens: "tableau-powerbi" },
  { name: "Cognos", opens: null },
  { name: "MicroStrategy", opens: "microstrategy-powerbi" },
  { name: "Qlik", opens: "qlik-powerbi" },
  { name: "Looker", opens: null },
];

function ThemeButton() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    setDark(document.documentElement.dataset.theme === "dark");
  }, []);
  function flip() {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setDark(!dark);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Not remembered is a smaller failure than not working.
    }
  }
  return (
    <button
      type="button"
      className="mg-iconbtn"
      onClick={flip}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
    >
      {dark ? <IconSun /> : <IconMoon />}
    </button>
  );
}

function LicenceBadge() {
  const probe = useLicense();
  if (probe.phase !== "known") return null;
  const { status } = probe;
  if (!status.licensed) {
    return <span className="mg-pill mg-pill--bad">Not licensed</span>;
  }
  if (typeof status.days_remaining === "number") {
    return (
      <span
        className={`mg-pill${status.expiring_soon ? " mg-pill--warn" : ""}`}
        title={status.customer ? `Licensed to ${status.customer}` : undefined}
      >
        <IconPulse size={13} /> {status.days_remaining} days left
      </span>
    );
  }
  return <span className="mg-pill">Licensed</span>;
}

export function AppShell({ crumbs, children }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const user = useCurrentUser();
  const { signOut } = useSession();
  const [query, setQuery] = useState("");

  const initial = (user?.display_name || user?.email || "?").trim().charAt(0).toUpperCase();
  const at = (prefix: string) => (pathname?.startsWith(prefix) ? "page" : undefined);

  return (
    <div className="mg mg-shell">
      <nav className="mg-rail" aria-label="Areas">
        <Link href="/migrate" className="mg-rail__logo" aria-label="DashboardBridge home">
          <IconSwap size={18} />
        </Link>
        <Link href="/jobs" className="mg-rail__item" aria-current={at("/jobs")} title="Migration jobs">
          <IconGrid />
        </Link>
        <Link href="/migrate" className="mg-rail__item" aria-current={at("/migrate")} title="Migrate">
          <IconSwap />
        </Link>
        <Link href="/classic" className="mg-rail__item" title="Guided analysis (classic view)">
          <IconHome />
        </Link>
      </nav>

      <aside className="mg-side" aria-label="Migrate">
        <div className="mg-side__label">Migrate</div>
        <Link href="/migrate" className="mg-side__link" aria-current={pathname === "/migrate" ? "page" : undefined}>
          <IconUpload /> Start Migration
        </Link>
        <Link href="/jobs" className="mg-side__link" aria-current={at("/jobs")}>
          <IconJobs /> Migration Jobs
        </Link>

        <div className="mg-side__label">Platforms</div>
        {PLATFORMS.map((platform) =>
          platform.opens !== null ? (
            <Link key={platform.name} href={`/migrate?open=${platform.opens}`} className="mg-side__link">
              <IconSwap /> {platform.name}
            </Link>
          ) : (
            <span
              key={platform.name}
              className="mg-side__link"
              aria-disabled="true"
              title={`No ${platform.name} reader exists yet`}
            >
              <IconSwap /> {platform.name}
            </span>
          ),
        )}
      </aside>

      <header className="mg-top">
        <nav className="mg-crumbs" aria-label="Breadcrumb">
          <Link href="/migrate" className="mg-brand">
            DashboardBridge
          </Link>
          <Link href="/migrate" aria-label="Home">
            <IconHome size={14} />
          </Link>
          {crumbs.map((crumb, index) => (
            <span key={crumb.label} style={{ display: "contents" }}>
              <span aria-hidden="true">›</span>
              {crumb.href && index < crumbs.length - 1 ? (
                <Link href={crumb.href}>{crumb.label}</Link>
              ) : (
                <span aria-current={index === crumbs.length - 1 ? "page" : undefined}>{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>

        <div className="mg-top__right">
          <form
            className="mg-search"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              router.push(`/jobs${query ? `?q=${encodeURIComponent(query)}` : ""}`);
            }}
          >
            <IconSearch size={14} />
            <input
              aria-label="Search migration jobs"
              placeholder="Search jobs…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <span className="mg-kbd">Enter</span>
          </form>
          <LicenceBadge />
          <button type="button" className="mg-iconbtn" disabled aria-label="Notifications (none yet)" title="No notifications">
            <IconBell />
          </button>
          <ThemeButton />
          <button
            type="button"
            className="mg-iconbtn"
            onClick={() => void signOut()}
            title={user ? `Signed in as ${user.email} — sign out` : "Sign out"}
            aria-label="Sign out"
          >
            <span className="mg-avatar">{initial}</span>
          </button>
        </div>
      </header>

      <main id="main" className="mg-main">
        {children}
      </main>
    </div>
  );
}
