# Release audit — App07 EML Viewer

Audit date: 2026-10-10. Baseline HEAD: `8abeb22829fa0c39a5afa3dea247a72fd36e22bd`.
Independent Codex review of the Gemini handoff.

## Contract

Exactly three directly uploaded assets for the chosen version:
- `App07_EmlViewer_Setup_v<version>.exe`
- `App07_EmlViewer_v<version>-manifest.json`
- `App07_EmlViewer_v<version>-SHA256SUMS.txt`

The previous audit's installer spelling and generic metadata names were incorrect. The manual publication checklist is `RELEASE_CHECKLIST.md` at the repository root, not `docs/RELEASE_CHECKLIST.md`.

`scripts/release_artifacts.py` verifies product/version/source provenance, installer hash, checksum ledger and signing receipts; promotion rejects collisions and preserves older official version files. Merely storing a signature receipt is not independent live signature verification. The root checklist therefore separately requires `VerifySignatures.ps1`, remote tag-commit verification, draft creation, download/name/hash/signature verification and publication.

There is no automated GitHub publisher wrapper in this project. Checklist compliance remains user-controlled and must not be reported as an automatically enforced end-to-end gate. The checklist now explicitly checks draft identity/state and signature command success before publication, and checks the final public asset state afterward.

## Verification

`.venv/Scripts/python.exe -m pytest tests/test_release_artifacts.py -q --basetemp <new owned build fixture directory>` — **34 tests passed**. Tests cover collision protection, rollback, source/hash/ledger mismatches, unsafe paths, provenance and real-signature gate rejection of fake receipts. No live signing or publication occurred.

The first run's tests reached completion but pytest exited with WinError 5 while cleaning the shared system temporary directory. It was not counted as a successful run. Rerunning with a new project-owned temporary directory exited successfully; no ACLs or shared temporary files were changed.

## Remaining gates

Preserve published v0.1.17 and its bytes/tag. Future binary changes require a new version, clean reviewed source, interactive user signing, actual installed-app/upgrade/UserSetting/EML association acceptance, and checklist-driven verified draft publication. Existing valid signing/release staging and historical generic metadata are preservation evidence, not deletion candidates.
