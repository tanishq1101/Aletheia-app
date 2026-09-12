import { SignUp } from "@clerk/nextjs";
import { redirect } from "next/navigation";

/** Registration. Which identifiers are offered — Google, email, username — is
 *  configured in the Clerk dashboard, not here, so the two cannot disagree. */
export default function SignUpPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) redirect("/sign-in");

  return (
    <div className="flex w-full flex-col items-center gap-8">
      <div className="flex w-full flex-col items-start gap-1.5">
        <div className="mb-4 h-[2px] w-12 bg-brass" />
        <p className="font-mono text-[11px] tracking-[1.32px] text-brass">
          THE ARCHIVE
        </p>
        <h1 className="font-display text-[26px] font-black text-primary">
          Create an account
        </h1>
        <p className="font-ui text-[13px] text-secondary">
          Continue with Google, or use an email address and username.
        </p>
      </div>

      <SignUp
        appearance={{ elements: { rootBox: "w-full", cardBox: "w-full" } }}
        signInUrl="/sign-in"
        fallbackRedirectUrl="/library"
      />
    </div>
  );
}
