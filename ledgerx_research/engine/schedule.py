"""Scheduling. Every schedule is verified (no machine overlap, precedence kept, nothing starts before its release),
and every result carries a lower bound so the possible gap to the true optimum is visible."""
import itertools

from .common import num, require_scipy


# ----------------------------------------------------------------------------- single machine

def single_machine(jobs, objective="total_completion"):
	"""jobs: [{id, hours, due=None, release=0}] (release is ignored: all jobs are available at 0).
	total_completion -> SPT (optimal); max_lateness -> EDD (optimal); total_tardiness -> exact DP up to 15 jobs,
	otherwise the better of EDD and SPT (flagged `exact: False`)."""
	jobs = [dict(j) for j in jobs]
	if objective == "total_completion":
		order = sorted(jobs, key=lambda j: (num(j["hours"]), str(j["id"])))
		exact = True
	elif objective == "max_lateness":
		order = sorted(jobs, key=lambda j: (num(j.get("due"), 1e18), str(j["id"])))
		exact = True
	elif objective == "total_tardiness":
		if len(jobs) <= 15:
			order, exact = _tardiness_dp(jobs), True
		else:
			cands = [sorted(jobs, key=lambda j: (num(j.get("due"), 1e18), str(j["id"]))), sorted(jobs, key=lambda j: (num(j["hours"]), str(j["id"])))]
			order, exact = min(cands, key=lambda o: evaluate_sequence(o)["total_tardiness"]), False
	else:
		raise ValueError("objective")
	res = evaluate_sequence(order)
	res.update({"order": [j["id"] for j in order], "exact": exact})
	return res


def evaluate_sequence(order):
	t, rows, tard, late, comp = 0.0, [], 0.0, float("-inf"), 0.0
	for j in order:
		start, t = t, t + num(j["hours"])
		due = j.get("due")
		l = t - num(due) if due is not None else 0.0
		tard += max(l, 0.0) if due is not None else 0.0
		late = max(late, l) if due is not None else late
		comp += t
		rows.append({"id": j["id"], "start": start, "end": t})
	return {"schedule": rows, "makespan": t, "total_completion": comp, "total_tardiness": tard, "max_lateness": None if late == float("-inf") else late}


def _tardiness_dp(jobs):
	n = len(jobs)
	INF = float("inf")
	p = [num(j["hours"]) for j in jobs]
	d = [num(j.get("due"), 1e18) for j in jobs]
	psum = [0.0] * (1 << n)
	for m in range(1, 1 << n):
		low = (m & -m).bit_length() - 1
		psum[m] = psum[m & (m - 1)] + p[low]
	best = [INF] * (1 << n)
	choice = [-1] * (1 << n)
	best[0] = 0.0
	for m in range(1, 1 << n):
		for j in range(n):
			if m & (1 << j):
				prev = m ^ (1 << j)
				v = best[prev] + max(psum[m] - d[j], 0.0)
				if v < best[m] - 1e-12:
					best[m], choice[m] = v, j
	order, m = [], (1 << n) - 1
	while m:
		j = choice[m]
		order.append(jobs[j])
		m ^= 1 << j
	return order[::-1]


# ----------------------------------------------------------------------------- parallel machines

def parallel_machines(jobs, machines, exact_limit=14):
	"""Assign jobs (hours of work) to machines (speed, available_from) to minimise the finish time of the last job.
	LPT heuristic always; exact MILP when jobs*machines is small. Result: assignment, per-machine finish, makespan, lower bound."""
	jobs = [dict(j) for j in jobs]
	ms = {m["id"]: (num(m.get("speed"), 1.0) or 1.0, num(m.get("available_from"))) for m in machines}
	if not jobs or not ms:
		return {"status": "empty", "assignment": {}, "makespan": 0.0, "lower_bound": 0.0, "verified": True, "exact": True}
	fin = {k: a for k, (_s, a) in ms.items()}
	assign = {k: [] for k in ms}
	for j in sorted(jobs, key=lambda j: (-num(j["hours"]), str(j["id"]))):
		k = min(ms, key=lambda m: (fin[m] + num(j["hours"]) / ms[m][0], str(m)))
		fin[k] += num(j["hours"]) / ms[k][0]
		assign[k].append(j["id"])
	makespan = max(fin.values())
	work = sum(num(j["hours"]) for j in jobs)
	smax, ssum = max(s for s, _a in ms.values()), sum(s for s, _a in ms.values())
	lb = max(max(num(j["hours"]) for j in jobs) / smax, (work + sum(s * a for s, a in ms.values())) / ssum)
	out = {"status": "optimal" if makespan <= lb + 1e-9 else "heuristic", "assignment": assign, "finish": fin, "makespan": makespan, "lower_bound": lb, "exact": makespan <= lb + 1e-9}
	if not out["exact"] and len(jobs) * len(ms) <= exact_limit * 4:
		ex = _parallel_exact(jobs, ms)
		if ex and ex["makespan"] < makespan - 1e-9:
			out.update(ex)
		if ex:
			out["exact"], out["status"] = True, "optimal"
			out["lower_bound"] = out["makespan"]
	out["gap_pct"] = (out["makespan"] / out["lower_bound"] - 1) * 100 if out["lower_bound"] > 0 else 0.0
	out["verified"] = _verify_parallel(jobs, ms, out)
	return out


def _parallel_exact(jobs, ms):
	require_scipy()
	import numpy as np
	from scipy.optimize import Bounds, LinearConstraint, milp

	J, K = list(jobs), list(ms)
	nj, nk = len(J), len(K)
	nv = nj * nk + 1
	c = np.zeros(nv)
	c[-1] = 1
	rows, lo, hi = [], [], []
	for i in range(nj):  # each job on exactly one machine
		r = np.zeros(nv)
		r[i * nk:(i + 1) * nk] = 1
		rows.append(r), lo.append(1), hi.append(1)
	for k, name in enumerate(K):  # finish_k <= C
		r = np.zeros(nv)
		for i in range(nj):
			r[i * nk + k] = num(J[i]["hours"]) / ms[name][0]
		r[-1] = -1
		rows.append(r), lo.append(-np.inf), hi.append(-ms[name][1])
	integ = np.ones(nv)
	integ[-1] = 0
	res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=integ, bounds=Bounds(np.zeros(nv), np.concatenate([np.ones(nv - 1), [np.inf]])))
	if res.status != 0:
		return None
	assign = {name: [] for name in K}
	fin = {name: ms[name][1] for name in K}
	for i in range(nj):
		k = int(np.argmax(res.x[i * nk:(i + 1) * nk]))
		assign[K[k]].append(J[i]["id"])
		fin[K[k]] += num(J[i]["hours"]) / ms[K[k]][0]
	return {"assignment": assign, "finish": fin, "makespan": max(fin.values())}


def _verify_parallel(jobs, ms, out):
	seen = sorted(map(str, sum(out["assignment"].values(), [])))
	if seen != sorted(str(j["id"]) for j in jobs):
		return False
	byid = {j["id"]: num(j["hours"]) for j in jobs}
	for k, ids in out["assignment"].items():
		if abs(ms[k][1] + sum(byid[i] for i in ids) / ms[k][0] - out["finish"][k]) > 1e-6:
			return False
	return abs(max(out["finish"].values()) - out["makespan"]) < 1e-6 and out["makespan"] >= out["lower_bound"] - 1e-6


# ----------------------------------------------------------------------------- job shop (work orders through workstations)

RULES = ("fifo", "spt", "lpt", "edd", "mwkr")


def job_shop(orders, rules=RULES, objective="makespan"):
	"""orders: [{id, ops: [(machine, hours), ...] in routing order, release=0, due=None}].
	Dispatches with several rules (non-delay list scheduling) and keeps the best by `objective`
	(makespan | total_tardiness). Heuristic: the result reports a lower bound and the gap."""
	best = None
	for rule in rules:
		s = _dispatch(orders, rule)
		key = s[objective] if objective in s else s["makespan"]
		if best is None or key < best[0] - 1e-12:
			best = (key, rule, s)
	s = best[2]
	s["rule"] = best[1]
	s["lower_bound"] = job_shop_lower_bound(orders)
	s["gap_pct"] = (s["makespan"] / s["lower_bound"] - 1) * 100 if s["lower_bound"] > 0 else 0.0
	s["verified"] = verify_job_shop(orders, s)
	return s


def job_shop_lower_bound(orders):
	load = {}
	for o in orders:
		for m, h in o["ops"]:
			load[m] = load.get(m, 0.0) + num(h)
	chain = max((num(o.get("release")) + sum(num(h) for _m, h in o["ops"]) for o in orders), default=0.0)
	return max(chain, max(load.values(), default=0.0))


def _dispatch(orders, rule):
	nxt = {o["id"]: 0 for o in orders}
	ready_at = {o["id"]: num(o.get("release")) for o in orders}
	free = {}
	rem = {o["id"]: sum(num(h) for _m, h in o["ops"]) for o in orders}
	by = {o["id"]: o for o in orders}
	ops = []
	left = sum(len(o["ops"]) for o in orders)
	while left:
		cand = []
		for oid, i in nxt.items():
			o = by[oid]
			if i < len(o["ops"]):
				m, h = o["ops"][i]
				cand.append((max(ready_at[oid], free.get(m, 0.0)), oid, m, num(h)))
		t0 = min(c[0] for c in cand)
		pool = [c for c in cand if c[0] <= t0 + 1e-12]
		key = {"fifo": lambda c: (ready_at[c[1]], str(c[1])), "spt": lambda c: (c[3], str(c[1])), "lpt": lambda c: (-c[3], str(c[1])),
			"edd": lambda c: (num(by[c[1]].get("due"), 1e18), str(c[1])), "mwkr": lambda c: (-rem[c[1]], str(c[1]))}[rule]
		start, oid, m, h = min(pool, key=key)
		end = start + h
		ops.append({"order": oid, "machine": m, "op": nxt[oid], "start": start, "end": end})
		free[m] = end
		ready_at[oid] = end
		rem[oid] -= h
		nxt[oid] += 1
		left -= 1
	done = {}
	for r in ops:
		done[r["order"]] = max(done.get(r["order"], 0.0), r["end"])
	tard = sum(max(done[o["id"]] - num(o["due"]), 0.0) for o in orders if o.get("due") is not None)
	return {"ops": ops, "makespan": max((r["end"] for r in ops), default=0.0), "completion": done, "total_tardiness": tard}


def verify_job_shop(orders, s):
	by = {o["id"]: o for o in orders}
	per_m = {}
	last_end = {}
	for r in sorted(s["ops"], key=lambda r: (r["order"], r["op"])):
		o = by[r["order"]]
		m, h = o["ops"][r["op"]]
		if m != r["machine"] or abs(r["end"] - r["start"] - num(h)) > 1e-6:
			return False
		if r["start"] < last_end.get(r["order"], num(o.get("release"))) - 1e-6:
			return False
		last_end[r["order"]] = r["end"]
		per_m.setdefault(r["machine"], []).append((r["start"], r["end"]))
	for lst in per_m.values():
		lst.sort()
		for (a1, b1), (a2, _b2) in zip(lst, lst[1:]):
			if a2 < b1 - 1e-6:
				return False
	return sum(len(o["ops"]) for o in orders) == len(s["ops"])


def job_shop_optimum_bruteforce(orders):
	"""Test oracle for tiny instances: tries every operation order on every machine."""
	mach = {}
	for o in orders:
		for i, (m, _h) in enumerate(o["ops"]):
			mach.setdefault(m, []).append((o["id"], i))
	names = list(mach)
	best = float("inf")
	by = {o["id"]: o for o in orders}
	for perms in itertools.product(*[itertools.permutations(mach[m]) for m in names]):
		pred = {}
		for m, perm in zip(names, perms):
			for a, b in zip(perm, perm[1:]):
				pred.setdefault(b, []).append(a)
		memo, ok = {}, True

		def end_of(node, stack=()):
			nonlocal ok
			if node in memo:
				return memo[node]
			if node in stack:
				ok = False
				return 0.0
			oid, i = node
			start = num(by[oid].get("release"))
			if i > 0:
				start = max(start, end_of((oid, i - 1), stack + (node,)))
			for p in pred.get(node, []):
				start = max(start, end_of(p, stack + (node,)))
			memo[node] = start + num(by[oid]["ops"][i][1])
			return memo[node]
		ms = max(end_of(n) for ns in mach.values() for n in ns)
		if ok:
			best = min(best, ms)
	return best
