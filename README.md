# next-export-strip-js

Remove the Next.js runtime from a static export when no page needs it, and refuse when one does.

A Next.js app built with `output: 'export'` writes complete HTML for every page. It then adds the React runtime, the client router and a second copy of each page's content (the React Server Components payload) so that React can take the page over in the browser. If no page has a client component, all of that is downloaded, parsed and run without changing anything a visitor sees or can do. `next-export-strip-js` runs after `next build`, removes it, and leaves the HTML, CSS, images, fonts, structured data and your own scripts.

**Who it is for:** sites built with the App Router and exported statically, where every page is a server component: documentation, company and marketing sites, blogs, portfolios. They use Next.js for the build (layouts, routing, metadata, `next/image`) and need nothing from React once the HTML exists. It is **not** for a site with any interactive React page; see [When to use it, and when not](#when-to-use-it-and-when-not).

It is one Python file with no dependencies (Python 3.10 or later). It refuses, and changes nothing, whenever the build shows that a page might need JavaScript in the browser.

## Start in 60 seconds

In your Next.js project, with `output: 'export'` in `next.config`:

```bash
curl -fsSLO https://raw.githubusercontent.com/TicketWaveHQ/next-export-strip-js/main/next_export_strip_js.py
npx next build                                    # writes out/ and .next/
python3 next_export_strip_js.py out --dry-run     # what it would remove; changes nothing
python3 next_export_strip_js.py out               # remove it
```

Run it in the project directory, straight after the build: it reads `.next` as well as `out/`. Then make it part of the build, so that a client component added later fails the build instead of shipping a broken page:

```json
{
  "scripts": {
    "build": "next build && python3 next_export_strip_js.py out"
  }
}
```

Other ways to install (it is not published to npm or PyPI):

```bash
pip install git+https://github.com/TicketWaveHQ/next-export-strip-js            # adds next-export-strip-js
npm install --save-dev github:TicketWaveHQ/next-export-strip-js                 # a Node wrapper; still needs Python 3.10+
```

## How it works

1. **It reads every page.** For each HTML file in the export it lists every `<script>` and classifies it: the Next.js runtime (a `src` under `/_next/static/`, the inline `self.__next_f.push(...)` payload scripts, the Turbopack bootstrap), a data block (JSON-LD or any other non-JavaScript `type`), one of yours (marked `data-keep`, or matched by `--keep`), or something else. Something else is a refusal. It also looks for inline event handler attributes and React's markers for content that must be rendered in the browser. HTML files with no Next.js markers at all are left alone.
2. **It reads the build manifest.** `next build` writes a client reference manifest for every route under `.next/server/app/`, listing by source path every client component (every `'use client'` module) the route's server components import. The tool allows only the Next.js internals it knows to be harmless once the page is static, and refuses anything else.
3. **It checks the two agree.** Every client module that a page's payload refers to must appear in those manifests, and `.next/BUILD_ID` must match the build that wrote the export. A stale `.next` cannot vouch for a newer export.
4. **It plans, checks, then writes.** Every change is worked out in memory first. The rewritten pages are read back: no runtime script may remain, and nothing may point at a file about to be deleted. Only then does it write the pages and delete the files. A refusal, an error or a failed check changes nothing.

## What it removes

| Removed | Why it can go |
| --- | --- |
| `<script src>` tags for JavaScript under `/_next/static/` | The runtime: React, the App Router, the webpack or Turbopack loader, polyfills. |
| Inline `self.__next_f.push(...)` scripts | The RSC payload: the page's content again, as data for hydration. |
| The inline Turbopack bootstrap (Next.js 16) | It only loads the chunks above. |
| `<link>` preload hints that point at those files | The browser would otherwise fetch files that no longer exist. |
| `.js`, `.mjs` and `.cjs` files under `_next/static/`, and their `.map` files | Nothing refers to them any more. |
| `.txt` RSC payload files: `about.txt` beside `about.html`, and Next.js 16's per-segment `__next.*.txt` files | The client router fetched these when navigating. There is no router now. |

It keeps everything else, including: every element of the page's content; stylesheets (also those under `_next/static/`); fonts and images under `_next/static/media/`; JSON-LD and other data blocks; scripts you keep; `robots.txt` and any `.txt` that is not a payload; and every file outside `_next/static/`. It never deletes JavaScript from your `public/` folder.

## What it refuses

The tool exits with status 1, prints every reason it found, and changes nothing, when it sees any of these:

- **A client component in the build manifest**, of yours or from a package. In the App Router, hooks such as `useState` and `useEffect`, and event handler props such as `onClick`, only work in client components: Next.js fails the build when a server component uses them. So this one check covers hooks and handlers too.
- **`next/script`, `next/form`, or any Next.js client component it does not know.** A new Next.js release can add one; the tool refuses until it has been checked (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- **A script it does not recognise**, inline or external: an analytics tag, a theme switcher, the inline script `next/script` writes for `strategy="beforeInteractive"`. It will not guess whether the page needs it. Mark it `data-keep`, pass `--keep`, or remove it.
- **An inline event handler** such as `onclick="..."`: it may call code this tool would delete.
- **React's late-content scripts** (`$RC` and similar) or a `<template data-dgst>` marker, which mean part of a page is completed or rendered in the browser.
- **A Pages Router export** (`__NEXT_DATA__`). Every Pages Router page hydrates, so the build cannot show which pages need React.
- **A payload that refers to a client module the manifests do not list**, which means `.next` does not describe this export.

It stops with status 2 for bad input: no export directory, the project directory passed by mistake, no `.next`, a `.next` from a different build, or a symbolic link anywhere inside the export (so that it can never write or delete outside the directory it was given).

### What it deliberately allows

- **The App Router's own client components** (the layout router, error and not-found boundaries, metadata boundaries, the built-in error page). They exist so the client router can swap parts of a page during navigation.
- **`next/link`.** It renders a plain `<a href>`. Without JavaScript a click is an ordinary page load, and nothing is prefetched.
- **`next/image`.** It renders a plain `<img>`, with `loading="lazy"`, and `srcset` and `sizes` when a loader provides them. One difference: with `placeholder="blur"`, React removes the blurred background when the image loads; without React it stays behind the image, and shows through any transparent parts.
- **`app/error.js` and `app/global-error.js`** (also under `src/app/` and in nested segments). They must be client components, but React only renders them in the browser, after an error in the browser. The report names each one it ignored.
- **Stylesheets** that webpack lists among the client modules (`app/globals.css`, `next/font`): they are styles, and the CSS files stay.

## When to use it, and when not

Use it when every page is complete without React: the content is server-rendered at build time, and whatever behaviour the site has (a menu toggle, a reveal on scroll) lives in a small script of your own, marked `data-keep`. You get smaller pages, no hydration work on the visitor's device, fewer requests, and no inline scripts of Next.js's own. A static export cannot use per-request nonces, so those inline payload scripts otherwise need `'unsafe-inline'`, or a hash for each one, in a Content Security Policy's `script-src`.

What you give up, even on a fully static site:

- **Client-side navigation and prefetching.** Every link is a normal page load. On a small static site this is usually fast, but it is a change, and the browser's own scroll and history behaviour applies.
- **Room for a client component later.** Adding one makes the tool refuse and, wired into `npm run build`, fails the build. That is the point: it is the moment to decide whether the site still suits this tool.
- **Nothing in development.** `next dev` is unaffected and still runs React. Check the stripped export, not the dev server.

Do not use it when:

- **any page is interactive through React**: a form with state, search, a filter, a cart, a menu written as a client component, a theme toggle, anything with `useState`, `useEffect` or `onClick`. The tool would refuse; the right answer is not to use it.
- you rely on `next/script`, a provider, or a component library that marks its components `'use client'`;
- the site uses the Pages Router, or does not use `output: 'export'` (server rendering, ISR, route handlers at request time).

## Options

```text
python3 next_export_strip_js.py [EXPORT_DIR] [--next-dir DIR] [--keep PATTERN] [--dry-run]
```

| Option | Meaning |
| --- | --- |
| `EXPORT_DIR` | The static export directory. Default: `out`. |
| `--next-dir DIR` | The build directory from the same `next build`. Default: `.next` beside the export directory. Needed if `distDir` is set or the build was moved. |
| `--keep PATTERN` | Keep `<script src>` tags whose `src` matches this glob, for example `'/js/*'` or `js/site.js`. Repeatable. |
| `--dry-run` | Report what would be removed, and change nothing. |
| `--version` | Print the version. |

To keep a script without a flag, add `data-keep` to its tag. React writes it as `data-keep="true"`:

```jsx
<script data-keep src="/js/site.js" defer></script>
```

Exit status: `0` done, or nothing to do; `1` refused; `2` bad input; `3` the internal check failed. Whenever the status is not 0, nothing was changed.

## Worked example

This is a real run on [`tests/fixture-app`](tests/fixture-app), built with Next.js 16.4.6 (Turbopack) on 2026-11-10. It has a home page with JSON-LD, an about page with `next/image`, a dynamic route with two posts, `next/link` in the layout, an `app/error.js`, a stylesheet and one script of its own marked `data-keep`. The recorded fixture [`tests/fixtures/next16`](tests/fixtures/next16) is the same build.

```text
$ npx next build
$ python3 next_export_strip_js.py out
next-export-strip-js 0.1.0
Export:  out (Next.js build b2DCiegyxVjVYscn0XKDV)
Checked: 6 pages; 11 client modules in the build manifest, 10 of them part of Next.js and safe to drop
         ignored app/error.js: an error boundary, which React only renders in the browser after an error there

Removed from the HTML of 6 pages
  inline RSC payload scripts                12     33.7 KB
  runtime script tags                       55      5.0 KB
  script preload hints                       6       588 B
Deleted files
  JavaScript files under _next/static       13    593.5 KB
  RSC payload files (.txt)                  20     67.4 KB

Total removed: 700.1 KB of 706.3 KB; the export is now 6.2 KB
Kept:    /js/site.js (data-keep) on 6 pages; 1 data block such as JSON-LD
```

`--dry-run` printed the same figures, with "Dry run: nothing was changed." The export went from 43 files to 10: six HTML pages, the stylesheet, `js/site.js`, the image and `robots.txt`. Sizes are bytes on disk, before compression. `posts/first.html` went from 7,421 bytes with 12 `<script>` tags to 698 bytes with one, the site's own:

```html
<!DOCTYPE html><html lang="en-GB"><head><meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><link rel="stylesheet" href="/_next/static/chunks/3bp3_n2w8t072.css" data-precedence="next"/><title>First post</title><meta name="description" content="A static site whose pages need no JavaScript."/><script data-keep="true" src="/js/site.js" defer=""></script></head><body><div hidden=""><!--$--><!--/$--></div><nav><a href="/">Home</a><a href="/about">About</a><a href="/posts/first">First post</a><a href="/posts/second">Second post</a></nav><main><h1>First post</h1><p>A page from a dynamic route, written at build time.</p></main><!--$--><!--/$--></body></html>
```

A second run reports `nothing to remove in out; no Next.js runtime found.` and exits 0.

With the interactive variant added (a `'use client'` counter using `useState`), the same build is refused and left as it was:

```text
$ python3 next_export_strip_js.py out
next-export-strip-js: refusing, and nothing was changed.
Something in this build says a page may need JavaScript in the browser:

  client component: app/counter/Counter.js
    a client component
    on: /counter

If a page needs React, this tool is not for this site. If it does not, remove the client code (or its 'use client' line) and build again.
```

On one 22-page production site, on 2026-11-10, the single-site script this project generalises reported: "22 pages, inline script removed 1002 KB; 9 JavaScript files deleted (558 KB); 84 payload files deleted". Its wording differs from this tool's report above.

## Limits

- **App Router static exports only.** Tested with Next.js 14.2.35, 15.5.29 and 16.4.6, the last with both Turbopack and webpack, and with `trailingSlash: true` on 15.5.29 and 16.4.6. Another version may write payloads or manifests it does not recognise; it then refuses or stops rather than guessing.
- **It needs `.next` from the same build.** Keep it until the tool has run, or pass `--next-dir`.
- **It refuses any client component, even one that is never rendered or does nothing.** If a component does not need to be a client component, remove its `'use client'` line.
- **It refuses inline event handlers even when they would only call a script you keep.** Attach the handler from that script with `addEventListener` instead.
- **It reads HTML with a small tokeniser** built for the regular markup React writes. It is not a general HTML parser, which is one reason it leaves alone any HTML file without Next.js markers.
- **It does not look inside the scripts you keep.** If one expected something the Next.js runtime provided, that is for you to check.
- **It works only on a plain directory.** A symbolic link anywhere inside the export stops it, with nothing changed.
- **It writes in place and is not atomic across files.** If it is interrupted while writing (power cut, full disk), build again and rerun.
- **It does not change your server or host configuration**, such as headers, caching or a Content Security Policy.
- React's empty Suspense markers (`<!--$--><!--/$-->`) and the hidden metadata `<div>` stay in the HTML. They are inert.
- CI runs on Linux; it was developed on macOS. It has not been tested on Windows.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for the tests, how to report a false refusal and how to add a Next.js version. Please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT. See [LICENSE](LICENSE).

Maintained by [TicketWave HQ](https://ticketwavehq.com), a UK company (Companies House 17143167).
