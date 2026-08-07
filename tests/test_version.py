"""version.py için temel testler."""

from version import __version__, __version_tuple__, APP_NAME


def test_version_matches_tuple():
    assert __version__ == ".".join(map(str, __version_tuple__))


def test_app_name_set():
    assert APP_NAME and isinstance(APP_NAME, str)
