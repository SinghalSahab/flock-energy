# Urja Meter Ops API Gateway

A robust, production-grade, documented REST API service built in front of the legacy **Urja Meter Ops** utility web portal (`https://urja-ops.flockenergy.tech`).

This service allows engineering teams and downstream software systems to query smart meter data, explore the electrical distribution network hierarchy, retrieve normalized consumption time-series, and perform geospatial proximity queries without ever interacting with or reverse engineering the legacy portal.

---

## Table of Contents
1. [Architecture & Features](#architecture--features)
2. [Project Layout](#project-layout)
3. [Quick Start & Installation](#quick-start--installation)
4. [Sample Request & Response](#sample-request--response)
5. [Key Design Decisions & Trade-Offs](#key-design-decisions--trade-offs)
6. [Hierarchy Reconciliation & Anomaly Auditing](#hierarchy-reconciliation--anomaly-auditing)
7. [Running Tests](#running-tests)
8. [What Was Intentionally Skipped](#what-was-intentionally-skipped)
9. [What I'd Improve with More Time](#what-id-improve-with-more-time)
10. [Documentation Links](#documentation-links)

---

## Architecture & Features

- **Reverse Engineered Portal Protocol**: Full automated session management for SvelteKit + `better-auth`, adhering to CSRF origin requirements and automatic re-authentication upon session expiration.
- **Bulk Cryptographic Ingestion Path**: Discovered and implemented the portal's HMAC-SHA256 signed `/portal/export` endpoint, syncing the entire estate of 403 meters, geo coordinates, and 7-level hierarchy in **2 polite requests** rather than hammering the portal with 420+ paginated calls.
- **Embedded Query & Geospatial Index**: High-performance SQLite in-memory repository with custom Haversine distance calculations for multi-attribute filtering (make, phase, status, wiring type, transformer, feeder) and spatial radius queries (`near_lat`, `near_lng`, `radius_km`).
- **Data Normalization**:
  - Time: Indian Standard Time (`DD/MM/YYYY HH:MM`) converted to strict ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`).
  - Units: Metric string conversions to IEEE floating-point numbers (`kWh`, `kVAh`, `Volts`).
  - Legacy vs v2 Unification: Normalizes both `legacy` parameter arrays and `v2` `classData` schemas into unified domain entities.
- **Network Hierarchy Reconstruction & Anomaly Detection**: Tolerates and reports real portal inconsistencies (22 empty codes/names and feeder mismatches) via `/hierarchy/anomalies`.
- **Standardized Error Envelope**: Guarantees all errors follow `{"error": {"code": "...", "message": "..."}}`. Never leaks upstream HTML or stack traces.
- **Self-Documenting OpenAPI 3.1 & Interactive Docs**: Fully typed Pydantic v2 schemas serving Swagger UI at `/docs` and Redoc at `/redoc`.

---

## Project Layout

```
.
├── src/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── health.py        # GET /health
│   │   │   ├── meters.py        # GET /meters, GET /meters/{id}, GET /meters/{id}/consumption
│   │   │   ├── hierarchy.py     # GET /hierarchy, GET /hierarchy/anomalies
│   │   │   └── cache.py         # GET /cache, POST /cache/refresh
│   │   └── dependencies.py      # Dependency injection providers
│   ├── config.py                # Pydantic Settings (.env configuration)
│   ├── db/
│   │   └── repository.py        # SQLite query engine with Haversine distance UDF
│   ├── models/
│   │   ├── errors.py            # Standardized error schema & exceptions
│   │   ├── meter.py             # Meter, DT, Geo, and Enum models
│   │   ├── consumption.py       # Consumption reading & summary models
│   │   └── hierarchy.py         # Cascading tree and anomaly models
│   ├── services/
│   │   ├── portal_client.py     # HTTP client, session manager, HMAC signer, retry logic
│   │   ├── normalizer.py        # IST->UTC, unit coercion, anomaly reconciliation
│   │   └── meter_service.py     # Caching, repository sync, domain coordinator
│   └── main.py                  # FastAPI factory, lifespan hooks, error handlers
├── tests/
│   ├── fixtures/                # Sanitized offline responses from Urja portal
│   ├── test_normalizer.py       # Normalizer unit tests
│   ├── test_portal_client.py    # PortalClient auth, retry, and HMAC tests
│   ├── test_meter_service.py    # MeterService and query engine tests
│   └── test_api.py              # End-to-end API route tests with mock client
├── openapi.json                 # Pinned OpenAPI 3.1 specification at repo root
├── PROTOCOL.md                  # Comprehensive reverse-engineered portal specification
├── flow.md                      # Code execution flow & sequence diagrams
├── decisions.md                 # Formal architectural decision log (D-001 through D-007)
├── REFLECTION.md                # Engineering reflection, assumptions, dead-ends, critique
├── HANDOVER.md                  # Interview defense guide & technical concepts
├── pyproject.toml               # Project metadata and tooling config
├── requirements.txt             # Pinned dependency manifest
└── .env.example                 # Configuration template
```

---

## Quick Start & Installation

### Prerequisites
- Python 3.11+ (tested on Python 3.13)
- `git`

### 1. Clone & Set Up Environment
```bash
git clone <repo-url> flock-energy
cd flock-energy

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Credentials
Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```ini
PORTAL_URL=https://urja-ops.flockenergy.tech
PORTAL_USERNAME=operator@urja.local
PORTAL_PASSWORD=urja-ops-2026
CACHE_TTL_SECONDS=300
PORT=8000
HOST=0.0.0.0
```

### 3. Run the API Gateway
```bash
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
On startup, the service automatically logs in to the Urja portal, downloads the bulk meter estate via cryptographic export, indexes all 403 meters into SQLite, audits network hierarchy anomalies, and begins serving traffic in ~500ms.

Open your browser to:
- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Interactive Redoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Sample Request & Response

### 1. Spatial & Multi-Attribute Query (`GET /meters`)
```bash
curl -X GET "http://localhost:8000/meters?make=HPL&near_lat=26.9389&near_lng=75.8309&radius_km=10.0&limit=1"
```
**Response (200 OK):**
```json
{
  "items": [
    {
      "id": "J100000",
      "serial_number": "SE33962",
      "make": "HPL",
      "phase": "single",
      "status": "Decommissioned",
      "install_type": "Whole Current",
      "build_version": "legacy",
      "dt_code": "DT-001",
      "location": {
        "latitude": 26.938961002479868,
        "longitude": 75.83095696146852,
        "distance_km": 0.01
      },
      "hierarchy": {
        "zone": {
          "code": "Z-01",
          "name": "Jaipur Zone 1"
        },
        "circle": {
          "code": "C-01",
          "name": "Circle 1"
        },
        "division": {
          "code": "D-01",
          "name": "Division 1"
        },
        "subdivision": {
          "code": "SD-01",
          "name": "Subdivision 1"
        },
        "substation": {
          "code": "SS-01",
          "name": "Substation 1"
        },
        "feeder": {
          "code": "F-001",
          "name": "Feeder 1"
        },
        "dt": {
          "code": "DT-001",
          "name": "Malviya Nagar DT 1"
        }
      }
    }
  ],
  "total": 62,
  "limit": 1,
  "offset": 0
}
```

### 2. Normalized Consumption Readings (`GET /meters/{id}/consumption`)
```bash
curl -X GET "http://localhost:8000/meters/J100000/consumption?limit=2"
```
**Response (200 OK):**
```json
{
  "meter_id": "J100000",
  "summary": {
    "total_readings": 2,
    "min_kwh": 48580.36,
    "max_kwh": 48580.79,
    "delta_kwh": 0.43,
    "average_voltage_volts": 225.0,
    "earliest_reading_utc": "2026-06-30T17:30:00Z",
    "latest_reading_utc": "2026-06-30T18:00:00Z"
  },
  "readings": [
    {
      "timestamp_utc": "2026-06-30T17:30:00Z",
      "timestamp_local": "30/06/2026 23:00",
      "active_energy_kwh": 48580.36,
      "apparent_energy_kvah": 52466.79,
      "voltage_phase_r_volts": 230.0
    },
    {
      "timestamp_utc": "2026-06-30T18:00:00Z",
      "timestamp_local": "30/06/2026 23:30",
      "active_energy_kwh": 48580.79,
      "apparent_energy_kvah": 52467.25,
      "voltage_phase_r_volts": 220.0
    }
  ]
}
```

### 3. Clean Error Envelope on Missing Resource (`GET /meters/INVALID_ID`)
```bash
curl -X GET "http://localhost:8000/meters/INVALID_ID"
```
**Response (404 Not Found):**
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Meter 'INVALID_ID' not found."
  }
}
```

---

## Key Design Decisions & Trade-Offs

Detailed architectural choices are logged in [`decisions.md`](decisions.md). Highlights:

| ID | Title | Choice | Reason & Trade-Off |
| :--- | :--- | :--- | :--- |
| **D-001** | Credential Isolation | `.env` strictly git-ignored; `.env.example` committed. | Zero risk of credential leaks in git history. Fresh clones require manual `.env` setup. |
| **D-002** | Technology Stack | Python 3.13 + FastAPI + Pydantic v2 + httpx. | Native async I/O, automated OpenAPI 3.1 generation, strict schema validation. |
| **D-003** | Ingestion Architecture | Smart Local Sync via Bulk Path vs On-Demand Scraping. | Ingesting via HMAC bulk export eliminates 99.5% of network roundtrips, reducing query latency from >1.5s to <5ms while protecting the legacy portal from hammering. |
| **D-004** | Extension Selection | Extensions 1, 2, and 3 (Hierarchy reconciliation, SQLite spatial index, TTL caching & auto re-login). | Solves high-value domain problems observed in Phase 1. Skipped frontend UI to focus on rock-solid API engineering. |
| **D-005** | Normalization Standards | ISO-8601 UTC timestamps, float energy metrics, uppercase/lowercase enums. | Eliminates legacy quirks for API consumers at minor parsing cost during ingestion. |
| **D-006** | SQLite Thread Safety | Persistent locked connection for in-memory SQLite. | Prevents in-memory DB drops across FastAPI threads while delivering microsecond queries. |
| **D-007** | Spatial Indexing | Custom Haversine UDF registered in SQLite. | Pushes spatial distance calculations and radius filtering into SQL query planner. |

---

## Hierarchy Reconciliation & Anomaly Auditing

During reverse-engineering of the 403 meters, we discovered that the legacy portal contains **22 data quality anomalies** across the network tree:
- **Missing Codes vs Names**: Certain circles, substations, and feeders have names (e.g. `Circle 6`, `Substation 16`, `Feeder 5`) with empty string codes (`""`), or codes (e.g. `C-01`, `F-003`) with empty string names.
- **Feeder Mismatches**: In 5 meters (`J100044`, `J100078`, `J100134`, `J100210`, `J100268`), the meter's hierarchy has an empty feeder code while the DT catalog assigns a specific feeder.

Our service cross-references the DT catalog and clean peer nodes to reconcile missing attributes automatically and exposes a dedicated audit endpoint:
```bash
curl -X GET "http://localhost:8000/hierarchy/anomalies"
```
Returns a complete ledger of all detected discrepancies, the raw reported values, and the inferred canonical values.

---

## Running Tests

The test suite runs **100% offline** against saved sanitized fixtures in `tests/fixtures/`. It does NOT require network access or live portal credentials:

```bash
# Run pytest with verbose output
.venv/bin/pytest tests -v
```

**Test Coverage:**
- `tests/test_normalizer.py`: Datetime parsing, IST to UTC conversion, numeric casting, legacy vs v2 build handling, and anomaly audit logic.
- `tests/test_portal_client.py`: Mock transport verifying SvelteKit login, Origin header verification, cookie extraction, HMAC calculation, 401 re-login retry, and 404 mapping.
- `tests/test_meter_service.py`: Caching staleness, SQLite repository querying, multi-attribute filtering, and spatial Haversine queries.
- `tests/test_api.py`: FastAPI route testing across `/health`, `/meters`, `/meters/{id}`, `/meters/{id}/consumption`, `/hierarchy`, `/hierarchy/anomalies`, `/cache/refresh`, and error envelopes.

---

## What Was Intentionally Skipped

1. **Frontend Web Client**: Skipped in favor of deeper API quality, full test coverage, and documentation. OpenAPI `/docs` provides an interactive UI.
2. **Persistent External Database (Postgres / Redis)**: An embedded SQLite repository was right-sized for 403 meters. Adding Docker/Postgres would add unnecessary operational overhead for a dataset of this scale.
3. **Write / Mutation Operations**: The assignment explicitly declared the legacy portal as READ-ONLY.

---

## What I'd Improve with More Time

1. **Scale Beyond 100k Meters**: If the utility expands to 500,000 meters, SQLite in-memory full table scans with Haversine math would degrade. We would introduce SQLite R*Tree / SpatiaLite spatial indexing or migrate to PostgreSQL with PostGIS.
2. **Dynamic Webhook / Change Detection**: Polling the HMAC export on TTL works well, but hash-comparing the bulk payload (ETag or SHA-256 fingerprint) would skip SQLite upserts if data has not changed.
3. **Readings Partitioning**: Storing historic 30-minute consumption readings in a time-series database (TimescaleDB or ClickHouse) for long-term historical analytics across years.

---

## Documentation Links

- [`PROTOCOL.md`](PROTOCOL.md) — Comprehensive reverse-engineered specification of the Urja Meter Ops portal.
- [`decisions.md`](decisions.md) — Full Architectural Decision Records (ADRs).
- [`flow.md`](flow.md) — Step-by-step execution traces and Mermaid sequence diagrams.
- [`REFLECTION.md`](REFLECTION.md) — Honest engineering reflection, assumptions, dead-ends, and critique.
- [`HANDOVER.md`](HANDOVER.md) — Interview defense preparation guide.
- [`openapi.json`](openapi.json) — Accurate OpenAPI 3.1 specification.
