# Withings2Garmin

> **This is a fork.** This repository builds on
> [sodelalbert/Withings2Garmin](https://github.com/sodelalbert/Withings2Garmin),
> and borrows specific fixes from other forks/PRs in that project's family
> tree rather than reinventing them:
>
> - The migration to the [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
>   library (replacing a hand-rolled `garth` session client) follows the
>   approach proposed by andrewleech in upstream
>   [PR #14](https://github.com/sodelalbert/Withings2Garmin/pull/14).
> - The BMI field written to the FIT weight message follows the pattern added
>   by eitanbehar in their fork
>   ([eitanbehar/Withings2Garmin](https://github.com/eitanbehar/Withings2Garmin),
>   branch `garmin-bmi-2026-working`).
>
> See [Acknowledgments](#acknowledgments) below for the full picture.

A comprehensive Withings to Garmin Connect synchronization tool built with modern Python tooling and `.env` configuration.

## Features

- **Automatic data synchronization** from Withings to Garmin Connect
- **Multiple output formats**: JSON, FIT files, and direct Garmin upload
- **Comprehensive health metrics support**:
  - Weight measurements with BMI calculation
  - Body composition (fat percentage, muscle mass, bone mass, body water)
  - Blood pressure readings (systolic, diastolic, heart rate)
- **Flexible date range selection** with automatic last sync tracking
- **Authentication management**:
  - OAuth 2.0 flow for Withings API
  - Multi-factor authentication support for Garmin Connect
  - Local token storage and automatic refresh
- **Robust logging system** with timestamped log files
- **FIT file encoding** compatible with Garmin devices
- **Environment-based configuration** using `.env` files
- **Modern Python packaging** with uv dependency management

## Installation

This project requires Python 3.12+.

### Run without installing (uvx)

With [uv](https://docs.astral.sh/uv/) installed, run the tool directly from PyPI
without a local checkout:

```bash
uvx withings2garmin --garmin
```

### Install for local development

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv

git clone https://github.com/sodelalbert/Withings2Garmin.git
cd Withings2Garmin
uv sync
```

## Configuration

### Environment Setup

Copy the example environment file and configure your credentials:

```bash
cp sample/.env.example .env
```

Edit `.env` with your credentials:

```bash
# Withings API Configuration
WITHINGS_CLIENT_ID=your_withings_client_id
WITHINGS_CLIENT_SECRET=your_withings_client_secret
WITHINGS_CALLBACK_URL=https://jaroslawhartman.github.io/withings-sync/contrib/withings.html

# Garmin Connect Configuration
GARMIN_USERNAME=your_garmin_username
GARMIN_PASSWORD=your_garmin_password
```

### Where files are stored

`withings2garmin` is a standalone CLI (installable via `uvx`), so it doesn't rely
on a "repo root" for storing your credentials, tokens, or logs. It resolves each
in order:

| What | 1. explicit override | 2. cwd (local dev) | 3. default |
|---|---|---|---|
| Config file (`.env`) | `$WITHINGS2GARMIN_CONFIG_FILE` | `./.env` | `<user config dir>/config.env` |
| Withings tokens | `$WITHINGS_TOKENS_FILE` | `./.withings_tokens.json` | `<user data dir>/withings_tokens.json` |
| Garmin session | `$GARMIN_SESSION_DIR` | `./.garmin_session` | `<user data dir>/garmin_session` |
| Logs | `$WITHINGS2GARMIN_LOG_DIR` | *(always)* | `<user log dir>` |

`<user config/data/log dir>` follow OS conventions via
[`platformdirs`](https://github.com/tox-dev/platformdirs) — e.g. on Linux,
`~/.config/withings2garmin`, `~/.local/share/withings2garmin`, and
`~/.local/state/withings2garmin/log` respectively; macOS and Windows use their
native equivalents. You can also override the whole config/data/log directory
at once with `WITHINGS2GARMIN_CONFIG_DIR`, `WITHINGS2GARMIN_DATA_DIR`, and
`WITHINGS2GARMIN_LOG_DIR`.

If you keep running `withings2garmin` from the same directory (e.g. a repo
checkout via `uv run`), files there are always found first — nothing changes
for that workflow.

### Withings API Setup

1. Create a Withings developer account at [Withings Developer Portal](https://developer.withings.com/)
2. Create a new application
3. Set the callback URL to: `https://jaroslawhartman.github.io/withings-sync/contrib/withings.html`
4. Copy the Client ID and Client Secret to your `.env` file

## Usage

All commands use `uv run` to ensure proper environment isolation and dependency management.

### Basic Operations

**Export measurements to JSON:**

```bash
uv run withings2garmin --output-json measurements.json
```

**Sync to Garmin Connect:**

```bash
uv run withings2garmin --garmin
```

**Generate FIT file:**

```bash
uv run withings2garmin --output-fit measurements.fit
```

**Multiple outputs with Garmin sync:**

```bash
uv run withings2garmin --garmin --output-json backup.json --output-fit backup.fit
```

### Date Range Specification

**Sync specific date range:**

```bash
uv run withings2garmin --garmin -f 2024-01-01 -t 2024-01-31
```

**Sync from specific date to today:**

```bash
uv run withings2garmin --garmin -f 2024-01-01
```

**Verbose logging for debugging:**

```bash
uv run withings2garmin --garmin --verbose
```

### Authentication Workflow

#### First-Time Withings Authorization

When running for the first time, you'll see:

```
============================================================
WITHINGS AUTHORIZATION REQUIRED
============================================================
Open this URL in your browser and copy the authorization code:

https://account.withings.com/oauth2_user/authorize2?response_type=code&client_id=...

You have 30 seconds to complete this process!
============================================================
Enter authorization code: [paste code here]
```

1. Open the provided URL in your browser
2. Log into your Withings account and authorize the application
3. Copy the authorization code from the callback URL
4. Paste it into the terminal prompt
5. Tokens are automatically saved for future use

#### Garmin Multi-Factor Authentication

If MFA is enabled on your Garmin account:

```
MFA code: [enter your 6-digit code]
```

1. Check your email for the Garmin verification code
2. Enter the 6-digit code when prompted
3. Session is saved locally for future authentication

## Project Architecture

```
Withings2Garmin/
├── src/withings2garmin/
│   ├── sync.py              # Main application entry point
│   ├── withings_client.py   # Withings API client with OAuth 2.0
│   ├── garmin_client.py     # Garmin Connect client with MFA support
│   ├── fit_encoder.py       # FIT file format encoder
│   └── paths.py             # Resolves config/data/log file locations
├── tests/                   # pytest test suite
├── pyproject.toml           # Project configuration and dependencies
├── uv.lock                  # Dependency lock file
├── .env                     # Environment configuration (optional, cwd override)
└── sample/
    └── .env.example         # Environment template
```

Credentials, tokens, session data, and logs live outside the repo by default —
see [Where files are stored](#where-files-are-stored).

## Dependencies

Core dependencies managed through `pyproject.toml`:

- **requests** (≥2.34.2) - HTTP client for API communications
- **garminconnect** (≥0.3.6) - Garmin Connect authentication and API interface
- **platformdirs** (≥4.0) - OS-appropriate config/data/log directory resolution

Development dependencies (`[dependency-groups.dev]`, installed automatically by
`uv sync` but not part of the published package):

- **black** (≥26.5.1) - Code formatting
- **mypy** (≥2.2.0) - Static type checking
- **flake8** with extensions - Code linting
- **isort** (≥8.0.1) - Import sorting
- **pytest** (≥9.1.1) - Testing framework

## Command Line Reference

```
usage: withings2garmin [-h] [-f FROM_DATE] [-t TO_DATE] [--garmin]
               [--output-json OUTPUT_JSON] [--output-fit OUTPUT_FIT] [--verbose]

options:
  -h, --help                    Show help message and exit
  -f FROM_DATE                  Start date (YYYY-MM-DD). If not specified, uses last sync date
  -t TO_DATE                    End date (YYYY-MM-DD). If not specified, uses today
  --garmin                      Enable Garmin Connect sync
  --output-json OUTPUT_JSON     Output measurements to JSON file
  --output-fit OUTPUT_FIT       Save FIT file to specified path
  --verbose, -v                 Enable verbose logging
```

## Data Processing

### Supported Withings Metrics

- **Weight**: Body weight with automatic BMI calculation
- **Body Composition**: Fat percentage, muscle mass, bone mass, body water
- **Cardiovascular**: Blood pressure (systolic/diastolic), heart rate
- **Physical**: Height measurements

### FIT File Format

The application generates standard FIT files compatible with:

- Garmin Connect
- Garmin devices
- Third-party fitness applications
- ANT+ ecosystem tools

### Data Transformation

- Automatic unit conversion to metric system
- BMI calculation using stored height data
- Timestamp normalization for cross-platform compatibility
- Data validation and error handling

## Logging and Monitoring

### Log Files

- **Location**: `<user log dir>/withings_sync_YYYYMMDD_HHMMSS.log` (see
  [Where files are stored](#where-files-are-stored); override with
  `WITHINGS2GARMIN_LOG_DIR`)
- **Retention**: Manual cleanup (logs are not auto-deleted)
- **Format**: Timestamped entries with log levels

### Log Levels

- **INFO**: Standard operation messages
- **DEBUG**: Detailed operation information (use `--verbose`)
- **WARNING**: Non-critical issues
- **ERROR**: Operation failures

### Console Output

- Real-time progress indicators
- Authentication prompts
- Success/failure summaries
- Error messages with context

## Troubleshooting

### Authentication Issues

Tokens/session files may be in your working directory or in the default user
data directory — see [Where files are stored](#where-files-are-stored) if
unsure. `--verbose` logs the resolved paths on every run.

**Withings token expiration:**

```bash
# Remove invalid tokens and re-authenticate
rm "$(uv run python -c 'from withings2garmin import paths; print(paths.withings_tokens_file())')"
uv run withings2garmin --garmin
```

**Garmin session issues:**

```bash
# Clear Garmin session and re-authenticate
rm -rf "$(uv run python -c 'from withings2garmin import paths; print(paths.garmin_session_dir())')"
uv run withings2garmin --garmin
```

### Data Issues

**No measurements found:**

- Verify date range with `-f` and `-t` options
- Check Withings account has data for specified period
- Ensure Withings device is synced

**FIT file generation errors:**

- Verify write permissions in target directory
- Check available disk space
- Ensure measurements contain valid data

### Network Issues

**API connection failures:**

- Check internet connectivity
- Verify firewall settings
- Confirm API endpoints are accessible

### Upgrading (breaking change: config/token/session/log locations)

`.env`, `.withings_tokens.json`, `.garmin_session/`, and `logs/` used to be
strictly relative to whatever directory you ran the tool from. They now
default to OS-appropriate user config/data/log directories instead (see
[Where files are stored](#where-files-are-stored)):

- **You keep running the tool from the same directory as before** (e.g. `uv
  run withings2garmin` from a repo checkout): no change — that directory is
  still checked first for `.env`/tokens/session.
- **You run it from a new directory, a fresh install, CI, or a container**:
  `.env`/tokens/session now resolve to the new default locations instead of
  erroring or silently treating you as unauthenticated with no explanation.
  Logs unconditionally move to the new default log directory (no cwd
  fallback, since there's no continuity to preserve for logs).
- To pin the old cwd-relative behavior explicitly, set
  `WITHINGS2GARMIN_CONFIG_FILE=./.env`, `WITHINGS_TOKENS_FILE=./.withings_tokens.json`,
  `GARMIN_SESSION_DIR=./.garmin_session`, and `WITHINGS2GARMIN_LOG_DIR=./logs`.

## Development

### Code Quality

The project uses automated code quality tools:

```bash
# Format code
uv run black .

# Sort imports
uv run isort .

# Lint code
uv run flake8 .

# Type checking
uv run mypy .
```

### Testing

```bash
# Run tests
uv run pytest
```

## License

MIT License - see project repository for full license text.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes following code quality standards
4. Submit a pull request

## Support

For issues and feature requests, please use the GitHub issue tracker.

## Acknowledgments

- The migration from a hand-rolled `garth` session client to the
  [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library
  follows the approach proposed by andrewleech in upstream
  [PR #14](https://github.com/sodelalbert/Withings2Garmin/pull/14).
- The BMI field written to the FIT weight message follows the pattern added by
  eitanbehar in their fork
  ([eitanbehar/Withings2Garmin](https://github.com/eitanbehar/Withings2Garmin),
  branch `garmin-bmi-2026-working`).
