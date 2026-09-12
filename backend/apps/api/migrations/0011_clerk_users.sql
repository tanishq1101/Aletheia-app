-- Real accounts (Clerk).
--
-- Until now every row in the database belonged to one seeded UUID and the API
-- took the caller's word for nothing because it never asked. `users` existed
-- as an empty shell with only an id.
--
-- The local UUID stays the primary key: every foreign key in the schema
-- already points at it, and Clerk's subject is an external identifier that can
-- outlive or change independently of our own rows. `clerk_user_id` is the
-- mapping, unique so two sessions for the same person cannot fork into two
-- accounts holding half a library each.
--
-- Email and username are cached from the token for display only. They are not
-- authoritative — Clerk is — and nothing authorises on them.

ALTER TABLE users
    ADD COLUMN clerk_user_id TEXT UNIQUE,
    ADD COLUMN email         TEXT,
    ADD COLUMN username      TEXT,
    ADD COLUMN last_seen_at  TIMESTAMPTZ;

-- Partial: the seeded development user has no Clerk subject and must not
-- collide with a real one. NULLs are already distinct in a UNIQUE index, but
-- naming the intent keeps the next reader from "fixing" it to NOT NULL.
COMMENT ON COLUMN users.clerk_user_id IS
    'Clerk subject (sub claim). NULL only for the seeded development user.';

CREATE INDEX idx_users_clerk_user_id ON users (clerk_user_id)
    WHERE clerk_user_id IS NOT NULL;
