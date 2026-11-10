# Security policy

## Reporting a vulnerability

Please report a vulnerability privately, by email to **hello@ticketwavehq.com**, and not in a public issue. The company's disclosure page is <https://ticketwavehq.com/security>.

A useful report says which version you ran, the command, and what happened, with the smallest export or build that shows it if you can share one.

## What counts

This tool rewrites HTML and deletes files in the directory you pass it. Treat these as security issues rather than ordinary bugs:

- it deletes or rewrites anything outside the export directory, or anything inside it that it should keep (your own scripts, stylesheets, images, `robots.txt`, files outside `_next/static`);
- it strips an export that it should have refused, so that a page loses behaviour it needed without a warning;
- input in an export (for example a crafted file name or page) makes it read or write somewhere it should not.

## Supported versions

Fixes are made on the latest release. The project is at 0.1.x.
