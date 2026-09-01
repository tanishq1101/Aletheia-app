import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 writes AGENTS.md / CLAUDE.md into the repo root on `next dev`.
  // We don't want AI-tooling files in this repository.
  agentRules: false,
};

export default nextConfig;
