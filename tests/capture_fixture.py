#!/usr/bin/env python3
"""Capture a built fixture app as a small, shareable test fixture.

    python3 tests/capture_fixture.py tests/fixture-app tests/fixtures/next16

Run it after `next build` in the app. It writes:

    <dest>/out/      the export, with every JavaScript file replaced by a
                     one-line placeholder. The tool only needs the file names;
                     the real chunks are Next.js and React, large, and under
                     their own licences.
    <dest>/next/     .next/BUILD_ID and the client reference manifests, with the
                     absolute project path replaced by "[project]/" (the form
                     Turbopack already uses), so no local path is committed.
    <dest>/source.json   the Next.js and React versions that built it.

HTML, payload files, CSS, images and everything else are copied unchanged.
"""

import json
import shutil
import sys
from pathlib import Path

JS_SUFFIXES = (".js", ".mjs", ".cjs")


def capture(app: Path, dest: Path) -> None:
    out, build = app / "out", app / ".next"
    if not (out / "index.html").is_file() or not (build / "BUILD_ID").is_file():
        sys.exit(f"capture_fixture: build {app} first (no out/index.html or .next/BUILD_ID)")
    if dest.exists():
        shutil.rmtree(dest)

    for path in sorted(out.rglob("*")):
        target = dest / "out" / path.relative_to(out)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.name.endswith(JS_SUFFIXES) and "_next" in path.relative_to(out).parts:
            target.write_text(f"/* placeholder for a Next.js build file of {path.stat().st_size} bytes */\n")
        else:
            shutil.copy2(path, target)

    roots = sorted({app.absolute().as_posix().rstrip("/") + "/", app.resolve().as_posix().rstrip("/") + "/"}, key=len, reverse=True)
    (dest / "next").mkdir(parents=True)
    shutil.copy2(build / "BUILD_ID", dest / "next" / "BUILD_ID")
    for path in sorted((build / "server" / "app").rglob("*_client-reference-manifest.js")):
        text = path.read_text(encoding="utf-8")
        for root in roots:
            text = text.replace(root, "[project]/")
        target = dest / "next" / path.relative_to(build)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    versions = {}
    for package in ("next", "react", "react-dom"):
        meta = app / "node_modules" / package / "package.json"
        if meta.is_file():
            versions[package] = json.loads(meta.read_text(encoding="utf-8"))["version"]
    (dest / "source.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
    print(f"captured {app} ({', '.join(f'{k} {v}' for k, v in versions.items())}) into {dest}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    capture(Path(sys.argv[1]), Path(sys.argv[2]))
