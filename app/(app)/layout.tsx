import AuthBridge from "@/components/AuthBridge";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { WorkspaceProvider } from "@/lib/workspace";

/** `useAuth` throws outside a ClerkProvider, and the provider is only mounted
 *  when a publishable key exists — so the bridge is conditional on the same
 *  fact rather than on a second, driftable flag. */
const authConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    // One provider for the shell: it resolves the API project every page is
    // scoped to and owns the single polling loop for its papers.
    <WorkspaceProvider>
      {/* Registers the session-token source before any page fetches. */}
      {authConfigured ? <AuthBridge /> : null}
      {/* The shell sizes itself by flex, not by percentages.
          `h-full` cannot work here: `<body>` is `min-h-full` with an auto
          height, so every `height: 100%` below it resolves against an
          indefinite containing block and collapses to the content — which is
          why the sidebar used to stop partway down the page. `flex-1` gives
          this element a definite height, and the default `stretch` alignment
          (rather than the `items-start` that used to be here) hands it to the
          sidebar and the content column. */}
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-base md:flex-row">
        <Sidebar />
        <div className="flex min-h-0 min-w-px flex-1 flex-col items-start overflow-hidden">
          <Topbar />
          <main className="flex w-full min-h-px flex-1 flex-col items-start gap-6 overflow-y-auto px-4 py-6 sm:px-6 md:px-10 md:py-8">
            {children}
          </main>
        </div>
      </div>
    </WorkspaceProvider>
  );
}
