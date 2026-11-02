"""Unit tests for ratchet. Run: python -m unittest -v"""
import os
import tempfile
import unittest

from ratchet import (
    ConfidenceVerifier,
    FunctionWorker,
    KnowledgeStore,
    Orchestrator,
    Result,
    Strategy,
    Task,
)


def worker(value="V", conf=1.0, strategy=None):
    return FunctionWorker(lambda t, s: Result(value=value, confidence=conf, strategy=strategy))


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "k.json")

    def test_result_confirm_and_persist(self):
        k = KnowledgeStore(self.path)
        k.confirm_result("web", "t1", "FLAG", 0.95)
        self.assertTrue(k.has_result("web", "t1"))
        self.assertEqual(KnowledgeStore(self.path).get_result("web", "t1"), "FLAG")

    def test_strategy_confirm_and_scoped_fetch(self):
        k = KnowledgeStore(self.path)
        k.confirm_strategy(Strategy("web", "idor", "swap the id and re-request"))
        k.confirm_strategy(Strategy("reversing", "diff", "diff vulnerable vs fixed"))
        reloaded = KnowledgeStore(self.path)  # survives reload
        web = reloaded.strategies_for("web")
        self.assertEqual(len(web), 1)
        self.assertEqual(web[0].name, "idor")
        self.assertEqual(reloaded.strategies_for("reversing")[0].name, "diff")
        self.assertEqual(reloaded.strategies_for("mobile"), [])

    def test_lane_counts_and_totals(self):
        k = KnowledgeStore(self.path)
        k.confirm_result("web", "a", "x")
        k.confirm_result("web", "b", "y")
        k.confirm_result("rev", "c", "z")
        self.assertEqual(k.lane_counts(), {"web": 2, "rev": 1})
        self.assertEqual(k.result_count(), 3)

    def test_corrupt_store_recovers(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        k = KnowledgeStore(self.path)
        self.assertEqual(k.result_count(), 0)
        self.assertEqual(k.strategy_count(), 0)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "k.json")

    def test_solve_then_reuse_results(self):
        calls = []

        def fn(task, strategies):
            calls.append(task.id)
            return Result(value="V", confidence=1.0)

        orch = Orchestrator(KnowledgeStore(self.path)).register("web", FunctionWorker(fn))
        tasks = [Task("web", f"t{i}") for i in range(5)]

        r1 = orch.run(tasks)
        self.assertEqual((r1.solved, r1.reused), (5, 0))

        r2 = orch.run(tasks)
        self.assertEqual((r2.reused, r2.solved), (5, 0))
        self.assertEqual(len(calls), 5)  # worker never re-invoked for known results

    def test_strategy_carries_forward_to_new_tasks(self):
        seen_strategies = []

        def fn(task, strategies):
            seen_strategies.append(len(strategies))
            strat = Strategy("web", "playbook", "the approach") if not strategies else None
            return Result(value="V", confidence=1.0, strategy=strat)

        orch = Orchestrator(KnowledgeStore(self.path)).register("web", FunctionWorker(fn))

        r1 = orch.run([Task("web", "a")])       # discovers + learns a strategy
        self.assertEqual(r1.strategies_learned, 1)

        r2 = orch.run([Task("web", "b")])       # NEW task id -> no result reuse
        self.assertEqual((r2.solved, r2.reused), (1, 0))
        self.assertEqual(r2.strategies_learned, 0)  # nothing new; it reused the approach
        self.assertEqual(seen_strategies, [0, 1])   # 2nd call received the carried strategy

    def test_low_confidence_not_ratcheted(self):
        orch = Orchestrator(
            KnowledgeStore(self.path), default_verifier=ConfidenceVerifier(0.9)
        ).register("web", worker(conf=0.5))
        r = orch.run([Task("web", "t1")])
        self.assertEqual((r.failed, r.solved), (1, 0))

    def test_worker_crash_is_failed_not_raised(self):
        def boom(task, strategies):
            raise RuntimeError("kaboom")

        orch = Orchestrator(KnowledgeStore(self.path)).register("web", FunctionWorker(boom))
        self.assertEqual(orch.run([Task("web", "t1")]).failed, 1)

    def test_unknown_lane_fails(self):
        orch = Orchestrator(KnowledgeStore(self.path))
        self.assertEqual(orch.run([Task("ghost", "t1")]).failed, 1)

    def test_parallel_lanes_run_concurrently(self):
        import time

        def slow(task, strategies):
            time.sleep(0.2)
            return Result(value="V", confidence=1.0)

        orch = Orchestrator(KnowledgeStore(self.path), max_workers=10)
        for lane in ("a", "b", "c", "d"):
            orch.register(lane, FunctionWorker(slow))
        tasks = [Task(lane, "t1") for lane in ("a", "b", "c", "d")]
        r = orch.run(tasks)
        self.assertEqual(r.solved, 4)
        # 4 x 0.2s serial would be 0.8s; in parallel it should be well under 0.5s
        self.assertLess(r.elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
