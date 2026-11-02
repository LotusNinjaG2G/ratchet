"""End-to-end demo of the ratchet.

It shows the three things the top CTF teams had that a naive agent loop doesn't:

  1. PARALLEL LANES          warmups / reversing / web run concurrently
  2. RESULT reuse            re-running the same tasks reuses confirmed answers
  3. STRATEGY carry-forward  a brand-new day's tasks reuse the *approach* learned
                             earlier -- so they solve faster, with no result reuse

Run:  python demo.py
(delete ratchet_state.json to start cold again)
"""
import time

from ratchet import (
    ConfidenceVerifier,
    FunctionWorker,
    KnowledgeStore,
    Orchestrator,
    Result,
    Strategy,
    Task,
)


def make_solver(lane: str):
    """A stand-in solver. First time in a lane it has to *discover* the approach
    (slow) and reports a Strategy. Once that strategy has been ratcheted in, it is
    handed back on future tasks and the solver *applies* it (fast)."""

    def solve(task: Task, strategies):
        value = f"{lane.upper()}-{abs(hash((lane, task.id))) % 10**12:012d}"
        if strategies:
            time.sleep(0.10)  # we already know how -> fast
            return Result(value=value, confidence=0.99)  # nothing new to learn
        time.sleep(0.40)  # figuring out the approach the first time -> slow
        strat = Strategy(
            lane=lane,
            name=f"{lane}-playbook",
            note=f"Standard {lane} approach, first proven on {task.id}.",
        )
        return Result(value=value, confidence=0.97, strategy=strat)

    return solve


def build() -> Orchestrator:
    knowledge = KnowledgeStore("ratchet_state.json")
    orch = Orchestrator(knowledge, default_verifier=ConfidenceVerifier(0.9), max_workers=8)
    for lane in ("warmups", "reversing", "web"):
        orch.register(lane, FunctionWorker(make_solver(lane)))
    return orch


def tasks_for(day: int):
    return [
        Task(lane=lane, id=f"day{day}-{lane}-{n}")
        for lane in ("warmups", "reversing", "web")
        for n in range(1, 6)
    ]


def main() -> None:
    orch = build()

    print("1) Day 1, cold run (nothing in the ratchet yet -- must discover approaches):")
    print("   ", orch.run(tasks_for(1)))

    print("\n2) Day 1 again (same tasks -> confirmed RESULTS are reused, no work):")
    print("   ", orch.run(tasks_for(1)))

    print("\n3) Day 2, all-new tasks (results can't be reused, but the STRATEGIES")
    print("   learned on Day 1 carry forward -> solved, and faster):")
    print("   ", orch.run(tasks_for(2)))

    kn = orch.knowledge
    print(
        f"\nRatchet now holds {kn.result_count()} results and "
        f"{kn.strategy_count()} strategies across lanes {kn.lane_counts()}."
    )


if __name__ == "__main__":
    main()
