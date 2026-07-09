"""FIT file encoder for health data.

Wraps Garmin's official `garmin_fit_sdk.Encoder` instead of hand-rolling the
binary FIT format (manual struct.pack, a hand-copied CRC-16 table, and
manually-transcribed field/type codes). The SDK's encoder applies field
scale/offset and None-vs-invalid handling itself (using `value is None`, not
Python truthiness - so a genuine 0 is never mistaken for "field omitted"),
and generates message definitions from Garmin's own profile rather than
hand-maintained constants.
"""

from datetime import datetime
from typing import Optional

from garmin_fit_sdk import Encoder


class FitEncoder:
    """FIT file encoder for weight and health data."""

    # FIT global message numbers (Profile['mesg_num'] in garmin_fit_sdk).
    MSG_FILE_ID = 0
    MSG_DEVICE_INFO = 23
    MSG_WEIGHT_SCALE = 30
    MSG_BLOOD_PRESSURE = 51

    def __init__(self):
        self._encoder = Encoder()

    def write_file_id(self):
        """Write file ID message."""
        self._encoder.write_mesg(
            {
                "mesg_num": self.MSG_FILE_ID,
                "type": "weight",
                "manufacturer": "garmin",
                "product": 0,
                "serial_number": 0,
                "time_created": datetime.now(),
            }
        )

    def write_device_info(self, timestamp: datetime):
        """Write device info message."""
        self._encoder.write_mesg(
            {
                "mesg_num": self.MSG_DEVICE_INFO,
                "timestamp": timestamp,
                "device_index": 0,
                "device_type": 119,  # ANT+ device profile: weight scale
                "manufacturer": "garmin",
                "product": 0,
                "software_version": 1.0,
            }
        )

    def write_weight_measurement(
        self,
        timestamp: datetime,
        weight: float,
        fat_percentage: Optional[float] = None,
        muscle_mass: Optional[float] = None,
        bone_mass: Optional[float] = None,
        body_water: Optional[float] = None,
        bmi: Optional[float] = None,
    ):
        """Write weight scale measurement."""
        self._encoder.write_mesg(
            {
                "mesg_num": self.MSG_WEIGHT_SCALE,
                "timestamp": timestamp,
                "weight": weight,
                "percent_fat": fat_percentage,
                "muscle_mass": muscle_mass,
                "bone_mass": bone_mass,
                "percent_hydration": body_water,
                "bmi": bmi,
            }
        )

    def write_blood_pressure(
        self,
        timestamp: datetime,
        systolic: int,
        diastolic: int,
        heart_rate: Optional[int] = None,
    ):
        """Write blood pressure measurement."""
        self._encoder.write_mesg(
            {
                "mesg_num": self.MSG_BLOOD_PRESSURE,
                "timestamp": timestamp,
                "systolic_pressure": systolic,
                "diastolic_pressure": diastolic,
                "heart_rate": heart_rate,
            }
        )

    def finalize(self) -> bytes:
        """Finalize the FIT file and return bytes."""
        return self._encoder.close()
