-- Sprint 1 has no authentication (not a Sprint 1 deliverable), but
-- projects.user_id is a real foreign key. This seeds a single fixed-UUID owner
-- so the upload flow works end to end without inventing an auth system.
-- Replace when auth arrives; the UUID is referenced by app.core.config.

INSERT INTO users (id) VALUES ('00000000-0000-0000-0000-000000000001')
ON CONFLICT (id) DO NOTHING;
