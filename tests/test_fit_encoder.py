from datetime import datetime

from withings2garmin.fit_encoder import FitEncoder, _calc_crc


def test_finalize_produces_valid_header_and_trailer():
    encoder = FitEncoder()
    encoder.write_file_id()
    data = encoder.finalize()

    # 12-byte header + 2-byte CRC trailer, at minimum.
    assert len(data) >= 14
    assert data[8:12] == b".FIT"

    header_size = data[0]
    assert header_size == FitEncoder.HEADER_SIZE

    data_size = int.from_bytes(data[4:8], "little")
    assert data_size == len(data) - FitEncoder.HEADER_SIZE - 2  # minus CRC


def test_finalize_crc_matches_recomputed_crc():
    encoder = FitEncoder()
    encoder.write_file_id()
    data = encoder.finalize()

    body, trailing_crc = data[:-2], int.from_bytes(data[-2:], "little")

    crc = 0
    for byte in body:
        crc = _calc_crc(crc, byte)

    assert crc == trailing_crc


def test_write_weight_measurement_encodes_scaled_fields():
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

    # weight (uint16, scale 100) = 8050 -> b'\xf5\x1f' little-endian
    assert int(80.5 * 100).to_bytes(2, "little") in data
    # bmi (uint16, scale 10) = 245 -> b'\xf5\x00'
    assert int(24.5 * 10).to_bytes(2, "little") in data


def test_write_weight_measurement_zero_values_are_not_marked_invalid():
    encoder = FitEncoder()
    encoder.write_file_id()

    # weight=0.0 and bmi=0.0 are legitimate values, not "field omitted" - they must
    # not be encoded as the FIT "invalid" uint16 sentinel (0xFFFF), which is what a
    # falsy check (`if weight else None`) would incorrectly produce.
    encoder.write_weight_measurement(
        timestamp=datetime(2024, 1, 1),
        weight=0.0,
        fat_percentage=20.0,
        muscle_mass=50.0,
        bone_mass=3.0,
        body_water=55.0,
        bmi=0.0,
    )
    data = encoder.finalize()

    assert b"\xff\xff" not in data


def test_write_weight_measurement_without_bmi_writes_invalid_marker():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_weight_measurement(timestamp=datetime(2024, 1, 1), weight=70.0)
    data = encoder.finalize()

    # FIT "invalid" uint16 sentinel (0xFFFF) must appear for the omitted BMI field.
    assert b"\xff\xff" in data


def test_write_blood_pressure_encodes_values():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_blood_pressure(
        timestamp=datetime(2024, 1, 1), systolic=120, diastolic=80, heart_rate=65
    )
    data = encoder.finalize()

    assert (120).to_bytes(2, "little") in data
    assert (80).to_bytes(2, "little") in data
    assert bytes([65]) in data


def test_device_info_definition_written_once():
    encoder = FitEncoder()
    encoder.write_file_id()
    encoder.write_device_info(datetime(2024, 1, 1))
    encoder.write_device_info(datetime(2024, 1, 2))

    assert encoder._device_info_written is True
