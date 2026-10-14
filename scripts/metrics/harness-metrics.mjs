#!/usr/bin/env node
// The three harness metrics of a project, read from its Claude Code session transcripts:
// context loaded before the first user message, tokens per commit, wall time of the gate
// before each commit. Every metric prints how many items it processed and the run fails if
// one processed zero (forge's rule: a control that saw nothing is not a PASS).
//
// Reads ~/.claude/projects/<transcript key>/*.jsonl (top-level session files only for
// metric 1; metrics 2 and 3 also read the matching subfolder's subagents/*.jsonl, whose
// tokens metric 2 labels separately), plus the sibling folders of the project's worktrees.
// The key is derived once, by `forge metrics` (forge/cli.py transcript_key), and passed in.
//
// Usage:
//   node scripts/metrics/harness-metrics.mjs --transcript-key=KEY --repo=DIR
//     [--since=YYYY-MM-DD] [--until=YYYY-MM-DD] [--events-until=ISO]
//     [--projects-dir=DIR] [--json]
//
// --transcript-key (required) names the transcript folder; its worktrees are
// <key>--claude-worktrees-<name>. --repo (required, env HARNESS_METRICS_REPO) is the project's
// repository: commits count only when their hash exists there.
// --since/--until bucket whole sessions by their first timestamp.
// --events-until drops every transcript line (main and subagent) stamped after
// the given instant, so a session that is still open cannot keep growing
// inside a bucket that has already been measured.
// --projects-dir (env HARNESS_METRICS_PROJECTS_DIR, default ~/.claude/projects) exists so the
// test can point the script at fixtures.
//
// Node 24+, ESM, no dependencies. Never reads .env* files.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, basename, resolve } from "node:path";
import { homedir } from "node:os";
import { spawnSync } from "node:child_process";

const DEFAULT_PROJECTS_DIR = join(homedir(), ".claude", "projects");

// A missing projects folder or main transcript folder crashed with ENOENT, and a worktree
// folder was never read when the main one was missing (break-it round on PR #23, U48).
function transcriptDirs(projectsDir, key) {
  if (!existsSync(projectsDir)) {
    console.error(`FAIL: projects dir ${projectsDir} does not exist`);
    process.exit(1);
  }
  return [
    join(projectsDir, key),
    ...readdirSync(projectsDir)
      .filter((n) => n.startsWith(`${key}--claude-worktrees-`))
      .map((n) => join(projectsDir, n)),
  ];
}

// ---------- CLI args ----------

function parseArgs(argv) {
  const args = {
    since: null,
    until: null,
    eventsUntil: null,
    projectsDir: process.env.HARNESS_METRICS_PROJECTS_DIR || DEFAULT_PROJECTS_DIR,
    repo: process.env.HARNESS_METRICS_REPO || null,
    transcriptKey: null,
    json: false,
  };
  const valued = { transcriptKey: "--transcript-key=", since: "--since=", until: "--until=", eventsUntil: "--events-until=", projectsDir: "--projects-dir=", repo: "--repo=" };
  for (const raw of argv) {
    if (raw === "--json") args.json = true;
    const key = Object.keys(valued).find((k) => raw.startsWith(valued[k]));
    if (key) args[key] = raw.slice(valued[key].length);
  }
  return args;
}

// ---------- stats helpers ----------

function percentile(sortedAsc, p) {
  if (sortedAsc.length === 0) return null;
  if (sortedAsc.length === 1) return sortedAsc[0];
  const idx = (p / 100) * (sortedAsc.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sortedAsc[lo];
  const frac = idx - lo;
  return sortedAsc[lo] + (sortedAsc[hi] - sortedAsc[lo]) * frac;
}

function summarize(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return {
    n: sorted.length,
    median: percentile(sorted, 50),
    p25: percentile(sorted, 25),
    p75: percentile(sorted, 75),
    min: sorted.length ? sorted[0] : null,
    max: sorted.length ? sorted[sorted.length - 1] : null,
  };
}

function round(x, d = 0) {
  if (x === null || x === undefined) return null;
  const f = 10 ** d;
  return Math.round(x * f) / f;
}

// ---------- transcript parsing ----------

/** Read a JSONL file into an array of parsed objects, skipping bad lines. */
function readJsonl(filePath) {
  const text = readFileSync(filePath, "utf8");
  const out = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.parse(line));
    } catch {
      // skip malformed line
    }
  }
  return out;
}

/** Extract tool_result content as a plain string, regardless of shape. */
function toolResultText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((b) => (b && typeof b === "object" && "text" in b ? b.text : ""))
      .join("");
  }
  return "";
}

// A successful `git commit` prints "[branch-name abc1234] subject". With `-q`
// it prints nothing, and this repo chains `&& git log --oneline -1`, whose
// "abc1234 subject" line is what the quiet form matches. Either may sit on any
// line: lefthook prints its banner first, and chained commands print before
// it. Both are anchored to the start of a line, so a bracket inside source
// code being read (like the example above) never matches.
const COMMIT_BRACKET_RE = /^\[[^\[\]\s]+(?:\s[^\[\]]+)?\s([0-9a-f]{7,40})\]/;
const COMMIT_QUIET_RE = /^([0-9a-f]{7,40})\s+\S/;
// A Bash call is a commit call when it RUNS `git commit`, not when it names the words: the
// command sits at the start of the line or after `;`, `&`, `|`, `(`, `{` (optionally behind
// VAR=value words), so a `git log --grep='git commit'` or an `echo "git commit"` is not one.
// Options of git itself may sit between `git` and `commit`: `-C dir`, `-c key=value` (the
// argument may be quoted), `--no-pager`, `--git-dir=x` and the like.
const GIT_ARG = String.raw`(?:"[^"]*"|'[^']*'|\S+)`;
const GIT_OPT = String.raw`(?:-[Cc]\s+${GIT_ARG}|--(?:git-dir|work-tree|namespace|exec-path|config-env)\s+${GIT_ARG}|-\S+)`;
const GIT_COMMIT_RE = new RegExp(
  String.raw`(?:^|[;&|\n({])\s*(?:[A-Za-z_]\w*=\S*\s+)*git(?:\s+${GIT_OPT})*\s+commit(?![\w-])`,
);
const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;

/**
 * The one hash a commit call's output confirms, or null. At most one per call:
 * git's own bracket line wins, else the first `hash subject` line, so a
 * chained `git log --oneline -5` counts once, not five times.
 */
function commitHashFromText(text) {
  const lines = text.replace(ANSI_RE, "").split(/\r?\n/);
  for (const line of lines) {
    const m = COMMIT_BRACKET_RE.exec(line);
    if (m) return m[1];
  }
  for (const line of lines) {
    const m = COMMIT_QUIET_RE.exec(line);
    if (m) return m[1];
  }
  return null;
}

/**
 * { sha, time } (full SHA, committer time in epoch seconds) if `hash` names a commit in `repo`,
 * else null. This is the repo
 * scope: a commit made from one of this project's sessions in another repository (a
 * forge agent's `cd ~/dev/Projects/forge && git commit`) has a hash this repo
 * does not contain. An amended or gc'd commit can also vanish from
 * the object store, and would then be dropped too, which is why reproducing
 * the recorded baseline is the real control for this check, not the check.
 */
function resolveCommit(repo, hash, cache) {
  if (cache.has(hash)) return cache.get(hash);
  const r = spawnSync(
    "git",
    ["-C", repo, "show", "-s", "--format=%H %ct", `${hash}^{commit}`],
    { encoding: "utf8" },
  );
  const [sha, time] = r.status === 0 ? r.stdout.trim().split(" ") : [];
  const found = sha ? { sha, time: Number(time) } : null;
  cache.set(hash, found);
  return found;
}

/**
 * The hash a commit call's output confirms, or null when the call failed (is_error) or
 * printed no confirmation. A <persisted-output> stub is read from its full stdout.
 */
function confirmedHash(call, data) {
  const result = data.toolResults.get(call.toolUseId);
  if (!result || result.isError) return null;
  const text =
    result.text.trimStart().startsWith("<persisted-output>") && result.stdout !== null
      ? result.stdout
      : result.text;
  return commitHashFromText(text);
}

/**
 * What one commit call amounts to: { kind, sha }. kind is "ok" for a commit this call created in
 * this repo, "none" (failed, or no confirmation hash), "notInRepo", "duplicate" (a SHA already
 * in `seen`) or "predates" (committed before the call started: a failed commit chained with
 * `; git log --oneline -1` re-prints the HEAD of before the call, which the call did not
 * create. Git's committer time has whole-second resolution, hence the floor).
 */
function landedCommit(call, data, repo, cache, seen) {
  const hash = confirmedHash(call, data);
  if (!hash) return { kind: "none" };
  const found = resolveCommit(repo, hash, cache);
  if (!found) return { kind: "notInRepo" };
  if (seen.has(found.sha)) return { kind: "duplicate" };
  const startMs = Date.parse(call.timestamp);
  if (!Number.isNaN(startMs) && found.time < Math.floor(startMs / 1000)) return { kind: "predates" };
  return { kind: "ok", sha: found.sha };
}

/**
 * True when the commit skips the pre-commit hook: --no-verify, or `-n` alone or in a flag
 * cluster (`-nm`), not counting the value of -m, -F, -C, -c or -t.
 */
function skipsGate(command) {
  if (/--no-verify\b/.test(command)) return true;
  const m = GIT_COMMIT_RE.exec(command);
  if (!m) return false;
  const words = command.slice(m.index + m[0].length).split(/[;&|\n]/)[0].split(/\s+/);
  for (let i = 0; i < words.length; i += 1) {
    if (["-m", "-F", "-C", "-c", "-t"].includes(words[i])) { i += 1; continue; }
    if (/^-[a-zA-Z]+$/.test(words[i]) && words[i].includes("n")) return true;
  }
  return false;
}

/**
 * Walk one transcript's parsed lines and extract everything the metrics need:
 * - sessionStart: earliest timestamp seen in the file
 * - assistantUsages: [{ tokens fields..., timestamp, order }] in file order
 * - commitCalls: [{ toolUseId, timestamp, command }] for Bash git-commit tool_use
 * - toolResults: Map(toolUseId -> { text, isError, timestamp })
 */
function extractSessionData(lines, eventsUntilMs) {
  let sessionStart = null;
  // Claude Code writes one line per content block and repeats message.usage on
  // each, so usage is keyed by message id + requestId; the last line wins.
  const usageByKey = new Map();
  const commitCalls = [];
  const toolResults = new Map();

  for (const d of lines) {
    if (!d || typeof d !== "object") continue;
    const ts = d.timestamp;
    if (eventsUntilMs !== null && ts && Date.parse(ts) > eventsUntilMs) continue;
    if (ts && (sessionStart === null || ts < sessionStart)) {
      sessionStart = ts;
    }

    const msg = d.message;
    if (!msg || typeof msg !== "object") continue;

    if (d.type === "assistant" && msg.usage) {
      const u = msg.usage;
      const key = `${msg.id ?? ""}|${d.requestId ?? ""}|${msg.id || d.requestId ? "" : usageByKey.size}`;
      const prev = usageByKey.get(key);
      usageByKey.set(key, {
        input: u.input_tokens || 0,
        cacheCreate: u.cache_creation_input_tokens || 0,
        cacheRead: u.cache_read_input_tokens || 0,
        output: u.output_tokens || 0,
        timestamp: prev?.timestamp ?? ts,
      });
    }

    const content = msg.content;
    if (!Array.isArray(content)) continue;

    for (const block of content) {
      if (!block || typeof block !== "object") continue;
      if (
        block.type === "tool_use" &&
        block.name === "Bash" &&
        typeof block.input?.command === "string" &&
        GIT_COMMIT_RE.test(block.input.command)
      ) {
        commitCalls.push({
          toolUseId: block.id,
          timestamp: ts,
          command: block.input.command,
        });
      }
      if (block.type === "tool_result" && block.tool_use_id) {
        const stdout = d.toolUseResult?.stdout;
        toolResults.set(block.tool_use_id, {
          text: toolResultText(block.content),
          // Full stdout, for when `text` is a <persisted-output> stub.
          stdout: typeof stdout === "string" ? stdout : null,
          isError: !!block.is_error,
          timestamp: ts,
        });
      }
    }
  }

  const assistantUsages = [...usageByKey.values()];
  return { sessionStart, assistantUsages, commitCalls, toolResults };
}

function inRange(dateStr, since, until) {
  if (!dateStr) return false;
  const day = dateStr.slice(0, 10);
  if (since && day < since) return false;
  if (until && day > until) return false;
  return true;
}

// ---------- main ----------

function main() {
  const args = parseArgs(process.argv.slice(2));
  for (const [flag, v] of [["--transcript-key", args.transcriptKey], ["--repo", args.repo]]) {
    if (!v) {
      console.error(`FAIL: ${flag}=... is required`);
      process.exit(1);
    }
  }
  const TRANSCRIPT_DIRS = transcriptDirs(args.projectsDir, args.transcriptKey);
  let eventsUntilMs = null;
  if (args.eventsUntil !== null) {
    eventsUntilMs = Date.parse(args.eventsUntil);
    if (Number.isNaN(eventsUntilMs)) {
      console.error(`FAIL: --events-until=${args.eventsUntil} is not a date`);
      process.exit(1);
    }
  }
  const repoCheck = spawnSync("git", ["-C", args.repo, "rev-parse", "--git-dir"], {
    encoding: "utf8",
  });
  if (repoCheck.status !== 0) {
    console.error(`FAIL: --repo=${args.repo} is not a git repository`);
    process.exit(1);
  }

  const topLevelFiles = TRANSCRIPT_DIRS.filter((dir) => existsSync(dir)).flatMap((dir) =>
    readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isFile() && e.name.endsWith(".jsonl"))
      .map((e) => ({ dir, name: e.name })),
  ).sort((a, b) => a.name.localeCompare(b.name));

  if (topLevelFiles.length === 0) {
    console.error(
      `FAIL: found 0 top-level transcript files in ${TRANSCRIPT_DIRS.join(", ")}`,
    );
    process.exit(1);
  }

  const sessions = []; // { id, dir, sessionStart, ...extracted }
  for (const { dir, name } of topLevelFiles) {
    const id = basename(name, ".jsonl");
    const lines = readJsonl(join(dir, name));
    const data = extractSessionData(lines, eventsUntilMs);
    if (!data.sessionStart) continue; // no timestamps at all, cannot place in time
    sessions.push({ id, dir, ...data });
  }

  const scannedCount = sessions.length;
  const included = sessions.filter((s) =>
    inRange(s.sessionStart, args.since, args.until),
  );

  // ---------- Metric 1: context before first user message ----------
  const metric1Values = [];
  let metric1ExcludedZero = 0;
  for (const s of included) {
    if (s.assistantUsages.length === 0) continue;
    const first = s.assistantUsages[0];
    const ctx = first.input + first.cacheCreate + first.cacheRead;
    // A first request with zero context is a transcript parse miss, not a measurement.
    if (ctx === 0) { metric1ExcludedZero += 1; continue; }
    metric1Values.push(ctx);
  }
  const metric1 = summarize(metric1Values);

  // ---------- Metric 2: tokens per commit ----------
  // Commit-detection heuristic (metric 2, and metric 3 times the same commits):
  // a Bash tool_use whose command runs `git commit` (GIT_COMMIT_RE) counts as a landed
  // commit iff its tool_result is not an error, commitHashFromText() finds a
  // confirmation hash on some line (git's "[fix/foo 500643fc] message", or a
  // quiet commit's chained "500643fc message"), and resolveCommit() finds that
  // hash in the repo; this also counts `--amend` re-commits as
  // separate commit events, which is intentional (each is a real git-commit
  // invocation with its own gate run), so it can overcount distinct final
  // commits relative to `git log`. A call that makes two commits counts once.
  // Unlike metric 3, `--no-verify` is not excluded here: a --no-verify commit
  // that lands in the repo is still a change, and scratch commits in
  // throwaway repos already fail the repo check.
  // Only sessions with >=1 landed commit contribute. The comparison figure is
  // uncached = input + cache_creation + output; cache_read grows with session
  // length rather than with the harness, so it is reported but not compared.
  let metric2TotalTokensMain = 0;
  let metric2TotalTokensSubagents = 0;
  let metric2TotalCommits = 0;
  const perSessionTokensPerCommit = [];
  let metric2SessionsWithCommits = 0;
  let metric2NotInRepo = 0;
  let metric2Duplicates = 0;
  let metric2Predates = 0;
  const shaCache = new Map();
  const kinds = { input: 0, cacheCreate: 0, cacheRead: 0, output: 0 };
  const addKinds = (acc, u) => {
    acc.input += u.input;
    acc.cacheCreate += u.cacheCreate;
    acc.cacheRead += u.cacheRead;
    acc.output += u.output;
  };
  const sumKinds = (k) => k.input + k.cacheCreate + k.cacheRead + k.output;
  const uncached = (k) => k.input + k.cacheCreate + k.output;

  // Subagent transcripts, loaded once: metric 2 sums their tokens and commits,
  // metric 3 times their commits.
  const loadSubagents = (s) => {
    const subDir = join(s.dir, s.id, "subagents");
    let subFiles = [];
    try {
      subFiles = readdirSync(subDir).filter((f) => f.endsWith(".jsonl"));
    } catch {
      // no subagents dir for this session
    }
    return subFiles.map((sf) => extractSessionData(readJsonl(join(subDir, sf)), eventsUntilMs));
  };
  for (const s of included) s.subs = loadSubagents(s);

  for (const s of included) {
    const sessionKinds = { input: 0, cacheCreate: 0, cacheRead: 0, output: 0 };
    for (const u of s.assistantUsages) addKinds(sessionKinds, u);
    const mainTokens = sumKinds(sessionKinds);

    // One SHA counts once per session: a commit that failed without is_error
    // (`git commit ... | grep`, `git commit ...; git log`) re-prints the old
    // HEAD, which is a real commit already counted.
    const seenShas = new Set();
    const countCommits = (data) => {
      let n = 0;
      for (const call of data.commitCalls) {
        const landed = landedCommit(call, data, args.repo, shaCache, seenShas);
        if (landed.kind === "notInRepo") metric2NotInRepo += 1;
        else if (landed.kind === "duplicate") metric2Duplicates += 1;
        else if (landed.kind === "predates") metric2Predates += 1;
        if (landed.kind !== "ok") continue;
        seenShas.add(landed.sha);
        n += 1;
      }
      return n;
    };
    let commitCount = countCommits(s);

    // Subagents (committer included) are parsed with the same dedup and their
    // commits count toward the session.
    let subagentTokens = 0;
    for (const sub of s.subs) {
      const before = sumKinds(sessionKinds);
      for (const u of sub.assistantUsages) addKinds(sessionKinds, u);
      subagentTokens += sumKinds(sessionKinds) - before;
      commitCount += countCommits(sub);
    }

    if (commitCount > 0) {
      metric2TotalTokensMain += mainTokens;
      metric2TotalTokensSubagents += subagentTokens;
      metric2TotalCommits += commitCount;
      for (const k of Object.keys(kinds)) kinds[k] += sessionKinds[k];
      metric2SessionsWithCommits += 1;
      perSessionTokensPerCommit.push(uncached(sessionKinds) / commitCount);
    }
  }

  const metric2CombinedTotalTokens =
    metric2TotalTokensMain + metric2TotalTokensSubagents;
  const metric2 = {
    sessionsWithCommits: metric2SessionsWithCommits,
    totalCommits: metric2TotalCommits,
    notInRepo: metric2NotInRepo,
    duplicates: metric2Duplicates,
    predates: metric2Predates,
    totalTokensMain: metric2TotalTokensMain,
    totalTokensSubagents: metric2TotalTokensSubagents,
    totalTokensCombined: metric2CombinedTotalTokens,
    perCommit: Object.fromEntries(
      Object.entries(kinds).map(([k, v]) => [k, metric2TotalCommits > 0 ? v / metric2TotalCommits : null]),
    ),
    uncachedPerCommit:
      metric2TotalCommits > 0 ? uncached(kinds) / metric2TotalCommits : null,
    tokensPerCommitOverall:
      metric2TotalCommits > 0
        ? metric2CombinedTotalTokens / metric2TotalCommits
        : null,
    medianPerSessionUncachedPerCommit: summarize(perSessionTokensPerCommit)
      .median,
  };

  // ---------- Metric 3: pre-commit gate wall time ----------
  // The same commits metric 2 counts: a call that confirms a hash of this repo, from the
  // main session or a subagent (the committer agent is the designated way to commit). It once
  // timed every main-session "git commit" call, including commits in other
  // repositories and failed ones, excluded only the literal --no-verify and not `-n`, and
  // never read a subagent (independent review of PR #23, ci-hooks-tooling m4).
  const metric3Values = [];
  let metric3Bypassed = 0;
  let metric3NotLanded = 0;
  let metric3Duplicates = 0;
  let metric3Predates = 0;
  for (const s of included) {
    const seen = new Set();
    for (const data of [s, ...s.subs]) {
      for (const call of data.commitCalls) {
        if (skipsGate(call.command)) { metric3Bypassed += 1; continue; }
        const landed = landedCommit(call, data, args.repo, shaCache, seen);
        if (landed.kind === "duplicate") { metric3Duplicates += 1; continue; }
        if (landed.kind === "predates") { metric3Predates += 1; continue; }
        if (landed.kind !== "ok") { metric3NotLanded += 1; continue; }
        seen.add(landed.sha);
        const result = data.toolResults.get(call.toolUseId);
        if (!call.timestamp || !result.timestamp) continue;
        const startMs = Date.parse(call.timestamp);
        const endMs = Date.parse(result.timestamp);
        if (Number.isNaN(startMs) || Number.isNaN(endMs)) continue;
        const seconds = (endMs - startMs) / 1000;
        if (seconds < 0) continue;
        metric3Values.push(seconds);
      }
    }
  }
  const metric3 = summarize(metric3Values);

  // ---------- report ----------
  const report = {
    transcriptDir: TRANSCRIPT_DIRS.join(", "),
    repo: args.repo,
    filters: { since: args.since, until: args.until, eventsUntil: args.eventsUntil },
    sessionsScanned: scannedCount,
    sessionsInRange: included.length,
    metric1_contextBeforeFirstUserMessage: {
      description:
        "usage of the FIRST assistant request per session = input + cache_creation + cache_read",
      itemsProcessed: metric1.n,
      excludedZeroContext: metric1ExcludedZero,
      n: metric1.n,
      median: round(metric1.median),
      p25: round(metric1.p25),
      p75: round(metric1.p75),
      min: round(metric1.min),
      max: round(metric1.max),
    },
    metric2_tokensPerChange: {
      description:
        "total tokens (main session + subagents, labeled separately) summed over sessions with >=1 landed commit, divided by total commits",
      itemsProcessed: metric2.sessionsWithCommits,
      sessionsWithAtLeastOneCommit: metric2.sessionsWithCommits,
      totalCommits: metric2.totalCommits,
      rejectedNotInRepo: metric2.notInRepo,
      rejectedDuplicateSha: metric2.duplicates,
      rejectedPredatesCall: metric2.predates,
      totalTokensMainSessionsOnly: metric2.totalTokensMain,
      totalTokensSubagentsOnly: metric2.totalTokensSubagents,
      totalTokensCombined: metric2.totalTokensCombined,
      comparisonFigure: "uncachedPerCommit = (input + cache_creation + output) / commits",
      uncachedPerCommit: round(metric2.uncachedPerCommit),
      medianPerSessionUncachedPerCommit: round(metric2.medianPerSessionUncachedPerCommit),
      perCommitByKind: Object.fromEntries(Object.entries(metric2.perCommit).map(([k, v]) => [k, round(v)])),
      tokensPerCommitOverallIncludingCacheRead: round(metric2.tokensPerCommitOverall),
      commitDetectionHeuristic:
        "Bash tool_use command that runs 'git commit' (at the start of a command, not merely mentioned), tool_result not is_error (its stdout when the result is a <persisted-output> stub), and one hash per call taken from a line starting with '[branch hash]' (default git output) or else the first line starting with 'hash subject' (this repo's `-q` commits chained with git log); the hash must name a commit in the repo, committed no earlier than the call started, and a SHA counts once per session; --amend counted as its own commit event.",
    },
    metric3_precommitGateSeconds: {
      description:
        "wall time from git-commit tool_use timestamp to its tool_result timestamp, for the commits metric 2 counts (main session and subagents, landed in this repo), excluding --no-verify and -n",
      itemsProcessed: metric3.n,
      excludedSkippedGate: metric3Bypassed,
      excludedNotLandedInRepo: metric3NotLanded,
      excludedDuplicateSha: metric3Duplicates,
      excludedPredatesCall: metric3Predates,
      n: metric3.n,
      median: round(metric3.median, 1),
      p25: round(metric3.p25, 1),
      p75: round(metric3.p75, 1),
    },
  };

  const zeroFailures = [];
  if (metric1.n === 0) zeroFailures.push("metric 1 (context before first user message) processed 0 sessions");
  if (metric2.sessionsWithCommits === 0) zeroFailures.push("metric 2 (tokens per change) processed 0 sessions with commits");
  if (metric3.n === 0) zeroFailures.push("metric 3 (pre-commit gate time) processed 0 gated commits");

  if (args.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`Transcript dir: ${report.transcriptDir}`);
    console.log(`Repo: ${args.repo}`);
    console.log(
      `Filters: since=${args.since ?? "none"} until=${args.until ?? "none"} events-until=${args.eventsUntil ?? "none"}`,
    );
    console.log(
      `Sessions scanned: ${report.sessionsScanned}, in range: ${report.sessionsInRange}`,
    );
    console.log("");
    console.log("Metric 1: context before first user message");
    console.log(
      `  n=${metric1.n} median=${round(metric1.median)} p25=${round(metric1.p25)} p75=${round(metric1.p75)} min=${round(metric1.min)} max=${round(metric1.max)} (excluded ${metric1ExcludedZero} with zero context)`,
    );
    console.log("");
    console.log("Metric 2: tokens per change");
    console.log(
      `  sessions with >=1 commit=${metric2.sessionsWithCommits}, total commits=${metric2.totalCommits} (rejected: ${metric2.notInRepo} not in repo, ${metric2.duplicates} duplicate SHA, ${metric2.predates} predating the call)`,
    );
    console.log(
      `  total tokens: main=${metric2.totalTokensMain} subagents=${metric2.totalTokensSubagents} combined=${metric2.totalTokensCombined}`,
    );
    console.log(
      `  COMPARED: uncached (input+cache_creation+output) per commit=${round(metric2.uncachedPerCommit)}, median per session=${round(metric2.medianPerSessionUncachedPerCommit)}`,
    );
    const pc = metric2.perCommit;
    console.log(
      `  per commit by kind: input=${round(pc.input)} cache_creation=${round(pc.cacheCreate)} cache_read=${round(pc.cacheRead)} output=${round(pc.output)} (all kinds incl. cache_read=${round(metric2.tokensPerCommitOverall)})`,
    );
    console.log(
      `  heuristic: ${report.metric2_tokensPerChange.commitDetectionHeuristic}`,
    );
    console.log("");
    console.log("Metric 3: pre-commit gate wall time (seconds)");
    console.log(
      `  n=${metric3.n} median=${round(metric3.median, 1)} p25=${round(metric3.p25, 1)} p75=${round(metric3.p75, 1)} (excluded ${metric3Bypassed} that skipped the gate, ${metric3NotLanded} not landed in this repo, ${metric3Duplicates} duplicate SHA, ${metric3Predates} predating the call)`,
    );
  }

  if (zeroFailures.length > 0) {
    console.error("");
    console.error("FAIL: one or more controls processed zero items:");
    for (const f of zeroFailures) console.error(`  - ${f}`);
    process.exit(1);
  }

  process.exit(0);
}

main();
