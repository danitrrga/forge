fwx is an agentic framework for Claude Code: a phase moves through stages (data/stages.json), and its state lives in `.fwx/`.
Agents write only what their task names; the owner decides what is not decided yet.
Put each fix in the strongest layer: code, then a check, then prose. A check is trusted only after it was seen failing; `NOT RUN` is not green.
Commands: `fwx state`, `fwx stage`, `fwx verify`, `fwx decide`, `fwx rounds`, `fwx model`, `fwx budget`.
Before building anything, look for a command, a skill or an agent that already does it.
