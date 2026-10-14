#!/usr/bin/env node
// harness-baseline.mjs — measure what the Claude Code harness costs before the
// first user token of a session. Run it after any harness change to see whether
// the change actually moved the number, rather than assuming it did.
//
//   node scripts/metrics/harness-baseline.mjs --repo=DIR --transcript-key=KEY [<session id>] [--json]
//
// Without a session id it reads the newest session of the project. --repo is the project's
// directory; --transcript-key names its folder under ~/.claude/projects and is derived once, by
// `forge metrics` (forge/cli.py transcript_key). Both are required: this script no longer
// guesses them from where it lives.
//
// It counts three things:
//   1. Session-start attachments (hook stdout, the skill and agent listings, MCP
//      instructions) read from the session transcript.
//   2. The always-on instruction chain: project CLAUDE.md (and CLAUDE.local.md),
//      every CLAUDE.md or CLAUDE.local.md in a directory above the repo (Claude
//      Code loads ancestors too), user CLAUDE.md, and every .claude/rules file with
//      no `paths:` frontmatter. Rules WITH `paths:`
//      are path-gated and cost nothing at startup, so they are reported separately.
//   3. The auto-memory index, which loads every session.

import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { homedir } from 'node:os';

const args = process.argv.slice(2);
const flag = (name) => (args.find((a) => a.startsWith(`--${name}=`)) ?? '').slice(name.length + 3);
const asJson = args.includes('--json');
const wantedId = args.find((a) => !a.startsWith('--'));
for (const name of ['repo', 'transcript-key']) {
  if (!flag(name)) {
    console.error(`FAIL: --${name}=... is required`);
    process.exit(1);
  }
}
const REPO = resolve(flag('repo'));
const SESSIONS = join(homedir(), '.claude', 'projects', flag('transcript-key'));
const MEMORY = join(SESSIONS, 'memory', 'MEMORY.md');

const size = (p) => (existsSync(p) ? statSync(p).size : 0);

function newestSession() {
  if (!existsSync(SESSIONS)) return null;
  const files = readdirSync(SESSIONS)
    .filter((f) => f.endsWith('.jsonl'))
    .map((f) => ({ f, m: statSync(join(SESSIONS, f)).mtimeMs }))
    .sort((a, b) => b.m - a.m);
  return files.length ? join(SESSIONS, files[0].f) : null;
}

// Session-start attachments: the listings, MCP instructions, and SessionStart
// hook stdout. Each type is counted once, at its first appearance, because these
// are emitted before the model can act on anything you typed. Per-turn hooks
// (UserPromptSubmit) are excluded; they recur and are not part of the baseline.
const STARTUP_TYPES = new Set([
  'skill_listing',
  'agent_listing_delta',
  'deferred_tools_delta',
  'mcp_instructions_delta',
]);

function readAttachments(file) {
  const out = {};
  const seen = new Set();
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let d;
    try { d = JSON.parse(line); } catch { continue; }
    const a = d.attachment;
    if (!a) continue;
    const isStartupHook =
      a.type === 'hook_success' && String(a.hookEvent || a.hookName || '').startsWith('SessionStart');
    if (!isStartupHook && !STARTUP_TYPES.has(a.type)) continue;
    const key = isStartupHook ? 'SessionStart hook stdout' : a.type;
    if (seen.has(key) && !isStartupHook) continue;
    seen.add(key);
    out[key] = (out[key] || 0) + JSON.stringify(a).length;
  }
  return out;
}

// A rule file without `paths:` frontmatter loads unconditionally.
function walkRules(dir, always, gated) {
  if (!existsSync(dir)) return;
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) { walkRules(p, always, gated); continue; }
    if (!e.name.endsWith('.md')) continue;
    const head = readFileSync(p, 'utf8').slice(0, 600);
    const fm = head.startsWith('---') ? head.slice(3, head.indexOf('---', 3)) : '';
    (/^\s*paths:/m.test(fm) ? gated : always).push([p, size(p)]);
  }
}

const file = wantedId
  ? join(SESSIONS, `${wantedId}.jsonl`)
  : newestSession();

if (!file || !existsSync(file)) {
  console.error(`No session transcript found under ${SESSIONS}`);
  process.exit(1);
}

const attachments = readAttachments(file);
const always = [];
const gated = [];
walkRules(join(REPO, '.claude', 'rules'), always, gated);

// CLAUDE.md imports AGENTS.md with an `@AGENTS.md` line, so AGENTS.md loads every
// session too. Missing it undercounted the chain by the whole of AGENTS.md
// (found in an independent review).
const claudeMd = join(REPO, 'CLAUDE.md');
const importsAgents = existsSync(claudeMd) && /^@AGENTS\.md\s*$/m.test(readFileSync(claudeMd, 'utf8'));

// Claude Code also loads the CLAUDE.md of every directory above the working directory:
// ~/dev/CLAUDE.md, 804 B, reached every session of that project and was left out until
// an independent review found it (PR #23, ci-hooks-tooling m6).
const ancestors = {};
for (let d = dirname(REPO); ; d = dirname(d)) {
  for (const name of ['CLAUDE.md', 'CLAUDE.local.md']) {
    if (existsSync(join(d, name))) ancestors[`${join(d, name)} (ancestor)`] = size(join(d, name));
  }
  if (d === dirname(d)) break;
}
if (!existsSync(claudeMd)) console.error(`warning: ${claudeMd} does not exist, so the project chain reads 0 B`);

const instructions = {
  'CLAUDE.md (project)': size(claudeMd),
  'CLAUDE.local.md (project)': size(join(REPO, 'CLAUDE.local.md')),
  ...ancestors,
  'AGENTS.md (imported by CLAUDE.md)': importsAgents ? size(join(REPO, 'AGENTS.md')) : 0,
  'CLAUDE.md (user)': size(join(homedir(), '.claude', 'CLAUDE.md')),
  'MEMORY.md (auto-memory index)': size(MEMORY),
  'rules with no paths: (always on)': always.reduce((n, [, b]) => n + b, 0),
};

const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
const total = sum(attachments) + sum(instructions);

if (asJson) {
  console.log(JSON.stringify({ session: file, attachments, instructions, total }, null, 2));
} else {
  const row = ([k, v]) => `  ${k.padEnd(44)}${String(v).padStart(8)} B  ${((v / total) * 100).toFixed(1).padStart(5)}%`;
  console.log(`session: ${file}`);
  console.log('note: attachment sizes are historical (what that session loaded);');
  console.log('      file sizes are read live. For a clean before/after, compare');
  console.log('      two sessions, not one session against the current disk.\n');
  console.log('Session-start attachments');
  Object.entries(attachments).sort((a, b) => b[1] - a[1]).forEach((e) => console.log(row(e)));
  console.log('\nAlways-on instructions');
  Object.entries(instructions).sort((a, b) => b[1] - a[1]).forEach((e) => console.log(row(e)));
  console.log(`\n  ${'TOTAL before the first user token'.padEnd(44)}${String(total).padStart(8)} B  ~${Math.round(total / 4)} tokens`);
  if (gated.length) {
    const g = gated.reduce((n, [, b]) => n + b, 0);
    console.log(`\n  ${gated.length} path-gated rule files (${g} B) cost nothing at startup.`);
  }
}
