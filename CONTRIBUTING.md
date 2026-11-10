# Contributing

Thank you for helping. Bug reports, false refusals, new Next.js versions and fixes are all welcome.

## Ground rules

- **Standard library only.** The tool is one file, `next_export_strip_js.py`, that runs on Python 3.10 or later with nothing installed. Please keep it that way.
- **Fail closed.** When the tool cannot tell whether a page needs JavaScript, it refuses. A change that makes it strip more builds must show, with a real build, that the pages it now strips do not need what it removes.
- **Nothing changes unless everything passes.** All the analysis happens before anything is written. Keep new checks inside `analyse()` or `verify()`, not in `apply()`.
- **Plain UK English** in messages and documentation, and no em-dashes.

## Running the tests

```bash
python3 -m unittest discover -s tests -v
```

These run offline, in a few seconds. They cover synthetic exports (`tests/test_strip.py`, `tests/test_refuse.py`) and recorded real builds from three Next.js versions (`tests/test_recorded_builds.py`).

To run the tool on a fresh build, as CI does:

```bash
cd tests/fixture-app
npm install
npx next build
cd ../..
NEXT_EXPORT_STRIP_JS_APP=tests/fixture-app NEXT_EXPORT_STRIP_JS_EXPECT=strip \
  python3 -m unittest discover -s tests -p test_live_build.py -v
```

For the refusal case, copy `tests/fixture-app/variants/interactive/app/` into `tests/fixture-app/app/`, build again and set `NEXT_EXPORT_STRIP_JS_EXPECT=refuse`. Remove the copied `app/counter/` folder afterwards.

## Reporting a false refusal

If the tool refuses a build whose pages you believe need no JavaScript, open an issue with:

- the Next.js version (`npx next --version`);
- the full refusal message, which names each module or tag it objected to;
- for a Next.js module, the file it names under `node_modules/next/dist/`.

## Adding a Next.js version, or a Next.js client component

Next.js lists its own client components in the build manifest, and the tool allows only those named in `FRAMEWORK_SAFE`. A new release can add one, and the tool then refuses until someone has checked it. To add one:

1. Read the module in `node_modules/next/dist/` and confirm what it does in the browser. It belongs in `FRAMEWORK_SAFE` only if a page without JavaScript behaves the same for a visitor, or degrades in a way the README already describes (as `next/link` and `next/image` do). If it loads, runs or changes something in the browser, add it to `FRAMEWORK_NEEDS_JS` with a message instead.
2. Build `tests/fixture-app` with that version and record it:

   ```bash
   cd tests/fixture-app && npm install next@<version> && npx next build && cd ../..
   python3 tests/capture_fixture.py tests/fixture-app tests/fixtures/next<major>
   ```

   `capture_fixture.py` replaces the JavaScript files with placeholders and the absolute project path with `[project]/`, so a fixture is small and holds no local paths.
3. Add the fixture to `test_each_version_strips_cleanly` and the version to the CI matrix, and say in `CHANGELOG.md` which version is now tested.

## Pull requests

- One change per pull request, with a test that fails without it.
- Update `CHANGELOG.md` under an "Unreleased" heading.
- CI must pass: the unit tests on every supported Python version, and the real builds.

By contributing, you agree that your contribution is licensed under the MIT licence in `LICENSE`.
