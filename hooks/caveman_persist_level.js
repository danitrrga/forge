#!/usr/bin/env node
// caveman_persist_level.js -- UserPromptSubmit hook: make a /caveman level change stick.
//
// WHY THIS EXISTS
//   The caveman plugin treats a level change as SESSION state: /caveman lite writes a
//   session flag that dies with the session, and the next session falls back to the
//   resolved default. The user's default is pinned per project through the forge profile's
//   env (CAVEMAN_DEFAULT_MODE), so without this hook a level he deliberately switched to
//   silently reverts on his next session. This writes the new level back to the profile,
//   which is the source of truth, and to the generated settings.local.json that actually
//   carries the env into the next session.
//
// WHY IT REUSES THE PLUGIN'S OWN PARSER
//   Re-implementing the /caveman grammar would drift the moment upstream changes it, and a
//   persisted level that disagrees with the active one is worse than no persistence. So the
//   hook requires the plugin's caveman-parse.js and asks it what the prompt meant. The
//   plugin lives under a content-hashed directory that changes on every update, so the path
//   is globbed, never hard-coded. No plugin -> no persistence, silently.
//
// WHY SLASH COMMANDS ONLY
//   parseModeChange also fires on natural language ("be brief", "fewer tokens"). Those are
//   fine as a session nudge but must not rewrite a checked-in config file: asking for a
//   shorter answer once is not a decision about every future session. skipNaturalLanguage
//   confines persistence to an explicit /caveman command, which is what was asked for.
//
// FAILURE POLICY
//   Always exits 0 and prints nothing on the no-change path. A hook on UserPromptSubmit
//   that can fail or chatter would tax every single prompt.
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// The checkout this script sits in: hooks/ is directly under it, so a clone finds its own profiles.
const FORGE = path.dirname(__dirname);
const PROFILES = path.join(FORGE, 'config', 'profiles');
const ENV_KEY = 'CAVEMAN_DEFAULT_MODE';

// commit/review/compress are one-shot task modes, not levels. The plugin calls them
// INDEPENDENT_MODES and reaches them by their own commands; persisting one would leave every
// future session stuck generating commit messages.
const ONE_SHOT = new Set(['commit', 'review', 'compress']);

function pluginHooksDir() {
  // ~/.claude/plugins/cache/caveman/caveman/<content hash>/src/hooks
  const base = path.join(os.homedir(), '.claude', 'plugins', 'cache', 'caveman', 'caveman');
  let entries;
  try {
    entries = fs.readdirSync(base);
  } catch (e) {
    return null;
  }
  for (const e of entries) {
    const dir = path.join(base, e, 'src', 'hooks');
    if (fs.existsSync(path.join(dir, 'caveman-parse.js'))) return dir;
  }
  return null;
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return null;
  }
}

// Same shape as the generator's write_atomic: temp file in the same directory, parse it back
// before swapping, then rename. A profile truncated mid-write would take the project's whole
// MCP and permission config down with it.
// `trailingNewline` mirrors whatever the file already had. The forge profiles end with one and
// the generated settings.local.json does not, and a hook that normalizes them would flip a byte
// on every level change and show up as a spurious diff next to the real one.
function writeJsonAtomic(file, data, trailingNewline) {
  const tmp = file + '.tmp-caveman';
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + (trailingNewline ? '\n' : ''), 'utf8');
  JSON.parse(fs.readFileSync(tmp, 'utf8'));
  fs.renameSync(tmp, file);
}

function endsWithNewline(file) {
  try {
    const buf = fs.readFileSync(file);
    return buf.length > 0 && buf[buf.length - 1] === 0x0a;
  } catch (e) {
    return true;
  }
}

// The profile whose project_path is the deepest ancestor of cwd. Deepest, not first: a project,
// its vault and its photos folder are three separate profiles, and a session inside the vault
// must update the vault's own profile rather than its parent's.
function profileForCwd(cwd) {
  let files;
  try {
    files = fs.readdirSync(PROFILES).filter((f) => f.endsWith('.claude.json'));
  } catch (e) {
    return null;
  }
  const target = path.resolve(cwd);
  let best = null;
  for (const f of files) {
    const p = path.join(PROFILES, f);
    const prof = readJson(p);
    if (!prof || !prof.project_path) continue;
    const root = path.resolve(prof.project_path);
    if (target !== root && !target.startsWith(root + path.sep)) continue;
    if (!best || root.length > best.root.length) best = { file: p, profile: prof, root: root };
  }
  return best;
}

function setEnvKey(obj, mode) {
  const env = obj.env || {};
  if (env[ENV_KEY] === mode) return false;
  // Rebuild so a newly added key lands first rather than after unrelated tuning vars.
  const next = { [ENV_KEY]: mode };
  for (const [k, v] of Object.entries(env)) if (k !== ENV_KEY) next[k] = v;
  obj.env = next;
  return true;
}

function main() {
  let payload = {};
  try {
    payload = JSON.parse(fs.readFileSync(0, 'utf8')) || {};
  } catch (e) {
    return 0; // no payload, nothing to parse
  }
  const prompt = payload.prompt;
  if (typeof prompt !== 'string' || !prompt.trim().startsWith('/')) return 0;

  const hooks = pluginHooksDir();
  if (!hooks) return 0;

  let parse, config;
  try {
    parse = require(path.join(hooks, 'caveman-parse.js'));
    config = require(path.join(hooks, 'caveman-config.js'));
  } catch (e) {
    return 0;
  }
  if (!parse || typeof parse.parseModeChange !== 'function') return 0;

  const cwd = payload.cwd || process.cwd();

  let change;
  try {
    change = parse.parseModeChange(prompt, {
      getDefaultMode: () => config.getDefaultMode(cwd),
      skipNaturalLanguage: true, // an explicit command only -- see header
    });
  } catch (e) {
    return 0;
  }
  if (!change) return 0;

  let mode = null;
  if (change.action === 'clear') mode = 'off';
  else if (change.action === 'set' && change.mode && !ONE_SHOT.has(change.mode)) mode = change.mode;
  if (!mode) return 0;

  const found = profileForCwd(cwd);
  if (!found) return 0;
  // A project whose profile pins plugins_keep without caveman has no caveman level to keep.
  // Without this, a /caveman typed there (a project that opted out) still parsed through the
  // plugin's cached parser and wrote CAVEMAN_DEFAULT_MODE into that project's profile and
  // settings.local.json. An untrimmed profile (no plugins_keep) inherits caveman from user
  // scope, so it keeps the old behaviour.
  const keep = found.profile.plugins_keep;
  if (Array.isArray(keep) && !keep.includes('caveman@caveman')) return 0;

  let wrote = [];
  try {
    if (setEnvKey(found.profile, mode)) {
      writeJsonAtomic(found.file, found.profile, endsWithNewline(found.file));
      wrote.push('profile');
    }
  } catch (e) { /* a failed profile write must not block the prompt */ }

  // settings.local.json carries the env into the NEXT session. The generator would rewrite it
  // at SessionStart, but Claude Code reads env at session init -- before hooks run -- so a
  // generator-only update would land one session late. Write it here too.
  const slp = path.join(found.root, '.claude', 'settings.local.json');
  try {
    const sl = readJson(slp);
    if (sl && setEnvKey(sl, mode)) {
      writeJsonAtomic(slp, sl, endsWithNewline(slp));
      wrote.push('settings.local.json');
    }
  } catch (e) { /* same: never block the prompt */ }

  if (wrote.length) {
    // One line, only on an actual change, so the level switch is visibly durable rather than
    // silently so. Goes into model context, hence the brevity.
    process.stdout.write(
      'caveman level "' + mode + '" persisted for ' + path.basename(found.root) +
      ' (' + wrote.join(' + ') + '); applies from the next session.\n'
    );
  }
  return 0;
}

process.exit(main());
