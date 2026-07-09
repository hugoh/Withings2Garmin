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
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError,
    GarminConnectTooManyRequestsError,
)

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

        # Token store location - store in project directory. garminconnect
        # (via garth) loads existing tokens from here if present and falls
        # back to a credential login, persisting fresh tokens afterwards.
        self.session_file = ".garmin_session"

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
            logger.info("Authenticated with Garmin Connect")
        except (
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        ) as e:
            raise GarminException(f"Garmin authentication failed: {e}")

    def upload_file(
        self, file_data: bytes, filename: str = "withings_sync.fit"
    ) -> bool:
        """Upload FIT file to Garmin Connect."""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                fit_path = Path(tmpdir) / filename
                fit_path.write_bytes(file_data)
                self.client.upload_activity(str(fit_path))

            logger.info(f"Successfully uploaded {filename} to Garmin Connect")
            return True

        except (
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
            GarminConnectInvalidFileFormatError,
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
