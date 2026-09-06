# Engineering lessons

- A queued terminal panel is not proof that a user can see or complete a masked prompt. Verify the
  expected local configuration file/state before reporting that a secret was stored.
- Model instructions such as “JSON only” are not a complete parser contract. Accept narrowly
  defined wrappers such as fenced JSON, then retain schema validation, caps, and a safe fallback.
