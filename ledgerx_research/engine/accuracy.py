"""How right were earlier decisions? Compare what a plan expected with what happened."""
from .common import num


def errors(pairs):
	"""pairs: [(expected, actual)] -> MAE, RMSE, WAPE (% of actual), bias % (+ = over-expected), tracking signal and a verdict."""
	n = len(pairs)
	if not n:
		return {"n": 0, "verdict": "no_data"}
	e = [num(a) - num(x) for x, a in pairs]  # actual - expected
	actual = sum(abs(num(a)) for _x, a in pairs)
	mae = sum(abs(v) for v in e) / n
	rmse = (sum(v * v for v in e) / n) ** 0.5
	wape = sum(abs(v) for v in e) / actual * 100 if actual else None
	bias = -sum(e) / actual * 100 if actual else None
	ts = (sum(e) / mae) if mae else 0.0
	verdict = "no_data" if wape is None else ("reliable" if wape <= 20 and abs(bias) <= 10 else ("usable" if wape <= 40 else "unreliable"))
	return {"n": n, "mae": mae, "rmse": rmse, "wape": wape, "bias": bias, "tracking_signal": ts, "verdict": verdict}


def row_error(expected, actual):
	x, a = num(expected), num(actual)
	return {"error": a - x, "error_pct": ((a - x) / abs(a) * 100) if a else (0.0 if not x else 100.0)}
