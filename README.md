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
> Most of the code on top of that baseline (packaging, the garminconnect
> migration itself, path resolution, tests) was assisted by an LLM
> (Claude Code).

Syncs Withings body measurements (weight, body composition, blood pressure)
to Garmin Connect as FIT files.

## Features

- Withings OAuth 2.0 flow and Garmin Connect auth (including MFA), with
  tokens cached locally so you don't re-authenticate every run
- Weight, body composition, and blood pressure sync, with BMI computed from
  Withings weight/height
- Output to JSON and/or FIT file, in addition to (or instead of) uploading to
  Garmin Connect
- Duplicate-safe: tracks what it's already uploaded and checks what Garmin
  already has before syncing (see [Sync Safety](#sync-safety)), retries
  transient network failures, and won't corrupt its own state on a crash

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

Run `withings2garmin --edit-config` for an interactive prompt that saves
your Garmin (and optionally Withings) credentials to the right config file
for you — no need to find or hand-edit it, which is especially handy for the
`uvx` no-checkout flow where there's no repo to find `sample/.env.example`
in. Passwords/secrets are entered without being echoed to the terminal.

Alternatively, copy the example environment file and configure it by hand:

```bash
cp sample/.env.example .env
```

Edit `.env` with your credentials:

```bash
# Garmin Connect Configuration (required)
GARMIN_USERNAME=your_garmin_username
GARMIN_PASSWORD=your_garmin_password

# Withings API Configuration (optional - see below)
WITHINGS_CLIENT_ID=your_withings_client_id
WITHINGS_CLIENT_SECRET=your_withings_client_secret
WITHINGS_CALLBACK_URL=https://jaroslawhartman.github.io/withings-sync/contrib/withings.html
```

### Withings API Setup (optional)

`WITHINGS_CLIENT_ID`/`WITHINGS_CLIENT_SECRET`/`WITHINGS_CALLBACK_URL` are
**optional**: if unset, this tool falls back to a shared Withings developer-
app registration baked into `withings_client.py` (`DEFAULT_CLIENT_ID`/
`DEFAULT_CLIENT_SECRET`/`DEFAULT_CALLBACK_URL`, the latter currently
`https://jaroslawhartman.github.io/withings-sync/contrib/withings.html`), the
same pattern upstream
[jaroslawhartman/withings-sync](https://github.com/jaroslawhartman/withings-sync)
uses for its own default — most users don't need to register their own app.
That shared app is rate-limited across everyone using it, so if you hit
limits or want your own quota, register your own:

1. Create a Withings developer account at [Withings Developer Portal](https://developer.withings.com/)
2. Create a new application
3. Set the callback URL to: `https://jaroslawhartman.github.io/withings-sync/contrib/withings.html`
4. Set `WITHINGS_CLIENT_ID`/`WITHINGS_CLIENT_SECRET` in `.env` to override
   the default

### Where files are stored

`withings2garmin` is a standalone CLI (installable via `uvx`), so it doesn't rely
on a "repo root" for storing your credentials, tokens, or logs. It resolves each
in order:

| What                 | 1. explicit override           | 2. cwd (local dev)        | 3. default                             |
| -------------------- | ------------------------------ | ------------------------- | -------------------------------------- |
| Config file (`.env`) | `$WITHINGS2GARMIN_CONFIG_FILE` | `./.env`                  | `<user config dir>/config.env`         |
| Withings tokens      | `$WITHINGS_TOKENS_FILE`        | `./.withings_tokens.json` | `<user data dir>/withings_tokens.json` |
| Garmin session       | `$GARMIN_SESSION_DIR`          | `./.garmin_session`       | `<user data dir>/garmin_session`       |
| Logs                 | `$WITHINGS2GARMIN_LOG_DIR`     | _(always)_                | `<user log dir>`                       |

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

## Usage

Run `withings2garmin --help` for the full flag reference. A couple of common
invocations:

```bash
# Sync to Garmin Connect (default date range: since last sync)
uv run withings2garmin --garmin

# Sync a specific date range and also save JSON/FIT files locally
uv run withings2garmin --garmin -f 2024-01-01 -t 2024-01-31 \
    --output-json backup.json --output-fit backup.fit

# See what would be uploaded without actually uploading or changing any state
uv run withings2garmin --garmin --dry-run --verbose
```

### Authentication Workflow

#### First-Time Withings Authorization

When running for the first time, you'll see:

```text
============================================================
WITHINGS AUTHORIZATION REQUIRED
============================================================
Open this URL in your browser and copy the authorization code:

https://account.withings.com/oauth2_user/authorize2?response_type=code&client_id=...

You have 30 seconds to complete this process!
============================================================
Enter authorization code: [paste code here]
```

Open the URL, authorize the application, and paste the resulting code back
into the terminal. Tokens are then saved for future runs.

#### Garmin Multi-Factor Authentication

If MFA is enabled on your Garmin account, you'll be prompted for `MFA code:`
on first login; the session is then saved locally for future runs.

## Sync Safety

By default (no `-f`), each run only fetches data since the last successful
sync, tracked in the Withings tokens file — a fresh install with no prior
sync defaults to the last 24 hours, not full history (pass `-f` explicitly
to backfill further back).

Within whatever range gets fetched, two independent checks keep a Garmin
upload from creating duplicates:

1. **Local tracking** — this tool records which Withings measurements it's
   already uploaded, so re-running over an overlapping range (e.g. a manual
   `-f`/`-t`, or a retry) skips anything it already pushed.
2. **Garmin-side check** — for whatever's left, it queries Garmin Connect's
   actual existing weight/blood-pressure entries for that date range and
   skips anything already there, regardless of source (another sync tool, a
   manual entry, a different machine). Best-effort: if this check fails, it
   logs a warning and falls back to uploading (layer 1 is still the primary
   guarantee).

Two flags for working with this:

- `--dry-run` — report what would be uploaded/skipped without uploading or
  changing any local state. Useful for a sanity check before trusting an
  automated (e.g. cron) run.
- `--force` — bypass both checks for one run and upload everything fetched,
  e.g. if you know Garmin lost some data and want to intentionally re-push
  it. Still records what it uploaded, so a normal run afterward won't
  re-trigger on the same data.

Beyond dedup: transient Withings API failures (connection errors, timeouts)
are retried automatically with backoff; the tokens file is written
atomically (a crash mid-write can't corrupt it); and a file lock prevents
two concurrent runs (e.g. an overlapping cron job) from racing on the same
state.

## Logging

Each run writes a timestamped log file under the log directory (see
[Where files are stored](#where-files-are-stored)). `--verbose` raises the
log level to DEBUG (including the resolved config/token/session paths);
default is INFO.

## Troubleshooting

Tokens/session files may be in your working directory or in the default user
data directory — see [Where files are stored](#where-files-are-stored) if
unsure. `--verbose` logs the resolved paths on every run.

**Withings token expiration / Garmin session issues:**

```bash
# Remove invalid Withings tokens and re-authenticate
rm "$(uv run python -c 'from withings2garmin import paths; print(paths.withings_tokens_file())')"

# Or clear the Garmin session and re-authenticate
rm -rf "$(uv run python -c 'from withings2garmin import paths; print(paths.garmin_session_dir())')"

uv run withings2garmin --garmin
```

**No measurements found:** verify the date range (`-f`/`-t`) covers a period
where your Withings device actually synced data.

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

Linting/formatting/hygiene checks are defined once in `hk.pkl` and run via
[`hk`](https://hk.jdx.dev) (tool versions pinned in `mise.toml` — run
`mise install` first):

```bash
hk check   # verify (lint, format-check, GH Actions security/pinning, etc.)
hk fix     # auto-fix what can be fixed

# Run tests
uv run pytest
```

If your global git hooks already invoke `hk` (per-machine setup, not
project-specific), `hk check` also runs automatically on commit/push. If not,
run `hk install` once in this repo to wire that up locally.

Dependencies are managed in `pyproject.toml`; run `uv lock --upgrade && uv sync`
to update them.

### Releases

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/)
(enforced by an `hk` `commit-msg` hook — `feat: ...`, `fix: ...`, etc.).
Pushing to `master` automatically bumps the version and publishes a GitHub
Release when a commit warrants it: `feat:` → minor, `fix:` → patch,
`BREAKING CHANGE:`/`!` → major. The package version itself is derived from
the latest git tag (via `hatch-vcs`) — nothing to bump by hand.

## License

MIT — see `pyproject.toml`.
