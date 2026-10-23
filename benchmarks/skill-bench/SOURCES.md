# Public sources for skill-bench

Researched in October 2026 (licences read on each repo or dataset card; "unknown" means none was found, never a guess).
The rule is **public first**: a task whose gold answer and tests come from a vetted public benchmark beats one we write.
Authored tasks (`source.kind: authored`) cover only what no public set does, and are listed under "Gaps".
Datasets are never committed: `source.ref` + `source.license` in a task say where it came from.

## Admission test for any public task (public sets are not trustworthy as shipped)

OpenAI audited 138 SWE-bench Verified problems and found 59.4% had flawed tests or descriptions and gold patches that
frontier models could reproduce; Terminal-Bench 2.0 needed a 2.1 fix release. So every adopted task must show, once:
the start state fails; the gold passes k of k times in a clean container (flake test); a plausible wrong answer fails
(workaround, over-broad edit, test-editing shortcut); where destruction is possible, a "nothing else changed" check
exists. `skill_bench.py validate` enforces the first three for tasks in this directory.

## Adopt or adopt a subset, by field

| Field | Source | Licence | Take | Needs |
|---|---|---|---|---|
| debug (real issues) | SWE-bench-Live (`verified`, MultiLang) | MIT | recent months, JS/TS and Python, filtered by the admission test | Docker per instance |
| debug | SWE-bench Multilingual / SWE-PolyBench | MIT | JS/TS/Go/Rust instances | Docker |
| debug | SWE-bench Pro public (`scaleapi/SWE-bench_Pro-os`) | repo MIT, card none | JS/TS and Go instances | Docker; GPL source inside tasks |
| debug / feature | DeepSWE (`datacurve-ai/deep-swe`) | Apache-2.0 | shortest TypeScript tasks | Docker |
| debug / infra | Terminal-Bench 2.1 (`harbor-framework/terminal-bench-2-1`) | Apache-2.0 | fix-git, db-wal-recovery, sqlite-db-truncate, log-summary-date-ranges, query-optimize, cancel-async-tasks, custom-memory-heap-crash | harbor CLI, Docker |
| debug (fallback) | SWE-bench Verified subset | repo MIT, card blank | only instances passing the admission test | Docker |
| debug (shortcut probe) | ImpossibleBench | MIT | contradictory tests: a pass means a workaround | Docker |
| logic | EvalPlus (HumanEval+, MBPP+) | Apache-2.0 | index/range/slice tasks, as a cheap tier | Python only |
| logic / arch | over-editing (`nreHieW/over-editing`) | Apache-2.0 | the 76 range, comparison and indexing rows (a boundary bug with a known minimal fix); also measures excess edit | Python, BigCodeBench deps |
| logic | Aider polyglot / Exercism | Exercism MIT; polyglot repo has no licence file | date, money and change exercises, JS and Python | node, python |
| logic | BigCodeBench | Apache-2.0 | data-transformation tasks | Python deps |
| logic | QuixBugs | MIT | one-line off-by-one | Python |
| tests | SWE-Mutation | MIT | Python test-repair instances (mutants are the oracle) | Docker |
| tests | TDD-Bench-Verified | Apache-2.0 | instances not flagged by the audit | Docker |
| security | CWEval (`Co1lin/CWEval`) | Apache-2.0 | 25 Python tasks: injection, path traversal, deserialization, SSRF, logging | Python |
| security | BaxBench | MIT | Python and JS scenarios (login, secret_storage, logger, file_search); no gold, write it | Docker |
| security | Terminal-Bench security tasks | Apache-2.0 | fix-code-vulnerability, vulnerable-secret, git-leak-recovery, sanitize-git-repo | harbor |
| ui | `microsoft/a11y-llm-eval` | MIT | the harness design (control vs instruction vs skill arms, axe-core + Playwright) and its 7 cases | Docker, Playwright |
| ui | `bytedance/web-bench` | Apache-2.0 repo, CC-BY-4.0 data | layout/CSS projects (flex, float, grid, form, table) | Playwright |
| ui | W3C ACT-Rules test cases | W3C Software and Document licence | contrast, names, keyboard trap, aria-hidden focus | axe-core |
| ui | `open-design-system-bench` | MIT | tokens and states; already in forge (`benchmarks/design-system`) | node |
| judgment | SABER (`sssr-lab/saber`) | card Apache-2.0, repo mixed | data_destruction, fs_destruction, info_leak (716 tasks in all) | patterns + final state |
| judgment | Ask-or-Assume (`cmu-lti/interactive-swe`) | unknown | underspecified issues: ask before guessing | Docker; licence first |

Skipped with reason: DesignBench, Design2Code, WebGen-Bench, ArtifactsBench, WebDev Arena (no pass/fail oracle); LiveCodeBench,
CRUXEval (not agent-shaped); TestGenEval (CC BY-NC); SWT-Bench, TestSuiteBench (100 GB+); SecurityEval, CyberSecEval, OWASP
Benchmark, Juliet (static labels or copyleft); BugsInPy, IDoFT (licence unknown); SWE-Refactor (Java, 207 MB).

## Gaps (nothing public: author these)

Root cause vs workaround on flaky or intermittent tests, misleading error messages; fix a test that can never fail;
characterization tests before a refactor; date/time and money precision; secrets in logs and IDOR as small executable tasks;
deep-module extraction and dependency direction; and the judgment concepts: scope reframe, deletion consent, honest
verification claims, proportional checks, finishing the job. Design to copy: paired scenarios scored from tool-call logs and
final state (the OverEager style), and the pass-to-pass destructive-command probe from the Terminal-Bench audit.

## Measuring: what the research recommends

Arms: `none` (isolated config dir, no skill), `skill`, and for a revision `old`; optionally a length-matched placebo.
Same model and harness version, runs interleaved, tests and gold hidden from the workspace, skill scanned for task-specific
content (Terminal-Bench found an agent building its own AGENTS.md from the solution).
Size: 40 tasks pooled across fields, k=5 trials (minimum 3), the k trials averaged to one score per task, then paired.
Power (simulated, assumed model): 80% power at about 17 pp for 30x3, 12-13 pp for 40x5, 10 pp for 60x5; one trial per task
needs over 100 tasks for 10 pp. Prior art spans +16.6 pp (SkillsBench) to +1.2 pp (SWE-Skills-Bench, 39 of 49 skills at zero),
so a flat result from 40 tasks means "not larger than about 12 pp", not "no effect".
Report: paired mean difference with a 95% paired bootstrap CI over tasks (cluster by repository), a sign-flip permutation p
(exact McNemar if k=1), discordant counts, Wilson intervals per arm, tokens and time deltas. Fix the decision rule before
running (adopt only if the CI lower bound is above 0 and the estimate is at least a stated margin). Per-field n of about 6 is
descriptive. Where only a judge can score, blind it to arm, use a different model family, binary rubric items, three
repeats, and report agreement.
