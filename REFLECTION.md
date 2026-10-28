# Engineering Reflection

## 1. What Assumptions Were Made?

1. **Read-Only Guarantees**: Assumed the legacy portal `https://urja-ops.flockenergy.tech` must never receive mutating requests or rapid polling. All architectural decisions prioritized minimal outbound traffic, polite request rates, and zero state mutation upstream.
2. **Timezone Context**: Assumed timestamps like `23/06/2026 23:30` on consumption readings are recorded in Indian Standard Time (IST, UTC+05:30) because the utility network coordinates are localized in Rajasthan/Jaipur (latitudes ~26.9, longitudes ~75.8) and field terminology conforms to Indian distribution utilities (Circle, Division, Subdivision, DT).
3. **Estate Scale (403 Meters)**: Assumed the entire active meter population is returned by `/portal/export` (403 total meters matching the search endpoint total). Because 403 meters easily fits in application memory (< 2MB of memory), we assumed an embedded in-memory SQLite store provides the optimal balance of zero operational footprint, extreme speed (< 5ms response time), and rich relational querying.
4. **Session Expiry Duration**: Inferred that the `better-auth` session token adheres to its declared `Max-Age=3600` (1 hour). We proactively refresh sessions after 55 minutes or automatically upon receiving an upstream HTTP 401.

---

## 2. Which Part Was Most Difficult and How Did It Get Unstuck?

### The Initial 403 Forbidden on Login POST
When probing the portal's `/login` route with a standard form POST, the portal immediately returned HTTP 403 with the body:
```
Cross-site POST form submissions are forbidden
```
**How it got unstuck**:
Inspecting the preload link headers on the initial HTML response revealed SvelteKit bundles (`_app/immutable/entry/start...`). SvelteKit's default form action security compares the `Origin` request header against the server's URL. Once we explicitly supplied `Origin: https://urja-ops.flockenergy.tech` and `Referer: https://urja-ops.flockenergy.tech/login`, the portal returned HTTP 200 with JSON `{"type":"redirect","status":303,"location":"/meters"}` and set the `__Secure-better-auth.session_token` cookie.

### Discovering the Cryptographic Bulk Export Path
Navigating `/meters` initially showed an empty table before client-side JS initiated `GET /portal/meters/search?q=&page=1`. Initially, retrieving all meters seemed to require 21 paginated calls, followed by 403 calls for geo coordinates and 403 calls for hierarchy lookups (over 820 HTTP requests).
By downloading and reading the client-side JavaScript bundle for `/transformers` (`nodes/4.2Bgc2kUI.js`), we discovered function `F()` which called `GET /portal/keys`, computed an HMAC-SHA256 signature using `signingSecret` over `[method, path, query, timestamp].join('\n')`, and issued `GET /portal/export?page=1`. Testing this HMAC signature unlocked the entire dataset of 403 meters with all geo and hierarchy trees in a single polite call.

---

## 3. What Mistake Was Made While Solving This?

### SQLite In-Memory Connection Drop (D-006)
During the transition from mock scripts to `SqliteRepository`, the initial implementation instantiated a new connection via `sqlite3.connect(":memory:")` inside a context manager for each method (`upsert_meters`, `query_meters`).
In SQLite, calling `connect(":memory:")` creates a distinct, ephemeral in-memory database each time. Consequently, `upsert_meters()` populated a database that evaporated as soon as the context manager closed, causing downstream unit tests to fail with `sqlite3.OperationalError: no such table: meters`.

**Resolution**:
We refactored `SqliteRepository` to maintain an open connection (`self._conn`) protected by a `threading.Lock()` across the lifetime of the repository. This resolved the issue immediately, ensuring persistent in-memory storage while guaranteeing thread safety across FastAPI worker threads.

### TestClient Lifespan Context
In our initial smoke test script, running `client = TestClient(app)` without a context manager failed to trigger FastAPI's `lifespan` hook, causing `request.app.state.meter_service` to be uninitialized (`AttributeError: 'State' object has no attribute 'meter_service'`).
Wrapping the test client in `with TestClient(app) as client:` correctly executed the lifespan startup hook, synchronizing the cache and passing all smoke tests.

---

## 4. With Another Day, What Would Be Improved?

1. **Persistent Cache on Disk**: While in-memory SQLite starts in ~500ms, storing the database in a local SQLite file (e.g. `data/meters.db`) would allow instantaneous restarts without needing to query the portal on every service reboot.
2. **Historic Energy Ingestion**: Currently, the portal only serves the default 7-day half-hourly window (337 readings) per meter via `/portal/meters/{id}/energy`. With more time, we could implement a scheduled background job to periodically poll and append readings into a time-series store (such as DuckDB or TimescaleDB) to accumulate months or years of historical consumption data.
3. **ETag / Content Hash Skip**: If the portal data has not changed across sync intervals, comparing the SHA-256 hash of the exported payload would skip database upserts entirely, minimizing CPU and memory cycles.
4. **Interactive Hierarchy Visualization**: A lightweight React or vanilla JS tree explorer embedded at `/explorer` to visualize the reconstructed electrical grid visually.

---

## 5. If Reviewing This Submission, What Would Be Criticised?

1. **Reliance on the Undocumented HMAC Export Endpoint**:
   - *Critique*: A reviewer might ask: "What if Flock Energy rotates or disables `/portal/export` or changes the HMAC canonical string format?"
   - *Defense*: The `/portal/export` endpoint was discovered directly in the production client bundle powering the official "Export all meters" UI button. However, if the export endpoint were ever decommissioned, our modular `PortalClient` could gracefully fallback to paginated scraping (`/portal/meters/search?page=N`) with minimal code changes.
2. **In-Memory Query Scope**:
   - *Critique*: For an enterprise utility with 2 million smart meters, storing all records in memory and performing Haversine math via Python SQLite UDFs would exhaust RAM and slow down spatial queries.
   - *Defense*: We deliberately right-sized for the observed 403-meter dataset. Adding PostgreSQL, PostGIS, and Redis would introduce container dependencies and setup complexity without providing user value at this scale. For larger scale, migrating to PostgreSQL with PostGIS geometry indexing is straightforward since Pydantic domain models isolate the database layer.
3. **Consumption Reading Range Limitations**:
   - *Critique*: The portal ignores query parameters on `/portal/meters/{id}/energy` and only returns the default 7-day window. Downstream clients asking for 30-day historical data only receive 7 days.
   - *Defense*: We documented this observed quirk in `PROTOCOL.md` and explicitly compute accurate aggregate statistics over whatever subset the user requests within that window.
