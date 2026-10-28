import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from src.models.errors import NotFoundError, PortalAuthenticationError, PortalError

logger = logging.getLogger("portal_client")


class PortalClient:
    """HTTP client interacting with Urja Meter Ops legacy portal.

    Handles SvelteKit CSRF origin requirements, session token persistence,
    automatic re-authentication on 401, HMAC-SHA256 request signing,
    timeouts, and polite exponential backoff.
    """

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: float = 15.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session_token: Optional[str] = None
        self._session_expiry: float = 0.0

        # Allow passing an injected client for testing/mocking
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=self.timeout,
            headers={"User-Agent": "Urja-API-Gateway/1.0"}
        )

    def is_authenticated(self) -> bool:
        return bool(self._session_token and time.time() < self._session_expiry)

    def login(self) -> None:
        """Authenticate with portal using configured credentials."""
        if not self.username or not self.password:
            raise PortalAuthenticationError("Missing PORTAL_USERNAME or PORTAL_PASSWORD in configuration")

        login_url = f"{self.base_url}/login"
        headers = {
            "Origin": self.base_url,
            "Referer": login_url,
        }
        data = {
            "email": self.username,
            "password": self.password,
        }

        logger.info("Authenticating with portal at %s as %s", login_url, self.username)
        try:
            resp = self.client.post(login_url, data=data, headers=headers)
        except httpx.RequestError as exc:
            logger.error("Network error during login: %s", exc)
            raise PortalError(f"Failed to connect to portal during login: {exc}") from exc

        # SvelteKit returns 200 with JSON payload
        if resp.status_code != 200:
            logger.error("Login failed with unexpected status code %s", resp.status_code)
            raise PortalAuthenticationError(f"Portal returned status {resp.status_code} on login")

        try:
            body = resp.json()
        except Exception:
            body = {}

        if body.get("type") == "failure":
            logger.error("Login rejected by portal: invalid credentials")
            raise PortalAuthenticationError("Invalid portal credentials")

        # Extract session token cookie
        token = self.client.cookies.get("__Secure-better-auth.session_token")
        if not token:
            # Check response Set-Cookie header directly if client cookie jar missed it
            set_cookies = resp.headers.get_list("set-cookie")
            for sc in set_cookies:
                if "__Secure-better-auth.session_token=" in sc:
                    parts = sc.split(";", 1)[0]
                    token = parts.split("=", 1)[1]
                    self.client.cookies.set("__Secure-better-auth.session_token", token)
                    break

        if not token:
            logger.error("Login succeeded but session token cookie was not found in response")
            raise PortalAuthenticationError("Session token missing from login response")

        self._session_token = token
        # Portal sets Max-Age=3600; use 3300s buffer for proactive refresh
        self._session_expiry = time.time() + 3300
        logger.info("Successfully authenticated. Session valid for ~55 minutes.")

    def _request_with_retry(
        self,
        method: str,
        path: str,
        query: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
        can_retry_auth: bool = True,
    ) -> httpx.Response:
        """Execute HTTP request with automatic re-auth on 401 and exponential backoff on 5xx."""
        if not self.is_authenticated():
            self.login()

        url = f"{self.base_url}{path}"
        req_headers = dict(headers or {})

        delay = 0.5
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.client.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=req_headers,
                )

                # Check if session expired upstream
                if resp.status_code == 401 and can_retry_auth:
                    logger.warning("Portal responded with 401 Unauthorized. Refreshing session...")
                    self.login()
                    # Retry once with renewed session
                    return self._request_with_retry(
                        method=method,
                        path=path,
                        query=query,
                        params=params,
                        headers=headers,
                        max_retries=1,
                        can_retry_auth=False,
                    )

                if resp.status_code == 404:
                    raise NotFoundError(f"Resource at '{path}' was not found upstream")

                if resp.status_code in (500, 502, 503, 504) and attempt < max_retries:
                    logger.warning("Upstream %s on %s (attempt %d/%d). Retrying in %.1fs...", resp.status_code, path, attempt, max_retries, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue

                if resp.status_code >= 400:
                    raise PortalError(f"Upstream portal returned error status {resp.status_code}")

                return resp

            except httpx.RequestError as exc:
                if attempt < max_retries:
                    logger.warning("Request failed (%s) on %s. Retrying in %.1fs...", exc, path, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.error("Request failed after %d attempts: %s", max_retries, exc)
                raise PortalError(f"Upstream connection failed: {exc}") from exc

        raise PortalError(f"Exceeded max retries calling {path}")

    def get_signing_key(self) -> str:
        """Retrieve HMAC signing secret from /portal/keys."""
        resp = self._request_with_retry("GET", "/portal/keys")
        data = resp.json()
        secret = data.get("data", {}).get("signingSecret")
        if not secret:
            raise PortalError("Portal keys endpoint did not return signingSecret")
        return secret

    def export_all_meters(self) -> List[Dict[str, Any]]:
        """Fetch complete meter estate via cryptographic HMAC signed export endpoint."""
        secret = self.get_signing_key()
        path = "/portal/export"
        query = "page=1"
        method = "GET"
        timestamp = str(int(time.time()))

        canonical_string = f"{method}\n{path}\n{query}\n{timestamp}"
        signature = hmac.new(
            secret.encode("utf-8"),
            canonical_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "x-timestamp": timestamp,
            "x-signature": signature,
        }

        logger.info("Executing HMAC bulk export request...")
        resp = self._request_with_retry(method, f"{path}?{query}", headers=headers)
        data = resp.json()
        meters = data.get("data", [])
        logger.info("Successfully exported %d meters from portal", len(meters))
        return meters

    def get_distribution_transformers(self, page: int = 1) -> Dict[str, Any]:
        """Fetch page of distribution transformers from /portal/dts."""
        resp = self._request_with_retry("GET", f"/portal/dts?page={page}")
        return resp.json()

    def get_all_distribution_transformers(self) -> List[Dict[str, Any]]:
        """Fetch all DTs by traversing pages."""
        dts = []
        page = 1
        while True:
            payload = self.get_distribution_transformers(page=page)
            items = payload.get("data", [])
            dts.extend(items)
            total = payload.get("total", 0)
            page_size = payload.get("pageSize", 20)
            if page * page_size >= total or not items:
                break
            page += 1
        return dts

    def get_meter_geo(self, meter_id: str) -> Dict[str, Any]:
        """Fetch geo coordinates for a specific meter from /portal/meters/{meter_id}/geo."""
        resp = self._request_with_retry("GET", f"/portal/meters/{meter_id}/geo")
        return resp.json().get("data", {})

    def get_meter_energy(self, meter_id: str) -> List[Dict[str, Any]]:
        """Fetch consumption readings for a specific meter from /portal/meters/{meter_id}/energy."""
        resp = self._request_with_retry("GET", f"/portal/meters/{meter_id}/energy")
        return resp.json().get("data", [])
