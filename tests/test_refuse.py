"""Every way the tool refuses. Each refusal must leave the export and the build untouched."""

import shutil
import unittest

from support import BUILD_ID, FRAMEWORK_MODULES, SiteTestCase, snapshot, tool


class ClientComponents(SiteTestCase):
    def with_module(self, key, module_id=900, route="/counter/page"):
        self.site.manifest(route, {**FRAMEWORK_MODULES, key: module_id})
        self.site.page("counter.html", module_ids=(39756, module_id))

    def test_a_client_component_in_the_app(self):
        self.with_module("[project]/app/counter/Counter.js")
        self.assertRefused("client component: app/counter/Counter.js", "on: /counter")

    def test_a_client_component_from_a_package(self):
        self.with_module("[project]/node_modules/some-ui/dist/button.js")
        self.assertRefused("node_modules/some-ui/dist/button.js", "a client component from a package")

    def test_next_script(self):
        self.with_module("[project]/node_modules/next/dist/client/script.js")
        self.assertRefused("next/dist/client/script", "the scripts it loads would no longer load")

    def test_a_next_client_component_the_tool_does_not_know(self):
        # A future Next.js release may add one. The tool fails closed until it is checked.
        self.with_module("[project]/node_modules/next/dist/client/components/something-new.js")
        self.assertRefused("next/dist/client/components/something-new", "does not know to be safe")

    def test_an_error_file_outside_the_app_directory_is_a_client_component(self):
        self.with_module("[project]/components/error.js")
        self.assertRefused("client component: components/error.js")

    def test_a_payload_that_refers_to_a_module_missing_from_the_manifest(self):
        # The build directory does not match the export: a stale .next, for example.
        self.site.page("about.html", module_ids=(39756, 4242))
        self.assertRefused("unknown client reference: module 4242", "about.html", "about.txt")

    def test_string_module_ids(self):
        self.site.page("about.html", module_ids=(39756, "app/x.js"))
        self.assertRefused("unknown client reference: module app/x.js")


class TheExportItself(SiteTestCase):
    def test_an_inline_script_that_is_not_the_runtime(self):
        self.site.page("index.html", head="<script>window.dataLayer = [];</script>")
        self.assertRefused("unrecognised script: <script>window.dataLayer = [];</script>", "add data-keep")

    def test_an_external_script_that_is_not_the_runtime(self):
        self.site.page("index.html", head='<script defer src="https://stats.example.com/script.js"></script>')
        err = self.assertRefused('unrecognised script: <script src="https://stats.example.com/script.js">')
        self.assertIn("--keep", err)

    def test_next_script_before_interactive_leaves_an_inline_script(self):
        tag = '<script>(self.__next_s=self.__next_s||[]).push([0,{"children":"window.x = 1;","id":"x"}])</script>'
        self.site.page("index.html", body="<main></main>" + tag)
        self.assertRefused("self.__next_s")

    def test_an_inline_event_handler(self):
        self.site.page("index.html", body='<button type="button" onclick="openMenu()">Menu</button>')
        self.assertRefused("inline event handler: onclick= on <button>", "on: index.html")

    def test_a_react_reveal_script(self):
        body = '<div hidden id="S:0"><p>late</p></div><script>$RC("B:0","S:0")</script>'
        self.site.page("index.html", body=body)
        self.assertRefused("would leave that content hidden")

    def test_a_client_side_rendering_bailout(self):
        body = '<template data-dgst="BAILOUT_TO_CLIENT_SIDE_RENDERING"></template>'
        self.site.page("index.html", body=body)
        self.assertRefused("client-side rendering", "BAILOUT_TO_CLIENT_SIDE_RENDERING")

    def test_a_pages_router_export_even_without_a_build_directory(self):
        data = '<script id="__NEXT_DATA__" type="application/json">{"page":"/"}</script>'
        self.site.page("index.html", body="<main></main>" + data)
        shutil.rmtree(self.site.next)
        self.assertRefused("Pages Router export", "App Router only")

    def test_the_same_problem_on_many_pages_is_reported_once(self):
        for n in range(8):
            self.site.page(f"p{n}.html", body='<a href="#" onmouseover="x()">x</a>')
        err = self.assertRefused("inline event handler: onmouseover= on <a>", "and 3 more")
        self.assertEqual(err.count("onmouseover="), 1)

    def test_all_problems_are_reported_together(self):
        self.site.manifest("/page", {**FRAMEWORK_MODULES, "[project]/app/Menu.js": 901})
        self.site.page("index.html", head="<script>track()</script>", body='<p onclick="x()">x</p>', module_ids=(39756, 901))
        self.assertRefused("app/Menu.js", "track()", "onclick=")


class BadInput(SiteTestCase):
    def assertUsageError(self, needle, *args):
        before = snapshot(self.site.root)
        code, out, err = tool_run(*args)
        self.assertEqual(code, tool.EXIT_USAGE, msg=out + err)
        self.assertIn(needle, err)
        self.assertEqual(snapshot(self.site.root), before)

    def test_missing_export_directory(self):
        self.assertUsageError("is not a directory", self.site.root / "nope")

    def test_the_project_directory_by_mistake(self):
        (self.site.root / "package.json").write_text("{}")
        self.assertUsageError("looks like the project directory", self.site.root)

    def test_no_html(self):
        empty = self.site.root / "empty"
        empty.mkdir()
        self.assertUsageError("no .html files", empty)

    def test_no_build_directory(self):
        shutil.rmtree(self.site.next)
        self.assertUsageError("BUILD_ID not found", self.site.out)

    def test_build_directory_from_another_build(self):
        (self.site.next / "BUILD_ID").write_text("someotherbuild")
        self.assertUsageError(f"is from build someotherbuild, but the export was written by build {BUILD_ID}", self.site.out)

    def test_no_manifests(self):
        for path in (self.site.next / "server" / "app").rglob("*.js"):
            path.unlink()
        self.assertUsageError("no client reference manifests", self.site.out)

    def test_a_symbolic_link_inside_the_export(self):
        # A linked directory outside the export must never be walked into or deleted from.
        outside = self.site.root / "elsewhere"
        outside.mkdir()
        (outside / "precious.js").write_text("keep me")
        (self.site.out / "_next" / "static" / "linked").symlink_to(outside, target_is_directory=True)
        self.assertUsageError("is a symbolic link", self.site.out)
        self.assertTrue((outside / "precious.js").is_file())

    def test_a_symbolic_link_to_a_page(self):
        (self.site.out / "copy.html").symlink_to(self.site.out / "index.html")
        self.assertUsageError("copy.html is a symbolic link", self.site.out)

    def test_next_dir_option(self):
        moved = self.site.root / "build-output"
        self.site.next.rename(moved)
        self.assertUsageError("BUILD_ID not found", self.site.out)
        code, _, err = tool_run(self.site.out, "--next-dir", moved)
        self.assertEqual(code, tool.EXIT_OK, msg=err)


class InternalCheck(SiteTestCase):
    def test_a_reference_the_plan_would_break_stops_everything(self):
        # Not a script or a preload, so nothing removes it, but it points at a file
        # the plan deletes. The self-check catches it before anything is written.
        self.site.page("about.html", body='<a href="/_next/static/chunks/main-app-1.js">source</a>')
        before = snapshot(self.site.root)
        code, _, err = tool_run(self.site.out)
        self.assertEqual(code, tool.EXIT_INTERNAL, msg=err)
        self.assertIn("internal check failed, nothing was changed", err)
        self.assertIn("about.html still refers to _next/static/chunks/main-app-1.js", err)
        self.assertEqual(snapshot(self.site.root), before)


def tool_run(*args):
    from support import run

    return run(*args)


if __name__ == "__main__":
    unittest.main()
