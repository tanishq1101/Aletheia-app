import { NextResponse } from "next/server";

/** Where the browser should send API calls, decided per request.
 *
 * `NEXT_PUBLIC_API_URL` is inlined into the bundle at build time, so changing
 * it means a rebuild — and with a Cloudflare quick tunnel, whose hostname
 * changes every time it reconnects, that was a full no-cache production
 * redeploy per tunnel restart.
 *
 * A plain server-side `process.env` read would not have fixed it: Vercel binds
 * environment variables to a deployment, so editing one still requires a
 * redeploy before any running lambda sees it. Edge Config is the piece that is
 * genuinely mutable in place — `vercel global-config update` takes effect on
 * the next request, with nothing rebuilt.
 */

/** Never cached, never prerendered. A stale answer here is exactly the failure
 *  this endpoint exists to remove. */
export const dynamic = "force-dynamic";
export const revalidate = 0;

/** Used when Edge Config names nothing. The default is the backend deployed
 *  with this app (`api/index.py`, reached through the `/api/py` rewrite in
 *  `next.config.ts`), on this same origin — locally the same rewrite proxies
 *  to port 8000. `NEXT_PUBLIC_API_URL` still points the app at a backend
 *  hosted somewhere else, and Edge Config overrides both without a redeploy. */
const FALLBACK = process.env.NEXT_PUBLIC_API_URL || "/api/py";

/** Reads one key out of Edge Config over its REST API.
 *
 *  Deliberately not `@vercel/edge-config`: the whole interaction is a single
 *  authenticated GET, and a dependency that has to be installed, versioned and
 *  kept current is a poor trade for the fetch below. `EDGE_CONFIG` is the
 *  standard connection string (`https://edge-config.vercel.com/<id>?token=…`),
 *  kept in that shape so the SDK remains a drop-in if this ever needs more
 *  than one key.
 *
 *  Note the token goes in an `Authorization` header rather than staying in the
 *  query string — the query-string form is rejected on the items endpoints. */
async function readApiBaseUrl(): Promise<string | null> {
  const connection = process.env.EDGE_CONFIG;
  if (!connection) return null;

  let id: string;
  let token: string | null;
  try {
    const url = new URL(connection);
    id = url.pathname.replace(/^\//, "");
    token = url.searchParams.get("token");
  } catch {
    return null;
  }
  if (!id || !token) return null;

  try {
    const response = await fetch(
      `https://edge-config.vercel.com/${id}/items`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      },
    );
    if (!response.ok) return null;
    const items = (await response.json()) as Record<string, unknown>;
    const value = items?.apiBaseUrl;
    return typeof value === "string" && value ? value : null;
  } catch {
    // Edge Config unreachable. The fallback below is a working answer rather
    // than a 500 that would take the whole app down with it.
    return null;
  }
}

export async function GET() {
  const fromStore = await readApiBaseUrl();

  return NextResponse.json(
    {
      // No trailing slash: every call site concatenates a path onto this.
      apiBaseUrl: (fromStore ?? FALLBACK).replace(/\/+$/, ""),
      source: fromStore
        ? "edge-config"
        : process.env.NEXT_PUBLIC_API_URL
          ? "build"
          : "bundled",
    },
    { headers: { "Cache-Control": "no-store, max-age=0" } },
  );
}
