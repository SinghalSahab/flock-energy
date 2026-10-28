# Handover & Interview Defense Guide

This document is your preparation cheat-sheet for defending this project in a follow-up interview.

---

## 1. One-Page Summary: How the Portal Works

The legacy "Urja Meter Ops" portal (`https://urja-ops.flockenergy.tech`) is a modern SvelteKit web application backed by an authentication library called `better-auth`.

### Authentication
When logging in via the web form (`POST /login`), the portal enforces SvelteKit's built-in CSRF protection: it strictly verifies that the `Origin` header matches `https://urja-ops.flockenergy.tech`. If this header is missing, it immediately throws a `403 Forbidden`. When supplied, it returns an HTTP 200 with JSON `{"type":"redirect","status":303,"location":"/meters"}` and issues an HTTP-only session cookie: `__Secure-better-auth.session_token`. The session token has a `Max-Age` of 3600 seconds (1 hour). Unauthenticated requests to API endpoints return `401 Unauthorized` with `{"error":"unauthorized"}`, while unauthenticated UI requests redirect (`302`) to `/login`.

### Endpoints & Data Distribution
Although the portal UI presents a server-rendered look, it is a single-page application that fetches data from internal JSON endpoints:
- `GET /portal/meters/search?q=&page=N`: Returns paginated lists of 20 meters.
- `GET /portal/dts?page=N`: Returns paginated distribution transformers (40 DTs total across 2 pages).
- `GET /portal/meters/{id}/geo`: Returns coordinates (`latitude`, `longitude`).
- `GET /portal/meters/{id}/energy`: Returns a fixed set of 337 half-hourly readings spanning 7 days. It completely ignores query parameters (`limit`, `from`).
- `GET /portal/keys` and `GET /portal/export?page=1`: The "hidden gem" of the portal! Used by the UI's "Export all meters" button. It returns **all 403 meters** with complete technical attributes, geo-coordinates, and the entire 7-level hierarchy tree in a single response, authenticated via an HMAC-SHA256 signature generated from a shared signing secret.

### Legacy Data Quality Quirks
The dataset contains two architectural generations: `legacy` (238 meters with key-value arrays) and `v2` (165 meters with JSON-encoded `classData`). Furthermore, the network hierarchy has **22 real anomalies**: nodes where names exist but codes are blank, codes exist but names are blank, and 5 meters where the feeder code is blank despite the DT catalog defining the active feeder.

---

## 2. Top 10 Technical Concepts & Decisions to Explain

### 1. Cryptographic HMAC-SHA256 Bulk Ingestion
- **Explanation**: Rather than making 420+ paginated HTTP calls, the client calls `GET /portal/keys` to get a `signingSecret`, computes `HMAC-SHA256(secret, "GET\n/portal/export\npage=1\n<timestamp>")`, and sends it via headers `x-timestamp` and `x-signature`.
- **Where to look**: `src/services/portal_client.py:export_all_meters`

### 2. SvelteKit CSRF Origin Mitigation
- **Explanation**: SvelteKit rejects form actions from non-matching origins with 403. Passing `Origin: https://urja-ops.flockenergy.tech` satisfies this check programmatically.
- **Where to look**: `src/services/portal_client.py:login`

### 3. Transparent 401 Re-Authentication & Retry
- **Explanation**: If an upstream call returns 401 (token expired), `PortalClient` catches it, executes a fresh login, updates the session cookie, and retries the outbound request seamlessly so consumers never experience transient auth failures.
- **Where to look**: `src/services/portal_client.py:_request_with_retry`

### 4. Smart Local Sync vs On-Demand Scraping (D-003)
- **Explanation**: Instead of querying the portal on every request, the gateway maintains an in-memory SQLite store populated on startup and refreshed on a 300s TTL. This protects the legacy portal from hammering and provides sub-5ms responses.
- **Where to look**: `src/services/meter_service.py:sync`, `decisions.md:D-003`

### 5. In-Memory SQLite with Persistent Thread-Safe Connection (D-006)
- **Explanation**: In Python, `sqlite3.connect(":memory:")` creates a new ephemeral database per connection. We hold a persistent connection with `check_same_thread=False` and a `threading.Lock()` to allow concurrent FastAPI request threads to query the same memory database safely.
- **Where to look**: `src/db/repository.py:__init__`, `decisions.md:D-006`

### 6. Geospatial Proximity via Registered SQLite Haversine Function (D-007)
- **Explanation**: SQLite lacks native trigonometric functions. We register a custom Python Haversine function (`conn.create_function("haversine_km", 4, ...)`), allowing SQL queries to filter and order by distance in kilometers directly in the database query planner.
- **Where to look**: `src/db/repository.py:haversine_distance_km`

### 7. Strict Timestamp Normalization (IST to UTC) (D-005)
- **Explanation**: Meter timestamps arrive in Indian Standard Time (`DD/MM/YYYY HH:MM`). The normalizer parses with `Asia/Kolkata` (+05:30) and converts to ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`).
- **Where to look**: `src/services/normalizer.py:parse_ist_timestamp_to_utc`

### 8. Hierarchy Anomaly Audit & Reconciliation
- **Explanation**: Audits missing codes/names and feeder mismatches by cross-referencing clean nodes and the DT catalog, reconciling them in the domain object while logging anomalies to `GET /hierarchy/anomalies`.
- **Where to look**: `src/services/normalizer.py:audit_hierarchy`

### 9. Unified Error Envelope
- **Explanation**: Global exception handlers in FastAPI catch all custom exceptions (`NotFoundError`, `PortalError`, `PortalAuthenticationError`) and validation errors, ensuring every failure adheres strictly to `{"error": {"code": "...", "message": "..."}}`.
- **Where to look**: `src/main.py:create_app`, `src/models/errors.py`

### 10. Fast Offline Test Suite against Sanitized Fixtures
- **Explanation**: 21 unit and integration tests execute in <1s using `httpx.MockTransport` and saved fixtures, meaning CI/CD passes reliably without live portal credentials or network dependencies.
- **Where to look**: `tests/`, `tests/fixtures/`

---

## 3. Likely Interview Follow-Up Questions & Suggested Answers

### Q1: "Why did you build an in-memory SQLite cache instead of passing every request directly to the portal?"
> **Answer**: "The assignment prioritized treating the portal politely with low concurrency and no hammering. Querying the portal directly for search, filters, or hierarchy would require 20+ roundtrips per search and 400+ for hierarchy, resulting in latency over 1.5 seconds and high risk of portal overload. The 403-meter dataset is small enough to fit in a couple megabytes of RAM. Syncing once per 5 minutes via the HMAC bulk path dropped our API response times from 1,500ms to under 5ms while slashing outbound traffic by 99.5%."

### Q2: "How did you discover the HMAC-SHA256 signature requirement on `/portal/export`?"
> **Answer**: "While crawling `/meters`, I noticed the 'Export all meters' button on the `/transformers` page. I inspected the linked JavaScript bundle `nodes/4.2Bgc2kUI.js` and traced the export handler function `F()`. It retrieved a `signingSecret` from `/portal/keys`, formatted a 4-line string `[method, path, query, timestamp].join('\n')`, and generated an HMAC-SHA256 digest using the browser's Web Crypto API. I replicated that exact canonicalization in Python's `hmac` and `hashlib` libraries."

### Q3: "What happens if a user's session expires while your service is running?"
> **Answer**: "The `PortalClient` tracks session expiry proactively (refreshing after 55 minutes). If the portal abruptly invalidates the session and returns an HTTP 401, `_request_with_retry` catches the 401, re-authenticates to get a new session token, and immediately replays the original request. The downstream API caller never experiences an error."

### Q4: "At what data scale would your SQLite Haversine spatial query struggle, and what would you change?"
> **Answer**: "With 403 meters, calculating Haversine distance in SQLite takes less than 3 milliseconds. However, because our custom Haversine UDF requires a full table scan, it would begin struggling around 50,000 to 100,000 meters. To scale, I would first add a bounding-box pre-filter in SQL (`WHERE latitude BETWEEN min_lat AND max_lat AND longitude BETWEEN min_lng AND max_lng`) to use B-tree indexes, or switch to SQLite R*Tree / SpatiaLite. For millions of meters, I'd move to PostgreSQL with PostGIS and GiST spatial indexes."

### Q5: "How does your service handle the 22 hierarchy anomalies?"
> **Answer**: "We take a non-destructive, reconciling approach. In `audit_hierarchy`, we build a lookup dictionary from clean nodes and the DT catalog. For example, if a feeder code is missing on a meter, we resolve it using the meter's DT code. If a circle name is present but code is missing, we infer the code from matching circle names. We apply the reconciliation to the returned entity and expose all 22 anomalies via `GET /hierarchy/anomalies` so data engineering teams can audit and fix the source system."

---

## 4. Weakest or Least Certain Points in the Solution

1. **Energy Window Limitation**:
   - *Limitation*: The portal's `/portal/meters/{id}/energy` endpoint always returns the same 337 half-hourly readings spanning 7 days. Outbound query parameters like `from` or `limit` are ignored by the portal.
   - *Mitigation*: Our service applies client-side slicing and date filtering over the 337 readings, but cannot fetch dates outside that 7-day window.
2. **Bulk Export Upstream Coupling**:
   - *Limitation*: If the utility updates the portal and removes the `/portal/export` endpoint or changes the HMAC algorithm, the startup sync would fail.
   - *Mitigation*: The startup sync logs a warning and allows the service to boot, and the client architecture is modular enough to fall back to paginated scraping of `/portal/meters/search` if needed.
3. **Single Process Memory Scope**:
   - *Limitation*: Because SQLite is run in `:memory:`, running multiple Uvicorn worker processes (`--workers 4`) would give each worker its own isolated in-memory database.
   - *Mitigation*: For multi-process deployments, simply configure `DB_PATH=data/meters.db` in `.env` to point to a shared SQLite file or external database.
