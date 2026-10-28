# Decision Log

## D-001: Environment Configuration, Credential Isolation, and Investigation Tooling
- **Date/step:** Phase 1 / Initialization
- **Context:** The Urja Meter Ops legacy portal requires authentication credentials (`PORTAL_URL`, `PORTAL_USERNAME`, `PORTAL_PASSWORD`). Credentials must never be committed to version control, logged, or exposed in API errors or test fixtures. We also need an HTTP investigation harness for Phase 1.
- **Options considered:**
  - Option A: Hardcode temporary test values into investigation scripts (pro: fast; con: dangerous, high leak risk, violates core constraint).
  - Option B: Use `.env` file excluded by `.gitignore` with `.env.example` committed and `python-dotenv` for loading (pro: standard 12-factor pattern, safe, easy local execution; con: requires manual copying of `.env.example` on fresh clones).
  - Option C: System environment variables only (pro: no files on disk; con: inconvenient for local reproduction and IDE test execution).
- **Decision:** Adopt Option B (`.env` strictly git-ignored, committed `.env.example` with non-sensitive placeholders). Use Python for the investigation script and downstream implementation due to rich tooling (`httpx`, `BeautifulSoup4`, `pydantic`, `fastapi`, `pytest`).
- **Reason:** Directly aligns with safety constraints, guarantees zero credentials in git history, and provides standard developer ergonomics for local execution.
- **Trade-offs / consequences:** Anyone cloning the repository must create `.env` before running live integration tests or starting the live daemon. Unit tests will run against sanitized offline fixtures.
- **Files affected:** `.gitignore`, `.env`, `.env.example`, `decisions.md`
