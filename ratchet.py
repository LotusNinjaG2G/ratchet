"""ratchet: a parallel agent-orchestration harness with a durable knowledge
'ratchet' that carries both confirmed RESULTS and reusable STRATEGIES forward.

Why both?
  * A **result** only helps if you hit the exact same task again.
  * A **strategy** is the approach that solved it -- and it carries forward to
    brand-new tasks in the same domain, so each run makes the next one faster.

Built after clearing Huntress CTF 2026: AI Arena. During the event I ran agents
to solve challenges but rebuilt know-how from scratch each day. The teams at the
top carried a knowledge ratchet forward and ran lanes in parallel. This is that
missing piece, generalized.

Pure standard library. Pairs with `agent-guardrails` for the human-approval gate.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, List, Optional

__all__ = [
    "Task",
    "Strategy",
    "Result",
    "KnowledgeStore",
    "Verifier",
    "ConfidenceVerifier",
    "HumanVerifier",
    "Worker",
    "FunctionWorker",
    "Lane",
    "Orchestrator",
    "RunReport",
]


@dataclass
class Task:
    lane: str
    id: str
    payload: Any = None


@dataclass
class Strategy:
    """A reusable approach that solved a task and generalizes to new ones."""

    lane: str
    name: str
    note: str  # the approach, in words or as a short recipe
    pattern: Optional[str] = None  # optional tag to match applicable tasks
    confidence: float = 1.0


@dataclass
class Result:
    value: Any = None
    confidence: float = 1.0
    ok: bool = True
    reused: bool = False
    error: Optional[str] = None
    strategy: Optional[Strategy] = None  # a *new* strategy to ratchet forward


class KnowledgeStore:
    """Durable, thread-safe store of confirmed results AND strategies -- the ratchet.

    Backed by a JSON file written atomically. Lets a fleet of agents carry proven
    knowledge forward across runs, days, crashes, and restarts instead of
    re-deriving it.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._results: dict[str, Any] = {}
        self._strategies: dict[str, Any] = {}
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                self._results = data.get("results", {})
                self._strategies = data.get("strategies", {})
            except (json.JSONDecodeError, OSError):
                self._results, self._strategies = {}, {}

    def _flush(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"results": self._results, "strategies": self._strategies},
                f,
                indent=2,
                sort_keys=True,
            )
        os.replace(tmp, self.path)

    # ---- results ----
    def has_result(self, lane: str, task_id: str) -> bool:
        with self._lock:
            return f"{lane}:{task_id}" in self._results

    def get_result(self, lane: str, task_id: str, default: Any = None) -> Any:
        with self._lock:
            rec = self._results.get(f"{lane}:{task_id}")
            return rec["value"] if rec else default

    def confirm_result(self, lane: str, task_id: str, value: Any, confidence: float = 1.0) -> None:
        with self._lock:
            self._results[f"{lane}:{task_id}"] = {
                "value": value,
                "confidence": confidence,
                "lane": lane,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._flush()

    # ---- strategies ----
    def confirm_strategy(self, strategy: Strategy) -> None:
        with self._lock:
            self._strategies[f"{strategy.lane}:{strategy.name}"] = {
                "lane": strategy.lane,
                "name": strategy.name,
                "note": strategy.note,
                "pattern": strategy.pattern,
                "confidence": strategy.confidence,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._flush()

    def strategies_for(self, lane: str) -> List[Strategy]:
        with self._lock:
            return [
                Strategy(
                    lane=v["lane"],
                    name=v["name"],
                    note=v["note"],
                    pattern=v.get("pattern"),
                    confidence=v.get("confidence", 1.0),
                )
                for v in self._strategies.values()
                if v["lane"] == lane
            ]

    # ---- summaries ----
    def result_count(self) -> int:
        with self._lock:
            return len(self._results)

    def strategy_count(self) -> int:
        with self._lock:
            return len(self._strategies)

    def lane_counts(self) -> dict:
        with self._lock:
            counts: dict[str, int] = {}
            for v in self._results.values():
                counts[v["lane"]] = counts.get(v["lane"], 0) + 1
            return counts


class Verifier:
    def verify(self, task: Task, result: Result) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class ConfidenceVerifier(Verifier):
    """Accept a result only if it clears a confidence threshold (non-interactive)."""

    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    def verify(self, task: Task, result: Result) -> bool:
        return result.ok and result.confidence >= self.threshold


class HumanVerifier(Verifier):
    """Ask a human to confirm before a result is ratcheted in. Use for serial runs."""

    def __init__(self, stream=None, out=None):
        self.stream = stream if stream is not None else sys.stdin
        self.out = out if out is not None else sys.stdout

    def verify(self, task: Task, result: Result) -> bool:
        self.out.write(
            f"\n[verify] {task.lane}/{task.id} -> {result.value!r} "
            f"(confidence {result.confidence:.0%}); accept? [y/N] "
        )
        self.out.flush()
        return self.stream.readline().strip().lower() in ("y", "yes")


class Worker:
    """Solves a task, optionally using strategies carried forward by the ratchet."""

    def solve(self, task: Task, strategies: List[Strategy]) -> Result:  # pragma: no cover
        raise NotImplementedError


class FunctionWorker(Worker):
    """Wrap a callable `fn(task, strategies) -> Result | value` as a Worker."""

    def __init__(self, fn: Callable[[Task, List[Strategy]], Any]):
        self.fn = fn

    def solve(self, task: Task, strategies: List[Strategy]) -> Result:
        out = self.fn(task, strategies)
        return out if isinstance(out, Result) else Result(value=out)


@dataclass
class Lane:
    name: str
    worker: Worker
    verifier: Optional[Verifier] = None


@dataclass
class RunReport:
    solved: int = 0
    reused: int = 0
    failed: int = 0
    strategies_learned: int = 0
    elapsed: float = 0.0
    per_lane: dict = field(default_factory=dict)

    def total(self) -> int:
        return self.solved + self.reused + self.failed

    def __str__(self) -> str:
        lanes = ", ".join(f"{k}:{v}" for k, v in sorted(self.per_lane.items()))
        return (
            f"RunReport(total={self.total()} solved={self.solved} "
            f"reused={self.reused} failed={self.failed} "
            f"strategies_learned={self.strategies_learned} "
            f"elapsed={self.elapsed:.2f}s | {lanes})"
        )


class Orchestrator:
    """Runs tasks across lanes in parallel. For each task it (1) reuses a confirmed
    result if one exists, otherwise (2) hands the worker the strategies carried
    forward for that lane, (3) verifies the result, and (4) ratchets in the result
    and any new strategy it produced."""

    def __init__(
        self,
        knowledge: KnowledgeStore,
        default_verifier: Optional[Verifier] = None,
        max_workers: int = 8,
    ):
        self.knowledge = knowledge
        self.default_verifier = default_verifier or ConfidenceVerifier()
        self.max_workers = max_workers
        self._lanes: dict[str, Lane] = {}

    def register(self, name: str, worker: Worker, verifier: Optional[Verifier] = None) -> "Orchestrator":
        self._lanes[name] = Lane(name, worker, verifier)
        return self

    def _handle(self, task: Task) -> tuple:
        if self.knowledge.has_result(task.lane, task.id):
            return ("reused", 0)

        lane = self._lanes.get(task.lane)
        if lane is None:
            return ("failed", 0)

        strategies = self.knowledge.strategies_for(task.lane)  # carried-forward know-how
        try:
            result = lane.worker.solve(task, strategies)
        except Exception:  # a worker crash must not sink the whole run
            return ("failed", 0)

        result.reused = False
        verifier = lane.verifier or self.default_verifier
        if result.ok and verifier.verify(task, result):
            self.knowledge.confirm_result(task.lane, task.id, result.value, result.confidence)
            learned = 0
            if result.strategy is not None:
                self.knowledge.confirm_strategy(result.strategy)
                learned = 1
            return ("solved", learned)
        return ("failed", 0)

    def run(self, tasks: Iterable[Task]) -> RunReport:
        tasks = list(tasks)
        report = RunReport()
        start = time.time()
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._handle, t): t for t in tasks}
            for fut in as_completed(futures):
                outcome, learned = fut.result()
                task = futures[fut]
                setattr(report, outcome, getattr(report, outcome) + 1)
                report.strategies_learned += learned
                report.per_lane[task.lane] = report.per_lane.get(task.lane, 0) + 1
        report.elapsed = time.time() - start
        return report
