"""Shared helpers. Every solver in this package returns a dict that includes `verified`: the answer was
re-checked by independent pure-Python code (feasibility and, for LPs, a duality certificate), so a wrong
solver result is caught instead of shown."""
TOL = 1e-6


def num(v, default=0.0):
	try:
		return float(v)
	except (TypeError, ValueError):
		return default


def require_scipy():
	try:
		import numpy  # noqa: F401
		import scipy  # noqa: F401
		from scipy.optimize import linprog, milp  # noqa: F401
	except Exception as e:  # pragma: no cover
		raise RuntimeError("scipy is required for the optimisation solvers: pip install scipy") from e


def close(a, b, tol=1e-6):
	return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
