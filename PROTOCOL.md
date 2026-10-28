# Urja Meter Ops Portal: Reverse Engineered Protocol Specification

This document details the observed and inferred behavior of the legacy **Urja Meter Ops** portal (`https://urja-ops.flockenergy.tech`). Every technical claim is labeled as either **[Observed]** (directly verified via HTTP probe or client bundle analysis) or **[Inferred]** (deduced from consistent architectural patterns or error responses).

---

## 1. Authentication & Session Management

### 1.1 Login Mechanism
- **Endpoint:** `POST /login` **[Observed]**
- **Content-Type:** `application/x-www-form-urlencoded` or standard form data **[Observed]**
- **Fields:**
  - `email`: string (e.g., `operator@urja.local`)
  - `password`: string
- **Required Headers:**
  - `Origin: https://urja-ops.flockenergy.tech` **[Observed]**
  - *(Note: Without the `Origin` header matching the host, the server immediately rejects the request with HTTP 403 and body `Cross-site POST form submissions are forbidden` due to SvelteKit's built-in CSRF mitigation)* **[Observed]**
- **Success Response:**
  - **Status Code:** `200 OK` (SvelteKit action standard) **[Observed]**
  - **Content-Type:** `application/json` **[Observed]**
  - **Body:** `{"type":"redirect","status":303,"location":"/meters"}` **[Observed]**
  - **Cookie Set:**
    ```http
    Set-Cookie: __Secure-better-auth.session_token=<token_id>.<signature>; Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax
    ```
    **[Observed]**
- **Invalid Credentials Response:**
  - **Status Code:** `200 OK` **[Observed]**
  - **Content-Type:** `application/json` **[Observed]**
  - **Body:** `{"type":"failure","status":401,"data":"[{\"email\":1,\"error\":2},\"operator@urja.local\",\"Invalid email or password.\"]"}` **[Observed]**

### 1.2 Session Lifecycle & Invalidation
- **Authentication Framework:** `better-auth` running on SvelteKit. **[Observed]**
- **Token Duration:** `Max-Age=3600` (1 hour from issue). **[Observed]**
- **Session Maintenance:** Client must supply `Cookie: __Secure-better-auth.session_token=...` on all subsequent requests. **[Observed]**
- **Expired / Missing Session on API endpoints:**
  - Status: `401 Unauthorized` **[Observed]**
  - Content-Type: `application/json` **[Observed]**
  - Body: `{"error":"unauthorized","message":"A valid session is required."}` **[Observed]**
- **Expired / Missing Session on UI routes:**
  - Status: `302 Found` with `Location: /login` **[Observed]**
- **Sign-Out Endpoint:** `POST /api/auth/sign-out` **[Observed in JS bundle `nodes/2.dJQ2wm_1.js`]**

---

## 2. API Endpoints & Routes

The portal exposes both frontend SvelteKit pages and underlying JSON API routes under `/portal/*`.

### 2.1 Meter Search (`GET /portal/meters/search`)
- **Method:** `GET` **[Observed]**
- **Query Parameters:**
  - `q`: string (search term matching meter ID or serial number, default empty) **[Observed]**
  - `page`: integer (1-indexed, default 1) **[Observed]**
- **Page Size:** Fixed at 20 items per page **[Observed in code & response]**
- **Sample Request:**
  ```http
  GET /portal/meters/search?q=&page=1 HTTP/1.1
  Host: urja-ops.flockenergy.tech
  Cookie: __Secure-better-auth.session_token=...
  ```
- **Sample Response:**
  ```json
  {
    "data": [
      {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "dtCode": "DT-001"
      }
    ],
    "total": 403,
    "page": 1,
    "pageSize": 20
  }
  ```
  **[Observed]**

### 2.2 Distribution Transformers (`GET /portal/dts`)
- **Method:** `GET` **[Observed]**
- **Query Parameters:**
  - `page`: integer (1-indexed) **[Observed]**
- **Page Size:** Fixed at 20 items per page (total 40 DTs across 2 pages) **[Observed]**
- **Sample Response:**
  ```json
  {
    "data": [
      {
        "code": "DT-001",
        "name": "Malviya Nagar DT 1",
        "feederCode": "F-001",
        "capacityKva": 100
      }
    ],
    "total": 40,
    "page": 1,
    "pageSize": 20
  }
  ```
  **[Observed]**

### 2.3 Bulk Cryptographic Export (`GET /portal/export`)
The portal provides an efficient bulk export endpoint used by the "Export all meters" UI button on `/transformers`.
- **Method:** `GET` **[Observed]**
- **Prerequisite Key Retrieval:** `GET /portal/keys` returns `{"data": {"signingSecret": "<secret>"}}` **[Observed]**
- **HMAC Authentication:**
  - Algorithm: `HMAC-SHA256` **[Observed in `nodes/4.2Bgc2kUI.js`]**
  - Canonical String:
    ```
    <METHOD>\n<PATH>\n<QUERY>\n<UNIX_TIMESTAMP>
    ```
    Example:
    ```
    GET
    /portal/export
    page=1
    1730168000
    ```
  - Required Request Headers:
    - `x-timestamp`: string (current UTC Unix timestamp in seconds) **[Observed]**
    - `x-signature`: hex-encoded HMAC-SHA256 digest of the canonical string using `signingSecret` **[Observed]**
- **Payload Coverage:** Returns **all 403 meters** in a single payload, complete with technical specs, geo-coordinates, and the complete 7-level electrical hierarchy! **[Observed]**
- **Sample Export Item:**
  ```json
  {
    "meterId": "J100000",
    "serialNo": "SE33962",
    "make": "HPL",
    "phaseType": "single",
    "installStatus": "Decommissioned",
    "installType": "Whole Current",
    "build": "legacy",
    "dtCode": "DT-001",
    "hierarchy": {
      "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
      "circle": {"name": "Circle 1", "code": "C-01"},
      "division": {"name": "Division 1", "code": "D-01"},
      "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
      "substation": {"name": "Substation 1", "code": "SS-01"},
      "feeder": {"name": "Feeder 1", "code": "F-001"},
      "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"}
    },
    "geo": {
      "lat": 26.938961002479868,
      "lng": 75.83095696146852
    }
  }
  ```
  **[Observed]**

### 2.4 Meter Geographic Location (`GET /portal/meters/{meterId}/geo`)
- **Method:** `GET` **[Observed]**
- **Response Format:**
  ```json
  {
    "data": {
      "latitude": "26.938961002479868",
      "longitude": "75.83095696146852"
    }
  }
  ```
  **[Observed]**
- **Status for Non-Existent Meter:** `404 Not Found` with `{"error":"not_found","message":"Meter not found"}` **[Observed]**

### 2.5 Meter Consumption Readings (`GET /portal/meters/{meterId}/energy`)
- **Method:** `GET` **[Observed]**
- **Query Parameters:** Query parameters (e.g. `limit`, `from`, `window`) are ignored by the portal server. **[Observed]**
- **Data Window:** Returns a fixed 7-day interval of 30-minute intervals (337 total readings). **[Observed]**
- **Sample Reading:**
  ```json
  {
    "timestamp": "23/06/2026 23:30",
    "kwh": "48438.74",
    "kvah": "52313.84",
    "voltR": "226"
  }
  ```
  **[Observed]**
- **Quirk - Timestamp Format:** Format is Indian Standard `DD/MM/YYYY HH:MM` (e.g. `23/06/2026 23:30`) in local time (+05:30). **[Observed]**
- **Quirk - String Numbers:** Numeric values (`kwh`, `kvah`, `voltR`) are serialized as strings. **[Observed]**

### 2.6 Meter Detail UI & SvelteKit Data (`GET /meters/{meterId}/__data.json`)
The portal does not have a `/portal/meters/{meterId}` JSON route (returns 404). Details are delivered via SvelteKit server load:
- **Build Types:** The dataset contains two distinct architectures:
  1. `legacy` build (238 meters): returns an array of name-value pairs `data: [{"parameterName": "Meter ID", "parameterValue": "..."}, ...]` **[Observed]**
  2. `v2` build (165 meters): returns a serialized JSON string in `classData: "{\"installed_meter\": {\"MeterId\": \"...\", ...}}"` **[Observed]**

---

## 3. Data Shapes & Normalization Requirements

| Portal Field | Legacy Shape | Target Normalized API Shape | Rationale |
| :--- | :--- | :--- | :--- |
| `meterId` | string (e.g. `J100000`) | `id`: string | Standard REST resource identifier |
| `serialNo` | string (e.g. `SE33962`) | `serial_number`: string | Pythonic snake_case |
| `make` | string (HPL, L&T, Genus, Allied, Secure) | `make`: string | Standardized string |
| `phaseType` | `single` or `three` | `phase`: `single` \| `three` | Clean enum |
| `installStatus` | `Installed`, `Decommissioned`, `Faulty` | `status`: enum | Consistent casing |
| `installType` | `Whole Current`, `CT Operated` | `install_type`: enum | Clean domain model |
| `build` | `legacy`, `v2` | `build_version`: string | Preserved for traceability |
| `dtCode` | `DT-001` | `distribution_transformer_id`: string | Explicit relation |
| `timestamp` | `DD/MM/YYYY HH:MM` (e.g. `23/06/2026 23:30`) | ISO-8601 UTC string (e.g. `2026-06-23T18:00:00Z`) | Standard UTC timestamp |
| `kwh` | string `"48438.74"` | `active_energy_kwh`: float `48438.74` | Correct numeric type |
| `kvah` | string `"52313.84"` | `apparent_energy_kvah`: float `52313.84` | Correct numeric type |
| `voltR` | string `"226"` | `voltage_phase_r_volts`: float `226.0` | Correct numeric type |
| `geo.lat`, `geo.lng` | string/float (e.g. `26.93896...`) | `latitude`: float, `longitude`: float | Floats for spatial indexing |

---

## 4. Hierarchy Anomalies & Inconsistencies

During our comprehensive inspection of all 403 meters and 40 DTs across the network, we detected the following real-world anomalies:

1. **Feeder Code Discrepancies (5 Meters):**
   - In meters `J100044`, `J100078`, `J100134`, `J100210`, `J100268`, the meter's `hierarchy.feeder.code` is an empty string `""`, while the feeder's name is present (e.g. `'Feeder 5'`) and the DT catalog specifies the active feeder code (e.g. `F-005`). **[Observed]**
2. **Missing Hierarchy Codes vs Names (22 Nodes):**
   - Certain nodes supply a name but have empty string codes (e.g., `Circle 6` with code `""`, `Substation 16` with code `""`).
   - Conversely, other nodes supply codes but empty string names (e.g., `C-01` with name `""`, `F-003` with name `""`). **[Observed]**
3. **Reconciliation Strategy:**
   - The API wrapper service must reconstruct the canonical hierarchy tree by cross-referencing DT codes and feeder lookups.
   - Any surviving inconsistencies or missing attributes must be flagged in an explicit `anomalies` list rather than crashing or returning blank values. **[Inferred]**

---

## 5. Bulk Path Recommendation

The portal provides two ways to access meter data:
1. **Interactive Pagination:** `GET /portal/meters/search?page=N` (requires 21 HTTP roundtrips, plus 403 subsequent roundtrips to retrieve geo and hierarchy details = 424 requests total).
2. **Bulk Signed Export:** `GET /portal/keys` followed by HMAC-signed `GET /portal/export?page=1` (requires **2 requests total** to get all 403 meters, all geo coordinates, and all hierarchy nodes).

**Engineering Recommendation:**
We strongly recommend utilizing the bulk cryptographic export path as the primary ingestion/indexing mechanism. This adheres strictly to the assignment's "be polite: low concurrency, small delays, no hammering" constraint, reducing network roundtrips by **99.5%** (from 424 requests to 2 requests) while delivering 100% data fidelity.
