"""Main sync application."""

import argparse
import getpass
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import dotenv_values, load_dotenv, set_key
from filelock import FileLock, Timeout

from . import paths
from .fit_encoder import FitEncoder
from .garmin_client import GarminClient, GarminException
from .withings_client import WithingsClient, WithingsException


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    logs_dir = str(paths.log_dir())

    # Configure logging level
    level = logging.DEBUG if verbose else logging.INFO

    # Create timestamp for unique log file per execution
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(logs_dir, f"withings_sync_{timestamp}.log")

    # Simple logging configuration
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),  # Console output
            logging.FileHandler(log_filename, encoding="utf-8"),  # File output
        ],
        force=True,  # Override any existing configuration
    )

    # Log the configuration
    logging.debug(f"Log file: {log_filename}")
    if verbose:
        logging.debug("Verbose logging enabled")


def load_env_file(env_file: str = ".env"):
    """Load environment variables from .env file.

    Real environment variables always take precedence over .env file
    values (override=False) - deployment/CI environments that export
    these explicitly shouldn't have them silently overridden by a
    stray .env file.
    """
    loaded = load_dotenv(dotenv_path=env_file, override=False)
    if loaded:
        logging.debug(f"Loaded environment file: {env_file}")
    else:
        logging.debug(f"Environment file '{env_file}' not found.")


def _prompt_with_default(prompt: str, current: Optional[str]) -> str:
    """Prompt for a value, showing the current one (if any) as the default."""
    suffix = f" [{current}]" if current else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or current or ""


def _prompt_secret_with_default(prompt: str, current: Optional[str]) -> str:
    """Prompt for a secret value (not echoed), keeping the current on blank input."""
    suffix = " (leave blank to keep current)" if current else ""
    value = getpass.getpass(f"{prompt}{suffix}: ").strip()
    return value or current or ""


def edit_config() -> int:
    """Interactively prompt for credentials and save them to the resolved
    config file (see paths.resolve_env_file()), for users who'd rather not
    hand-edit it - notably the `uvx withings2garmin` no-checkout flow, where
    there's no repo to find sample/.env.example in."""
    env_path = str(paths.resolve_env_file())
    current = dotenv_values(env_path) if os.path.exists(env_path) else {}

    print(f"Configuring {env_path}\n")

    username = _prompt_with_default(
        "Garmin username/email", current.get("GARMIN_USERNAME")
    )
    while not username:
        print("Garmin username is required.")
        username = _prompt_with_default(
            "Garmin username/email", current.get("GARMIN_USERNAME")
        )

    password = _prompt_secret_with_default(
        "Garmin password", current.get("GARMIN_PASSWORD")
    )
    while not password:
        print("Garmin password is required.")
        password = _prompt_secret_with_default(
            "Garmin password", current.get("GARMIN_PASSWORD")
        )

    to_write = {"GARMIN_USERNAME": username, "GARMIN_PASSWORD": password}

    configure_withings = (
        input(
            "\nConfigure a custom Withings API app instead of the shared "
            "default? [y/N]: "
        )
        .strip()
        .lower()
    )
    if configure_withings == "y":
        client_id = _prompt_with_default(
            "Withings client ID", current.get("WITHINGS_CLIENT_ID")
        )
        client_secret = _prompt_secret_with_default(
            "Withings client secret", current.get("WITHINGS_CLIENT_SECRET")
        )
        callback_url = _prompt_with_default(
            "Withings callback URL", current.get("WITHINGS_CALLBACK_URL")
        )
        for key, value in (
            ("WITHINGS_CLIENT_ID", client_id),
            ("WITHINGS_CLIENT_SECRET", client_secret),
            ("WITHINGS_CALLBACK_URL", callback_url),
        ):
            if value:
                to_write[key] = value

    for key, value in to_write.items():
        set_key(env_path, key, value)

    if os.name != "nt":
        os.chmod(env_path, 0o600)

    print(f"\nSaved configuration to {env_path}")
    return 0


def convert_to_fit(measurements: List[Dict], height: Optional[float] = None) -> bytes:
    """Convert measurements to FIT file format."""
    encoder = FitEncoder()
    encoder.write_file_id()

    for measurement in measurements:
        timestamp = measurement["timestamp"]
        data = measurement["measurements"]

        # Write device info for each measurement
        encoder.write_device_info(timestamp)

        # Write weight data if available
        if "weight" in data:
            bmi = None
            if height:
                # BMI = weight (kg) / height (m)^2. Credit: eitanbehar's fork
                # (https://github.com/eitanbehar/Withings2Garmin), which computes
                # BMI from a Garmin height lookup; here we reuse the height
                # already fetched from Withings instead of an extra API call.
                bmi = data["weight"] / (height**2)

            encoder.write_weight_measurement(
                timestamp=timestamp,
                weight=data.get("weight"),
                fat_percentage=data.get("fat_ratio"),
                muscle_mass=data.get("muscle_mass"),
                bone_mass=data.get("bone_mass"),
                body_water=data.get("hydration"),
                bmi=bmi,
            )

        # Write blood pressure data if available
        if "systolic_bp" in data and "diastolic_bp" in data:
            encoder.write_blood_pressure(
                timestamp=timestamp,
                systolic=int(data["systolic_bp"]),
                diastolic=int(data["diastolic_bp"]),
                heart_rate=(
                    int(data.get("heart_rate", 0)) if data.get("heart_rate") else None
                ),
            )

    return encoder.finalize()


def _extract_latest_height(measurements: List[Dict]) -> Optional[float]:
    """Find the most recent height reading already present in fetched measurements."""
    latest_height = None
    latest_timestamp = None

    for entry in measurements:
        height = entry["measurements"].get("height")
        if height is None:
            continue
        if latest_timestamp is None or entry["timestamp"] > latest_timestamp:
            latest_height = height
            latest_timestamp = entry["timestamp"]

    return latest_height


def _classify_for_garmin_upload(
    measurements: List[Dict],
    withings: WithingsClient,
    garmin: GarminClient,
    start_date: datetime,
    end_date: datetime,
    force: bool,
) -> tuple[List[Dict], List[Dict]]:
    """Split measurements into (already_on_garmin, to_upload) for a sync.

    already_on_garmin: determined to already exist on Garmin (locally
    tracked, or found via a live existence check) - not re-uploaded, but
    still worth recording locally so future runs skip the live check too.
    to_upload: measurements that should actually be uploaded.
    """
    if force:
        return [], list(measurements)

    candidates = withings.filter_unsynced(measurements)
    if not candidates:
        return [], []

    existing_weight_ts = garmin.get_existing_weight_timestamps(start_date, end_date)
    existing_bp_ts = garmin.get_existing_blood_pressure_timestamps(start_date, end_date)

    already_on_garmin = []
    to_upload = []
    for m in candidates:
        data = m["measurements"]
        is_dup_weight = "weight" in data and m["timestamp"] in existing_weight_ts
        is_dup_bp = (
            "systolic_bp" in data
            and "diastolic_bp" in data
            and m["timestamp"] in existing_bp_ts
        )
        if is_dup_weight or is_dup_bp:
            already_on_garmin.append(m)
        else:
            to_upload.append(m)

    return already_on_garmin, to_upload


def save_measurements_json(measurements: List[Dict], filename: str):
    """Save measurements to JSON file."""
    # Convert datetime objects to strings for JSON serialization
    serializable_data = []
    for measurement in measurements:
        data = measurement.copy()
        data["timestamp"] = data["timestamp"].isoformat()
        serializable_data.append(data)

    with open(filename, "w") as f:
        json.dump(serializable_data, f, indent=2)

    logging.getLogger(__name__).info(
        f"Saved {len(measurements)} measurements to {filename}"
    )


def sync_data(args):
    """Main sync function.

    Wrapped in a file lock so two concurrent invocations (e.g. an
    overlapping cron run) can't race on last_sync/tokens state - one waits
    up to 5s for the other to finish, then gives up rather than proceeding
    unsafely.
    """
    logger = logging.getLogger(__name__)

    try:
        with FileLock(str(paths.sync_lock_file()), timeout=5):
            return _sync_data_locked(args, logger)
    except Timeout:
        logger.error("Another sync is already running; aborting")
        return 1
    except WithingsException as e:
        logger.error(f"Withings error: {e}")
        return 1
    except GarminException as e:
        logger.error(f"Garmin error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
        return 1


def _sync_data_locked(args, logger):
    """The actual sync logic, called with the sync lock already held."""
    # Initialize clients
    logger.debug("Initializing Withings client...")
    withings = WithingsClient()

    garmin = None
    if args.garmin:
        logger.debug("Initializing Garmin client...")
        garmin = GarminClient()

    # Determine date range
    if args.from_date:
        start_date = datetime.strptime(args.from_date, "%Y-%m-%d")
    else:
        # Use last sync date or default to 7 days ago
        last_sync = withings.get_last_sync()
        start_date = datetime.fromtimestamp(last_sync)

    if args.to_date:
        end_date = datetime.strptime(args.to_date, "%Y-%m-%d")
    else:
        end_date = datetime.now()

    logger.info(f"Syncing data from {start_date.date()} to {end_date.date()}")

    # Get measurements
    measurements = withings.get_measurements(start_date, end_date)

    if not measurements:
        logger.info("No measurements found for the specified period")
        return

    logger.info(f"Found {len(measurements)} measurements")

    # Get height for BMI calculation - reuse it if already present in the
    # fetched measurements (avoids an extra Withings API call), otherwise
    # fall back to a dedicated height lookup. A failure there shouldn't
    # abort the whole sync (BMI is auxiliary), but must be logged rather
    # than silently treated the same as "no height on file".
    height = _extract_latest_height(measurements)
    if height is None:
        try:
            height = withings.get_height()
        except WithingsException as e:
            logger.warning(f"Could not fetch height for BMI calculation: {e}")
    if height:
        logger.debug(f"User height: {height:.2f} m")

    # Save to JSON if requested
    if args.output_json:
        save_measurements_json(measurements, args.output_json)

    # Save FIT file if requested - the full fetched range, not filtered
    # by dedup below: this is an explicit export request, not "what's
    # new for Garmin", so it can legitimately differ from what actually
    # gets uploaded.
    if args.output_fit:
        fit_data = convert_to_fit(measurements, height)
        with open(args.output_fit, "wb") as f:
            f.write(fit_data)
        logger.info(f"Saved FIT file to {args.output_fit}")

    # Upload to Garmin if requested
    if args.garmin:
        assert garmin is not None  # constructed above whenever args.garmin

        already_on_garmin, to_upload = _classify_for_garmin_upload(
            measurements, withings, garmin, start_date, end_date, args.force
        )

        if already_on_garmin:
            logger.info(
                f"{len(already_on_garmin)} measurement(s) already present "
                "on Garmin; skipping"
            )
            if not args.dry_run:
                withings.mark_synced(already_on_garmin)

        upload_ok = True
        if not to_upload:
            logger.info("Nothing new to upload to Garmin")
        elif args.dry_run:
            logger.info(
                f"[dry-run] Would upload {len(to_upload)} measurement(s) "
                "to Garmin Connect"
            )
        else:
            fit_data = convert_to_fit(to_upload, height)
            logger.info(
                f"Uploading {len(to_upload)} measurement(s) to Garmin Connect..."
            )
            upload_ok = garmin.upload_file(fit_data)
            if upload_ok:
                logger.info("Successfully uploaded to Garmin Connect")
                withings.mark_synced(to_upload)
            else:
                logger.error("Failed to upload to Garmin Connect")

        # Advance the cursor whenever the window was fully handled
        # without an upload failure - including when there was nothing
        # new to upload, so an already-fully-synced window doesn't get
        # re-fetched and re-checked against Garmin on every run. Only a
        # real upload failure withholds it, so that case retries next
        # time. Automatic-range runs only (-f runs never advance it),
        # and a dry run must not mutate any state.
        if upload_ok and not args.from_date and not args.dry_run:
            withings.set_last_sync()

    logger.info("Sync completed successfully")
    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Withings to Garmin sync tool")

    parser.add_argument(
        "-f",
        dest="from_date",
        help="Start date (YYYY-MM-DD). If not specified, uses last sync date",
    )
    parser.add_argument(
        "-t", dest="to_date", help="End date (YYYY-MM-DD). If not specified, uses today"
    )
    parser.add_argument(
        "--garmin", action="store_true", help="Enable Garmin Connect sync"
    )
    parser.add_argument("--output-json", help="Output measurements to JSON file")
    parser.add_argument("--output-fit", help="Save FIT file to specified path")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show what would be synced to Garmin without uploading or "
            "changing any state"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass duplicate checks and upload all fetched measurements to Garmin",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--edit-config",
        action="store_true",
        help=(
            "Interactively enter Garmin/Withings credentials and save them "
            "to the resolved config file, then exit"
        ),
    )

    args = parser.parse_args()

    if args.edit_config:
        return edit_config()

    # Must run before setup_logging(): .env can set WITHINGS2GARMIN_LOG_DIR,
    # which setup_logging() -> paths.log_dir() reads from os.environ.
    load_env_file(str(paths.resolve_env_file()))
    setup_logging(args.verbose)

    return sync_data(args)


if __name__ == "__main__":
    exit(main())
