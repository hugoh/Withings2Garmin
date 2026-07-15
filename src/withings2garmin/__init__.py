from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("withings2garmin-hugoh")
except PackageNotFoundError:
    __version__ = "unknown"
