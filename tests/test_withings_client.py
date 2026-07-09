import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from withings2garmin.withings_client import WithingsClient, WithingsException


@pytest.fixture(autouse=True)
def withings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WITHINGS_CLIENT_ID", "client-id")
    monkeypatch.setenv("WITHINGS_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("WITHINGS_TOKENS_FILE", str(tmp_path / "withings_tokens.json"))
    monkeypatch.chdir(tmp_path)


def _client_with_tokens(tokens):
    with open(os.environ["WITHINGS_TOKENS_FILE"], "w") as f:
        json.dump(tokens, f)
    with patch("withings2garmin.withings_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            json=lambda: {
                "status": 0,
                "body": {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "userid": "u1",
                },
            }
        )
        return WithingsClient()


def test_missing_env_vars_raise(monkeypatch):
    monkeypatch.delenv("WITHINGS_CLIENT_ID", raising=False)
    monkeypatch.delenv("WITHINGS_CLIENT_SECRET", raising=False)
    with pytest.raises(WithingsException):
        WithingsClient()


def test_ensure_authenticated_prompts_for_auth_code_when_no_tokens():
    with (
        patch("builtins.input", return_value="the-auth-code"),
        patch("withings2garmin.withings_client.requests.post") as mock_post,
    ):
        mock_post.return_value = MagicMock(
            json=lambda: {
                "status": 0,
                "body": {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "userid": "u1",
                },
            }
        )
        client = WithingsClient()

    assert client.tokens["access_token"] == "access"
    assert client.tokens["auth_code"] == "the-auth-code"


def test_ensure_authenticated_reuses_saved_tokens():
    client = _client_with_tokens(
        {"access_token": "existing", "refresh_token": "existing-refresh"}
    )
    assert client.tokens["access_token"] == "new-access"


def test_get_auth_code_raises_on_empty_input():
    with patch("builtins.input", return_value="   "):
        client = WithingsClient.__new__(WithingsClient)
        client.client_id = "id"
        client.callback_url = "http://localhost/callback"
        with pytest.raises(WithingsException):
            client._get_auth_code()


def test_process_measurements_maps_known_types():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    raw = [
        {
            "date": int(datetime(2024, 1, 1).timestamp()),
            "measures": [
                {"type": 1, "value": 8000, "unit": -2},  # weight 80.00
                {"type": 6, "value": 2000, "unit": -2},  # fat_ratio 20.00
            ],
        }
    ]
    processed = client._process_measurements(raw)

    assert len(processed) == 1
    assert processed[0]["measurements"]["weight"] == 80.0
    assert processed[0]["measurements"]["fat_ratio"] == 20.0


def test_get_measurements_raises_on_error_status():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    with patch("withings2garmin.withings_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(json=lambda: {"status": 1})
        with pytest.raises(WithingsException):
            client.get_measurements(datetime(2024, 1, 1), datetime(2024, 1, 2))


def test_get_height_raises_on_error_status():
    # get_height() must raise like get_measurements() does for the identical
    # failure signature, rather than silently returning None - indistinguish-
    # able from "no height recorded" and previously logged nowhere.
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    with patch("withings2garmin.withings_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(json=lambda: {"status": 1})
        with pytest.raises(WithingsException):
            client.get_height()


def test_get_height_returns_latest_value():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    with patch("withings2garmin.withings_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            json=lambda: {
                "status": 0,
                "body": {
                    "measuregrps": [
                        {
                            "date": int(datetime(2023, 1, 1).timestamp()),
                            "measures": [{"type": 4, "value": 175, "unit": -2}],
                        },
                        {
                            "date": int(datetime(2024, 1, 1).timestamp()),
                            "measures": [{"type": 4, "value": 180, "unit": -2}],
                        },
                    ]
                },
            }
        )
        height = client.get_height()

    assert height == pytest.approx(1.80)


def test_get_last_sync_and_set_last_sync():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    client.set_last_sync()
    assert client.get_last_sync() == client.tokens["last_sync"]
