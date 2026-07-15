from datetime import UTC, datetime

from garmin_fit_sdk import Decoder, Stream

from withings2garmin.fit_encoder import FitEncoder


def _decode(data: bytes):
    """Decode FIT bytes with the official SDK and assert they're valid."""
    stream = Stream.from_byte_array(bytearray(data))
    messages, errors = Decoder(stream).read()
    assert errors == []
    return messages


def test_finalize_produces_a_valid_decodable_fit_file():
    encoder = FitEncoder()
    encoder.write_file_id()
    data = encoder.finalize()

    messages = _decode(data)

    assert len(messages["file_id_mesgs"]) == 1
    file_id = messages["file_id_mesgs"][0]
    assert file_id["type"] == "weight"
    assert file_id["manufacturer"] == "garmin"


def test_write_weight_measurement_round_trips_scaled_fields():
    encoder = FitEncoder()
    encoder.write_file_id()
    timestamp = datetime(2024, 1, 1, 12, 0, 0)

    encoder.write_weight_measurement(
        timestamp=timestamp,
        weight=80.5,
        fat_percentage=20.25,
        muscle_mass=60.1,
        bone_mass=3.2,
        body_water=55.0,
        bmi=24.5,
    )
    data = encoder.finalize()

    weight_scale = _decode(data)["weight_scale_mesgs"][0]
    assert weight_scale["weight"] == 80.5
    assert weight_scale["percent_fat"] == 20.25
    assert weight_scale["muscle_mass"] == 60.1
    assert weight_scale["bone_mass"] == 3.2
    assert weight_scale["percent_hydration"] == 55.0
    assert weight_scale["bmi"] == 24.5
    assert weight_scale["timestamp"] == timestamp.astimezone(UTC)


def test_write_weight_measurement_zero_values_round_trip_as_zero():
    # Regression test: 0.0 is a legitimate value, not "field omitted". A
    # falsy check (`if weight else None`) would drop it as invalid instead
    # of encoding the literal 0 - garmin_fit_sdk's encoder checks
    # `value is None`, so this can't happen here.
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_weight_measurement(
        timestamp=datetime(2024, 1, 1),
        weight=0.0,
        bmi=0.0,
    )
    data = encoder.finalize()

    weight_scale = _decode(data)["weight_scale_mesgs"][0]
    assert weight_scale["weight"] == 0.0
    assert weight_scale["bmi"] == 0.0


def test_write_weight_measurement_omitted_fields_are_absent():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_weight_measurement(timestamp=datetime(2024, 1, 1), weight=70.0)
    data = encoder.finalize()

    weight_scale = _decode(data)["weight_scale_mesgs"][0]
    assert weight_scale["weight"] == 70.0
    assert "bmi" not in weight_scale
    assert "percent_fat" not in weight_scale


def test_write_blood_pressure_round_trips_values():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_blood_pressure(
        timestamp=datetime(2024, 1, 1), systolic=120, diastolic=80, heart_rate=65
    )
    data = encoder.finalize()

    bp = _decode(data)["blood_pressure_mesgs"][0]
    assert bp["systolic_pressure"] == 120
    assert bp["diastolic_pressure"] == 80
    assert bp["heart_rate"] == 65


def test_write_blood_pressure_without_heart_rate_omits_field():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_blood_pressure(
        timestamp=datetime(2024, 1, 1), systolic=120, diastolic=80
    )
    data = encoder.finalize()

    bp = _decode(data)["blood_pressure_mesgs"][0]
    assert "heart_rate" not in bp


def test_write_device_info_round_trips_and_can_be_called_multiple_times():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_device_info(datetime(2024, 1, 1))
    encoder.write_device_info(datetime(2024, 1, 2))
    data = encoder.finalize()

    device_infos = _decode(data)["device_info_mesgs"]
    assert len(device_infos) == 2
    assert device_infos[0]["device_type"] == 119
    assert device_infos[0]["manufacturer"] == "garmin"


def test_full_measurement_sequence_decodes_with_all_message_types():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_device_info(datetime(2024, 1, 1))
    encoder.write_weight_measurement(timestamp=datetime(2024, 1, 1), weight=80.0)
    encoder.write_blood_pressure(
        timestamp=datetime(2024, 1, 1), systolic=120, diastolic=80
    )
    data = encoder.finalize()

    messages = _decode(data)
    assert len(messages["file_id_mesgs"]) == 1
    assert len(messages["device_info_mesgs"]) == 1
    assert len(messages["weight_scale_mesgs"]) == 1
    assert len(messages["blood_pressure_mesgs"]) == 1
