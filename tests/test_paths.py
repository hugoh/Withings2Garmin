from withings2garmin import paths


def test_config_dir_uses_env_override(monkeypatch, tmp_path):
    override = tmp_path / "cfg"
    monkeypatch.setenv("WITHINGS2GARMIN_CONFIG_DIR", str(override))

    result = paths.config_dir()

    assert result == override
    assert result.is_dir()


def test_config_dir_falls_back_to_platformdirs(monkeypatch, tmp_path):
    monkeypatch.delenv("WITHINGS2GARMIN_CONFIG_DIR", raising=False)
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir", lambda name: str(tmp_path / name)
    )

    result = paths.config_dir()

    assert result == tmp_path / paths.APP_NAME
    assert result.is_dir()


def test_data_dir_and_log_dir_use_env_overrides(monkeypatch, tmp_path):
    data_override = tmp_path / "data"
    log_override = tmp_path / "log"
    monkeypatch.setenv("WITHINGS2GARMIN_DATA_DIR", str(data_override))
    monkeypatch.setenv("WITHINGS2GARMIN_LOG_DIR", str(log_override))

    assert paths.data_dir() == data_override
    assert paths.log_dir() == log_override


def test_resolve_env_file_uses_explicit_override(monkeypatch, tmp_path):
    override = tmp_path / "custom.env"
    monkeypatch.setenv("WITHINGS2GARMIN_CONFIG_FILE", str(override))

    assert paths.resolve_env_file() == override


def test_resolve_env_file_prefers_cwd_env(monkeypatch, tmp_path):
    monkeypatch.delenv("WITHINGS2GARMIN_CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FOO=bar\n")

    assert paths.resolve_env_file().resolve() == tmp_path / ".env"


def test_resolve_env_file_falls_back_to_config_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("WITHINGS2GARMIN_CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    config_override = tmp_path / "cfgdir"
    monkeypatch.setenv("WITHINGS2GARMIN_CONFIG_DIR", str(config_override))

    assert paths.resolve_env_file() == config_override / "config.env"


def test_withings_tokens_file_uses_env_override(monkeypatch, tmp_path):
    override = tmp_path / "tokens.json"
    monkeypatch.setenv("WITHINGS_TOKENS_FILE", str(override))

    assert paths.withings_tokens_file() == override


def test_withings_tokens_file_prefers_cwd_file(monkeypatch, tmp_path):
    monkeypatch.delenv("WITHINGS_TOKENS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".withings_tokens.json").write_text("{}")

    assert paths.withings_tokens_file().resolve() == tmp_path / ".withings_tokens.json"


def test_withings_tokens_file_falls_back_to_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("WITHINGS_TOKENS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)  # no cwd tokens file
    data_override = tmp_path / "datadir"
    monkeypatch.setenv("WITHINGS2GARMIN_DATA_DIR", str(data_override))

    assert paths.withings_tokens_file() == data_override / "withings_tokens.json"


def test_garmin_session_dir_uses_env_override(monkeypatch, tmp_path):
    override = tmp_path / "session"
    monkeypatch.setenv("GARMIN_SESSION_DIR", str(override))

    assert paths.garmin_session_dir() == override


def test_garmin_session_dir_prefers_cwd_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_SESSION_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".garmin_session").mkdir()

    assert paths.garmin_session_dir().resolve() == tmp_path / ".garmin_session"


def test_garmin_session_dir_falls_back_to_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("GARMIN_SESSION_DIR", raising=False)
    monkeypatch.chdir(tmp_path)  # no cwd session dir
    data_override = tmp_path / "datadir"
    monkeypatch.setenv("WITHINGS2GARMIN_DATA_DIR", str(data_override))

    assert paths.garmin_session_dir() == data_override / "garmin_session"
