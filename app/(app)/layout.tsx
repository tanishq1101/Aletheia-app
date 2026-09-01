import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { WorkspaceProvider } from "@/lib/workspace";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    // One provider for the shell: it resolves the API project every page is
    // scoped to and owns the single polling loop for its papers.
    <WorkspaceProvider>
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
