import ThemeToggle from "@/components/ThemeToggle";

/** The sign-in shell.
 *
 * The toggle is here as well as in the app shell because this page is outside
 * it: a reader who prefers light should not have to sign in through a dark
 * form to reach the control that changes it. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-full w-full flex-1 items-center justify-center bg-base px-6 py-12">
      <div className="absolute right-6 top-6">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-[440px]">{children}</div>
    </div>
  );
}
