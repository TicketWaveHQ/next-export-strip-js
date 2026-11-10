#!/usr/bin/env python3
"""Remove the Next.js runtime from a static export when no page needs it.

    python3 next_export_strip_js.py out

A Next.js app built with ``output: 'export'`` writes complete HTML for every
page. It then adds the React runtime, the client router and a second copy of
each page's content (the React Server Components payload) so that React can
take the page over in the browser. When no page has a client component, none
of that changes what a visitor sees or can do. This tool removes it.

It refuses, and changes nothing, when anything in the build says a page needs
JavaScript in the browser: a client component in the build manifest, a script
it does not recognise as part of the Next.js runtime, an inline event handler,
or a part of a page that React would render in the browser.

Standard library only. Python 3.10 or later. See README.md.
"""

from __future__ import annotations

import argparse
import fnmatch
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

__version__ = "0.1.0"

if sys.version_info < (3, 10):
    sys.exit("next-export-strip-js needs Python 3.10 or later")

PROG = "next-export-strip-js"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

# Client components that ship with Next.js and do nothing a visitor needs once
# the page is static HTML. Paths are relative to next/dist, without the esm/
# prefix or the file extension. Anything not listed here refuses, so a new
# Next.js release that adds a client component fails closed until it has been
# checked and added.
FRAMEWORK_SAFE = {
    # The App Router's own building blocks. They let the client router swap
    # segments during navigation; without the router there is nothing to swap.
    "client/components/app-router": "the App Router",
    "client/components/layout-router": "the App Router",
    "client/components/render-from-template-context": "the App Router",
    "client/components/client-page": "the App Router",
    "client/components/client-segment": "the App Router",
    "client/components/error-boundary": "an error boundary",
    "client/components/not-found-boundary": "an error boundary",
    "client/components/http-access-fallback/error-boundary": "an error boundary",
    "client/components/builtin/global-error": "the built-in error page",
    "client/components/metadata/async-metadata": "metadata streaming",
    "lib/framework/boundary-components": "metadata streaming",
    "lib/metadata/generate/icon-mark": "metadata streaming",
    # next/link renders a plain <a href>. Without JavaScript a click is an
    # ordinary page load: no client-side navigation and no prefetching.
    "client/link": "next/link",
    "client/app-dir/link": "next/link",
    # next/image renders a plain <img>, with loading="lazy", and srcset and
    # sizes when a loader provides them.
    "client/image-component": "next/image",
}

# Next.js client components that do work in the browser, named so that the
# refusal can say what would stop working.
FRAMEWORK_NEEDS_JS = {
    "client/script": "next/script: the scripts it loads would no longer load",
    "client/form": "next/form: its client-side navigation would stop",
}

# Webpack lists imported stylesheets among the client modules. They are styles,
# not code, and the CSS files they become are never deleted.
STYLESHEET = re.compile(r"\.(?:css|scss|sass|less|styl|pcss)$")

# app/error.js and app/global-error.js must be client components, but React
# only renders them in the browser, after an error in the browser. A static
# export has no such errors once the runtime has gone, so they are ignored.
ERROR_FILE = re.compile(r"^(?:src/)?app/(?:[^/]+/)*(?:global-)?error\.(?:js|jsx|ts|tsx|mjs|cjs)$")

# The JavaScript MIME types from the HTML standard, plus "module". A <script>
# with any other type (JSON-LD, importmap, a template) is a data block.
JS_TYPES = {
    "",
    "module",
    "application/ecmascript",
    "application/javascript",
    "application/x-ecmascript",
    "application/x-javascript",
    "text/ecmascript",
    "text/javascript",
    "text/javascript1.0",
    "text/javascript1.1",
    "text/javascript1.2",
    "text/javascript1.3",
    "text/javascript1.4",
    "text/javascript1.5",
    "text/jscript",
    "text/livescript",
    "text/x-ecmascript",
    "text/x-javascript",
}

JS_SUFFIXES = (".js", ".mjs", ".cjs")

TAG = re.compile(
    r"""<([A-Za-z][A-Za-z0-9:-]*)"""
    r"""((?:\s+[^\s"'>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)"""
    r"""\s*(/?)>"""
)
ATTR = re.compile(r"""([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")
RAW_TEXT = ("script", "style", "textarea", "title")
CLOSE_TAG = {name: re.compile(r"</%s\s*>" % name, re.I) for name in RAW_TEXT}

# The inline scripts Next.js writes. The payload scripts carry the page's
# content a second time, as React Server Components rows, for hydration.
PAYLOAD_SCRIPT = re.compile(r"^(?:\(self\.__next_f\s*=\s*self\.__next_f\s*\|\|\s*\[\]\)|self\.__next_f)\.push\(")
TURBOPACK_SCRIPT = re.compile(r"""^\(globalThis(?:\[["']TURBOPACK["']\]|\.TURBOPACK)\s*\|\|""")
PUSH_CALL = re.compile(r"self\.__next_f\.push\(")
# React's own inline scripts that move late Suspense content into place ($RC and friends).
REACT_REVEAL = re.compile(r"\$R[A-Z]\b")

# A client reference row in an RSC payload: `3:I[22016,["..."],""]`.
CLIENT_ROW = re.compile(r'(?m)^[0-9a-f]+:I\[\s*("(?:[^"\\]|\\.)*"|[^,\]\s]+)')
# A payload file starts with a row (`0:`, `1:I[`) or a resource hint row (`:HL[`).
PAYLOAD_FILE_HEAD = re.compile(rb"^(?:[0-9a-f]{1,8}:|:H[A-Za-z]?\[)")
MANIFEST_ENTRY = re.compile(r'__RSC_MANIFEST\[("(?:[^"\\]|\\.)*")\]\s*=\s*')


class UsageError(Exception):
    """The input is not what the tool needs. Nothing was changed."""


class InternalCheckError(Exception):
    """The plan failed its own check before anything was written."""


@dataclass
class Element:
    start: int
    end: int
    name: str
    attrs: dict
    content: str = ""


@dataclass
class Finding:
    """One reason to refuse."""

    kind: str
    subject: str
    detail: str
    places: list = field(default_factory=list)


@dataclass
class Page:
    path: Path
    rel: str
    text: str
    removals: list = field(default_factory=list)  # (start, end, category)
    links: list = field(default_factory=list)  # (Element, export-relative target)
    new_text: str = ""


@dataclass
class Plan:
    export_dir: Path
    next_dir: Path
    dry_run: bool = False
    build_id: str = ""
    pages: list = field(default_factory=list)
    left_alone: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    removed: dict = field(default_factory=dict)  # category -> (count, bytes)
    deletions: list = field(default_factory=list)  # (Path, category, size)
    kept_scripts: dict = field(default_factory=dict)  # label -> set of pages
    kept_files: set = field(default_factory=set)
    data_blocks: int = 0
    client_ids: dict = field(default_factory=dict)  # module id -> set of places
    modules: dict = field(default_factory=dict)  # display path -> (kind, label, routes)
    ignored: list = field(default_factory=list)
    next_dirs: list = field(default_factory=list)
    export_bytes: int = 0
    nothing_to_do: bool = False


# Categories, in report order.
CAT_PAYLOAD = "inline RSC payload scripts"
CAT_RUNTIME = "runtime script tags"
CAT_PRELOAD = "script preload hints"
CAT_JS = "JavaScript files under _next/static"
CAT_MAPS = "source maps for those files"
CAT_TXT = "RSC payload files (.txt)"
HTML_CATS = (CAT_PAYLOAD, CAT_RUNTIME, CAT_PRELOAD)
FILE_CATS = (CAT_JS, CAT_MAPS, CAT_TXT)


def parse_attrs(raw: str) -> dict:
    attrs = {}
    for m in ATTR.finditer(raw):
        name = m.group(1).lower()
        if m.group(2) is not None:
            value = m.group(2)
        elif m.group(3) is not None:
            value = m.group(3)
        else:
            value = m.group(4)
        attrs.setdefault(name, None if value is None else html.unescape(value))
    return attrs


def elements(doc: str):
    """Yield every start tag in an HTML document, with the text of raw-text elements.

    Comments, end tags and doctypes are skipped. This is enough for the HTML that
    React writes, which is regular; it is not a general HTML parser.
    """
    pos = 0
    n = len(doc)
    while True:
        lt = doc.find("<", pos)
        if lt < 0:
            return
        if doc.startswith("<!--", lt):
            end = doc.find("-->", lt + 4)
            pos = n if end < 0 else end + 3
            continue
        if doc.startswith(("</", "<!", "<?"), lt):
            end = doc.find(">", lt)
            pos = n if end < 0 else end + 1
            continue
        m = TAG.match(doc, lt)
        if not m:
            pos = lt + 1
            continue
        name = m.group(1).lower()
        attrs = parse_attrs(m.group(2))
        if name in RAW_TEXT:
            close = CLOSE_TAG[name].search(doc, m.end())
            content_end = close.start() if close else n
            end = close.end() if close else n
            yield Element(lt, end, name, attrs, doc[m.end():content_end])
            pos = end
        else:
            yield Element(lt, m.end(), name, attrs)
            pos = m.end()


def url_path(url: str) -> str:
    return unquote(url.split("#", 1)[0].split("?", 1)[0])


def static_target(url: str | None) -> str | None:
    """The export-relative path of a URL that points into _next/static, or None."""
    if not url:
        return None
    path = url_path(url)
    i = path.find("/_next/static/")
    if i >= 0:
        return path[i + 1:]
    if path.startswith("_next/static/"):
        return path
    return None


def is_executable(script: Element) -> bool:
    kind = (script.attrs.get("type") or "").split(";", 1)[0].strip().lower()
    return kind in JS_TYPES


def keep_match(src: str, patterns) -> bool:
    path = url_path(src)
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path.lstrip("/"), p.lstrip("/")) for p in patterns)


def classify_script(script: Element, keep_patterns) -> str:
    """Return data, kept, runtime, payload or unknown."""
    if not is_executable(script):
        return "data"
    if "data-keep" in script.attrs:
        return "kept"
    src = script.attrs.get("src")
    if src is not None:
        if keep_match(src, keep_patterns):
            return "kept"
        if static_target(src):
            return "runtime"
        return "unknown"
    body = script.content.strip()
    if PAYLOAD_SCRIPT.match(body):
        return "payload"
    if TURBOPACK_SCRIPT.match(body):
        return "runtime"
    return "unknown"


def payload_text(script_body: str) -> str:
    """The RSC rows carried by the inline payload scripts of one page."""
    parts = []
    decoder = json.JSONDecoder()
    for m in PUSH_CALL.finditer(script_body):
        try:
            value, _ = decoder.raw_decode(script_body, m.end())
        except ValueError:
            continue
        if isinstance(value, list) and len(value) >= 2 and value[0] == 1 and isinstance(value[1], str):
            parts.append(value[1])
    return "".join(parts)


def client_ids_in(rows: str):
    for m in CLIENT_ROW.finditer(rows):
        value = m.group(1)
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        yield str(value)


def snippet(text: str, limit: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", "surrogateescape")


def write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", "surrogateescape"))


def text_bytes(text: str) -> int:
    return len(text.encode("utf-8", "surrogateescape"))


class Findings:
    """Collect reasons to refuse, grouping the same reason across pages."""

    def __init__(self):
        self.by_key = {}

    def add(self, kind: str, subject: str, detail: str, place: str | None = None):
        key = (kind, subject)
        finding = self.by_key.get(key)
        if finding is None:
            finding = self.by_key[key] = Finding(kind, subject, detail)
        if place and place not in finding.places:
            finding.places.append(place)

    def __bool__(self):
        return bool(self.by_key)

    def all(self):
        return list(self.by_key.values())


def scan_page(page: Page, keep_patterns, plan: Plan, findings: Findings, flight: list):
    """Classify every tag on one page. Removals are decided later, once all pages are read."""
    payload_bodies = []
    for el in elements(page.text):
        for name in el.attrs:
            if len(name) > 2 and name.startswith("on") and name[2:].isalpha():
                findings.add(
                    "inline event handler",
                    f"{name}= on <{el.name}>",
                    "an inline handler can call code that this tool would delete; "
                    "move it into a script you keep",
                    page.rel,
                )
        if el.name == "template" and ("data-dgst" in el.attrs or "data-msg" in el.attrs):
            findings.add(
                "client-side rendering",
                f"<template data-dgst=\"{el.attrs.get('data-dgst') or ''}\">",
                "React leaves this marker where part of a page could not be rendered at build "
                "time and must be rendered in the browser",
                page.rel,
            )
        if el.name == "script":
            if el.attrs.get("id") == "__NEXT_DATA__":
                findings.add(
                    "Pages Router export",
                    "<script id=\"__NEXT_DATA__\">",
                    "every Pages Router page hydrates, so the build cannot show which pages "
                    "need React; this tool supports the App Router only",
                    page.rel,
                )
                continue
            kind = classify_script(el, keep_patterns)
            if kind == "data":
                plan.data_blocks += 1
            elif kind == "kept":
                src = el.attrs.get("src")
                how = "data-keep" if "data-keep" in el.attrs else "--keep"
                label = f"{url_path(src)} ({how})" if src else "an inline script (data-keep)"
                plan.kept_scripts.setdefault(label, set()).add(page.rel)
                target = static_target(src)
                if target:
                    plan.kept_files.add(target)
            elif kind == "payload":
                page.removals.append((el.start, el.end, CAT_PAYLOAD))
                payload_bodies.append(el.content)
            elif kind == "runtime":
                page.removals.append((el.start, el.end, CAT_RUNTIME))
            else:
                src = el.attrs.get("src")
                body = el.content.strip()
                if REACT_REVEAL.search(body):
                    detail = ("React writes this to reveal content that finished rendering late; "
                              "removing it would leave that content hidden")
                else:
                    detail = ("not part of the Next.js runtime, so this tool will not guess whether "
                              "the page needs it; add data-keep to the tag to keep it"
                              + (" (or pass --keep)" if src else "")
                              + ", or remove it from the source")
                findings.add(
                    "unrecognised script",
                    f"<script src=\"{snippet(src)}\">" if src else f"<script>{snippet(body)}</script>",
                    detail,
                    page.rel,
                )
        elif el.name == "link":
            target = static_target(el.attrs.get("href"))
            if target and target.endswith(JS_SUFFIXES):
                page.links.append((el, target))
    rows = "".join(payload_text(body) for body in payload_bodies)
    if rows:
        flight.append((page.rel, rows))


def payload_files(export_dir: Path, files, html_files: set):
    """The .txt files Next.js writes beside each page for the client router."""
    found = []
    for path in files:
        if path.suffix != ".txt":
            continue
        rel_parts = path.relative_to(export_dir).parts
        if rel_parts[:1] == ("_next",):
            continue
        if not (path.name.startswith("__next.") or path.with_suffix(".html") in html_files):
            continue
        with path.open("rb") as f:
            head = f.read(16)
        if PAYLOAD_FILE_HEAD.match(head):
            found.append(path)
    return found


def route_label(manifest_key: str) -> str:
    route = manifest_key
    for suffix in ("/page", "/route"):
        if route.endswith(suffix):
            route = route[: -len(suffix)]
            break
    return route or "/"


def module_relpath(key: str, roots, relative_app_dir: str = "") -> str:
    """A manifest key as a path relative to the app.

    Webpack keys are absolute paths from where the build ran; Turbopack keys start
    with "[project]/", which is the workspace root (the app's parent in a monorepo).
    Query strings (next/font adds them) and Turbopack's " <module evaluation>"
    style suffixes are dropped.
    """
    path = key.replace("\\", "/").split(" <", 1)[0].split("#", 1)[0].split("?", 1)[0]
    if path.startswith("[project]/"):
        rel = path[len("[project]/"):]
        prefix = relative_app_dir.strip("/")
        if prefix and rel.startswith(prefix + "/"):
            rel = rel[len(prefix) + 1:]
        return rel
    for root in roots:
        if path.startswith(root):
            return path[len(root):]
    return path


def classify_module(rel: str):
    """Return (kind, label, name) for a client module path relative to the project.

    Next.js modules are named by their path under next/dist, so that the CommonJS
    and ESM copies that webpack builds list separately count once.
    """
    if STYLESHEET.search(rel):
        return "stylesheet", "a stylesheet", rel
    marker = "node_modules/next/dist/"
    i = rel.rfind(marker)
    if i >= 0:
        tail = rel[i + len(marker):]
        if tail.startswith("esm/"):
            tail = tail[4:]
        tail = re.sub(r"\.(?:js|mjs|cjs)$", "", tail)
        name = "next/dist/" + tail
        if tail in FRAMEWORK_SAFE:
            return "framework", FRAMEWORK_SAFE[tail], name
        return "framework-needs-js", FRAMEWORK_NEEDS_JS.get(
            tail, "a Next.js client component this tool does not know to be safe to remove"
        ), name
    if "/node_modules/" in "/" + rel:
        return "client", "a client component from a package", rel
    if ERROR_FILE.match(rel):
        return "error-boundary", "an error boundary, which React only renders in the browser after an error there", rel
    return "client", "a client component", rel


def read_manifests(next_dir: Path):
    """Yield (route, clientModules) from every client reference manifest of the build."""
    app_dir = next_dir / "server" / "app"
    if not app_dir.is_dir():
        raise UsageError(
            f"{next_dir}/server/app does not exist. This tool needs the App Router build "
            "directory from the same `next build` that wrote the export."
        )
    files = sorted(app_dir.rglob("*_client-reference-manifest.js"))
    if not files:
        raise UsageError(f"no client reference manifests under {app_dir}: cannot see which client components the pages use.")
    decoder = json.JSONDecoder()
    for path in files:
        text = read_text(path)
        entries = 0
        for m in MANIFEST_ENTRY.finditer(text):
            try:
                route = json.loads(m.group(1))
                data, _ = decoder.raw_decode(text, m.end())
            except ValueError as exc:
                raise UsageError(f"cannot read {path}: {exc}") from exc
            modules = data.get("clientModules")
            if not isinstance(modules, dict):
                raise UsageError(f"{path} has no clientModules: this Next.js version is not supported yet.")
            entries += 1
            yield route, modules
        if not entries:
            raise UsageError(f"cannot read {path}: no __RSC_MANIFEST entry found.")


def project_roots(next_dir: Path):
    """Where the app was when it was built, for reading webpack's absolute paths.

    .next/required-server-files.json records it (appDir, and relativeAppDir inside
    a monorepo); the build directory's parent is the fallback, for when it is absent.
    """
    candidates, relative_app_dir = [], ""
    meta = next_dir / "required-server-files.json"
    if meta.is_file():
        try:
            data = json.loads(read_text(meta))
        except ValueError:
            data = {}
        if isinstance(data.get("appDir"), str):
            candidates.append(data["appDir"].replace("\\", "/"))
        if isinstance(data.get("relativeAppDir"), str):
            relative_app_dir = data["relativeAppDir"].replace("\\", "/")
    project = next_dir.parent
    candidates += [project.absolute().as_posix(), project.resolve().as_posix()]
    roots = []
    for candidate in candidates:
        root = candidate.rstrip("/") + "/"
        if root not in roots:
            roots.append(root)
    return roots, relative_app_dir


def check_manifests(plan: Plan, findings: Findings):
    next_dir = plan.next_dir
    build_id_file = next_dir / "BUILD_ID"
    if not build_id_file.is_file():
        raise UsageError(
            f"{build_id_file} not found. Pass --next-dir with the build directory from the "
            "same `next build` that wrote the export (it is .next unless distDir is set)."
        )
    plan.build_id = build_id_file.read_text(encoding="utf-8").strip()
    static = plan.export_dir / "_next" / "static"
    if static.is_dir():
        exported = sorted(d.name for d in static.iterdir() if d.is_dir() and (d / "_buildManifest.js").is_file())
        if exported and plan.build_id not in exported:
            raise UsageError(
                f"{next_dir} is from build {plan.build_id}, but the export was written by build "
                f"{', '.join(exported)}. Run the tool straight after the build that wrote the export."
            )
    roots, relative_app_dir = project_roots(next_dir)
    known_ids = set()
    for route, modules in read_manifests(next_dir):
        for key, info in modules.items():
            if isinstance(info, dict) and "id" in info:
                known_ids.add(str(info["id"]))
            kind, label, name = classify_module(module_relpath(key, roots, relative_app_dir))
            if kind == "stylesheet":
                continue
            entry = plan.modules.setdefault(name, (kind, label, []))
            if route_label(route) not in entry[2]:
                entry[2].append(route_label(route))
    for rel, (kind, label, routes) in sorted(plan.modules.items()):
        if kind == "error-boundary":
            plan.ignored.append((rel, label))
        elif kind in ("client", "framework-needs-js"):
            findings.add("client component", rel, label)
            for route in sorted(routes):
                findings.add("client component", rel, label, route)
    for module_id, places in sorted(plan.client_ids.items()):
        if module_id not in known_ids:
            findings.add(
                "unknown client reference",
                f"module {module_id}",
                f"the page payload refers to a client module that is not in the manifests in {next_dir}; "
                "the build directory may not be from the build that wrote the export",
            )
            for place in sorted(places):
                findings.add("unknown client reference", f"module {module_id}", "", place)


def walk(export_dir: Path):
    """Every file and directory in the export, without following symbolic links.

    The tool rewrites and deletes files, so it refuses to work on an export that
    contains a link: a link could lead it outside the directory it was given.
    """
    files, dirs = [], []
    for root, dirnames, filenames in os.walk(export_dir, followlinks=False):
        for name in sorted(dirnames) + sorted(filenames):
            path = Path(root) / name
            if path.is_symlink():
                raise UsageError(
                    f"{path} is a symbolic link. This tool only works on a plain export "
                    "directory, so that it can never write or delete outside it."
                )
        dirs.extend(Path(root) / name for name in sorted(dirnames))
        files.extend(Path(root) / name for name in sorted(filenames))
    return files, dirs


def analyse(export_dir, next_dir=None, keep=(), dry_run=False) -> Plan:
    """Work out everything the tool would do, without changing anything."""
    export_dir = Path(export_dir)
    if not export_dir.is_dir():
        raise UsageError(f"{export_dir} is not a directory. Run `next build` with output: 'export' first.")
    if (export_dir / "package.json").is_file() or (export_dir / "node_modules").is_dir():
        raise UsageError(f"{export_dir} looks like the project directory. Pass the export directory (usually out).")
    next_dir = Path(next_dir) if next_dir else export_dir.absolute().parent / ".next"
    plan = Plan(export_dir=export_dir, next_dir=next_dir, dry_run=dry_run)
    findings = Findings()

    all_files, all_dirs = walk(export_dir)
    html_files = [p for p in all_files if p.suffix == ".html"]
    if not html_files:
        raise UsageError(f"no .html files in {export_dir}: this does not look like a static export.")
    plan.export_bytes = sum(p.stat().st_size for p in all_files)
    plan.next_dirs = [d for d in all_dirs if d.relative_to(export_dir).parts[:1] == ("_next",)]

    flight = []
    for path in html_files:
        rel = path.relative_to(export_dir).as_posix()
        text = read_text(path)
        if "/_next/" not in text and "__next_f" not in text:
            plan.left_alone.append(rel)
            continue
        page = Page(path=path, rel=rel, text=text)
        scan_page(page, keep, plan, findings, flight)
        plan.pages.append(page)

    payloads = payload_files(export_dir, all_files, set(html_files))
    for path in payloads:
        rows = read_text(path)
        flight.append((path.relative_to(export_dir).as_posix(), rows))
    for place, rows in flight:
        for module_id in client_ids_in(rows):
            plan.client_ids.setdefault(module_id, set()).add(place)

    js_files = [
        p for p in all_files
        if p.relative_to(export_dir).parts[:2] == ("_next", "static") and p.name.endswith(JS_SUFFIXES)
    ]

    if not any(page.removals for page in plan.pages) and not payloads and not js_files:
        plan.nothing_to_do = True
        return plan

    try:
        check_manifests(plan, findings)
    except UsageError:
        if not findings:
            raise
        # The export already shows why it cannot be stripped; report that.
    plan.findings = findings.all()
    if plan.findings:
        return plan

    files_set = set(all_files)
    for path in js_files:
        rel = path.relative_to(export_dir).as_posix()
        if rel in plan.kept_files:
            continue
        plan.deletions.append((path, CAT_JS, path.stat().st_size))
        source_map = path.with_name(path.name + ".map")
        if source_map in files_set:
            plan.deletions.append((source_map, CAT_MAPS, source_map.stat().st_size))
    for path in payloads:
        plan.deletions.append((path, CAT_TXT, path.stat().st_size))
    deleted = {p.relative_to(export_dir).as_posix() for p, _, _ in plan.deletions}

    for page in plan.pages:
        removals = list(page.removals)
        for el, target in page.links:
            if target in deleted:
                removals.append((el.start, el.end, CAT_PRELOAD))
        removals.sort()
        out, pos = [], 0
        for start, end, category in removals:
            out.append(page.text[pos:start])
            count, total = plan.removed.get(category, (0, 0))
            plan.removed[category] = (count + 1, total + text_bytes(page.text[start:end]))
            pos = end
        out.append(page.text[pos:])
        page.new_text = "".join(out)
    for _, category, nbytes in plan.deletions:
        count, total = plan.removed.get(category, (0, 0))
        plan.removed[category] = (count + 1, total + nbytes)

    verify(plan, deleted, keep)
    return plan


def verify(plan: Plan, deleted: set, keep) -> None:
    """Re-read every rewritten page: no runtime left, and nothing points at a deleted file."""
    for page in plan.pages:
        for el in elements(page.new_text):
            if el.name == "script" and classify_script(el, keep) in ("runtime", "payload"):
                raise InternalCheckError(f"a runtime script survived in {page.rel}: {snippet(page.new_text[el.start:el.end])}")
            for attr in ("src", "href"):
                target = static_target(el.attrs.get(attr))
                if target and target in deleted:
                    raise InternalCheckError(f"{page.rel} still refers to {target}, which would be deleted")


def apply(plan: Plan) -> None:
    for page in plan.pages:
        if page.new_text != page.text:
            write_text(page.path, page.new_text)
    parents = set()
    for path, _, _ in plan.deletions:
        path.unlink()
        parents.add(path.parent)
    # Directories emptied by the deletions, and the empty ones Next.js leaves
    # in its own _next directory. Other empty directories are not touched.
    parents.update(plan.next_dirs)
    if plan.next_dirs:
        parents.add(plan.export_dir / "_next")
    root = plan.export_dir.resolve()
    for directory in sorted(parents, key=lambda p: len(p.resolve().parts), reverse=True):
        current = directory.resolve()
        while current != root and root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def print_refusal(plan: Plan, stream) -> None:
    print(f"{PROG}: refusing, and nothing was changed.", file=stream)
    print("Something in this build says a page may need JavaScript in the browser:", file=stream)
    for finding in plan.findings:
        print(f"\n  {finding.kind}: {finding.subject}", file=stream)
        if finding.detail:
            print(f"    {finding.detail}", file=stream)
        if finding.places:
            shown = finding.places[:5]
            more = len(finding.places) - len(shown)
            where = ", ".join(shown) + (f" and {more} more" if more else "")
            print(f"    on: {where}", file=stream)
    print(
        "\nIf a page needs React, this tool is not for this site. If it does not, remove the "
        "client code (or its 'use client' line) and build again.",
        file=stream,
    )


def print_report(plan: Plan, stream) -> None:
    def w(line=""):
        print(line, file=stream)

    w(f"{PROG} {__version__}")
    w(f"Export:  {plan.export_dir} (Next.js build {plan.build_id})")
    counts = {}
    for kind, _, _ in plan.modules.values():
        counts[kind] = counts.get(kind, 0) + 1
    w(f"Checked: {len(plan.pages)} pages; {len(plan.modules)} client modules in the build manifest, "
      f"{counts.get('framework', 0)} of them part of Next.js and safe to drop")
    for rel, label in plan.ignored:
        w(f"         ignored {rel}: {label}")
    if plan.left_alone:
        w(f"         left alone: {len(plan.left_alone)} HTML files that are not Next.js pages")
    w()
    if plan.dry_run:
        w("Dry run: nothing was changed. This is what would be removed.")
        w()
    rows = [(c, *plan.removed[c]) for c in HTML_CATS if c in plan.removed]
    if rows:
        w(f"Removed from the HTML of {len(plan.pages)} pages")
        for category, count, nbytes in rows:
            w(f"  {category:<38}{count:>6}  {size(nbytes):>10}")
    rows = [(c, *plan.removed[c]) for c in FILE_CATS if c in plan.removed]
    if rows:
        w("Deleted files")
        for category, count, nbytes in rows:
            w(f"  {category:<38}{count:>6}  {size(nbytes):>10}")
    total = sum(nbytes for _, nbytes in plan.removed.values())
    w()
    w(f"Total removed: {size(total)} of {size(plan.export_bytes)}; the export is now {size(plan.export_bytes - total)}")
    kept = []
    for label, pages in sorted(plan.kept_scripts.items()):
        kept.append(f"{label} on {len(pages)} page{'s' if len(pages) != 1 else ''}")
    if plan.data_blocks:
        kept.append(f"{plan.data_blocks} data block{'s' if plan.data_blocks != 1 else ''} such as JSON-LD")
    w("Kept:    " + ("; ".join(kept) if kept else "no scripts"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Remove the Next.js runtime from a static export (output: 'export') when no page "
            "needs JavaScript. Refuses, and changes nothing, if any page does."
        ),
        epilog=(
            "Exit status: 0 done (or nothing to do), 1 refused, 2 bad input, 3 internal check "
            "failed. In every case other than 0, nothing was changed."
        ),
    )
    parser.add_argument("export_dir", nargs="?", default="out", help="the static export directory (default: out)")
    parser.add_argument(
        "--next-dir",
        metavar="DIR",
        help="the build directory from the same `next build` (default: .next beside the export directory)",
    )
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="PATTERN",
        help="keep <script src> tags whose src matches this glob, for example '/js/*'; repeatable. "
        "Tags marked data-keep are always kept",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would be removed and change nothing")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        plan = analyse(args.export_dir, args.next_dir, args.keep, args.dry_run)
    except UsageError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except InternalCheckError as exc:
        print(f"{PROG}: internal check failed, nothing was changed: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    if plan.findings:
        print_refusal(plan, sys.stderr)
        return EXIT_REFUSED
    if plan.nothing_to_do:
        print(f"{PROG}: nothing to remove in {plan.export_dir}; no Next.js runtime found.")
        return EXIT_OK
    if not plan.dry_run:
        apply(plan)
    print_report(plan, sys.stdout)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
