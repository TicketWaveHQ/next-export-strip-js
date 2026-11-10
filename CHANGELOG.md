# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [0.1.0] - 2026-11-10

First release.

### Added

- `next_export_strip_js.py`: a standard-library Python 3.10+ command that removes the Next.js runtime from an App Router static export. It removes the runtime `<script>` tags, the inline React Server Components payload scripts, the Turbopack bootstrap script and the preload hints for those files from every page, and deletes the JavaScript under `_next/static` and the `.txt` payload files.
- Refusal, with nothing changed, when the build manifest lists a client component other than the Next.js internals the tool knows to be safe; when a page has a script the tool does not recognise, an inline event handler, a React late-content script or a client-side rendering marker; when the export is from the Pages Router; and when a page's payload refers to a client module the manifest does not list.
- Checks that `.next` is from the build that wrote the export (`BUILD_ID`), a self-check of the rewritten pages before anything is written, and a stop, with nothing changed, if the export contains a symbolic link.
- `data-keep` on a `<script>` tag, and `--keep PATTERN`, to keep your own scripts.
- `--dry-run`, `--next-dir` and a report of what was removed, by category, in bytes.
- An optional npm wrapper (`bin/next-export-strip-js.js`) and `pyproject.toml` for `pip install`.
- Tests on synthetic exports and on recorded builds from Next.js 14.2.35, 15.5.29 and 16.4.6, and a CI job that builds a real app with each of those versions (16.4.6 with both Turbopack and webpack) and runs the tool on it.

[0.1.0]: https://github.com/TicketWaveHQ/next-export-strip-js/releases/tag/v0.1.0
