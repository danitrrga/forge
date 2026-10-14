#!/usr/bin/env node
// Cases for harness-metrics.mjs: commit detection (metric 2), and now the
// numbers of all three metrics, the subagent tokens, the uncached figure and the date
// buckets. Before, the cases pinned commit detection only, and 8 of 9 weakenings of the
// rest passed them (independent review of PR #23, ci-hooks-tooling m5).
//
// Builds one tiny fake transcript pool per case in a temp dir, plus a real
// temp git repo whose hashes stand in for the project's, runs the script under
// test against each pool, and checks what it reports.
//
// Usage: node test-harness-metrics.mjs [path/to/harness-metrics.mjs]
//
// HOME is pointed at the fixture root, and the script also gets the explicit
// --transcript-key, --projects-dir and --repo flags. Prints how many cases ran; fails on zero.

import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const script = resolve(process.argv[2] ?? join(here, "harness-metrics.mjs"));
// A key that looks like no real project, passed to the script as --transcript-key.
const TRANSCRIPT_NAME = "-toy-world-projects-harness-fixture";

const root = mkdtempSync(join(tmpdir(), "harness-metrics-test-"));

// ---------- a real repo with three commits ----------

const repo = join(root, "repo");
mkdirSync(repo);
// Without GIT_* from the caller: run from a git hook, GIT_DIR and GIT_INDEX_FILE would
// point these commands at the repository being committed instead of this temp repo.
const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith("GIT_")));
const git = (...a) => {
  const r = spawnSync(
    "git",
    ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", ...a],
    { cwd: repo, encoding: "utf8", env: cleanEnv },
  );
  if (r.status !== 0) throw new Error(`git ${a.join(" ")}: ${r.stderr}`);
  return r.stdout.trim();
};
git("init", "-q", "-b", "main");
const h = [];
for (const s of ["one", "two", "three", "four"]) {
  git("commit", "-q", "--allow-empty", "-m", `feat: ${s}`);
  h.push(git("rev-parse", "--short=8", "HEAD"));
}
// A commit made before every session below (a committer date earlier than every session start):
// the repo's HEAD as it was when a session began.
const preSession = (() => {
  const r = spawnSync(
    "git",
    ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", "chore: before the session"],
    { cwd: repo, encoding: "utf8", env: { ...cleanEnv, GIT_COMMITTER_DATE: new Date(Date.UTC(2026, 7, 1)).toISOString().replace(".000Z", "Z") } },
  );
  if (r.status !== 0) throw new Error(`git commit: ${r.stderr}`);
  return git("rev-parse", "--short=8", "HEAD");
})();
// A hash that exists in no repo here, standing in for a forge commit.
let foreign = randomBytes(4).toString("hex");
while (h.includes(foreign)) foreign = randomBytes(4).toString("hex");

// ---------- transcript builders ----------

let seq = 0;
function commitTurn(ts, command, text, { isError = false, stdout, usage = 100, cacheRead = 0, secs = 3 } = {}) {
  const id = `toolu_${++seq}`;
  const resultTs = new Date(Date.parse(ts) + secs * 1000).toISOString();
  return [
    {
      type: "assistant",
      timestamp: ts,
      requestId: `req_${seq}`,
      message: {
        id: `msg_${seq}`,
        role: "assistant",
        usage: { input_tokens: 0, cache_creation_input_tokens: usage, cache_read_input_tokens: cacheRead, output_tokens: 0 },
        content: [{ type: "tool_use", id, name: "Bash", input: { command } }],
      },
    },
    {
      type: "user",
      timestamp: resultTs,
      message: { role: "user", content: [{ type: "tool_result", tool_use_id: id, content: text, is_error: isError }] },
      toolUseResult: { stdout: stdout ?? text, stderr: "", interrupted: false, isImage: false },
    },
  ];
}
const userTurn = (ts) => ({ type: "user", timestamp: ts, message: { role: "user", content: "go" } });
const jsonl = (lines) => lines.map((l) => JSON.stringify(l)).join("\n") + "\n";

const T0 = new Date(Date.UTC(2026, 8, 1, 10)).toISOString();
const dayAt = (day) => `2026-09-${day}T10:00:00.000Z`;
const isoDay = (y, m, d) => new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
const one = (ts, hash, opts) => [userTurn(ts), ...commitTurn(new Date(Date.parse(ts) + 60000).toISOString(), "git commit -m x", `[main ${hash}] x`, opts)];
const at = (min) => new Date(Date.parse(T0) + min * 60000).toISOString();
const quiet = "git commit -q -m 'feat: x' && git log --oneline -1";

// Each case: sessions { id: { main: [lines], subagents?: { name: [lines] } } },
// extra CLI args, expected totalCommits, optional expected main tokens.
const cases = [
  {
    name: "normal commit, git's [branch hash] line",
    sessions: { s1: { main: [userTurn(at(0)), ...commitTurn(at(1), "git commit -m 'feat: x'", `[main ${h[0]}] feat: one\n 1 file changed`)] } },
    expect: 1,
  },
  {
    name: "result opens with lefthook's banner",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), quiet, `┃  gitleaks ❯ \n2:36PM INF no leaks found\n✔️ gitleaks (0.30 seconds)\n${h[0]} feat: one`),
        ],
      },
    },
    expect: 1,
  },
  {
    name: "-q commit chained with git log --oneline -1",
    sessions: { s1: { main: [userTurn(at(0)), ...commitTurn(at(1), quiet, `${h[0]} feat: one`)] } },
    expect: 1,
  },
  {
    name: "commit in another repository (hash not in the repo)",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), `cd ~/dev/Projects/forge && ${quiet}`, `${foreign} feat(app): the app leaves a plugin`),
        ],
      },
    },
    expect: 0,
  },
  {
    name: "chained git log --oneline -5 counts once",
    sessions: {
      s1: { main: [userTurn(at(0)), ...commitTurn(at(1), "git commit -q -m x && git log --oneline -5", `${h[2]} feat: three\n${h[1]} feat: two\n${h[0]} feat: one`)] },
    },
    expect: 1,
  },
  {
    name: "failing commit (is_error) with a hash in its output",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -q -m x; git log --oneline -1", `Exit code 1\nlint failed\n${h[0]} feat: one`, { isError: true }),
        ],
      },
    },
    expect: 0,
  },
  {
    name: "<persisted-output> stub, confirmation only in toolUseResult.stdout",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(
            at(1),
            "git diff --cached --stat && git commit -m x",
            "<persisted-output>\nOutput too large (40.8KB). Full output saved to: /tmp/x.txt\n\nPreview (first 2KB):\n src/a.ts | 1 +\n...\n</persisted-output>",
            { stdout: `${" src/a.ts | 1 +\n".repeat(50)}[main ${h[1]}] feat: two\n 50 files changed` },
          ),
        ],
      },
    },
    expect: 1,
  },
  {
    name: "other diagnostic output before the chained commit",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), `node tools/harness-metrics.mjs && ${quiet}`, `Transcript dir: /x\nSessions scanned: 3\n  n=21 median=67966\n${h[0]} feat: one`),
        ],
      },
    },
    expect: 1,
  },
  {
    name: "bracket inside source code being read",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(
            at(1),
            "sed -n 100,115p tools/harness-metrics.mjs # git commit detection",
            `// A successful \`git commit\` prints "[main ${h[0]}] subject". With \`-q\`\n// it prints nothing.`,
          ),
        ],
      },
    },
    expect: 0,
  },
  {
    name: "masked failed commit re-prints the HEAD already counted",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] feat: one`),
          ...commitTurn(at(5), "git commit -q -m y 2>/dev/null; git log --oneline -1", `${h[0]} feat: one`),
        ],
      },
    },
    expect: 1,
  },
  {
    name: "subagent commits in another repository",
    sessions: {
      s1: {
        main: [userTurn(at(0)), ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] feat: one`)],
        subagents: { "agent-forge": [userTurn(at(2)), ...commitTurn(at(3), `cd ~/dev/Projects/forge && ${quiet}`, `${foreign} feat: forge`)] },
      },
    },
    expect: 1,
  },
  {
    name: "scratch --no-verify commit in a throwaway repo",
    sessions: {
      s1: {
        main: [userTurn(at(0)), ...commitTurn(at(1), `cd /tmp/scratch && git commit -q --no-verify -m t && git log --oneline -1`, `${foreign} t`)],
      },
    },
    expect: 0,
  },
  {
    name: "--events-until drops the later commit and its tokens",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] feat: one`, { usage: 100 }),
          ...commitTurn(at(120), "git commit -m y", `[main ${h[1]}] feat: two`, { usage: 7000 }),
        ],
      },
    },
    args: [`--events-until=${at(60)}`],
    expect: 1,
    expectMainTokens: 100,
  },
  // Metric 3 times the commits metric 2 counts: this repo's, from the main session and from
  // subagents, and not the ones that skipped the gate (review of PR #23, m4).
  {
    name: "metric 3 times in-repo commits from main and subagents, and skips -n and the no-verify flag",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] x`, { secs: 10 }),
          ...commitTurn(at(5), "git commit -n -m y", `[main ${h[1]}] y`, { secs: 1 }),
          ...commitTurn(at(7), "git commit --no-verify -m v", `[main ${h[3]}] v`, { secs: 2 }),
          ...commitTurn(at(10), `cd ~/dev/Projects/forge && git commit -m z`, `[main ${foreign}] z`, { secs: 40 }),
        ],
        subagents: { "agent-committer": [userTurn(at(20)), ...commitTurn(at(21), "git commit -m w", `[main ${h[2]}] w`, { secs: 50 })] },
      },
    },
    expect: 4,
    json: { "metric3_precommitGateSeconds.n": 2, "metric3_precommitGateSeconds.median": 30, "metric3_precommitGateSeconds.excludedSkippedGate": 2 },
  },
  {
    name: "metric 3 with only gate-skipping commits is a FAIL, not a pass",
    sessions: { s1: { main: [userTurn(at(0)), ...commitTurn(at(1), "git commit -nm x", `[main ${h[0]}] x`)] } },
    expectFail: "metric 3 (pre-commit gate time) processed 0",
  },
  {
    name: "metric 3 drops a negative duration",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] x`, { secs: -5 }),
          ...commitTurn(at(3), "git commit -m y", `[main ${h[1]}] y`, { secs: 10 }),
        ],
      },
    },
    expect: 2,
    json: { "metric3_precommitGateSeconds.n": 1, "metric3_precommitGateSeconds.median": 10 },
  },
  // Round 9, finding 1: a call that only MENTIONS "git commit" (a grep, an echo) and prints a
  // "hash subject" line is not a commit. Seen red before the fix: "commits 2 (want 0)".
  {
    name: "a git log --grep='git commit' and an echo that print a hash line are not commits",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git log --oneline -3 --grep='git commit'", `${h[0]} feat: one`),
          ...commitTurn(at(3), `echo "run git commit later"; git log --oneline -1`, `run git commit later\n${h[1]} feat: two`),
        ],
      },
    },
    expect: 0,
  },
  // Round 9, finding 2: a commit that failed without is_error (`; git log`) re-prints the HEAD
  // of BEFORE the session, which no call of the session created. Seen red before the fix:
  // "commits 1 (want 0), metric3_precommitGateSeconds.n 1 (want 0)".
  {
    name: "failed commit chained with git log re-prints the HEAD from before the session",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -m nothing; git log --oneline -1", `nothing to commit, working tree clean\n${preSession} chore: before the session`),
        ],
      },
    },
    expect: 0,
    json: { "metric3_precommitGateSeconds.n": 0 },
  },
  // Round 9, finding 3: `git -C DIR commit` and `git -c k=v commit` are commits, and `-n` on them
  // skips the gate like on a plain `git commit`. Seen red before the fix: "commits 0 (want 3),
  // metric3_precommitGateSeconds.n 0 (want 1), .median null (want 20), .excludedSkippedGate 0 (want 2)".
  {
    name: "git -C DIR commit and git -c k=v commit are detected, and -n on them skips the gate",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), `git -C ${repo} commit -n -m skip`, `[main ${h[0]}] skip`, { secs: 1 }),
          ...commitTurn(at(3), `git -c user.name=x -c core.editor=true commit -n -m skip2`, `[main ${h[1]}] skip2`, { secs: 2 }),
          ...commitTurn(at(5), `git -C "${repo}" --no-pager commit -m normal`, `[main ${h[2]}] normal`, { secs: 20 }),
        ],
      },
    },
    expect: 3,
    json: { "metric3_precommitGateSeconds.n": 1, "metric3_precommitGateSeconds.median": 20, "metric3_precommitGateSeconds.excludedSkippedGate": 2 },
  },
  // Round 9, finding 4: metric 3 labelled a duplicate SHA "not landed in this repo", though the
  // commit did land (metric 2 says "duplicate SHA"). Seen red before the fix:
  // "excludedNotLandedInRepo 1 (want 0), excludedDuplicateSha undefined (want 1)".
  {
    name: "metric 3 reports a duplicate SHA under its own label, not as not landed",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -q -m normal", `${h[0]} feat: one`, { secs: 5 }),
          ...commitTurn(at(3), "git commit -q -m again; git log --oneline -1", `${h[0]} feat: one`, { secs: 5 }),
        ],
      },
    },
    expect: 1,
    json: {
      "metric3_precommitGateSeconds.n": 1,
      "metric3_precommitGateSeconds.excludedNotLandedInRepo": 0,
      "metric3_precommitGateSeconds.excludedDuplicateSha": 1,
      "metric2_tokensPerChange.rejectedDuplicateSha": 1,
    },
  },
  // Metric 1: the first request of each session, and a zero-context first request is a
  // parse miss, not a measurement.
  {
    name: "metric 1 reads the first request of a session, not the last",
    sessions: {
      s1: {
        main: [
          userTurn(at(0)),
          ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] x`, { usage: 100 }),
          ...commitTurn(at(3), "git commit -m y", `[main ${h[1]}] y`, { usage: 7000 }),
        ],
      },
    },
    expect: 2,
    json: { "metric1_contextBeforeFirstUserMessage.median": 100 },
  },
  {
    name: "metric 1 leaves out a session whose first request has zero context",
    sessions: { s1: { main: one(at(0), h[0], { usage: 0 }) }, s2: { main: one(at(10), h[1], { usage: 100 }) } },
    expect: 2,
    json: { "metric1_contextBeforeFirstUserMessage.n": 1, "metric1_contextBeforeFirstUserMessage.excludedZeroContext": 1 },
  },
  {
    name: "metric 1 with no measurable session is a FAIL, not a pass",
    sessions: { s1: { main: one(at(0), h[0], { usage: 0 }) } },
    expectFail: "metric 1 (context before first user message) processed 0",
  },
  // Metric 2's token figures.
  {
    name: "subagent tokens count, labelled apart from the main session's",
    sessions: {
      s1: {
        main: one(at(0), h[0], { usage: 100 }),
        subagents: { "agent-x": [userTurn(at(5)), ...commitTurn(at(6), "ls", "a.txt", { usage: 500 })] },
      },
    },
    expect: 1,
    json: { "metric2_tokensPerChange.totalTokensMainSessionsOnly": 100, "metric2_tokensPerChange.totalTokensSubagentsOnly": 500 },
  },
  {
    name: "the compared figure leaves cache reads out",
    sessions: { s1: { main: one(at(0), h[0], { usage: 100, cacheRead: 1000 }) } },
    expect: 1,
    json: { "metric2_tokensPerChange.uncachedPerCommit": 100, "metric2_tokensPerChange.tokensPerCommitOverallIncludingCacheRead": 1100 },
  },
  {
    name: "the per-session figure is the median, not the mean",
    sessions: {
      s1: { main: one(dayAt("01"), h[0], { usage: 100 }) },
      s2: { main: one(dayAt("02"), h[1], { usage: 200 }) },
      s3: { main: one(dayAt("03"), h[2], { usage: 900 }) },
    },
    expect: 3,
    json: { "metric2_tokensPerChange.medianPerSessionUncachedPerCommit": 200 },
  },
  {
    name: "--since and --until bucket whole sessions by their first timestamp",
    sessions: {
      s1: { main: one(dayAt("01"), h[0]) },
      s2: { main: one(dayAt("10"), h[1]) },
      s3: { main: one(dayAt("20"), h[2]) },
    },
    args: [`--since=${isoDay(2026, 9, 5)}`, `--until=${isoDay(2026, 9, 15)}`],
    expect: 1,
    json: { sessionsInRange: 1 },
  },
  // Missing folders (break-it round on PR #23, U48): a clean FAIL, not an ENOENT stack, and
  // a worktree folder is still read when the main one does not exist.
  { name: "no projects folder at all", layout: "none", sessions: {}, expectFail: "FAIL: projects dir" },
  { name: "an empty projects folder", layout: "empty", sessions: {}, expectFail: true },
  {
    name: "only a worktree folder holds sessions",
    layout: "worktree",
    sessions: { s1: { main: [userTurn(at(0)), ...commitTurn(at(1), "git commit -m x", `[main ${h[0]}] feat: one`)] } },
    expect: 1,
  },
];

// ---------- run ----------

let ran = 0;
let failed = 0;
for (const [i, c] of cases.entries()) {
  const home = join(root, `case-${i}`);
  const projects = join(home, ".claude", "projects");
  const layout = c.layout ?? "main";
  const tdir = join(projects, layout === "worktree" ? `${TRANSCRIPT_NAME}--claude-worktrees-x` : TRANSCRIPT_NAME);
  if (layout === "empty") mkdirSync(projects, { recursive: true });
  if (layout === "main" || layout === "worktree") mkdirSync(tdir, { recursive: true });
  for (const [sid, s] of Object.entries(c.sessions)) {
    writeFileSync(join(tdir, `${sid}.jsonl`), jsonl(s.main));
    for (const [name, lines] of Object.entries(s.subagents ?? {})) {
      const sd = join(tdir, sid, "subagents");
      mkdirSync(sd, { recursive: true });
      writeFileSync(join(sd, `${name}.jsonl`), jsonl(lines));
    }
  }
  const r = spawnSync(
    process.execPath,
    [script, "--json", `--transcript-key=${TRANSCRIPT_NAME}`, `--projects-dir=${projects}`, `--repo=${repo}`, ...(c.args ?? [])],
    { encoding: "utf8", env: { ...cleanEnv, HOME: home } },
  );
  ran += 1;
  if (c.expectFail) {
    const first = r.stderr.trim().split("\n")[0];
    // true: any clean FAIL; a string: the FAIL has to name that control.
    const ok = r.status === 1 && r.stderr.trimStart().startsWith("FAIL:") &&
      (c.expectFail === true || r.stderr.includes(c.expectFail));
    if (!ok) failed += 1;
    const want = c.expectFail === true ? '"FAIL: ..."' : JSON.stringify(c.expectFail);
    console.log(`${ok ? "PASS" : "FAIL"}  ${c.name}: exit ${r.status}, stderr ${JSON.stringify(first)} (want exit 1 and ${want})`);
    continue;
  }
  let got;
  let tokens;
  let report = {};
  try {
    report = JSON.parse(r.stdout);
    const m2 = report.metric2_tokensPerChange;
    got = m2.totalCommits;
    tokens = m2.totalTokensMainSessionsOnly;
  } catch {
    got = `no JSON (exit ${r.status}): ${r.stderr.trim().split("\n")[0]}`;
  }
  // Zero commits leaves metric 2 with 0 sessions, so tokens are only checked when counted.
  const tokensOk = c.expectMainTokens === undefined || tokens === c.expectMainTokens;
  // Each "a.b" key is a path into the JSON report.
  const jsonBad = Object.entries(c.json ?? {})
    .map(([k, want]) => [k, want, k.split(".").reduce((o, part) => o?.[part], report)])
    .filter(([, want, value]) => value !== want);
  const ok = got === c.expect && tokensOk && jsonBad.length === 0;
  if (!ok) failed += 1;
  const tokenNote = c.expectMainTokens === undefined ? "" : `, main tokens ${tokens} (want ${c.expectMainTokens})`;
  const jsonNote = jsonBad.map(([k, want, value]) => `, ${k} ${value} (want ${want})`).join("");
  console.log(`${ok ? "PASS" : "FAIL"}  ${c.name}: commits ${got} (want ${c.expect})${tokenNote}${jsonNote}`);
}

rmSync(root, { recursive: true, force: true });

console.log("");
console.log(`script: ${script}`);
console.log(`cases run: ${ran}, failed: ${failed}`);
if (ran === 0) {
  console.error("FAIL: ran 0 cases");
  process.exit(1);
}
process.exit(failed > 0 ? 1 : 0);
