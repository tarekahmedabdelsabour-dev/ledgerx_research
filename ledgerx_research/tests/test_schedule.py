import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ledgerx_research.engine import schedule as S


class TestSingleMachine(unittest.TestCase):
	def _jobs(self, rnd, n):
		return [{"id": f"j{i}", "hours": rnd.randint(1, 9), "due": rnd.randint(2, 25)} for i in range(n)]

	def test_spt_optimal_total_completion(self):
		rnd = random.Random(1)
		for _ in range(30):
			jobs = self._jobs(rnd, 6)
			best = min(S.evaluate_sequence(p)["total_completion"] for p in itertools.permutations(jobs))
			self.assertAlmostEqual(S.single_machine(jobs, "total_completion")["total_completion"], best, 6)

	def test_edd_optimal_max_lateness(self):
		rnd = random.Random(2)
		for _ in range(30):
			jobs = self._jobs(rnd, 6)
			best = min(S.evaluate_sequence(p)["max_lateness"] for p in itertools.permutations(jobs))
			self.assertAlmostEqual(S.single_machine(jobs, "max_lateness")["max_lateness"], best, 6)

	def test_tardiness_dp_exact(self):
		rnd = random.Random(3)
		for _ in range(30):
			jobs = self._jobs(rnd, 7)
			best = min(S.evaluate_sequence(p)["total_tardiness"] for p in itertools.permutations(jobs))
			r = S.single_machine(jobs, "total_tardiness")
			self.assertAlmostEqual(r["total_tardiness"], best, 6)
			self.assertTrue(r["exact"])

	def test_empty_and_bad_objective(self):
		self.assertEqual(S.single_machine([], "total_completion")["makespan"], 0.0)
		with self.assertRaises(ValueError):
			S.single_machine([], "nope")


class TestParallel(unittest.TestCase):
	def test_known(self):
		jobs = [{"id": i, "hours": h} for i, h in enumerate([7, 7, 6, 6, 5, 5, 4, 4, 4])]  # classic LPT trap: optimum 15 on 3 machines
		r = S.parallel_machines(jobs, [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}])
		self.assertTrue(r["verified"])
		self.assertAlmostEqual(r["makespan"], 16, 6)

	def test_exact_matches_bruteforce(self):
		rnd = random.Random(5)
		for _ in range(25):
			n, m = rnd.randint(3, 6), rnd.randint(2, 3)
			jobs = [{"id": i, "hours": rnd.randint(1, 12)} for i in range(n)]
			machines = [{"id": f"m{k}", "speed": rnd.choice([1, 1, 2]), "available_from": rnd.choice([0, 0, 3])} for k in range(m)]
			best = float("inf")
			for assign in itertools.product(range(m), repeat=n):
				fin = [machines[k]["available_from"] for k in range(m)]
				for j, k in zip(jobs, assign):
					fin[k] += j["hours"] / machines[k]["speed"]
				best = min(best, max(fin))
			r = S.parallel_machines(jobs, machines)
			self.assertTrue(r["verified"])
			self.assertAlmostEqual(r["makespan"], best, 6)

	def test_lower_bound_never_above_makespan(self):
		rnd = random.Random(8)
		for _ in range(40):
			jobs = [{"id": i, "hours": rnd.randint(1, 30)} for i in range(rnd.randint(10, 25))]
			r = S.parallel_machines(jobs, [{"id": f"m{k}"} for k in range(rnd.randint(2, 5))])
			self.assertTrue(r["verified"])
			self.assertLessEqual(r["lower_bound"], r["makespan"] + 1e-9)

	def test_empty(self):
		self.assertEqual(S.parallel_machines([], [{"id": "m"}])["status"], "empty")


class TestJobShop(unittest.TestCase):
	def _orders(self, rnd, n, m):
		out = []
		for i in range(n):
			ms = rnd.sample(range(m), rnd.randint(1, m))
			out.append({"id": f"o{i}", "ops": [(f"m{k}", rnd.randint(1, 6)) for k in ms], "due": rnd.randint(8, 30)})
		return out

	def test_feasible_and_bounded(self):
		rnd = random.Random(13)
		for _ in range(40):
			orders = self._orders(rnd, rnd.randint(2, 8), rnd.randint(2, 4))
			s = S.job_shop(orders)
			self.assertTrue(s["verified"])
			self.assertGreaterEqual(s["makespan"], s["lower_bound"] - 1e-9)

	def test_against_bruteforce_optimum(self):
		rnd = random.Random(17)
		gaps = []
		for _ in range(30):
			orders = self._orders(rnd, 3, 3)
			opt = S.job_shop_optimum_bruteforce(orders)
			s = S.job_shop(orders)
			self.assertGreaterEqual(s["makespan"], opt - 1e-9)  # a schedule can never beat the true optimum
			gaps.append(s["makespan"] / opt - 1)
		self.assertLess(sum(gaps) / len(gaps), 0.12)  # on tiny shops the best-of-rules is within a few percent on average

	def test_best_of_rules_not_worse_than_fifo(self):
		rnd = random.Random(19)
		for _ in range(30):
			orders = self._orders(rnd, 6, 3)
			self.assertLessEqual(S.job_shop(orders)["makespan"], S.job_shop(orders, rules=("fifo",))["makespan"] + 1e-9)

	def test_release_respected(self):
		orders = [{"id": "a", "ops": [("m", 3)], "release": 10}]
		s = S.job_shop(orders)
		self.assertEqual(s["ops"][0]["start"], 10)
		self.assertTrue(s["verified"])

	def test_tardiness_objective(self):
		orders = [{"id": "a", "ops": [("m", 5)], "due": 5}, {"id": "b", "ops": [("m", 1)], "due": 1}]
		s = S.job_shop(orders, objective="total_tardiness")
		self.assertEqual(s["total_tardiness"], 1.0)  # b first (due 1), then a finishing at 6 (1 late)


if __name__ == "__main__":
	unittest.main()
