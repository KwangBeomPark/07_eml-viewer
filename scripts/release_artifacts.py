"""Integrity and no-overwrite promotion for the locally signed release pipeline.

Authenticode is checked by ReleasePipeline.ps1.
This module never signs, builds, installs, deletes old releases or publishes.
Standard single installer release format:
- App07_EmlViewer-Setup_v{version}.exe
- build-manifest.json
- SHA256SUMS.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_identity(root: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args]).decode("utf-8")

    names = sorted(
        set(
            git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(
                "\0"
            )
        )
        - {""}
    )
    digest = hashlib.sha256()
    for name in names:
        path = root / name
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(
            (sha256(path) if path.is_file() else "<missing>").encode("ascii") + b"\0"
        )
    return {
        "commit": git("rev-parse", "HEAD").strip(),
        "dirty": bool(git("status", "--porcelain")),
        "fingerprint": digest.hexdigest(),
    }


def leaf(name: str) -> str:
    if (
        not name
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or ":" in name
        or name in (".", "..")
    ):
        raise ValueError(f"Invalid artifact name: {name!r}")
    return name


def names(version: str) -> dict[str, str]:
    if not version or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Version must use numeric major.minor.patch format")
    return {
        "installer": f"App07_EmlViewer_Setup_v{version}.exe",
        "manifest": f"App07_EmlViewer_v{version}-manifest.json",
        "sums": f"App07_EmlViewer_v{version}-SHA256SUMS.txt",
    }


def package(stage: Path, version: str) -> None:
    bundle = stage / "dist" / "EmlViewer"
    if bundle.exists():
        for forbidden in bundle.rglob("UserSetting*"):
            raise ValueError(f"Forbidden settings directory packaged: {forbidden}")
    artifacts = stage / "artifacts"
    n = names(version)
    installer = artifacts / n["installer"]
    if not installer.is_file():
        raise FileNotFoundError(f"Missing installer: {installer}")


def write_manifest(stage: Path, version: str, receipt: dict) -> Path:
    n = names(version)
    artifacts = stage / "artifacts"
    installer_file = n["installer"]
    installer_path = artifacts / installer_file
    installer_hash = sha256(installer_path)
    manifest = {
        "schema": 1,
        "product": "App07_EmlViewer",
        "version": version,
        **receipt,
        "artifacts": {installer_file: installer_hash},
    }
    output = artifacts / n["manifest"]
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (artifacts / n["sums"]).write_text(
        f"{installer_hash}  {installer_file}\n",
        encoding="utf-8",
    )
    return output


def verify(folder: Path, version: str, expected_source: dict) -> dict:
    n = names(version)
    manifest_file = folder / n["manifest"]
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Missing manifest: {manifest_file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != 1
        or manifest.get("product") != "App07_EmlViewer"
        or manifest.get("version") != version
    ):
        raise ValueError("Release identity mismatch")
    if (
        manifest.get("source") != expected_source
        or manifest.get("tests") != "pytest tests -q: passed"
        or manifest.get("signing_tests") != "Test-ReleaseSigning.ps1: passed"
        or manifest.get("backup_tests") != "test_user_data_backup.ps1: passed"
        or manifest.get("source", {}).get("dirty") is not False
    ):
        raise ValueError("Source or test provenance mismatch")
    if not manifest.get("signer_thumbprint") or not manifest.get("signed_payloads"):
        raise ValueError("Missing signing provenance")
    required_signed = {"EmlViewer/EmlViewer.exe", n["installer"]}
    if not required_signed.issubset(manifest.get("signed_payloads", {}).keys()):
        raise ValueError("Missing required signed payload entry")
    expected_files = {n["installer"]}
    if set(manifest["artifacts"]) != expected_files:
        raise ValueError("Unexpected or missing release artifact")
    for name, digest in manifest["artifacts"].items():
        path = folder / leaf(name)
        if path.is_symlink() or sha256(path) != digest:
            raise ValueError(f"Artifact mismatch: {name}")
    installer_name = n["installer"]
    expected_sums = f"{manifest['artifacts'][installer_name]}  {installer_name}\n"
    sums_file = folder / n["sums"]
    if not sums_file.is_file() or sums_file.read_text(encoding="utf-8") != expected_sums:
        raise ValueError("Checksum ledger mismatch")
    for signature in manifest["signed_payloads"].values():
        if (
            signature.get("status") != "Valid"
            or signature.get("signer_thumbprint", "").upper()
            != manifest["signer_thumbprint"].upper()
            or not signature.get("timestamp_thumbprint")
        ):
            raise ValueError("Signature provenance mismatch")
    return manifest


def preflight(release: Path, version: str) -> None:
    n = names(version)
    artifacts = [*n.values()]
    release = release.absolute()
    for ancestor in (release, *release.parents):
        if ancestor.exists() and (
            ancestor.is_symlink()
            or (hasattr(ancestor, "is_junction") and ancestor.is_junction())
        ):
            raise ValueError("Release path must not use reparse points")
    for name in artifacts:
        destination = release / leaf(name)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Existing official artifact is protected: {name}")


def promote(stage: Path, release: Path, version: str, source: dict) -> None:
    folder = stage / "artifacts"
    manifest = verify(folder, version, source)
    n = names(version)
    artifacts = [*manifest["artifacts"], n["sums"], n["manifest"]]
    release = release.absolute()
    preflight(release, version)
    release.mkdir(parents=True, exist_ok=True)
    created: list[tuple[Path, str, tuple[int, int, int, int]]] = []
    pending: list[Path] = []
    try:
        for name in artifacts:
            with tempfile.NamedTemporaryFile(
                dir=release, prefix=".app07-stage-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                pending.append(temporary)
                with (folder / name).open("rb") as original:
                    shutil.copyfileobj(original, stream)
                stream.flush()
                os.fsync(stream.fileno())
            expected_hash = sha256(folder / name)
            if sha256(temporary) != expected_hash:
                raise ValueError("Promotion copy mismatch")
            snapshot = temporary.stat()
            identity = (
                snapshot.st_dev,
                snapshot.st_ino,
                snapshot.st_size,
                snapshot.st_mtime_ns,
            )
            destination = release / name
            os.link(temporary, destination)
            created.append((destination, expected_hash, identity))
            temporary.unlink()
            pending.remove(temporary)
        verify(release, version, source)
    except BaseException as original_error:
        retained = []
        for path, expected_hash, identity in reversed(created):
            try:
                snapshot = path.lstat()
                current_identity = (
                    snapshot.st_dev,
                    snapshot.st_ino,
                    snapshot.st_size,
                    snapshot.st_mtime_ns,
                )
                if (
                    not stat.S_ISREG(snapshot.st_mode)
                    or current_identity != identity
                    or sha256(path) != expected_hash
                ):
                    retained.append(str(path))
                    continue
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                retained.append(str(path))
        if retained:
            raise RuntimeError(
                "Promotion failed; rollback retained externally changed or unavailable new files: "
                + ", ".join(retained)
            ) from original_error
        raise
    finally:
        for path in pending:
            path.unlink(missing_ok=True)


def assert_authenticode(stage: Path, version: str, source: dict) -> None:
    folder = stage / "artifacts"
    manifest = verify(folder, version, source)
    with tempfile.TemporaryDirectory(prefix="signature-check-", dir=stage) as temporary:
        output = Path(temporary)
        installer = folder / names(version)["installer"]
        shutil.copy2(installer, output / installer.name)
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_name("VerifySignatures.ps1")),
                "-Directory",
                str(output),
                "-CertificateThumbprint",
                manifest["signer_thumbprint"],
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "identity",
            "package",
            "manifest",
            "verify",
            "promote",
            "extract",
            "preflight",
        ),
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--release", type=Path)
    args = parser.parse_args()
    if args.action == "identity":
        print(json.dumps(source_identity(args.root)))
        return
    if args.action == "preflight":
        preflight(args.release, args.version)
        return
    receipt = (
        json.loads((args.stage / "receipt.json").read_text(encoding="utf-8-sig"))
        if args.action not in ("package",)
        else None
    )
    if args.action == "package":
        package(args.stage, args.version)
    elif args.action == "manifest":
        write_manifest(args.stage, args.version, receipt)
    elif args.action == "promote":
        if source_identity(args.root) != receipt["source"]:
            raise ValueError("Source changed before promotion")
        assert_authenticode(args.stage, args.version, receipt["source"])
        promote(args.stage, args.release, args.version, receipt["source"])
    elif args.action in ("verify", "extract"):
        folder = args.release or args.stage / "artifacts"
        verify(folder, args.version, receipt["source"])


if __name__ == "__main__":
    main()
