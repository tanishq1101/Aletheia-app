"use client";

import { SignedIn, SignedOut, UserButton } from "@clerk/nextjs";
import Link from "next/link";

/** Account control in the app shell.
 *
 * Rendered only where a ClerkProvider exists — see Topbar — so it never has to
 * ask whether authentication is configured. `SignedOut` still matters inside
 * that: the session can end while a tab is open, and a shell with no way to
 * sign back in is a dead end. */
export default function UserMenu() {
  return (
    <>
      <SignedIn>
        {/* Where sign-out lands is set once on ClerkProvider, so the shell
            and any other future entry point cannot disagree about it. */}
        <UserButton appearance={{ elements: { avatarBox: "size-8" } }} />
      </SignedIn>
      <SignedOut>
        <Link
          href="/sign-in"
          className="shrink-0 rounded-md border border-brass px-3 py-[7px] font-ui text-[13px] font-semibold text-brass hover:bg-surface-raised"
        >
          Sign in
        </Link>
      </SignedOut>
    </>
  );
}
