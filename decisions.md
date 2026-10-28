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

## D-002: Architecture and Technology Stack Selection
- **Date/step:** Phase 2 / Design
- **Context:** Need to build an API service in front of the legacy portal that isolates consumers from portal quirks, normalizes data, and provides high performance and type safety.
- **Options considered:**
  - Option A: Node.js + TypeScript + Fastify (pro: good async I/O; con: more boilerplate for cryptographic HMAC and datetime parsing, heavier toolchain).
  - Option B: Python 3.13 + FastAPI + Pydantic v2 + httpx (pro: automatic OpenAPI 3.1 generation, strict data validation with Pydantic v2, clean async HTTP client with connection pooling, native typing and rapid testing; con: requires python environment).
- **Decision:** Choose Option B (Python 3.13, FastAPI, Pydantic v2, httpx, uvicorn).
- **Reason:** FastAPI provides automatic OpenAPI generation (`openapi.json` at repo root), interactive Swagger UI at `/docs`, first-class Pydantic schema validation, and clean dependency injection for mockable clients.
- **Trade-offs / consequences:** Python GIL is not a bottleneck here because the workload is I/O-bound network calls and lightweight JSON normalization.
- **Files affected:** `pyproject.toml`, `requirements.txt`, `src/`

## D-003: Ingestion Architecture: Smart Local Sync via Bulk Path vs On-Demand Pass-Through
- **Date/step:** Phase 2 / Design
- **Context:** The portal contains 403 meters. Querying the portal on every incoming API request would require 21 paginated calls or high latency, risking portal overload and violating the "no hammering / polite" constraint.
- **Options considered:**
  - Option A: Pass-through proxying on every request (pro: stateless; con: sluggish responses >1s, fragile under concurrent requests, hammers the legacy portal).
  - Option B: Periodic background sync / cached local SQLite layer fed by `/portal/export` (pro: instantaneous sub-millisecond API responses, polite to portal with only 1 sync call per TTL, enables rich cross-attribute filtering and geo queries; con: small staleness window equal to TTL).
- **Decision:** Adopt Option B. The service maintains an in-memory / SQLite query layer populated via the portal's HMAC bulk export endpoint. The cache refreshes on a configurable TTL (default 300s) or on explicit invalidation. Consumption readings (`/meters/{id}/consumption`) remain on-demand with caching.
- **Reason:** Maximizes client performance, protects the legacy portal from hammering, and leverages the discovered bulk export path.
- **Trade-offs / consequences:** Data changes on the portal are visible after the cache TTL expires unless manually flushed via `/cache/refresh`.
- **Files affected:** `src/services/portal_client.py`, `src/services/meter_service.py`, `src/db/`

## D-004: Extension Scope Selection
- **Date/step:** Phase 2 / Scope
- **Context:** Assignment allows picking 1–3 optional extensions with high value-for-effort.
- **Options considered:**
  - Option 1: Network hierarchy reconstruction that tolerates messy/inconsistent data and reports anomalies explicitly.
  - Option 2: Local index / query layer (SQLite) enabling cross-attribute filtering and spatial/location querying.
  - Option 3: Caching with explicit staleness strategy (TTL, background refresh, cache headers).
  - Option 4: Full frontend UI web client.
- **Decision:** Select Extensions 1, 2, and 3 (Hierarchy reconstruction with anomaly detection, SQLite local query/spatial index, and TTL caching with auto re-login robustness). Skip Option 4 (web client) to focus on rock-solid API engineering, correctness, and comprehensive testing.
- **Reason:** Directly solves the real data quality problems observed during Phase 1 (22 missing hierarchy attributes, feeder mismatches) and provides immense practical utility for downstream consumers.
- **Trade-offs / consequences:** No graphical web UI provided, but interactive Swagger UI (`/docs`) and Scalar/Redoc are fully available.
- **Files affected:** `src/models/`, `src/services/`, `src/api/`

## D-005: Normalization Standards: Timestamps, Units, and Enums
- **Date/step:** Phase 2 / Data Modeling
- **Context:** The portal provides dates in Indian Standard Time (`DD/MM/YYYY HH:MM`), stringified numeric metrics (`"48438.74"`), and inconsistent casing (`legacy` vs `v2` builds).
- **Options considered:**
  - Option A: Pass portal representations unchanged (pro: zero transformation overhead; con: leaks legacy quirks to API consumers, violates requirements).
  - Option B: Full strict normalization to ISO-8601 UTC, IEEE floating-point numbers, and uppercase/lowercase standardized enums.
- **Decision:** Option B. All timestamps are parsed assuming Asia/Kolkata (+05:30) and converted to ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ`). Energy is normalized to float `kWh`, `kVAh`, and `volts`. Meter status is mapped to clean enums (`INSTALLED`, `DECOMMISSIONED`, `FAULTY`).
- **Reason:** Provides an enterprise-grade developer experience for external systems consuming the API.
- **Trade-offs / consequences:** Slight CPU parsing cost during data ingestion, handled transparently by Pydantic models.
- **Files affected:** `src/models/meter.py`, `src/models/consumption.py`, `src/models/hierarchy.py`

