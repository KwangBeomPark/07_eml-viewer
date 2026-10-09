"""Failure injection exercises production release helpers without real signing."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "release_artifacts", Path(__file__).parents[1] / "scripts" / "release_artifacts.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
VERSION = "0.1.99"
SOURCE = {"commit": "a" * 40, "dirty": False, "fingerprint": "b" * 64}


@pytest.fixture
def staged(tmp_path):
    stage = tmp_path / "stage"
    folder = stage / "artifacts"
    folder.mkdir(parents=True)
    bundle = stage / "dist" / "EmlViewer"
    bundle.mkdir(parents=True)
    (bundle / "EmlViewer.exe").write_bytes(b"mock signed main")
    (bundle / "data.txt").write_bytes(b"resource")
    (folder / release.names(VERSION)["installer"]).write_bytes(b"mock signed installer")
    release.package(stage, VERSION)
    receipt = {
        "source": SOURCE,
        "tests": "pytest tests -q: passed",
        "signing_tests": "Test-ReleaseSigning.ps1: passed",
        "backup_tests": "test_user_data_backup.ps1: passed",
        "signer_thumbprint": "TEST-SIGNER",
        "signed_payloads": {
            name: {
                "status": "Valid",
                "signer_thumbprint": "TEST-SIGNER",
                "timestamp_thumbprint": "TEST-TIMESTAMP",
            }
            for name in ("EmlViewer/EmlViewer.exe", release.names(VERSION)["installer"])
        },
        "payload_hashes": {
            "EmlViewer/" + path.name: release.sha256(path) for path in bundle.iterdir()
        },
    }
    release.write_manifest(stage, VERSION, receipt)
    return stage, receipt


def test_valid_set_promotes_without_changing_previous_release(staged, tmp_path):
    stage, _ = staged
    official = tmp_path / "release"
    official.mkdir()
    (official / "old.exe").write_bytes(b"old signed release")
    (official / "SHA256SUMS.txt").write_bytes(b"old ledger")
    release.promote(stage, official, VERSION, SOURCE)
    release.verify(official, VERSION, SOURCE)
    assert (official / "old.exe").read_bytes() == b"old signed release"
    assert (official / "SHA256SUMS.txt").read_bytes() == b"old ledger"
    assert not list(official.glob(".app07-stage-*"))


def test_same_version_collision_has_no_partial_output(staged, tmp_path):
    stage, _ = staged
    official = tmp_path / "release"
    official.mkdir()
    existing = official / release.names(VERSION)["installer"]
    existing.write_bytes(b"previous official installer")
    with pytest.raises(FileExistsError):
        release.promote(stage, official, VERSION, SOURCE)
    assert list(official.iterdir()) == [existing]
    assert existing.read_bytes() == b"previous official installer"


@pytest.mark.parametrize("failure", ["link", "copy", "verification"])
def test_failure_rolls_back_only_new_owned_artifacts(
    staged, tmp_path, monkeypatch, failure
):
    stage, _ = staged
    official = tmp_path / "release"
    official.mkdir()
    sentinel = official / "old.exe"
    sentinel.write_bytes(b"keep")
    if failure == "verification":
        original = release.verify

        def verify(folder, *args):
            if folder == official:
                raise ValueError("injected final verification failure")
            return original(folder, *args)

        monkeypatch.setattr(release, "verify", verify)
    else:
        original = release.os.link if failure == "link" else shutil.copyfileobj
        calls = 0

        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected write failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(
            release.os if failure == "link" else shutil,
            "link" if failure == "link" else "copyfileobj",
            fail,
        )
    with pytest.raises((OSError, ValueError)):
        release.promote(stage, official, VERSION, SOURCE)
    assert list(official.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"keep"


@pytest.mark.parametrize("field", ["commit", "fingerprint", "dirty"])
def test_wrong_source_is_rejected(staged, field):
    stage, _ = staged
    expected = {**SOURCE, field: "different"}
    with pytest.raises(ValueError, match="provenance"):
        release.verify(stage / "artifacts", VERSION, expected)


@pytest.mark.parametrize("mutation", ["content", "replacement"])
def test_rollback_preserves_externally_changed_new_destination(
    staged, tmp_path, monkeypatch, mutation
):
    stage, _ = staged
    official = tmp_path / "release"
    official.mkdir()
    old = official / "old.exe"
    old.write_bytes(b"previous official")
    destination = official / release.names(VERSION)["installer"]
    original_link = release.os.link
    calls = 0

    def changed_then_fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if mutation == "content":
                destination.write_bytes(b"external writer update")
            else:
                replacement = official / "foreign.tmp"
                replacement.write_bytes(destination.read_bytes())
                release.os.replace(replacement, destination)
            raise OSError("injected failure after concurrent update")
        return original_link(*args, **kwargs)

    monkeypatch.setattr(release.os, "link", changed_then_fail)
    with pytest.raises(
        RuntimeError, match="rollback retained externally changed"
    ) as error:
        release.promote(stage, official, VERSION, SOURCE)
    assert isinstance(error.value.__cause__, OSError)
    assert str(destination) in str(error.value)
    assert set(official.iterdir()) == {old, destination}
    assert old.read_bytes() == b"previous official"
    expected = (
        b"external writer update" if mutation == "content" else b"mock signed installer"
    )
    assert destination.read_bytes() == expected


def test_corrupted_artifact_is_rejected(staged):
    stage, _ = staged
    (stage / "artifacts" / release.names(VERSION)["installer"]).write_bytes(b"bad")
    with pytest.raises(ValueError, match="Artifact mismatch"):
        release.verify(stage / "artifacts", VERSION, SOURCE)


def test_manifest_with_unexpected_artifact_is_rejected(staged):
    stage, _ = staged
    manifest_path = stage / "artifacts" / release.names(VERSION)["manifest"]
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["artifacts"]["extra.exe"] = "0" * 64
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected or missing release artifact"):
        release.verify(stage / "artifacts", VERSION, SOURCE)


def test_tampered_installer_is_rejected_with_manifest_mismatch(staged):
    stage, receipt = staged
    installer = stage / "artifacts" / release.names(VERSION)["installer"]
    installer.write_bytes(b"tampered content")
    with pytest.raises(ValueError, match="Artifact mismatch"):
        release.verify(stage / "artifacts", VERSION, SOURCE)


@pytest.mark.parametrize(
    "value", ["../escape.exe", "C:escape.exe", "sub/file.exe", "sub\\file.exe"]
)
def test_leaf_names_reject_escape(value):
    with pytest.raises(ValueError):
        release.leaf(value)


@pytest.mark.parametrize("value", ["..", "1..2", "1.2", "../1.2.3"])
def test_version_requires_three_numeric_components(value):
    with pytest.raises(ValueError, match="major.minor.patch"):
        release.names(value)


def test_settings_never_packaged(staged):
    stage, _ = staged
    settings = stage / "dist" / "EmlViewer" / "UserSetting"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "settings.json").write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="UserSetting"):
        release.package(stage, VERSION)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-exe",
        "missing-timestamp",
        "wrong-signer",
        "failed-tests",
        "failed-signing-tests",
        "failed-backup-tests",
        "dirty-source",
    ],
)
def test_incomplete_provenance_is_rejected(staged, mutation):
    stage, receipt = staged
    if mutation == "missing-exe":
        receipt["signed_payloads"].pop("EmlViewer/EmlViewer.exe")
    elif mutation == "missing-timestamp":
        receipt["signed_payloads"]["EmlViewer/EmlViewer.exe"][
            "timestamp_thumbprint"
        ] = ""
    elif mutation == "wrong-signer":
        receipt["signed_payloads"]["EmlViewer/EmlViewer.exe"]["signer_thumbprint"] = (
            "OTHER"
        )
    elif mutation == "failed-tests":
        receipt["tests"] = "not run"
    elif mutation == "failed-signing-tests":
        receipt["signing_tests"] = "not run"
    elif mutation == "failed-backup-tests":
        receipt["backup_tests"] = "not run"
    else:
        receipt["source"] = {**SOURCE, "dirty": True}
    release.write_manifest(stage, VERSION, receipt)
    with pytest.raises(ValueError):
        release.verify(stage / "artifacts", VERSION, receipt["source"])


def test_checksum_ledger_tamper_is_rejected(staged):
    stage, _ = staged
    (stage / "artifacts" / release.names(VERSION)["sums"]).write_text(
        "bad", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ledger"):
        release.verify(stage / "artifacts", VERSION, SOURCE)


def test_real_signature_gate_rejects_fake_json_receipt(staged):
    stage, _ = staged
    # These bytes have no real Authenticode signature despite the fake test receipt.
    with pytest.raises(subprocess.CalledProcessError):
        release.assert_authenticode(stage, VERSION, SOURCE)
    assert not list(stage.glob("signature-check-*"))


def test_promotion_junction_target_rejected(staged, tmp_path):
    if not hasattr(Path, "is_junction"):
        pytest.skip("Junction detection requires Python 3.12+")
    stage, _ = staged
    target = tmp_path / "target"
    target.mkdir()
    junction = tmp_path / "release-link"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(ValueError, match="reparse"):
            release.promote(stage, junction, VERSION, SOURCE)
        assert not list(target.iterdir())
    finally:
        junction.rmdir()
