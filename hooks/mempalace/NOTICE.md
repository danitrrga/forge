# Copied from MemPalace

The four `.sh` files in this directory are MemPalace's Claude Code hook scripts, copied byte for byte (no
edit, no added line) from the `.claude-plugin/hooks/` directory of the tag below. forge writes the rows that
run them into the `.claude/settings.local.json` of a project that lists `mempalace` in `servers`, while
`integrations.mempalace` is on (`forge/hooks.py`). They are the upstream scripts and are not reworded: a
change goes to upstream, or here as a new pinned copy with a new hash.

- Source: https://github.com/MemPalace/mempalace
- Tag: `v3.12.0`
- Commit: `4df7b830ff1398332d4118884520a24f1aab9cc1`
- Licence: MIT, Copyright (c) 2026 MemPalace Contributors (text below)

Each file's line is the `copied-from:` record and the sha256 of the file as stored here, which is the sha256
of the upstream file; `tests/test_mempalace_project_hooks.py` compares the two on every run.

```
copied-from: MemPalace/mempalace .claude-plugin/hooks/mempal-stop-hook.sh @4df7b83  sha256 cc16eca20204cdc3a999bc6a471e853ef55b74823538493f10620f0d2f0bb9ce  mempal-stop-hook.sh
copied-from: MemPalace/mempalace .claude-plugin/hooks/mempal-session-end-hook.sh @4df7b83  sha256 d6e53593228a141f11ff8e68263182bcf54e2796e08080595aa7211ab56a9e38  mempal-session-end-hook.sh
copied-from: MemPalace/mempalace .claude-plugin/hooks/mempal-precompact-hook.sh @4df7b83  sha256 68b681c4f5493463d650f89879c584220ce16e5780e6012fe1d4d2da7cca8d58  mempal-precompact-hook.sh
copied-from: MemPalace/mempalace .claude-plugin/hooks/mempal_hook_run.sh @4df7b83  sha256 26393371839545d01d214a87bfad9d2baf761c1cf259fc1990c2281d5693132b  mempal_hook_run.sh
```

The timeouts forge writes for the three rows are upstream's own (`.claude-plugin/hooks/hooks.json` of the same tag):
Stop 30 s, SessionEnd 10 s, PreCompact 90 s. The SessionEnd script puts its save in a detached background process
and returns at once, because Claude Code gives a SessionEnd hook 1.5 s by default.

## Licence of the copied files

MIT License

Copyright (c) 2026 MemPalace Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
