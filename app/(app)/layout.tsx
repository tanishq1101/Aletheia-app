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
      <div className="flex h-full w-full items-start overflow-hidden bg-base">
        <Sidebar />
        <div className="flex h-full min-w-px flex-1 flex-col items-start overflow-hidden">
          <Topbar />
          <main className="flex w-full min-h-px flex-1 flex-col items-start gap-6 overflow-y-auto px-10 py-8">
            {children}
          </main>
        </div>
      </div>
    </WorkspaceProvider>
  );
}
