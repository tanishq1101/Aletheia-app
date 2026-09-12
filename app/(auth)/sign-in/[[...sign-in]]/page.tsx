import { SignIn } from "@clerk/nextjs";
import Link from "next/link";

/** Sign-in.
 *
 * Clerk hosts the form itself, so this file does not touch credentials: no
 * password ever enters this codebase, and Google sign-in is a provider
 * enabled in the Clerk dashboard rather than an OAuth flow implemented here.
 *
 * With no publishable key the page falls back to what it honestly said
 * before — that this build has no accounts — instead of rendering a form that
 * cannot work. */
export default function SignInPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return (
      <div className="flex w-full flex-col items-start gap-7 rounded-lg border border-hairline bg-surface p-12">
        <div className="h-[2px] w-12 shrink-0 bg-brass" />

        <div className="flex w-full flex-col items-start gap-1.5">
          <p className="font-mono text-[11px] tracking-[1.32px] text-brass">
            THE ARCHIVE
          </p>
          <h1 className="font-display text-[26px] font-black text-primary">
            Development build
          </h1>
        </div>

        <p className="w-full font-ui text-[13px] text-secondary">
          Accounts are built, but this instance has no Clerk keys configured, so
          sign-in is switched off. Every project belongs to a single seeded
          development user, and anyone who can reach the API can read and change
          everything in it.
        </p>

        <p className="w-full font-ui text-xs text-muted">
          Set <code className="font-mono">NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY</code>{" "}
          and <code className="font-mono">CLERK_SECRET_KEY</code> here, and{" "}
          <code className="font-mono">CLERK_ISSUER</code> on the API, to require
          sign-in. Until then, do not put anything sensitive in a deployed
          instance.
        </p>

        <Link
          href="/library"
          className="flex w-full items-center justify-center rounded-md bg-oxblood py-[13px] font-ui text-sm font-semibold text-primary"
        >
          Continue to the library
        </Link>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col items-center gap-8">
      <div className="flex w-full flex-col items-start gap-1.5">
        <div className="mb-4 h-[2px] w-12 bg-brass" />
        <p className="font-mono text-[11px] tracking-[1.32px] text-brass">
          THE ARCHIVE
        </p>
        <h1 className="font-display text-[26px] font-black text-primary">
          Sign in to Aletheia
        </h1>
        <p className="font-ui text-[13px] text-secondary">
          Your library, papers and conversations are private to your account.
        </p>
      </div>

      <SignIn
        appearance={{ elements: { rootBox: "w-full", cardBox: "w-full" } }}
        signUpUrl="/sign-up"
        fallbackRedirectUrl="/library"
      />
    </div>
  );
}
