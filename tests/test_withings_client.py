import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

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
            "grpid": 12345,
            "date": int(datetime(2024, 1, 1).timestamp()),
            "measures": [
                {"type": 1, "value": 8000, "unit": -2},  # weight 80.00
                {"type": 6, "value": 2000, "unit": -2},  # fat_ratio 20.00
            ],
        }
    ]
    processed = client._process_measurements(raw)

    assert len(processed) == 1
    assert processed[0]["grpid"] == "12345"
    assert processed[0]["measurements"]["weight"] == 80.0
    assert processed[0]["measurements"]["fat_ratio"] == 20.0


def test_process_measurements_falls_back_to_synthetic_id_when_grpid_missing(caplog):
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    raw = [
        {
            "date": int(datetime(2024, 1, 1).timestamp()),
            "measures": [{"type": 1, "value": 8000, "unit": -2}],
        }
    ]
    processed = client._process_measurements(raw)

    assert processed[0]["grpid"].startswith("synthetic:")
    assert "missing grpid" in caplog.text


def test_filter_unsynced_excludes_already_synced_grpids():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})
    client.tokens["synced_grpids"] = ["1"]

    measurements = [
        {"grpid": "1", "timestamp": datetime(2024, 1, 1), "measurements": {}},
        {"grpid": "2", "timestamp": datetime(2024, 1, 2), "measurements": {}},
    ]

    unsynced = client.filter_unsynced(measurements)

    assert [m["grpid"] for m in unsynced] == ["2"]


def test_mark_synced_persists_grpids():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    measurements = [
        {"grpid": "1", "timestamp": datetime(2024, 1, 1), "measurements": {}},
        {"grpid": "2", "timestamp": datetime(2024, 1, 2), "measurements": {}},
    ]
    client.mark_synced(measurements)

    assert client.tokens["synced_grpids"] == ["1", "2"]

    # Persisted to disk, not just in-memory.
    with open(client.tokens_file) as f:
        saved = json.load(f)
    assert saved["synced_grpids"] == ["1", "2"]


def test_mark_synced_with_no_measurements_is_a_noop():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})
    client.mark_synced([])
    assert "synced_grpids" not in client.tokens


def test_save_tokens_writes_via_temp_file_and_replace():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    with patch("withings2garmin.withings_client.os.replace") as mock_replace:
        client._save_tokens()

    mock_replace.assert_called_once()
    tmp_arg, target_arg = mock_replace.call_args[0]
    assert tmp_arg == f"{client.tokens_file}.tmp.{os.getpid()}"
    assert target_arg == client.tokens_file


def test_save_tokens_crash_mid_write_leaves_target_untouched():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})
    original_content = open(client.tokens_file).read()

    with patch(
        "withings2garmin.withings_client.json.dump", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            client._save_tokens()

    # Target file is exactly as it was before the failed write attempt.
    assert open(client.tokens_file).read() == original_content


def test_save_tokens_crash_mid_write_removes_stray_temp_file():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})
    tmp_path = f"{client.tokens_file}.tmp.{os.getpid()}"

    with patch(
        "withings2garmin.withings_client.json.dump", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            client._save_tokens()

    assert not os.path.exists(tmp_path)


def test_save_tokens_survives_a_stale_leftover_temp_file():
    # A prior crash could have left a same-named temp file behind (e.g. PID
    # reuse across reboots); a fresh save must not be blocked by it.
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})
    tmp_path = f"{client.tokens_file}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        f.write("stale leftover content")

    client.tokens["last_sync"] = 12345
    client._save_tokens()

    with open(client.tokens_file) as f:
        assert json.load(f)["last_sync"] == 12345


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


def test_get_measurements_retries_on_connection_error_then_succeeds():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    success = MagicMock(json=lambda: {"status": 0, "body": {"measuregrps": []}})
    with (
        patch(
            "withings2garmin.withings_client.requests.post",
            side_effect=[requests.exceptions.ConnectionError("boom"), success],
        ) as mock_post,
        patch("time.sleep"),
    ):
        result = client.get_measurements(datetime(2024, 1, 1), datetime(2024, 1, 2))

    assert result == []
    assert mock_post.call_count == 2


def test_get_measurements_gives_up_after_max_attempts():
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    with (
        patch(
            "withings2garmin.withings_client.requests.post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ) as mock_post,
        patch("time.sleep"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            client.get_measurements(datetime(2024, 1, 1), datetime(2024, 1, 2))

    assert mock_post.call_count == 3


def test_get_measurements_does_not_retry_on_withings_status_error():
    # A non-zero Withings status is an auth/logic error, not transient -
    # retrying it wastes time and won't change the outcome.
    client = _client_with_tokens({"access_token": "a", "refresh_token": "r"})

    with (
        patch("withings2garmin.withings_client.requests.post") as mock_post,
        patch("time.sleep") as mock_sleep,
    ):
        mock_post.return_value = MagicMock(json=lambda: {"status": 1})
        with pytest.raises(WithingsException):
            client.get_measurements(datetime(2024, 1, 1), datetime(2024, 1, 2))

    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()
