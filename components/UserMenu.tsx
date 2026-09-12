"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import Link from "next/link";

/** Account control in the app shell.
 *
 * Rendered only where a ClerkProvider exists — see Topbar — so it never has to
 * ask whether authentication is configured. The signed-out branch still
 * matters inside that: a session can end while a tab is open, and a shell with
 * no way to sign back in is a dead end.
 *
 * This reads the session through `useAuth` rather than `<SignedIn>` /
 * `<SignedOut>`. Those are still *exported* by @clerk/nextjs 7, but Core 3
 * removed them for Next.js and they throw when rendered — which surfaced only
 * once real keys existed, because without a publishable key the provider is
 * never mounted and this component is never reached. The build failed
 * prerendering `/cross-paper`.
 */
export default function UserMenu() {
  const { isLoaded, isSignedIn } = useAuth();

  // Nothing until Clerk has resolved the session. Guessing either way would
  // flash the wrong control and, during prerender, bake that guess into the
  // static HTML for every visitor.
  if (!isLoaded) return null;

  if (isSignedIn) {
    // Where sign-out lands is set once on ClerkProvider, so the shell and any
    // other future entry point cannot disagree about it.
    return <UserButton appearance={{ elements: { avatarBox: "size-8" } }} />;
  }

  return (
    <Link
      href="/sign-in"
      className="shrink-0 rounded-md border border-brass px-3 py-[7px] font-ui text-[13px] font-semibold text-brass hover:bg-surface-raised"
    >
      Sign in
    </Link>
  );
}
