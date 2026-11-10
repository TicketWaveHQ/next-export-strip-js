"""The tool on a fresh `next build` of tests/fixture-app. Skipped unless CI sets it up.

    NEXT_EXPORT_STRIP_JS_APP=tests/fixture-app NEXT_EXPORT_STRIP_JS_EXPECT=strip \\
        python3 -m unittest discover -s tests

NEXT_EXPORT_STRIP_JS_EXPECT is "strip" for the app as committed, or "refuse" after
CI has copied variants/interactive into it. The build is copied to a temporary
directory first, so the real JavaScript is stripped without changing the app,
and so webpack's absolute paths no longer match where the build directory is.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support import run, snapshot, tool
from test_recorded_builds import check_stripped, page_texts

APP = os.environ.get("NEXT_EXPORT_STRIP_JS_APP")
EXPECT = os.environ.get("NEXT_EXPORT_STRIP_JS_EXPECT", "strip")


@unittest.skipUnless(APP, "set NEXT_EXPORT_STRIP_JS_APP to a built fixture app to run")
class LiveBuild(unittest.TestCase):
    def setUp(self):
        app = Path(APP)
        if not (app / "out" / "index.html").is_file():
            self.fail(f"{app} has not been built: run `npm run build` in it first")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "app"
        shutil.copytree(app / "out", self.root / "out")
        shutil.copytree(app / ".next", self.root / ".next", ignore=shutil.ignore_patterns("cache", "trace*"))
        self.out = self.root / "out"

    @unittest.skipUnless(EXPECT == "strip", "the app is expected to be refused")
    def test_strips_the_real_runtime(self):
        before, texts = snapshot(self.out), page_texts(self.out)
        js_before = sum(1 for rel in before if rel.startswith("_next/static/") and rel.endswith(".js"))
        self.assertGreater(js_before, 0, "a real build ships JavaScript")
        code, dry, err = run(self.out, "--dry-run")
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertEqual(snapshot(self.out), before)
        code, report, err = run(self.out)
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        print("\n" + report)
        check_stripped(self, self.out, before, texts)
        self.assertIn("ignored app/error.js", report)
        code, again, _ = run(self.out)
        self.assertEqual(code, tool.EXIT_OK)
        self.assertIn("nothing to remove", again)

    @unittest.skipUnless(EXPECT == "refuse", "the app is expected to be stripped")
    def test_refuses_the_interactive_variant(self):
        before = snapshot(self.root)
        code, _, err = run(self.out)
        print("\n" + err)
        self.assertEqual(code, tool.EXIT_REFUSED)
        self.assertIn("client component: app/counter/Counter.js", err)
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
