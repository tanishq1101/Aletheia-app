import type { NextConfig } from "next";

/** Where `/api/py/*` goes.
 *
 * On Vercel, to the Python function in `api/index.py` — the FastAPI backend
 * deployed with the app, on the same origin. The function receives the
 * original `/api/py/...` path and strips the prefix itself.
 *
 * In `next dev`, to the backend running under uvicorn or docker compose on
 * port 8000, which serves its routes without the prefix. The browser uses
 * `/api/py` in both cases, so local development exercises the same URLs as
 * production. Override with BACKEND_DEV_URL if the API listens elsewhere. */
const devBackend = (process.env.BACKEND_DEV_URL ?? "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  // Next 16 writes AGENTS.md / CLAUDE.md into the repo root on `next dev`.
  // We don't want AI-tooling files in this repository.
  agentRules: false,
  async rewrites() {
    return [
      {
        source: "/api/py/:path*",
        destination:
          process.env.NODE_ENV === "development"
            ? `${devBackend}/:path*`
            : "/api/",
      },
    ];
  },
};

export default nextConfig;
