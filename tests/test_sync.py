import argparse
import json
from datetime import datetime
from unittest.mock import patch

from withings2garmin.garmin_client import GarminException
from withings2garmin.sync import (
    convert_to_fit,
    load_env_file,
    save_measurements_json,
    sync_data,
)
from withings2garmin.withings_client import WithingsException


def test_convert_to_fit_includes_bmi_from_height():
    measurements = [
        {"timestamp": datetime(2024, 1, 1), "measurements": {"weight": 80.0}}
    ]
    data = convert_to_fit(measurements, height=2.0)

    # bmi = 80 / 2^2 = 20.0 -> scale 10 -> 200 -> b'\xc8\x00'
    assert (200).to_bytes(2, "little") in data


def test_convert_to_fit_handles_blood_pressure():
    measurements = [
        {
            "timestamp": datetime(2024, 1, 1),
            "measurements": {"systolic_bp": 120, "diastolic_bp": 80},
        }
    ]
    data = convert_to_fit(measurements)
    assert (120).to_bytes(2, "little") in data


def test_save_measurements_json_writes_file(tmp_path, caplog):
    measurements = [
        {"timestamp": datetime(2024, 1, 1), "measurements": {"weight": 70.0}}
    ]
    out_file = tmp_path / "out.json"

    save_measurements_json(measurements, str(out_file))

    saved = json.loads(out_file.read_text())
    assert saved[0]["measurements"]["weight"] == 70.0


def test_load_env_file_sets_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('FOO_BAR="baz"\n# comment\nEMPTY_IGNORED\n')
    monkeypatch.delenv("FOO_BAR", raising=False)

    load_env_file(str(env_file))

    assert __import__("os").environ["FOO_BAR"] == "baz"


def test_load_env_file_missing_file_is_noop(tmp_path):
    load_env_file(str(tmp_path / "does-not-exist.env"))  # should not raise


def _args(**overrides):
    defaults = dict(
        from_date=None,
        to_date=None,
        garmin=False,
        output_json=None,
        output_fit=None,
        verbose=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_sync_data_no_measurements_returns_none():
    with patch("withings2garmin.sync.WithingsClient") as MockWithings:
        instance = MockWithings.return_value
        instance.get_last_sync.return_value = 0
        instance.get_measurements.return_value = []

        result = sync_data(_args())

    assert result is None


def test_sync_data_success_uploads_to_garmin():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        withings = MockWithings.return_value
        withings.get_last_sync.return_value = 0
        withings.get_measurements.return_value = [
            {"timestamp": datetime(2024, 1, 1), "measurements": {"weight": 80.0}}
        ]
        withings.get_height.return_value = 1.8

        garmin = MockGarmin.return_value
        garmin.upload_file.return_value = True

        result = sync_data(_args(garmin=True))

    assert result == 0
    garmin.upload_file.assert_called_once()
    withings.set_last_sync.assert_called_once()


def test_sync_data_withings_exception_returns_1():
    with patch(
        "withings2garmin.sync.WithingsClient", side_effect=WithingsException("x")
    ):
        result = sync_data(_args())

    assert result == 1


def test_sync_data_garmin_exception_returns_1():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient", side_effect=GarminException("x")),
    ):
        instance = MockWithings.return_value
        instance.get_last_sync.return_value = 0

        result = sync_data(_args(garmin=True))

    assert result == 1


def test_sync_data_unexpected_exception_returns_1():
    with patch("withings2garmin.sync.WithingsClient", side_effect=RuntimeError("boom")):
        result = sync_data(_args())

    assert result == 1
