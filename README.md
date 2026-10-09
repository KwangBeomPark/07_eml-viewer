# EML Viewer

English | [한국어](README.ko.md)

EML Viewer is a Windows-first desktop app for opening `.eml` and Outlook `.msg` email files with a layout that behaves like a normal desktop window and renders HTML email bodies with Qt WebEngine.

## Why This Exists

I started this project because the default email viewer I used at work did not behave well with Windows window snapping shortcuts such as `Win + Left` and `Win + Right`. What began as a small viewer for reading email files has gradually become a convenience-focused alternative to the default email reader: easier window handling, clearer metadata, readable plain text and HTML views, inline image rendering, and attachment saving.

This is an open project. The documentation intentionally avoids company names, internal system names, real email content, and other confidential details.

## Features

- Open a single `.eml` or `.msg` file from the app or from a file association.
- Display subject, sender, To, Cc, and date, with one-click copy feedback.
- Show Plain Text and HTML body tabs.
- Render HTML email with Qt WebEngine for better table, CSS, and inline image support.
- Resolve embedded `cid:` images, `Content-Location` images, relative image paths, CSS `url(...)`, and `srcset` references.
- Block remote images by default, with a setting to show external images automatically.
- Translate the current message body between Korean, English, and Polish.
- Forward mail as plain text and HTML while preserving embedded images and attaching the original email file.
- Enter multiple forwarding recipients with commas and reuse recent recipient groups.
- Show and save attachments.
- Resize the window freely and preserve the last size and position.
- Check GitHub Releases for updates.
- Show user-friendly error dialogs instead of closing unexpectedly.

## Quick Manual

![EML Viewer quick manual](assets/manual-en.png)

1. Open an `.eml` or `.msg` file from the app.
2. Use the HTML tab for the closest rendering of the original message, including embedded images.
3. Select Translate to create a translated reading view without changing the source file.
4. Forward a message with one or more comma-separated recipients. Successful recipient groups appear in the next forwarding dialog.
5. Resize the window as needed; its size and position are restored the next time you open the app.

## Install For General Use

The Windows installer is intended for users who do not have Python installed.

1. Download and run `App07_EmlViewer_Setup_v<version>.exe`.
2. Keep the file association option enabled if you want `.eml` and `.msg` files to open with EML Viewer.
3. After installation, launch `EML Viewer` from the Start menu or double-click an `.eml` or `.msg` file.

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the app:

```powershell
python -m eml_viewer
```

Open a sample file directly:

```powershell
python -m eml_viewer .\samples\example_plain_text.eml
```

Run tests:

```powershell
python -m unittest discover -s tests
```

## Build

Build the Windows app folder:

```powershell
python -m pip install -e ".[build]"
.\scripts\build_windows.ps1
```

The unsigned output is created in `dist\EmlViewer`. Signing a development bundle
requires explicit `-Signed` and a certificate thumbprint. Use the release pipeline below
for the complete signed distribution.

Build the Windows installer:

```powershell
python -m pip install -e ".[build]"
.\scripts\build_installer.ps1
```

Inno Setup 6 or 7 is required. This command creates an **unsigned preview** in a unique
`build\release-staging\<id>\artifacts` folder and never changes `release\`.

For a new signed release, commit the reviewed source, install `pytest`, activate your signing session and run:

```powershell
.\scripts\sign_and_release.ps1 -CertificateThumbprint $env:SIGN_CERT_THUMBPRINT
```

The pipeline tests and fingerprints the source, signs all bundled EXEs before
packaging and signs one installer, `App07_EmlViewer_Setup_v<version>.exe`.
Signatures, hashes and a version-specific manifest/checksum list are verified
before promotion. Installer aliases and ZIP packages are no longer generated.
Existing official files are never overwritten; use a
new version for the next release. No command above publishes or installs the app.
See the current [release checklist and remaining Windows checks](RELEASE_CHECKLIST.md).

## Design Notes

- UI code and email parsing logic are kept separate.
- `EmlParser` parses the message and classifies attachments versus inline resources.
- `MessageBodyWidget` prepares HTML resources and renders the body.
- HTML rendering uses Qt WebEngine because accurate email body rendering is more important than keeping the package as small as possible.
- Remote images are blocked by default to reduce tracking and privacy risk.
- Attachment saving follows a preview, confirm, execute flow.

## Privacy And Public Repository Notes

- Do not commit real email files, company data, internal URLs, credentials, or customer information.
- The included sample uses `example.com` addresses only.
- Before publishing a release, scan tracked files for secrets or confidential strings.

Useful checks:

```powershell
git grep -n -I -i -E "api[_-]?key|secret|token|password|credential|client_secret|private key|confidential|internal|proprietary" -- .
git grep -n -I -E "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|https?://" -- .
```


Shared installation, settings, release goals, and current exceptions are documented in [Suite standardization](docs/SUITE_STANDARDIZATION.md).

Packaging definitions are maintained in `installer/eml_viewer.spec` and `installer/setup.iss`.
The previous `packaging/` entry points delegate to these files for compatibility.
[Public code map](docs/CODE_MAP.md) describes module responsibilities and storage.
[Backup and verified restore](docs/USER_DATA.md) and the Windows PowerShell
[backup tool](scripts/Manage-UserData.ps1) preserve UserSetting; original emails,
saved attachments and PDFs require separate backups. Settings displays the actual saved folder.
See [settings, layout and UI verification](docs/STANDARDIZATION_PHASE3_5_REVIEW.md).
