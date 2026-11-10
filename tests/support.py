"""Shared helpers: synthetic exports, a snapshot of a directory tree, and running the CLI."""

import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(REPO))

import next_export_strip_js as tool  # noqa: E402

BUILD_ID = "testbuild123"

# Client modules every App Router build lists, keyed as Turbopack writes them.
FRAMEWORK_MODULES = {
    "[project]/node_modules/next/dist/esm/client/components/layout-router.js": 39756,
    "[project]/node_modules/next/dist/esm/client/components/render-from-template-context.js": 37457,
    "[project]/node_modules/next/dist/client/app-dir/link.js": 22016,
}


def run(*args):
    """Run the CLI in-process. Returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = tool.main([str(a) for a in args])
        except SystemExit as exc:  # argparse exits for --version and --help
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def snapshot(root: Path) -> dict:
    """Every file under root, relative path to SHA-256, plus every directory."""
    result = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        result[rel] = "dir" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def rows_for(module_ids) -> str:
    """RSC rows that refer to the given client module ids, like a real payload."""
    lines = ['1:"$Sreact.fragment"']
    for n, module_id in enumerate(module_ids, start=2):
        lines.append(f'{n:x}:I[{json.dumps(module_id)},["$1"],""]')
    lines.append('0:{"b":"%s","c":["",""]}' % BUILD_ID)
    return "\n".join(lines) + "\n"


def next_page(body="<main><h1>Hello</h1></main>", head="", tail="", module_ids=(39756, 22016)):
    """A page shaped like a Next.js App Router export."""
    rows = rows_for(module_ids)
    return (
        '<!DOCTYPE html><html lang="en-GB"><head><meta charSet="utf-8"/>'
        '<link rel="stylesheet" href="/_next/static/css/site.css" data-precedence="next"/>'
        '<link rel="preload" as="script" fetchPriority="low" href="/_next/static/chunks/webpack-1.js"/>'
        '<script src="/_next/static/chunks/main-app-1.js" async=""></script>'
        f"<title>Test</title>{head}</head><body>{body}"
        '<script src="/_next/static/chunks/webpack-1.js" id="_R_" async=""></script>'
        "<script>(self.__next_f=self.__next_f||[]).push([0])</script>"
        f"<script>self.__next_f.push({json.dumps([1, rows])})</script>"
        f"{tail}</body></html>"
    )


def manifest_js(route: str, modules: dict) -> str:
    client_modules = {
        key: {"id": module_id, "name": "*", "chunks": ["/_next/static/chunks/main-app-1.js"], "async": False}
        for key, module_id in modules.items()
    }
    data = {"moduleLoading": {"prefix": ""}, "clientModules": client_modules, "ssrModuleMapping": {}}
    return (
        "globalThis.__RSC_MANIFEST = globalThis.__RSC_MANIFEST || {};\n"
        f"globalThis.__RSC_MANIFEST[{json.dumps(route)}] = {json.dumps(data)};\n"
    )


class Site:
    """A synthetic Next.js export in a temporary directory: <root>/out and <root>/.next."""

    def __init__(self, root: Path):
        self.root = root
        self.out = root / "out"
        self.next = root / ".next"
        self.out.mkdir(parents=True)
        (self.next / "server" / "app").mkdir(parents=True)
        (self.next / "BUILD_ID").write_text(BUILD_ID)
        self.write(f"_next/static/{BUILD_ID}/_buildManifest.js", "self.__BUILD_MANIFEST={};")
        self.write("_next/static/chunks/main-app-1.js", "/* runtime */" * 50)
        self.write("_next/static/chunks/webpack-1.js", "/* webpack */" * 20)
        self.write("_next/static/css/site.css", "body{margin:0}")
        self.manifest("/page", FRAMEWORK_MODULES)

    def write(self, rel: str, content, under=None) -> Path:
        path = (under or self.out) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def page(self, rel: str, html: str = None, payload: bool = True, **kwargs) -> Path:
        """Write a page, and (like Next.js) its .txt payload beside it."""
        path = self.write(rel, html if html is not None else next_page(**kwargs))
        if payload:
            ids = kwargs.get("module_ids", (39756, 22016))
            self.write(rel[: -len(".html")] + ".txt", rows_for(ids))
        return path

    def manifest(self, route: str, modules: dict) -> Path:
        folder = route.strip("/").rsplit("/", 1)[0] if "/" in route.strip("/") else ""
        name = route.rstrip("/").rsplit("/", 1)[-1]
        rel = f"server/app/{folder + '/' if folder else ''}{name}_client-reference-manifest.js"
        return self.write(rel, manifest_js(route, modules), under=self.next)

    def read(self, rel: str) -> str:
        return (self.out / rel).read_text(encoding="utf-8")


class SiteTestCase(unittest.TestCase):
    """Each test gets a fresh synthetic site with a home page."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.site = Site(Path(self._tmp.name) / "site")
        self.site.page("index.html")

    def strip(self, *extra):
        return run(self.site.out, *extra)

    def assertRefused(self, *needles, args=()):
        before = snapshot(self.site.root)
        code, out, err = self.strip(*args)
        self.assertEqual(code, tool.EXIT_REFUSED, msg=out + err)
        self.assertIn("refusing, and nothing was changed", err)
        for needle in needles:
            self.assertIn(needle, err)
        self.assertEqual(snapshot(self.site.root), before, "a refusal must not change anything")
        return err


def copy_fixture(name: str, dest: Path) -> tuple:
    """Copy a recorded build into dest. Returns (export dir, build dir)."""
    source = FIXTURES / name
    shutil.copytree(source / "out", dest / "out")
    shutil.copytree(source / "next", dest / ".next")
    return dest / "out", dest / ".next"


SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")


def visible_text(html: str) -> str:
    """The text a visitor reads: tags and script bodies removed."""
    return TAGS.sub(" ", SCRIPT.sub(" ", html)).split()
