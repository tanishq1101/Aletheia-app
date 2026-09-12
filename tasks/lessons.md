# Engineering lessons

- A queued terminal panel is not proof that a user can see or complete a masked prompt. Verify the
  expected local configuration file/state before reporting that a secret was stored.
- Model instructions such as “JSON only” are not a complete parser contract. Accept narrowly
  defined wrappers such as fenced JSON, then retain schema validation, caps, and a safe fallback.
- `prisma migrate diff` is not a faithful copy of a Postgres database. It silently drops every
  CHECK constraint, rewrites an HNSW index as a btree (which pgvector cannot even build), strips
  the WHERE clause off partial indexes, and omits expression indexes entirely. A baseline
  generated from it looked complete and was missing 18 constraints and 2 indexes. Always diff a
  generated baseline back against the source database — apply it to a scratch database and
  compare `information_schema.columns`, `pg_indexes` and `pg_constraint` — before trusting it.
- When an ORM cannot express a database object, the danger is not that migrations fail; it is
  that they succeed. Dropping an HNSW index degrades vector search to a sequential scan that
  still returns correct results, so nothing breaks until it is slow months later. Objects an ORM
  cannot see need an explicit assertion (`scripts/verify_schema.py`), not a comment.
- Synthetic key events are not proof of user-facing behaviour. A CDP-dispatched Enter arrives
  with `isTrusted: true` and bubbles un-prevented to `window`, yet does not run Chromium's
  default form action, so a working form looks broken. Distinguish "did not reproduce under
  automation" from "does not work" and say which one is being reported.
- The same list written down three times will disagree in three ways. A trained model was
  missing from the training page, from its notebook download route, and from the notebook
  validator — three independent hardcoded arrays that each forgot it. None of them failed;
  they just quietly showed two of three. When a set is read in more than one place, make it one
  exported registry and give the tooling a check that fails when a member is missing, rather
  than trusting three literals to be edited together.
- A notebook with empty `outputs` has never been run, whatever its prose claims. Executing one
  for the first time found a `NameError` on cell 4 that would have hit every user who chose
  "Run all". "Reproducible" is a property that has to be exercised, not asserted in a markdown
  cell.
- A code generator that overwrites its output unconditionally will eventually revert a fix made
  to that output. Running the notebook builder would have silently undone a bug fix, dropped a
  download retry loop and reintroduced 12 broken f-string interpolations. Generators that write
  over a checked-in artifact should compare first and refuse, not overwrite and print "Wrote".
- Fix the generator, not its output — but check which one is actually ahead first. The stale
  artifact here was the *generator*; regenerating "to fix it properly" would have thrown away
  better code. Diff before regenerating.
- Escaping is not uniform inside one file. Blanket-replacing `{{` with `{` across a builder
  broke every block that really was an f-string while fixing the ones that were not. A
  mechanical edit across mixed contexts needs a per-site check, and the fastest way to find out
  is to run the thing immediately after.
- Authorisation gaps are invisible while there is one user. Every route scoped by `project_id`
  looked correct for months because `dev_user_id` was the only owner; adding accounts turned the
  same code into an IDOR that allowed deleting another user's library. When adding auth to a
  single-user system, audit every route that accepts a resource id — the absence of a filter is
  not visible in any test that only ever has one user.
- Enforce ownership where a new route inherits it. FastAPI resolves dependencies after route
  matching, so `request.path_params` is populated and a router-level dependency can check
  whichever id the matched route declares. Per-handler checks are N edits and one omission, and
  the omission is the whole vulnerability.
- Prove a security test can fail. Removing the ownership dependency and confirming all four
  cross-user tests went red took thirty seconds and is the only reason to believe they test
  anything. A guard with only passing tests is an assumption.
- Fail closed on missing auth configuration. An API that treats "no identity provider set" as
  "run open" turns one forgotten environment variable into a public database. Refusing to start
  unless openness is stated explicitly (`ALLOW_UNAUTHENTICATED=true`) makes the dangerous state
  deliberate instead of accidental.
- 402 and 429 are different failures and must read differently. "Out of credits" sends someone
  to a billing page; "free-tier quota, retry in 37s" tells them to wait. Collapsing them into
  one message costs money or wastes an hour, depending on which way round it is wrong.
- A learning curve without a validation line cannot show the one thing curves are for. Recording
  only training loss costs nothing to fix — one forward pass per sampled epoch — and its absence
  is not noticeable until someone asks whether a model overfit.
