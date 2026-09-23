"use client";

import { useCurrentUser, useSession } from "@/lib/hooks/useSession";

/**
 * Who is signed in, and the way out.
 *
 * Small on purpose. On a shared on-premise deployment the useful fact is
 * *which* account this browser is acting as - a colleague's session left open
 * on a shared machine is the ordinary way work ends up attributed to the wrong
 * person, and the only defence is that the name is visible.
 *
 * Renders nothing while the session is unknown, rather than a placeholder: a
 * name that appears and then changes is worse than one that appears late.
 */
export function AccountControl() {
  const user = useCurrentUser();
  const { signOut } = useSession();

  if (user === null) return null;

  return (
    <div className="flex items-center gap-2.5">
      <span className="text-xs text-ink-muted" title={user.email}>
        {user.display_name || user.email}
      </span>
      <button
        type="button"
        className="btn btn-quiet px-2.5 py-1 text-xs"
        onClick={() => void signOut()}
      >
        Sign out
      </button>
    </div>
  );
}
