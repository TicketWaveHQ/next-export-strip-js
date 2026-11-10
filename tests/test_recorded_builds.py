"""Real Next.js exports, recorded from tests/fixture-app with tests/capture_fixture.py.

Each fixture is the output of `next build` with one Next.js version, with the
JavaScript files replaced by placeholders (see capture_fixture.py). These run
offline; test_live_build.py runs the same checks on a fresh build in CI.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, copy_fixture, run, snapshot, tool, visible_text

SCRIPT_TAG = re.compile(r"<script\b([^>]*)>", re.I)


def check_stripped(test, out: Path, before: dict, texts: dict):
    """Assertions shared with the live build test."""
    after = snapshot(out)
    for rel in sorted(before):
        path = out / rel
        if rel.startswith("_next/static/") and rel.endswith(".js"):
            test.assertFalse(path.exists(), f"{rel} should be deleted")
        elif rel.endswith(".txt") and rel != "robots.txt":
            test.assertFalse(path.exists(), f"payload {rel} should be deleted")
        elif rel.endswith((".css", ".png", "robots.txt", "js/site.js")):
            test.assertEqual(after.get(rel), before[rel], f"{rel} should be unchanged")
    for rel, words in texts.items():
        html = (out / rel).read_text(encoding="utf-8")
        test.assertEqual(visible_text(html), words, f"the visible text of {rel} changed")
        for attrs in SCRIPT_TAG.findall(html):
            test.assertTrue(
                "data-keep" in attrs or "application/ld+json" in attrs,
                f"{rel} still has <script{attrs}>",
            )
        test.assertNotIn("__next_f", html)
        test.assertIsNone(re.search(r'(?:src|href)="[^"]*/_next/static/[^"]*\.js"', html), rel)
        test.assertIn('<script data-keep="true" src="/js/site.js" defer="">', html)
    home = (out / "index.html").read_text(encoding="utf-8")
    test.assertIn('<script type="application/ld+json">', home)
    test.assertRegex(home, r'<link rel="stylesheet" href="/_next/static/[^"]+\.css"')


def page_texts(out: Path) -> dict:
    return {p.relative_to(out).as_posix(): visible_text(p.read_text(encoding="utf-8")) for p in out.rglob("*.html")}


class RecordedBuilds(unittest.TestCase):
    def strip_fixture(self, name):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out, build = copy_fixture(name, Path(tmp.name))
        before, texts = snapshot(out), page_texts(out)
        code, report, err = run(out)
        return out, build, before, texts, code, report, err

    def test_each_version_strips_cleanly(self):
        for name in ("next14", "next15", "next16"):
            versions = json.loads((FIXTURES / name / "source.json").read_text())
            with self.subTest(fixture=name, next=versions.get("next")):
                out, _, before, texts, code, report, err = self.strip_fixture(name)
                self.assertEqual(code, tool.EXIT_OK, msg=err)
                check_stripped(self, out, before, texts)
                self.assertIn("ignored app/error.js", report)
                self.assertIn("/js/site.js (data-keep) on 6 pages" if name == "next16" else "/js/site.js (data-keep) on 5 pages", report)

    def test_the_interactive_build_is_refused_and_untouched(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out, _ = copy_fixture("next16-interactive", Path(tmp.name))
        before = snapshot(Path(tmp.name))
        code, _, err = run(out)
        self.assertEqual(code, tool.EXIT_REFUSED)
        self.assertIn("client component: app/counter/Counter.js", err)
        self.assertIn("on: /counter", err)
        self.assertNotIn("app/error.js", err)
        self.assertEqual(snapshot(Path(tmp.name)), before)


if __name__ == "__main__":
    unittest.main()
