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
- A stub that is more forgiving than the thing it replaces will hide the bug it was written to
  cover. `test_endpoints_refuse_a_garbage_token` passed for weeks while the real endpoint answered
  500, because the fake JWKS client returned a key for any string whereas PyJWKClient parses the
  token header first and raises. The test was not wrong about what it asserted; it was wrong about
  what it was talking to. When a stub stands in for a library, make it fail where the library
  fails, and run the real one at least once against something you control.
- Catch by behaviour, not by inheritance, when a library's exception tree is not a hierarchy.
  `DecodeError` and `PyJWKClientError` are siblings under `PyJWTError`, so two carefully chosen
  `except` clauses still let a malformed token through to a 500. An unauthenticated caller could
  then write a traceback into the log at will. Read the tree before trusting that a base class
  covers the case.
- A script that cannot run must not exit 0. The npm scripts named a POSIX venv path, so on Windows
  cmd.exe printed "'backend' is not recognized" and npm reported success — which meant
  `db:verify`, the guard asserting the indexes and constraints Prisma cannot express, had been
  passing without executing. A green check that never ran is worse than a red one, because nobody
  investigates it.
- gzip output is not a stable identity for its input. Comparing the base64 of a compressed blob
  reported drift between two machines whose zlib differed, on bytes that decode identically. When
  comparing generated artifacts, compare what they mean — decode first — or the check cries wolf
  until someone adds `--force` to their muscle memory.
- Decide which artifact is ahead *before* reconciling, then delete the question. The generator was
  behind its notebook in four separate ways, and the escaping bug in it had already survived one
  blanket fix that broke the cells it did not apply to. Rewriting every cell body as a raw,
  non-f-string constant removed the class of bug rather than its instances: there is no longer a
  site where a brace could need escaping.
- A regeneration that discards recorded outputs silently undoes a validation run. Preserve them
  when the code is unchanged and drop them loudly when `--force` changes it — an output that no
  longer describes its cell is a false claim, not a stale one.
- `hash()` is salted per process, so it cannot key anything shared. Using it for the rate-limit
  identity would have given every worker a different bucket for the same caller and handed each of
  them a full budget — a shared counter that was shared in name only, and the bug would have
  appeared only under the multi-worker deployment it was built for. Any hash that crosses a
  process boundary has to be a stable one.
- Decide what a dependency is *for* before deciding what its outage means. Redis here counts
  requests; it does not serve them. Failing a request because the limiter is unreachable would let
  anyone who can disrupt Redis take the API down, so the limiter degrades to a per-process window,
  says so in `/health`, and the service keeps answering. "Fail closed" is right for authorisation
  and wrong for throttling.
- A cleanup script that deletes rows needs its refusals tested more than its successes. Finding the
  duplicate is visible immediately; taking a project someone deliberately named the same thing, or
  one that acquired a paper between the survey and the delete, is not. The survey is not a lock, so
  the delete re-checks its own preconditions in the transaction that performs it.
- A redirect is not a landing page. `/` sent signed-out visitors straight to a sign-in form having
  never told them what the product was or why its answers should be trusted — and for a system
  whose entire claim is that it does not fabricate citations, the explanation is the product.
- Code behind a feature flag that is off has not been tested, however many tests cover it. Clerk
  was "built and tested" for a sprint, but without a publishable key the provider never mounts, so
  none of it ran: the day real keys arrived, the build failed on a removed component, protected
  pages answered 404 instead of redirecting, and a correctly signed-in user saw "requires a
  signed-in session". Three defects in code that had been green the whole time. Get the credential
  early; a disabled integration is unverified by definition.
- A test suite that reads deployment config is a suite that passes for the wrong reason. These
  tests only passed while nobody had configured an identity provider, so configuring one correctly
  turned 119 of them red on a machine where nothing was broken. Pin the environment your tests
  need in the fixture, including the settings you want *off*.
- Registration from an effect races the first fetch. The token provider was published in
  useEffect, the workspace fetched on mount, and whichever requests lost went out unauthenticated
  and came back 401 — so the signed-in user saw an error and an "API offline" badge. Fix it at the
  single choke point every call passes through, not at the call sites: the next endpoint someone
  adds inherits the fix instead of rediscovering the bug.
- Match UI controls exactly, not by substring, when automating. "continue" also matches "Continue
  with Google", so a sign-in script quietly drove the browser into Google's OAuth flow and then
  reported that the session was missing. The failure looked like a broken login; it was a bad
  selector.
- Bot protection is a fact about your test strategy. Clerk's Turnstile on sign-up cannot be solved
  headlessly, so end-to-end tests have to create accounts through the Backend API and exercise
  sign-in. Better to know that than to conclude sign-up is broken.
- "Could not reproduce under automation" is a statement about the harness until you have tried a
  second harness. Enter-to-submit was carried as a suspected bug across two sprints because a
  JavaScript-dispatched KeyboardEvent does not run Chromium's default actions, so the form looked
  broken. The same key sent through CDP's Input domain submitted it immediately. Before filing the
  product as faulty, change the instrument.
- A fallback is also a place for a bug to hide. `LLM_PROVIDER=openai` had been the
  configured primary for as long as OpenAI was configured, and had never once answered:
  `gpt-5.6-luna` rejects `temperature=0.0` with a 400, and the automatic Gemini failover
  served every request instead. Nothing was red, no log said "primary is broken" loudly
  enough to notice, and `/settings` cheerfully reported OpenAI. Removing the failover
  surfaced it in one test run. A retry path that can substitute a *different vendor*
  should report which one answered, or the metric you are watching is availability and
  the thing you have lost is the ability to tell that half your configuration is dead.
- "Off" has to mean off, or it is not a switch. Enrolling Gemini as a standby because its
  key happened to be present meant the only way to *not* call Google was to delete the
  key — so the config could not express "keep this credential, do not use it", and an
  operator could be billed by a vendor they thought they had disabled. Make the flag the
  thing that decides, and never the presence of a credential.
- One-shot retries do not compose. The 400 handler could swap `max_tokens` for
  `max_completion_tokens`, and separately could have dropped an unsupported
  `temperature` — but a model needing both hit the second 400 having already spent its
  retry, and failed. When adaptations are read off the provider's own error, loop over
  them and track which have been applied, rather than writing one `if` per symptom.
- Point the live tests at the configuration that ships. These were pinned to
  `GEMINI_API_KEY`, so they proved the *backup* worked and skipped silently on the
  primary. Keying the skip off the enabled provider instead is what turned a
  long-standing outage into a failing test.
- On a reasoning model, `max_tokens` is not an answer budget — it is a *shared* budget for
  hidden reasoning and the visible answer, and the split is not proportional. gpt-5.6-luna
  spent all 2048 on reasoning and returned an empty completion; at 8192 it reasoned for 69
  tokens and wrote 6559. The configured ceiling was therefore below the floor at which the
  model produces any output, and the symptom was not "answers are short" but "the report
  randomly fails". When a completion comes back empty, read `finish_reason` before retrying:
  `length` means raise the ceiling, anything else means try again as-is. Retrying `length`
  unchanged fails identically, forever.
- A generic error message is a decision to discard the diagnosis. "The combined report could
  not be generated" was caught from a bare `except Exception` and replaced the real cause,
  which was an empty completion from a starved budget — recoverable, and named in the
  exception that was thrown away. The step-level errors in the same file already carried
  `str(exc)`; the synthesis path did not, so the one failure users actually hit was the one
  with no reason attached. Put the cause in the message the user sees.
- Two error notices rendering at once means two components disagree about who owns the
  failure. The agent page showed `synthesis_error` *and* a hardcoded fallback, because the
  fallback keyed off "synthesis is absent" rather than "synthesis was requested and failed".
  A fallback for a missing value has to distinguish "not asked for" from "asked for and
  broken", or it will eventually accuse the system of a failure that did not happen.
- Negotiated protocol state belongs on the connection, not the call. Discovering which
  request fields a model accepts cost a 400 — and on this model a second 400 — before every
  single completion in the application: three round-trips where one would do, on every
  answer, every agent step, every extraction. A fixed model name cannot change its mind, so
  learn it once and keep it. The same bug's twin: the 402 retry path rebuilt its request from
  the defaults and threw the learned shape away, so the one retry that exists to rescue a low
  balance would have failed on an unrelated 400.
- Endpoint tests passing is not evidence that a browser can use the endpoint. `Content-
  Disposition` was set, asserted, and green in the API tests — and invisible to the actual
  download, because a browser hides every response header from JavaScript except the six
  CORS-safelisted ones. The first real click in a signed-in browser found it immediately.
  Cross-origin behaviour is not observable from a test client that is not a browser.
- Write the test so that disabling the code makes it fail, then check. The paper-id
  cross-check test passed against the guard *and* against `if False:` — ownership was
  404ing on an unknown UUID long before the guard was reached, so the test proved nothing
  about the thing it was named after. It only became a real test once it used a paper the
  caller genuinely owns.
- An export must be rendered from the result on screen, never regenerated. These models do
  not reproduce their own answers, so a "download this report" endpoint that re-ran the
  question would hand back a different document and call it the same one.
- When a capability the product promises turns out to be unavailable, say so on the artefact
  rather than deleting the promise quietly. Temperature 0 is what made answers re-verifiable,
  and no model in the 5.5/5.6 generation accepts it (`seed` is accepted but does not
  reproduce either — measured). The answer now carries `reproducible`, and it is printed on
  every exported PDF, because the person deciding whether to trust a cited claim is reading
  the PDF, not the server log.
