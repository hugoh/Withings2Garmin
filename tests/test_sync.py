import argparse
import json
import os
import sys
from datetime import datetime
from unittest.mock import patch

from garmin_fit_sdk import Decoder, Stream

from withings2garmin.garmin_client import GarminException
from withings2garmin.sync import (
    _extract_latest_height,
    convert_to_fit,
    load_env_file,
    main,
    save_measurements_json,
    sync_data,
)
from withings2garmin.withings_client import WithingsException


def _decode(data: bytes):
    stream = Stream.from_byte_array(bytearray(data))
    messages, errors = Decoder(stream).read()
    assert errors == []
    return messages


def test_convert_to_fit_includes_bmi_from_height():
    measurements = [
        {"timestamp": datetime(2024, 1, 1), "measurements": {"weight": 80.0}}
    ]
    data = convert_to_fit(measurements, height=2.0)

    weight_scale = _decode(data)["weight_scale_mesgs"][0]
    assert weight_scale["weight"] == 80.0
    assert weight_scale["bmi"] == 20.0  # 80 / 2^2


def test_convert_to_fit_handles_blood_pressure():
    measurements = [
        {
            "timestamp": datetime(2024, 1, 1),
            "measurements": {"systolic_bp": 120, "diastolic_bp": 80},
        }
    ]
    data = convert_to_fit(measurements)

    bp = _decode(data)["blood_pressure_mesgs"][0]
    assert bp["systolic_pressure"] == 120
    assert bp["diastolic_pressure"] == 80


def test_extract_latest_height_returns_most_recent():
    measurements = [
        {"timestamp": datetime(2023, 1, 1), "measurements": {"height": 1.75}},
        {"timestamp": datetime(2024, 1, 1), "measurements": {"height": 1.80}},
        {"timestamp": datetime(2022, 1, 1), "measurements": {"weight": 80.0}},
    ]
    assert _extract_latest_height(measurements) == 1.80


def test_extract_latest_height_returns_none_when_absent():
    measurements = [
        {"timestamp": datetime(2024, 1, 1), "measurements": {"weight": 80.0}}
    ]
    assert _extract_latest_height(measurements) is None


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

    assert os.environ["FOO_BAR"] == "baz"


def test_load_env_file_missing_file_is_noop(tmp_path):
    load_env_file(str(tmp_path / "does-not-exist.env"))  # should not raise


def test_load_env_file_preserves_trailing_quote_char_in_value(tmp_path, monkeypatch):
    # Regression test: a hand-rolled parser's `.strip('"').strip("'")` would
    # truncate an unquoted value that happens to end in an apostrophe (e.g. a
    # password), since strip() removes ANY leading/trailing occurrence of
    # those characters rather than only a deliberately matched wrapping pair.
    env_file = tmp_path / ".env"
    env_file.write_text("GARMIN_PASSWORD=P@ssw0rd's\n")
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

    load_env_file(str(env_file))

    assert os.environ["GARMIN_PASSWORD"] == "P@ssw0rd's"


def test_load_env_file_does_not_override_existing_env_var(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO_BAR=from_dotenv\n")
    monkeypatch.setenv("FOO_BAR", "from_real_env")

    load_env_file(str(env_file))

    assert os.environ["FOO_BAR"] == "from_real_env"


def test_main_loads_env_file_before_configuring_logging(tmp_path, monkeypatch):
    # .env must be loaded before setup_logging() runs, since setup_logging()
    # resolves the log directory from WITHINGS2GARMIN_LOG_DIR via os.environ -
    # if the order were reversed, this env var set only in .env would be
    # silently ignored and logs would go to the platformdirs default instead.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WITHINGS2GARMIN_LOG_DIR", raising=False)
    log_dir = tmp_path / "custom-logs"
    (tmp_path / ".env").write_text(f"WITHINGS2GARMIN_LOG_DIR={log_dir}\n")
    monkeypatch.setattr(sys, "argv", ["withings2garmin"])

    with patch("withings2garmin.sync.sync_data", return_value=0) as mock_sync_data:
        main()

    mock_sync_data.assert_called_once()
    assert log_dir.is_dir()


def _args(**overrides):
    defaults = dict(
        from_date=None,
        to_date=None,
        garmin=False,
        output_json=None,
        output_fit=None,
        dry_run=False,
        force=False,
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


def _measurement(grpid, **data):
    return {
        "grpid": grpid,
        "timestamp": datetime(2024, 1, 1),
        "measurements": data,
    }


def _garmin_sync_mocks(MockWithings, MockGarmin, measurements):
    """Common setup: nothing locally tracked, nothing already on Garmin."""
    withings = MockWithings.return_value
    withings.get_last_sync.return_value = 0
    withings.get_measurements.return_value = measurements
    withings.get_height.return_value = 1.8
    withings.filter_unsynced.return_value = measurements

    garmin = MockGarmin.return_value
    garmin.get_existing_weight_timestamps.return_value = set()
    garmin.get_existing_blood_pressure_timestamps.return_value = set()
    garmin.upload_file.return_value = True

    return withings, garmin


def test_sync_data_success_uploads_to_garmin():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)

        result = sync_data(_args(garmin=True))

    assert result == 0
    garmin.upload_file.assert_called_once()
    withings.mark_synced.assert_called_once_with(measurements)
    withings.set_last_sync.assert_called_once()


def test_sync_data_skips_already_locally_synced_measurements():
    # filter_unsynced() (layer A) returning nothing means no candidates -
    # the Garmin existence check (layer B) shouldn't even be called.
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)
        withings.filter_unsynced.return_value = []

        result = sync_data(_args(garmin=True))

    assert result == 0
    garmin.get_existing_weight_timestamps.assert_not_called()
    garmin.upload_file.assert_not_called()
    withings.mark_synced.assert_not_called()
    withings.set_last_sync.assert_called_once()


def test_sync_data_skips_measurements_already_on_garmin():
    # layer A doesn't know about it yet, but layer B finds a matching
    # timestamp already on Garmin - should skip upload but backfill layer A.
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)
        garmin.get_existing_weight_timestamps.return_value = {datetime(2024, 1, 1)}

        result = sync_data(_args(garmin=True))

    assert result == 0
    garmin.upload_file.assert_not_called()
    withings.mark_synced.assert_called_once_with(measurements)
    withings.set_last_sync.assert_called_once()


def test_sync_data_partial_sync_uploads_only_new_measurements():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        already_on_garmin = _measurement("1", weight=80.0)
        new = {**_measurement("2", weight=81.0), "timestamp": datetime(2024, 1, 2)}
        withings, garmin = _garmin_sync_mocks(
            MockWithings, MockGarmin, [already_on_garmin, new]
        )
        garmin.get_existing_weight_timestamps.return_value = {datetime(2024, 1, 1)}

        result = sync_data(_args(garmin=True))

    assert result == 0
    garmin.upload_file.assert_called_once()
    withings.mark_synced.assert_any_call([already_on_garmin])
    withings.mark_synced.assert_any_call([new])


def test_sync_data_last_sync_not_advanced_on_upload_failure():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)
        garmin.upload_file.return_value = False

        result = sync_data(_args(garmin=True))

    assert result == 0
    withings.mark_synced.assert_not_called()
    withings.set_last_sync.assert_not_called()


def test_sync_data_dry_run_does_not_upload_or_mutate_state():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)

        result = sync_data(_args(garmin=True, dry_run=True))

    assert result == 0
    garmin.upload_file.assert_not_called()
    withings.mark_synced.assert_not_called()
    withings.set_last_sync.assert_not_called()


def test_sync_data_dry_run_reports_already_on_garmin_without_marking_synced():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)
        garmin.get_existing_weight_timestamps.return_value = {datetime(2024, 1, 1)}

        result = sync_data(_args(garmin=True, dry_run=True))

    assert result == 0
    withings.mark_synced.assert_not_called()


def test_sync_data_force_bypasses_dedup_but_still_marks_synced():
    with (
        patch("withings2garmin.sync.WithingsClient") as MockWithings,
        patch("withings2garmin.sync.GarminClient") as MockGarmin,
    ):
        measurements = [_measurement("1", weight=80.0)]
        withings, garmin = _garmin_sync_mocks(MockWithings, MockGarmin, measurements)
        # Even though layer A/B would both say "already synced"...
        withings.filter_unsynced.return_value = []
        garmin.get_existing_weight_timestamps.return_value = {datetime(2024, 1, 1)}

        result = sync_data(_args(garmin=True, force=True))

    assert result == 0
    # ...--force uploads everything anyway, bypassing both checks entirely.
    withings.filter_unsynced.assert_not_called()
    garmin.get_existing_weight_timestamps.assert_not_called()
    garmin.upload_file.assert_called_once()
    withings.mark_synced.assert_called_once_with(measurements)
    withings.set_last_sync.assert_called_once()


def test_sync_data_reuses_height_already_in_measurements():
    # Avoid the extra Withings API call when a height reading is already
    # present in the fetched measurements.
    with patch("withings2garmin.sync.WithingsClient") as MockWithings:
        withings = MockWithings.return_value
        withings.get_last_sync.return_value = 0
        withings.get_measurements.return_value = [
            {
                "timestamp": datetime(2024, 1, 1),
                "measurements": {"weight": 80.0, "height": 1.8},
            }
        ]

        sync_data(_args())

    withings.get_height.assert_not_called()


def test_sync_data_get_height_failure_does_not_abort_sync():
    # A height-lookup failure is auxiliary (BMI only) and must not fail the
    # whole sync - but it needs to be surfaced (caplog), not silent.
    with patch("withings2garmin.sync.WithingsClient") as MockWithings:
        withings = MockWithings.return_value
        withings.get_last_sync.return_value = 0
        withings.get_measurements.return_value = [
            {"timestamp": datetime(2024, 1, 1), "measurements": {"weight": 80.0}}
        ]
        withings.get_height.side_effect = WithingsException("api error")

        result = sync_data(_args())

    assert result == 0


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
