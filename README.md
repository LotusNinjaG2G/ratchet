# ratchet

**A parallel agent-orchestration harness with a durable knowledge "ratchet."** It carries two kinds of knowledge forward across runs so a fleet of agents gets faster every day:

- **Results** — confirmed answers, reused instantly when the same task comes back.
- **Strategies** — the *approach* that solved a task, applied to brand-new tasks in the same domain.

A result only helps if you hit the exact same task again. A **strategy** compounds. That's what makes this a ratchet, not a cache.

Pure Python standard library. No dependencies.

---

## Why this exists

This came out of clearing **[Huntress CTF 2026: AI Arena](https://github.com/LotusNinjaG2G/huntress-ctf-2026-writeups)** with an AI-agent workflow. I ran agents to solve challenges, but I rebuilt know-how from scratch every day. The teams at the very top did two things I didn't:

1. ran their lanes **in parallel**, and
2. carried a **knowledge ratchet** forward — confirmed facts *and* reusable tactics — so each day started ahead of the last.

`ratchet` is that missing piece, generalized into a small reusable harness. It pairs with **[agent-guardrails](https://github.com/LotusNinjaG2G/agent-guardrails)** for the human-approval gate on consequential actions.

## What it does

- **Parallel lanes.** Register a worker per lane (e.g. `warmups`, `reversing`, `web`); tasks run concurrently on a thread pool.
- **Result reuse.** A confirmed result is returned instantly — the worker is never re-invoked for a task already solved.
- **Strategy carry-forward.** When a worker solves a task it can report the *strategy* it used. Verified strategies are ratcheted in and handed to the worker on every future task in that lane, so new tasks solve faster.
- **Verification before commit.** Nothing enters the ratchet until a `Verifier` accepts it — a confidence threshold, a human prompt, or your own policy.
- **Durable + crash-safe.** The whole ratchet is one atomically-written JSON file; it survives restarts and reloads clean (even from a corrupt file).

## Install

```bash
git clone https://github.com/LotusNinjaG2G/ratchet.git
cd ratchet
python -m unittest -v   # run the tests (standard library only)
python demo.py          # watch the ratchet compound
```

## Quickstart

```python
from ratchet import Orchestrator, KnowledgeStore, FunctionWorker, Task, Result, Strategy

def solve(task, strategies):
    # `strategies` are the approaches already proven in this lane -- reuse them.
    if strategies:
        return Result(value=do_it_fast(task), confidence=0.99)
    # first time: solve the hard way and report the approach so it carries forward
    return Result(
        value=figure_it_out(task),
        confidence=0.95,
        strategy=Strategy(lane=task.lane, name="idor", note="swap the object id and re-request"),
    )

orch = Orchestrator(KnowledgeStore("state.json"))
orch.register("web", FunctionWorker(solve))

orch.run([Task("web", "target-1"), Task("web", "target-2")])  # solves, learns the strategy
orch.run([Task("web", "target-3")])                           # new task, reuses the strategy
```

## Demo output

```
1) Day 1, cold run (nothing in the ratchet yet -- must discover approaches):
    RunReport(total=15 solved=15 reused=0 failed=0 strategies_learned=3 elapsed=0.81s | ...)

2) Day 1 again (same tasks -> confirmed RESULTS are reused, no work):
    RunReport(total=15 solved=0 reused=15 failed=0 strategies_learned=0 elapsed=0.00s | ...)

3) Day 2, all-new tasks (results can't be reused, but the STRATEGIES
   learned on Day 1 carry forward -> solved, and faster):
    RunReport(total=15 solved=15 reused=0 failed=0 strategies_learned=0 elapsed=0.21s | ...)
```

Day 1 cold: **0.81s**. Day 2's all-new tasks: **0.21s** — ~4× faster, purely from carried-forward strategy.

## How it works

```
                         task
                          │
              ┌───────────▼────────────┐
              │  result already known? │ ── yes ──► reuse confirmed result
              └───────────┬────────────┘
                          │ no
            fetch strategies for this lane  ◄── the "ratchet"
                          │
                 worker.solve(task, strategies)
                          │
                 Verifier.verify(...)  ── reject ──► failed (nothing committed)
                          │ accept
          confirm result  +  confirm any new strategy  ──► ratchet grows
```

All of it runs across lanes in parallel on a `ThreadPoolExecutor`.

## Compose with agent-guardrails

For a hard human-approval gate before a result is committed (not just a confidence check), wrap the commit in an [agent-guardrails](https://github.com/LotusNinjaG2G/agent-guardrails) `Guard` inside a custom `Verifier`. The two libraries are designed to stack: `ratchet` decides *what to run and remember*; `agent-guardrails` decides *what's allowed to take effect*.

## Roadmap

`v0.1` (here): parallel lanes, result reuse, strategy carry-forward, pluggable verification, durable crash-safe store.

Next:
- **Pattern-matched strategies** — apply a strategy only to tasks whose `pattern` matches, with ranking by past success.
- **Strategy decay / scoring** — promote tactics that keep working, retire ones that don't.
- **Async workers + rate limits** — for real LLM/tool backends.
- **Shared/remote store** — SQLite or Redis so a whole team of agents ratchets together.
- **Run history + audit** — every solve, reuse, and verification, timestamped.

Issues and PRs welcome.

## License

MIT — see [LICENSE](LICENSE).

---

*Built by Jennifer Schieferle Uhlenbrock. Origin story: [Huntress CTF 2026 write-ups](https://github.com/LotusNinjaG2G/huntress-ctf-2026-writeups). Companion library: [agent-guardrails](https://github.com/LotusNinjaG2G/agent-guardrails).*
