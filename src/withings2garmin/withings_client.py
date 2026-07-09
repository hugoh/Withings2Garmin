"""Simplified Withings client using .env configuration."""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import paths

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
GETMEAS_URL = "https://wbsapi.withings.net/measure?action=getmeas"

# Shared Withings developer-app credentials, used whenever
# WITHINGS_CLIENT_ID/WITHINGS_CLIENT_SECRET aren't set via env/.env - lets
# this fork be used out of the box without everyone registering their own
# Withings app. Setting your own via WITHINGS_CLIENT_ID/WITHINGS_CLIENT_SECRET
# is optional and overrides these. Not a secret in the traditional sense:
# this is a shared, rate-limited app registration meant for exactly this
# kind of reuse (same pattern as upstream jaroslawhartman/withings-sync,
# whose callback page this project's default WITHINGS_CALLBACK_URL already
# points at).
DEFAULT_CLIENT_ID = "ac5f36d9fb0b8a4f05f340fc86e77b7cd21ecd551ca0cc3ed465303637ed82ea"
DEFAULT_CLIENT_SECRET = (
    "56a69ccff7ab4c3c17e63bea82e1f2b181ea1154390609019f37fe917a428d65"
)

# Retry only network-level failures (connection refused, DNS, timeout) -
# not Withings' own status != 0 responses, which are typically auth/logic
# errors (wrong credentials, expired token) that a retry won't fix.
_retry_on_transient_network_errors = retry(
    retry=retry_if_exception_type(
        (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class WithingsException(Exception):
    """Exception for Withings API errors."""

    pass


class WithingsClient:
    """Simplified Withings client using .env configuration."""

    def __init__(self):
        # Load configuration from environment variables, falling back to
        # the shared DEFAULT_CLIENT_ID/DEFAULT_CLIENT_SECRET if unset.
        self.client_id = os.getenv("WITHINGS_CLIENT_ID") or DEFAULT_CLIENT_ID
        self.client_secret = (
            os.getenv("WITHINGS_CLIENT_SECRET") or DEFAULT_CLIENT_SECRET
        )
        self.callback_url = os.getenv(
            "WITHINGS_CALLBACK_URL", "http://localhost:8080/callback"
        )

        if not self.client_id or not self.client_secret:
            raise WithingsException(
                "Missing Withings API credentials: set WITHINGS_CLIENT_ID/"
                "WITHINGS_CLIENT_SECRET (env or .env), or DEFAULT_CLIENT_ID/"
                "DEFAULT_CLIENT_SECRET in withings_client.py"
            )

        # User tokens file location (env override -> cwd -> user data dir)
        self.tokens_file = str(paths.withings_tokens_file())
        logger.debug(f"Using Withings tokens file: {self.tokens_file}")
        self.tokens = self._load_tokens()

        # Ensure we have valid tokens
        self._ensure_authenticated()

    def _load_tokens(self) -> Dict:
        """Load tokens from file."""
        try:
            with open(self.tokens_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_tokens(self):
        """Save tokens to file.

        Writes to a temp file and atomically renames it onto the target
        path, rather than writing the target directly - a crash or power
        loss mid-write can never leave a truncated/corrupt tokens file.
        The PID suffix means two processes never collide on the same temp
        file name even without the lock added elsewhere.
        """
        tmp_path = f"{self.tokens_file}.tmp.{os.getpid()}"
        try:
            with open(tmp_path, "w") as f:
                json.dump(self.tokens, f, indent=2)
            os.replace(tmp_path, self.tokens_file)
        except Exception:
            # Don't leave a stray temp file behind on a write failure - the
            # target path itself is never touched in this branch.
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _ensure_authenticated(self):
        """Ensure we have valid authentication tokens."""
        if not self.tokens.get("access_token"):
            if not self.tokens.get("auth_code"):
                self.tokens["auth_code"] = self._get_auth_code()
            self._get_access_token()

        # Try to refresh token
        self._refresh_access_token()
        self._save_tokens()

    def _get_auth_code(self) -> str:
        """Get authorization code from user."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "state": "OK",
            "scope": "user.metrics",
            "redirect_uri": self.callback_url,
        }

        url = AUTHORIZE_URL + "?" + "&".join([f"{k}={v}" for k, v in params.items()])

        logger.info(
            "\n"
            + "=" * 60
            + "\nWITHINGS AUTHORIZATION REQUIRED\n"
            + "=" * 60
            + "\nOpen this URL in your browser and copy the authorization code:"
            + f"\n\n{url}\n"
            + "\nYou have 30 seconds to complete this process!\n"
            + "=" * 60
        )

        auth_code = input("Enter authorization code: ").strip()
        if not auth_code:
            raise WithingsException("No authorization code provided")

        return auth_code

    @_retry_on_transient_network_errors
    def _get_access_token(self):
        """Exchange authorization code for access token."""
        params = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": self.tokens["auth_code"],
            "redirect_uri": self.callback_url,
        }

        response = requests.post(TOKEN_URL, params=params)
        data = response.json()

        if data.get("status") != 0:
            raise WithingsException(f"Token request failed: {data}")

        body = data.get("body", {})
        self.tokens.update(
            {
                "access_token": body.get("access_token"),
                "refresh_token": body.get("refresh_token"),
                "user_id": body.get("userid"),
            }
        )

        logger.info("Successfully obtained access token")

    @_retry_on_transient_network_errors
    def _refresh_access_token(self):
        """Refresh the access token."""
        if not self.tokens.get("refresh_token"):
            return

        params = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.tokens["refresh_token"],
        }

        response = requests.post(TOKEN_URL, params=params)
        data = response.json()

        if data.get("status") == 0:
            body = data.get("body", {})
            self.tokens.update(
                {
                    "access_token": body.get("access_token"),
                    "refresh_token": body.get("refresh_token"),
                    "user_id": body.get("userid"),
                }
            )
            logger.info("Successfully refreshed access token")
        else:
            logger.warning(f"Token refresh failed: {data}")

    @_retry_on_transient_network_errors
    def get_measurements(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Get measurements from Withings API."""
        params = {
            "access_token": self.tokens["access_token"],
            "category": 1,  # All measurements
            "startdate": int(start_date.timestamp()),
            "enddate": int(end_date.timestamp()),
        }

        response = requests.post(GETMEAS_URL, params=params)
        data = response.json()

        if data.get("status") != 0:
            raise WithingsException(f"Measurements request failed: {data}")

        measurements = data.get("body", {}).get("measuregrps", [])
        logger.info(f"Retrieved {len(measurements)} measurement groups")

        return self._process_measurements(measurements)

    @_retry_on_transient_network_errors
    def get_height(self) -> Optional[float]:
        """Get user's height."""
        params = {
            "access_token": self.tokens["access_token"],
            "meastype": 4,  # Height type
            "category": 1,
        }

        response = requests.post(GETMEAS_URL, params=params)
        data = response.json()

        if data.get("status") != 0:
            raise WithingsException(f"Height request failed: {data}")

        measurements = data.get("body", {}).get("measuregrps", [])
        if not measurements:
            return None

        # Get the latest height measurement
        latest_height = None
        latest_date = None

        for group in measurements:
            for measure in group.get("measures", []):
                if measure.get("type") == 4:  # Height
                    value = measure["value"] * (10 ** measure["unit"])
                    date = datetime.fromtimestamp(group["date"])

                    if latest_date is None or date > latest_date:
                        latest_height = value
                        latest_date = date

        return latest_height

    def _process_measurements(self, raw_measurements: List[Dict]) -> List[Dict]:
        """Process raw measurements into structured format."""
        processed = []

        for group in raw_measurements:
            timestamp = datetime.fromtimestamp(group["date"])
            measurements = {}

            for measure in group.get("measures", []):
                value = measure["value"] * (10 ** measure["unit"])
                measure_type = measure["type"]

                # Map measurement types to readable names
                type_mapping = {
                    1: "weight",
                    4: "height",
                    5: "fat_free_mass",
                    6: "fat_ratio",
                    8: "fat_mass_weight",
                    9: "diastolic_bp",
                    10: "systolic_bp",
                    11: "heart_rate",
                    12: "temperature",
                    76: "muscle_mass",
                    77: "hydration",
                    88: "bone_mass",
                }

                if measure_type in type_mapping:
                    measurements[type_mapping[measure_type]] = round(value, 2)

            if measurements:
                processed.append(
                    {
                        "grpid": self._group_id(group),
                        "timestamp": timestamp,
                        "measurements": measurements,
                    }
                )

        return processed

    def _group_id(self, group: Dict) -> str:
        """Stable unique ID for a measurement group, for dedup tracking."""
        grpid = group.get("grpid")
        if grpid is not None:
            return str(grpid)

        # Withings' API contract documents grpid as always present; this is
        # a defensive fallback in case a response ever omits it, so dedup
        # tracking degrades to "less precise" rather than crashing.
        types = ",".join(sorted(str(m["type"]) for m in group.get("measures", [])))
        synthetic_id = f"synthetic:{group.get('date')}:{types}"
        logger.warning(
            f"Measurement group missing grpid, using synthetic ID: {synthetic_id}"
        )
        return synthetic_id

    def filter_unsynced(self, measurements: List[Dict]) -> List[Dict]:
        """Return only measurements not already marked as synced to Garmin."""
        synced = set(self.tokens.get("synced_grpids", []))
        return [m for m in measurements if m["grpid"] not in synced]

    def mark_synced(self, measurements: List[Dict]):
        """Record measurements as synced to Garmin, so future runs skip them."""
        if not measurements:
            return
        synced = set(self.tokens.get("synced_grpids", []))
        synced.update(m["grpid"] for m in measurements)
        self.tokens["synced_grpids"] = sorted(synced)
        self._save_tokens()

    def get_last_sync(self) -> int:
        """Get last sync timestamp."""
        return self.tokens.get(
            "last_sync", int(time.time()) - 86400
        )  # Default to 24h ago

    def set_last_sync(self):
        """Set last sync timestamp to now."""
        self.tokens["last_sync"] = int(time.time())
        self._save_tokens()
        logger.info("Updated last sync timestamp")
