"""Keep default settings and legacy migration sources in isolated test folders."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_user_data(tmp_path_factory):
    root = tmp_path_factory.mktemp("eml-viewer-user-data")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LOCALAPPDATA", str(root / "Local"))
        patch.setenv("APPDATA", str(root / "Roaming"))
        patch.setenv("USERPROFILE", str(root / "Profile"))
        yield root


@pytest.fixture(autouse=True)
def isolated_working_directory(tmp_path, monkeypatch):
    """Avoid creating runtime results beside repository source during tests."""
    monkeypatch.chdir(tmp_path)
