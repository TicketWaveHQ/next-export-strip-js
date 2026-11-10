#!/usr/bin/env node
// Runs next_export_strip_js.py with the first Python 3 it finds, passing every
// argument through. The tool is the Python file; this wrapper only lets
// `npx next-export-strip-js` and package.json scripts call it. Set PYTHON to
// choose the interpreter.
'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path');

const script = path.join(__dirname, '..', 'next_export_strip_js.py');
const args = process.argv.slice(2);
const candidates = process.env.PYTHON
  ? [[process.env.PYTHON]]
  : process.platform === 'win32'
    ? [['py', '-3'], ['python']]
    : [['python3'], ['python']];

for (const [python, ...pre] of candidates) {
  const result = spawnSync(python, [...pre, script, ...args], { stdio: 'inherit' });
  if (result.error && result.error.code === 'ENOENT') continue;
  if (result.error) {
    console.error(`next-export-strip-js: could not run ${python}: ${result.error.message}`);
    process.exit(2);
  }
  process.exit(result.status === null ? 1 : result.status);
}

console.error('next-export-strip-js: needs Python 3.10 or later, and found none on PATH (set PYTHON to choose one).');
process.exit(2);
