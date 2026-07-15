"""Simplified Garmin client using .env configuration.

Garmin auth/upload is delegated to the `garminconnect` library instead of
talking to `garth` directly, per upstream PR #14
(https://github.com/sodelalbert/Withings2Garmin/pull/14) by andrewleech,
independently confirmed working by eitanbehar's fork
(https://github.com/eitanbehar/Withings2Garmin, branch garmin-bmi-2026-working).
"""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError,
    GarminConnectTooManyRequestsError,
)

from . import paths

logger = logging.getLogger(__name__)


class GarminException(Exception):
    """Exception for Garmin API errors."""

    pass


class GarminClient:
    """Simplified Garmin client using .env configuration."""

    def __init__(self):
        # Load configuration from environment variables
        self.username = os.getenv("GARMIN_USERNAME")
        self.password = os.getenv("GARMIN_PASSWORD")

        if not self.username or not self.password:
            raise GarminException(
                "Missing required environment variables:"
                " GARMIN_USERNAME, GARMIN_PASSWORD"
            )

        # Token store location (env override -> cwd -> user data dir).
        # garminconnect loads existing tokens from here if present and falls
        # back to a credential login, persisting fresh tokens afterwards.
        self.session_file = str(paths.garmin_session_dir())
        logger.debug(f"Using Garmin session directory: {self.session_file}")

        self.client = Garmin(
            email=self.username,
            password=self.password,
            prompt_mfa=self._prompt_mfa,
        )

        # Authenticate
        self._authenticate()

    @staticmethod
    def _prompt_mfa() -> str:
        """Prompt the user for a Garmin Connect MFA code."""
        return input("MFA code: ").strip()

    def _authenticate(self):
        """Authenticate with Garmin Connect."""
        try:
            self.client.login(self.session_file)
            logger.debug("Authenticated with Garmin Connect")
        except (
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
            # garminconnect's login() re-raises a bare FileNotFoundError
            # unchanged (e.g. a stale/corrupt token store path) instead of
            # wrapping it in one of the exception types above.
            FileNotFoundError,
        ) as e:
            raise GarminException(f"Garmin authentication failed: {e}") from e

    def upload_file(
        self, file_data: bytes, filename: str = "withings_sync.fit"
    ) -> bool:
        """Upload FIT file to Garmin Connect."""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                fit_path = Path(tmpdir) / filename
                fit_path.write_bytes(file_data)
                self.client.upload_activity(str(fit_path))

            logger.debug(f"Successfully uploaded {filename} to Garmin Connect")
            return True

        except (
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
            GarminConnectInvalidFileFormatError,
            # The session can expire between construction and a later
            # upload call (e.g. a long-running sync); garminconnect raises
            # this from its internal request layer when that happens.
            GarminConnectAuthenticationError,
        ) as e:
            logger.error(f"Failed to upload file to Garmin Connect: {e}")
            return False

    def test_connection(self) -> bool:
        """Test connection to Garmin Connect."""
        try:
            full_name = self.client.get_full_name()
            logger.info(f"Connected to Garmin Connect as: {full_name}")
            return bool(full_name)
        except Exception as e:
            logger.error(f"Garmin connection test failed: {e}")
            return False

    def get_existing_weight_timestamps(
        self, start_date: datetime, end_date: datetime
    ) -> set[datetime]:
        """Timestamps of weight entries already on Garmin Connect in range.

        Best-effort: this is a safety net on top of this tool's own local
        sync tracking, not the primary dedup mechanism, so any failure here
        is logged and treated as "found nothing" rather than aborting sync.
        """
        try:
            response = self.client.get_body_composition(
                start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
            )
        except Exception as e:
            logger.warning(f"Could not check existing Garmin weight entries: {e}")
            return set()

        timestamps = set()
        for entry in (response or {}).get("dateWeightList") or []:
            raw = (
                entry.get("timestampGMT") or entry.get("timestamp") or entry.get("date")
            )
            parsed = _parse_garmin_timestamp(raw)
            if parsed is not None:
                timestamps.add(parsed)
        return timestamps

    def get_existing_blood_pressure_timestamps(
        self, start_date: datetime, end_date: datetime
    ) -> set[datetime]:
        """Timestamps of blood pressure entries already on Garmin in range.

        Best-effort, same rationale as get_existing_weight_timestamps().
        """
        try:
            response = self.client.get_blood_pressure(
                start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
            )
        except Exception as e:
            logger.warning(
                f"Could not check existing Garmin blood pressure entries: {e}"
            )
            return set()

        timestamps = set()
        for summary in (response or {}).get("measurementSummaries") or []:
            for measurement in summary.get("measurements") or []:
                parsed = _parse_garmin_timestamp(
                    measurement.get("measurementTimestampLocal")
                )
                if parsed is not None:
                    timestamps.add(parsed)
        return timestamps


def _parse_garmin_timestamp(raw) -> datetime | None:
    """Parse a Garmin API timestamp (ISO string or epoch millis) to a naive
    local datetime, matching how Withings timestamps are represented
    elsewhere in this codebase (datetime.fromtimestamp(...))."""
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        return datetime.fromtimestamp(raw / 1000)
    except (ValueError, TypeError, OSError) as e:
        logger.debug(f"Could not parse Garmin timestamp {raw!r}: {e}")
        return None
