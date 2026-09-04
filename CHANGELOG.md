# Changelog

All notable changes to the ES3 Save Editor are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [v1.1.0] — 2026-09-04

### Added
- **Raw File view**: new tab next to the Editor showing the full decrypted
  save text, with Refresh, Copy to clipboard, and Export to `.json`/`.txt`.
  Shortcut: `Ctrl+R` (also `View` menu and toolbar button).
- **Sortable field list**: click any column header (Field, Type, Value, S)
  to sort; click again to reverse direction (▲/▼ indicator).
  Field sort is natural and case-insensitive (`Coins2 < coins9 < coins10`);
  Value sort is type-aware (numbers numerically, `false < true`, strings
  A–Z, lists/dicts by size); S sorts by category
  (safe → caution → advanced).
- **README**: project overview, feature list, and setup/build instructions.

### Fixed
- Mouse wheel now scrolls the Edit Value panel (object inspector canvas),
  the per-field raw editor, and the Raw File view — previously only
  dragging the scrollbar thumb worked.
- Replaced deprecated `datetime.utcfromtimestamp()` with timezone-aware
  `datetime.fromtimestamp(..., timezone.utc)` (Python 3.12+ warning).

### Changed
- Version bumped to 1.1.0.
- Stopped tracking sensitive/local files: `config.json` (saved passwords),
  `save_data1.es3`, and build outputs — all now covered by `.gitignore`.

## [v1.0.0] — 2026-08-21

First release.

### Added
- ES3 save editor (`main.py`, Tkinter desktop app):
  - AES-128-CBC decryption/encryption via `es3-modifier` + PBKDF2 key handling.
  - Automatic GZip detection/decompression.
  - Type-aware editors: numbers with ＋/－ steppers, booleans with
    True/False radios, strings, comma-separated list editor, DateTime
    read-only view, custom-object inspector tables, raw-block fallback.
  - Safety indicators: 🟢 Safe / 🟡 Caution / 🔴 Advanced with color-coded rows.
  - Password dialog with show/hide and per-file "remember password".
  - Recent-files welcome dialog on startup.
  - Auto-backup (`.bak`) on first save + `File → Restore Backup`.
  - Search + safety filter for the field list.
- App icons (`icon.ico`, `icon.png`) with taskbar support.
- About menu.
- `run.bat` launcher with automatic venv setup.
- PyInstaller one-file Windows build (`ES3-Save-Editor.spec`).
- GitHub Actions CI/CD (`.github/workflows/release.yml`): tag push builds
  the `.exe` and publishes a GitHub Release.

[v1.1.0]: https://github.com/Eduwilll/ES3-save-editor/releases/tag/v1.1.0
[v1.0.0]: https://github.com/Eduwilll/ES3-save-editor/releases/tag/v1.0.0
