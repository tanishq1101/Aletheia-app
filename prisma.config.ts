/** Prisma CLI configuration (Prisma 7 moved connection URLs out of the schema).
 *
 * Only the CLI reads this — `migrate`, `db pull`, `studio`. No Prisma Client is
 * generated: the API is Python and queries the database through psycopg. See
 * the header of prisma/schema.prisma for why.
 *
 * The connection string comes from `backend/.env`, the same file FastAPI loads,
 * so there is exactly one place to point at Neon. Two copies of a connection
 * string is how a migration ends up applied to the wrong database.
 *
 *   DATABASE_URL         pooled Neon endpoint (host contains "-pooler") — what
 *                        the application uses.
 *   DIRECT_DATABASE_URL  unpooled endpoint. Preferred here, because everything
 *                        this file configures is a migration, and PgBouncer in
 *                        transaction mode cannot hold the session-level
 *                        advisory locks a migration takes. Unset for local
 *                        Postgres, which has no pooler in front of it.
 *
 * Prisma 7 removed the `directUrl` datasource property, so the choice is made
 * here rather than declared: the CLI gets the direct endpoint when one exists.
 */
import { config as loadEnv } from "dotenv";
import path from "node:path";
import { defineConfig } from "prisma/config";

loadEnv({ path: path.join(__dirname, "backend", ".env") });

const migrationUrl = process.env.DIRECT_DATABASE_URL ?? process.env.DATABASE_URL;
if (!migrationUrl) {
  throw new Error(
    "Neither DIRECT_DATABASE_URL nor DATABASE_URL is set. Prisma reads them " +
      "from backend/.env — the same file the API uses. Add it there rather " +
      "than creating a second copy.",
  );
}

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: {
    url: migrationUrl,
    shadowDatabaseUrl: process.env.SHADOW_DATABASE_URL,
  },
});
