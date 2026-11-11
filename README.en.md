<div align="center">

<img src="docs/icon.png" width="128" alt="Anonymiseur icon">

# Anonymiseur

**Strip the metadata from your files, and mask what they contain, without sending anything over the Internet.**

[![MIT License](https://img.shields.io/badge/license-MIT-1f6f50)](LICENSE)
![macOS](https://img.shields.io/badge/macOS-12%2B-1f6f50)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-1f6f50)
![Standalone](https://img.shields.io/badge/nothing%20to%20install-%E2%9C%93-1f6f50)

[Version française](README.md) · [Download](../../releases/latest)

<img src="docs/screenshots/02-file-attente.png" width="860" alt="Anonymiseur: queued files, pick your actions, Launch button">

</div>

> The app interface is in French. / L'interface de l'application est en français.

## What it does

A photo, a PDF or a Word document holds far more than what you see: **where and when** it was made, **with which device
and software**, **by whom**, sometimes **with which AI**. Anonymiseur removes those traces, checks that none are left,
and shows you exactly what it found.

- **Erases metadata**: dates, GPS position, device, author, software, thumbnails, AI signatures (C2PA, Stable
  Diffusion/ComfyUI generation prompts…), editing identifiers, comment authors' names.
- **Shows the "detected origin"** before cleaning (device, software, author, place, AI hints) and confirms nothing is left
  afterwards.
- **Leak check**: searches the final file for every name or serial number that was in it before. If one comes back, it is
  shown in red.
- **Masks the content** (separate button): e-mails, phone numbers, IBANs, bank cards, social security numbers, paths, IP
  addresses, authors' names and your own words, inside the text of PDF, Word, Excel, PowerPoint, draw.io, SVG and plain
  text or code files.
- **Sets your own metadata** (separate button): author, title, date, GPS location, device, software of your choice.
- **Every action is an independent button**: anonymize the file without touching its content, or the opposite, or both.
  Your choices are remembered.
- **You stay in control**: drop files, pick actions, then click **"Lancer"** (Launch). Nothing starts by itself.
- **Folders and archives** (ZIP, tar.gz): processed file by file, structure kept.
- **Originals are never modified**: the result is always a copy.

### Supported formats

| Family | Formats |
|---|---|
| Images | JPEG, PNG, WebP, GIF, TIFF, HEIC, PSD (Photoshop) |
| Documents | PDF, Word, Excel, PowerPoint, OpenDocument (ODT/ODS/ODP) |
| Drawing | draw.io (`.drawio`, `.dio`, `.drawio.svg`, `.drawio.png`), SVG (Inkscape, Illustrator) |
| Audio / video | MP4, MOV, MKV, AVI, MP3, M4A, WAV, FLAC, OGG… |
| Archives | ZIP, TAR, GZ, TGZ |
| Web / text | HTML, `.po` translation files, text and code (content masking only) |

Code, text files and fonts carry no personal metadata: they are copied as-is (in folders) or reported as "no metadata".

## Screenshots

| | |
|---|---|
| ![Home](docs/screenshots/01-accueil.png) | ![Result on a photo](docs/screenshots/03-resultat-photo.png) |
| **Home**: drop, choose, launch. | **Result**: detected origin, leak check, before/after. |
| ![Masked content](docs/screenshots/05-contenu-masque.png) | ![Your metadata](docs/screenshots/06-mes-metadonnees.png) |
| **Content masked** in a Word document. | **Your own metadata** in place of the originals. |
| ![Folder](docs/screenshots/07-dossier.png) | ![Result on a document](docs/screenshots/04-resultat-document.png) |
| **A whole folder**, file by file. | An **author's name** left in the text is flagged. |

*All the data shown is fictitious (see `examples/`).*

## Installation

1. Download `Anonymiseur-1.0-arm64.dmg` from the [releases page](../../releases/latest).
2. Open the `.dmg` and **drag Anonymiseur into Applications**.
3. **First launch**: the app is ad-hoc signed but **not notarized by Apple** (that requires a paid developer account), so
   macOS blocks it the first time:
   - **right-click** Anonymiseur → **Open** → **Open**; or
   - in Terminal: `xattr -dr com.apple.quarantine /Applications/Anonymiseur.app`

**Nothing else to install**: Python, FFmpeg and ExifTool are bundled in the app (≈ 105 MB). No Internet connection is
needed; the engine only listens on `127.0.0.1` and contacts no server.

You can verify the download with the SHA-256 shown on the release page: `shasum -a 256 Anonymiseur-1.0-arm64.dmg`

## Getting started

1. **Drop** files or folders into the window (or click to pick them, or right-click → *Open With* → Anonymiseur in the
   Finder). They appear under "Prêts à traiter" (ready to process).
2. **Pick the actions** (buttons): erase metadata, random file name, mask content, etc.
3. Click **"Lancer l'anonymisation"**, then **Télécharger** each result (or **Tout enregistrer…** to save them all).

Fictitious sample files are in [`examples/`](examples).

## Compatibility and known limits

**What was tested**

- Apple Silicon Mac running **macOS 26.6.2**.
- The app's engine was run **without Homebrew** (a `sandbox-exec` profile forbidding `/opt/homebrew` and `/usr/local`) and
  passed the test suite (32 test files × 5 option combinations, i.e. 711 checks, `tests/run_tests.py`).
- Opening files from the Finder (queued without automatic processing) was tried in the real window.

**What was not tested**

- Another Mac, or another macOS version: the **macOS 12** minimum is computed from the bundled binaries but was not
  verified on a machine running macOS 12 to 15.
- The first launch with Gatekeeper quarantine on a downloaded `.dmg`.
- With the mouse, in the window: drag-and-drop, "Tout enregistrer…", "Original à la corbeille" (move to Trash), report
  export.
- **Intel Macs** are not supported (Apple Silicon only).

**Cleaning limits (please read)**

- Some traces are **in the content itself** and cannot be erased: a camera sensor's own noise, invisible AI watermarks
  (e.g. SynthID), writing style. The "re-encoded images" mode erases the file structure but not those traces.
- Text **visible inside an image or video** is not read (no text recognition), so it is not masked.
- **MKV**: the library itself writes an `encoder=Lavf` marker that cannot be removed.
- **PSD**: each layer's modification date is kept (removing it could corrupt the file).
- **Word / Excel**: an e-mail split into several pieces by the word processor may escape masking.
- **Folders**: file and folder names are kept so the structure stays intact.
- **Unsupported formats**: Affinity (`.afpub`…), InDesign, Sketch, password-protected ZIP. The app says so; export to PDF or
  an image first, then anonymize the export.
- Anonymizing does not guarantee anonymity: the text of a document, a face or a recognizable place in a photo remain.

## Build from source

Requirements: an Apple Silicon Mac, the **Xcode command line tools** (`xcode-select --install`), and **ExifTool** for the
build only (`brew install exiftool`). An Internet connection is needed the first time.

```bash
./build_app.sh            # downloads and verifies components (SHA-256), builds a minimal FFmpeg, builds dist/Anonymiseur.app
./make_dmg.sh             # builds dist/Anonymiseur-1.0-arm64.dmg and its SHA-256 checksum
./build_app.sh --install  # alternative: build, then install into /Applications
```

The script checks that no personal path from your machine ends up inside the app.

## Code layout

```
src/cleaners.py     engine: cleaning, masking, inspection, leak check
src/server.py       small local server (127.0.0.1) between the window and the engine
src/index.html      interface (French, light theme)
src/main.swift      macOS window (WebKit); launches the bundled engine
src/pdfflat.swift   tool that redraws and blacks out PDFs (PDFKit)
scripts/            verified download of components, FFmpeg build, screenshots
tests/              fake test-file generator and test suite
examples/           fictitious sample files
build_app.sh        builds the standalone app ;  make_dmg.sh: builds the .dmg
```

## Tests

```bash
.deps/python/bin/python3 tests/run_tests.py          # after a first ./build_app.sh
```

The test fails if a test file is missing, so it can never "pass" by testing nothing.

## Contributing

Reports of badly handled formats and proposals (issues, pull requests) are welcome. Run the tests above before sending a
change. **Never add real files or personal data** to the repository: use fictitious data.

## License

[MIT](LICENSE) © 2026 Wudstyz. Bundled components have their own licenses: see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Trademarks mentioned belong to their owners; this project is not
affiliated with any of these companies.
