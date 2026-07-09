from unittest.mock import patch

import pytest

from withings2garmin.garmin_client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminException,
)


@pytest.fixture(autouse=True)
def garmin_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GARMIN_USERNAME", "user")
    monkeypatch.setenv("GARMIN_PASSWORD", "pass")
    monkeypatch.setenv("GARMIN_SESSION_DIR", str(tmp_path / "garmin_session"))
    monkeypatch.chdir(tmp_path)


def test_missing_env_vars_raise(monkeypatch):
    monkeypatch.delenv("GARMIN_USERNAME", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    with pytest.raises(GarminException):
        GarminClient()


def test_authenticate_success(tmp_path):
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.return_value = (None, None)

        client = GarminClient()

    instance.login.assert_called_once_with(str(tmp_path / "garmin_session"))
    assert client.client is instance


def test_authenticate_failure_raises_garmin_exception():
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.side_effect = GarminConnectAuthenticationError("bad creds")

        with pytest.raises(GarminException):
            GarminClient()


def test_upload_file_success():
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.return_value = (None, None)
        client = GarminClient()

        instance.upload_activity.return_value = {}
        assert client.upload_file(b"FITDATA", "test.fit") is True
        instance.upload_activity.assert_called_once()


def test_upload_file_failure_returns_false():
    from withings2garmin.garmin_client import GarminConnectConnectionError

    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.return_value = (None, None)
        client = GarminClient()

        instance.upload_activity.side_effect = GarminConnectConnectionError("down")
        assert client.upload_file(b"FITDATA") is False


def test_upload_file_session_expired_mid_run_returns_false():
    # garminconnect's request layer raises this from upload_activity() when
    # the session has expired since login() - must not escape as an
    # unwrapped exception past this method.
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.return_value = (None, None)
        client = GarminClient()

        instance.upload_activity.side_effect = GarminConnectAuthenticationError(
            "session expired"
        )
        assert client.upload_file(b"FITDATA") is False


def test_authenticate_stale_token_store_raises_garmin_exception():
    # garminconnect's login() re-raises a bare FileNotFoundError unchanged
    # (e.g. a stale/corrupt token store path) rather than wrapping it.
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.side_effect = FileNotFoundError("no such token store")

        with pytest.raises(GarminException):
            GarminClient()


def test_test_connection_returns_full_name():
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.return_value = (None, None)
        instance.get_full_name.return_value = "Test User"
        client = GarminClient()

        assert client.test_connection() is True


def test_prompt_mfa_reads_input():
    with patch("builtins.input", return_value=" 123456 "):
        assert GarminClient._prompt_mfa() == "123456"


def test_garmin_constructed_with_mfa_prompt():
    with patch("withings2garmin.garmin_client.Garmin") as MockGarmin:
        instance = MockGarmin.return_value
        instance.login.return_value = (None, None)

        GarminClient()

        _, kwargs = MockGarmin.call_args
        assert kwargs["prompt_mfa"] == GarminClient._prompt_mfa
