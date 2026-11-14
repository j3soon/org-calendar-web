# Repository Guidelines

## Commit style

- Follow Conventional Commits, adding a scope when useful, for example
  `feat(calendar): ...`, `fix(parser): ...`, or `docs: ...`.
- Make each commit a complete, reviewable change. Keep unrelated work separate.
- Select the type by behavior: `feat` adds a capability, `fix` corrects a defect,
  and `perf` improves efficiency without changing behavior.
- Keep the body to two short paragraphs or fewer. Explain the reason and result
  so readers do not need the conversation. Include validation only when it adds
  useful context beyond routine successful checks.
- Let Git use the configured human name and email. Do not replace them with an
  agent identity.
- End agent-written messages with `by <Harness> (<Model>)` on a separate line.
  Use the actual harness and full model slug. Verify them if uncertain. Add no
  coauthor trailers, session links, or other attribution.
- Use real paragraph breaks. After committing, inspect the stored message with
  `git log -1 --format=fuller` and check that attribution is the final line.
