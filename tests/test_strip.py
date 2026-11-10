"""What the tool removes, what it keeps, and how it reports it (synthetic exports)."""

import unittest

from support import BUILD_ID, SiteTestCase, next_page, run, snapshot, tool

JSON_LD = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite"}</script>'


class StripsTheRuntime(SiteTestCase):
    def test_removes_runtime_tags_payloads_and_preloads(self):
        code, out, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        html = self.site.read("index.html")
        self.assertNotIn("<script", html)
        self.assertNotIn("__next_f", html)
        self.assertNotIn('as="script"', html)
        self.assertIn("<h1>Hello</h1>", html)
        self.assertIn('<link rel="stylesheet" href="/_next/static/css/site.css"', html)

    def test_deletes_framework_javascript_and_payload_files(self):
        self.strip()
        self.assertFalse((self.site.out / "_next/static/chunks").exists(), "emptied directories go too")
        self.assertFalse((self.site.out / f"_next/static/{BUILD_ID}").exists())
        self.assertFalse((self.site.out / "index.txt").exists())
        self.assertTrue((self.site.out / "_next/static/css/site.css").is_file(), "stylesheets stay")

    def test_keeps_structured_data_and_other_data_blocks(self):
        self.site.page(
            "about.html",
            head='<script type="importmap">{"imports":{}}</script>',
            body=f"<main>{JSON_LD}"
            '<script type="application/json" id="config">{"a":1}</script></main>',
        )
        code, out, _ = self.strip()
        self.assertEqual(code, tool.EXIT_OK)
        html = self.site.read("about.html")
        self.assertIn(JSON_LD, html)
        self.assertIn('<script type="application/json" id="config">{"a":1}</script>', html)
        self.assertIn('<script type="importmap">', html)
        self.assertIn("3 data blocks such as JSON-LD", out)

    def test_leaves_files_outside_next_alone(self):
        self.site.write("robots.txt", "User-agent: *\nAllow: /\n")
        self.site.write("notes.txt", "1: not a payload, because there is no notes.html\n")
        self.site.write("js/unused.js", "console.log('not referenced, but not ours to delete');")
        self.site.write("images/logo.svg", "<svg></svg>")
        (self.site.out / "empty").mkdir()
        self.strip()
        for rel in ("robots.txt", "notes.txt", "js/unused.js", "images/logo.svg"):
            self.assertTrue((self.site.out / rel).is_file(), rel)
        self.assertTrue((self.site.out / "empty").is_dir(), "empty directories outside _next are not touched")

    def test_a_txt_beside_a_page_is_deleted_only_if_it_is_a_payload(self):
        self.site.page("guide.html", payload=False)
        self.site.write("guide.txt", "A plain text version of the guide.\n")
        self.site.page("contact.html")
        self.strip()
        self.assertTrue((self.site.out / "guide.txt").is_file())
        self.assertFalse((self.site.out / "contact.txt").exists())

    def test_deletes_segment_payloads_and_hint_rows(self):
        # Next.js 16 writes per-segment payloads, and a payload can open with a hint row.
        self.site.page("about.html")
        self.site.write("about/__next._tree.txt", ':HL["/_next/static/css/site.css","style"]\n2:[["children"]]\n')
        self.site.write("about/__next.about.__PAGE__.txt", '1:"$Sreact.fragment"\n')
        self.strip()
        self.assertFalse((self.site.out / "about").exists())

    def test_url_encoded_chunk_paths_are_matched(self):
        chunk = "_next/static/chunks/app/posts/[slug]/page-1.js"
        self.site.write(chunk, "/* page chunk */")
        self.site.page(
            "posts/first.html",
            head='<link rel="preload" as="script" href="/_next/static/chunks/app/posts/%5Bslug%5D/page-1.js"/>'
            '<script src="/_next/static/chunks/app/posts/%5Bslug%5D/page-1.js" async=""></script>',
        )
        code, _, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertFalse((self.site.out / chunk).exists())
        self.assertNotIn("%5Bslug%5D", self.site.read("posts/first.html"))

    def test_asset_prefix_and_base_path_urls(self):
        self.site.page(
            "docs.html",
            head='<script src="https://cdn.example.com/_next/static/chunks/main-app-1.js" async=""></script>'
            '<script src="/docs/_next/static/chunks/webpack-1.js?dpl=abc" async=""></script>',
        )
        code, _, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertNotIn("<script", self.site.read("docs.html"))

    def test_source_maps_go_with_their_files(self):
        self.site.write("_next/static/chunks/main-app-1.js.map", "{}")
        code, out, _ = self.strip()
        self.assertEqual(code, tool.EXIT_OK)
        self.assertFalse((self.site.out / "_next/static/chunks/main-app-1.js.map").exists())
        self.assertIn("source maps for those files", out)

    def test_html_that_is_not_a_next_page_is_left_alone(self):
        legacy = '<html><body><button onclick="go()">Go</button><script>function go(){}</script></body></html>'
        self.site.write("legacy/demo.html", legacy)
        code, out, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertEqual(self.site.read("legacy/demo.html"), legacy)
        self.assertIn("left alone: 1 HTML files that are not Next.js pages", out)

    def test_byte_counts_match_what_was_removed(self):
        html_before = (self.site.out / "index.html").stat().st_size
        js = sum(p.stat().st_size for p in (self.site.out / "_next").rglob("*.js"))
        txt = (self.site.out / "index.txt").stat().st_size
        plan = tool.analyse(self.site.out)  # analyse changes nothing
        code, _, _ = self.strip()
        self.assertEqual(code, tool.EXIT_OK)
        html_after = (self.site.out / "index.html").stat().st_size
        removed_html = sum(plan.removed[c][1] for c in tool.HTML_CATS if c in plan.removed)
        self.assertEqual(removed_html, html_before - html_after)
        self.assertEqual(plan.removed[tool.CAT_JS][1], js)
        self.assertEqual(plan.removed[tool.CAT_TXT], (1, txt))
        self.assertEqual(plan.removed[tool.CAT_PAYLOAD][0], 2)
        self.assertEqual(plan.removed[tool.CAT_RUNTIME][0], 2)
        self.assertEqual(plan.removed[tool.CAT_PRELOAD][0], 1)


class KeepList(SiteTestCase):
    def test_data_keep_scripts_stay(self):
        self.site.write("js/site.js", "document.documentElement.classList.add('js');")
        tag = '<script data-keep="true" src="/js/site.js" defer=""></script>'
        inline = '<script data-keep="">document.documentElement.dataset.ready = "1";</script>'
        self.site.page("index.html", head=tag + inline)
        code, out, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        html = self.site.read("index.html")
        self.assertIn(tag, html)
        self.assertIn(inline, html)
        self.assertTrue((self.site.out / "js/site.js").is_file())
        self.assertIn("/js/site.js (data-keep) on 1 page", out)

    def test_kept_scripts_are_counted_by_page(self):
        tag = '<script data-keep src="/js/site.js"></script>'
        self.site.page("index.html", head=tag + tag)
        self.site.page("about.html", head=tag)
        code, out, _ = self.strip()
        self.assertEqual(code, tool.EXIT_OK)
        self.assertIn("/js/site.js (data-keep) on 2 pages", out)

    def test_keep_pattern_keeps_matching_script_tags(self):
        tag = '<script src="/js/analytics.js" defer=""></script>'
        self.site.page("index.html", head=tag)
        for pattern in ("/js/*", "js/analytics.js"):
            with self.subTest(pattern=pattern):
                plan = tool.analyse(self.site.out, keep=[pattern])
                self.assertFalse(plan.findings)
        code, out, _ = self.strip("--keep", "/js/*")
        self.assertEqual(code, tool.EXIT_OK)
        self.assertIn(tag, self.site.read("index.html"))
        self.assertIn("/js/analytics.js (--keep)", out)

    def test_a_kept_file_under_next_static_is_not_deleted(self):
        self.site.write("_next/static/chunks/widget.js", "/* kept */")
        tag = '<script data-keep src="/_next/static/chunks/widget.js"></script>'
        self.site.page("index.html", head=tag)
        code, _, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertTrue((self.site.out / "_next/static/chunks/widget.js").is_file())
        self.assertFalse((self.site.out / "_next/static/chunks/main-app-1.js").exists())


class Modes(SiteTestCase):
    def test_dry_run_changes_nothing_and_reports_the_same(self):
        before = snapshot(self.site.root)
        code, dry, _ = self.strip("--dry-run")
        self.assertEqual(code, tool.EXIT_OK)
        self.assertEqual(snapshot(self.site.root), before)
        self.assertIn("Dry run: nothing was changed.", dry)
        code, real, _ = self.strip()
        self.assertEqual(code, tool.EXIT_OK)
        tables = lambda text: [line for line in text.splitlines() if line.startswith("  ")]  # noqa: E731
        self.assertEqual(tables(dry), tables(real))

    def test_second_run_finds_nothing_to_do(self):
        self.assertEqual(self.strip()[0], tool.EXIT_OK)
        after_first = snapshot(self.site.root)
        code, out, _ = self.strip()
        self.assertEqual(code, tool.EXIT_OK)
        self.assertIn("nothing to remove", out)
        self.assertEqual(snapshot(self.site.root), after_first)

    def test_error_boundaries_are_ignored_and_named(self):
        self.site.manifest("/page", {**_framework(), "[project]/app/error.tsx": 1, "[project]/src/app/blog/global-error.js": 2})
        self.site.page("index.html", module_ids=(39756, 1, 2))
        code, out, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertIn("ignored app/error.tsx", out)
        self.assertIn("ignored src/app/blog/global-error.js", out)

    def test_stylesheets_in_a_webpack_manifest_are_not_client_components(self):
        modules = {**_framework(), "[project]/app/globals.css": 5, '[project]/node_modules/next/font/google/target.css?{"path":"app/layout.js"}': 6}
        self.site.manifest("/page", modules)
        code, _, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)

    def test_webpack_absolute_paths_are_read_relative_to_the_app(self):
        # Webpack writes absolute paths from where the build ran, which may not be
        # where the build directory is now (CI artefacts, copies).
        built_at = "/home/builder/project"
        self.site.write("required-server-files.json", '{"version":1,"appDir":"%s","relativeAppDir":""}' % built_at, under=self.site.next)
        self.site.manifest("/page", {
            f"{built_at}/node_modules/next/dist/client/components/layout-router.js": 39756,
            f"{built_at}/node_modules/next/dist/esm/client/components/layout-router.js": 39756,
            f"{built_at}/node_modules/next/dist/client/app-dir/link.js": 22016,
            f"{built_at}/app/error.js": 7,
        })
        code, out, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertIn("ignored app/error.js", out)
        self.assertIn("3 client modules in the build manifest, 2 of them part of Next.js", out)

    def test_turbopack_paths_in_a_monorepo(self):
        self.site.write("required-server-files.json", '{"version":1,"appDir":"/repo/apps/web","relativeAppDir":"apps/web"}', under=self.site.next)
        self.site.manifest("/page", {**_framework(), "[project]/apps/web/app/error.js": 7})
        code, out, err = self.strip()
        self.assertEqual(code, tool.EXIT_OK, msg=err)
        self.assertIn("ignored app/error.js", out)

    def test_version_and_help(self):
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn(tool.__version__, out)
        code, out, _ = run("--help")
        self.assertEqual(code, 0)
        self.assertIn("--dry-run", out)


def _framework():
    from support import FRAMEWORK_MODULES

    return dict(FRAMEWORK_MODULES)


class Tokeniser(unittest.TestCase):
    def test_quoted_attributes_with_angle_brackets(self):
        doc = '<div title="a > b" data-x=\'<script>\'><script src="/_next/static/a.js"></script></div>'
        found = [(e.name, e.attrs) for e in tool.elements(doc)]
        self.assertEqual(found[0], ("div", {"title": "a > b", "data-x": "<script>"}))
        self.assertEqual(found[1][0], "script")

    def test_script_text_is_not_parsed_as_markup(self):
        doc = '<script>var s = "<button onclick=x>";</script><p>after</p>'
        names = [e.name for e in tool.elements(doc)]
        self.assertEqual(names, ["script", "p"])

    def test_comments_are_skipped(self):
        doc = "<!-- <script>bad()</script> --><p>x</p>"
        self.assertEqual([e.name for e in tool.elements(doc)], ["p"])

    def test_payload_rows_are_decoded(self):
        body = 'self.__next_f.push([1,"2:I[22016,[],\\"\\"]\\n3:I[\\"abc\\",[],\\"\\"]\\n"])'
        self.assertEqual(list(tool.client_ids_in(tool.payload_text(body))), ["22016", "abc"])


if __name__ == "__main__":
    unittest.main()
