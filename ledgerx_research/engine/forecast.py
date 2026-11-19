"""Demand forecasting with honest model selection: every method is back-tested on the history itself
(rolling origin) and the winner is chosen by out-of-sample error, never by in-sample fit."""
import math

from .common import num


def moving_average(series, h=1, window=3):
	w = max(1, min(window, len(series)))
	return [sum(series[-w:]) / w] * h


def ses_fit(series, alpha):
	level = series[0]
	for y in series[1:]:
		level = alpha * y + (1 - alpha) * level
	return level


def ses(series, h=1, alpha=None):
	if alpha is None:
		alpha = _best_alpha(series, lambda s, a: [ses_fit(s, a)] * 1)
	return [ses_fit(series, alpha)] * h


def _best_alpha(series, fc):
	best, ba = None, 0.3
	for a in [i / 20 for i in range(1, 20)]:
		err = 0.0
		for t in range(2, len(series)):
			err += (series[t] - fc(series[:t], a)[0]) ** 2
		if best is None or err < best:
			best, ba = err, a
	return ba


def holt(series, h=1, alpha=0.5, beta=0.3):
	if len(series) < 2:
		return [series[-1]] * h if series else [0.0] * h
	level, trend = series[0], series[1] - series[0]
	for y in series[1:]:
		prev = level
		level = alpha * y + (1 - alpha) * (level + trend)
		trend = beta * (level - prev) + (1 - beta) * trend
	return [level + (k + 1) * trend for k in range(h)]


def seasonal_naive(series, h=1, period=12):
	if len(series) < period:
		return moving_average(series, h)
	return [series[-period + (k % period)] for k in range(h)]


METHODS = {
	"moving_average": lambda s, h, p: moving_average(s, h, 3),
	"exp_smoothing": lambda s, h, p: ses(s, h),
	"holt_trend": lambda s, h, p: holt(s, h),
	"seasonal_naive": lambda s, h, p: seasonal_naive(s, h, p),
}


def backtest(series, method, period=12, min_train=None):
	"""Rolling-origin one-step errors. Returns (rmse, mae, wape); wape = sum|e| / sum|actual|."""
	min_train = min_train or max(3, period if method == "seasonal_naive" else 3)
	errs, acts = [], []
	for t in range(min_train, len(series)):
		f = METHODS[method](series[:t], 1, period)[0]
		errs.append(series[t] - f)
		acts.append(abs(series[t]))
	if not errs:
		return None
	rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
	mae = sum(abs(e) for e in errs) / len(errs)
	wape = sum(abs(e) for e in errs) / sum(acts) if sum(acts) else float("inf")
	return rmse, mae, wape


def forecast(series, h=3, period=12):
	"""Pick the best method by back-test RMSE and return forecasts with a ~95% band from the residual spread."""
	series = [max(num(v), 0.0) for v in series]
	if len(series) < 4:
		m = sum(series) / len(series) if series else 0.0
		return {"method": "average", "forecast": [m] * h, "low": [max(m, 0)] * h, "high": [m] * h, "rmse": None, "warning": "history too short: simple average"}
	scores = {}
	for name in METHODS:
		if name == "seasonal_naive" and len(series) < period * 2:
			continue
		bt = backtest(series, name, period)
		if bt:
			scores[name] = bt
	best = min(scores, key=lambda k: scores[k][0])
	fc = METHODS[best](series, h, period)
	rmse = scores[best][0]
	band = [1.96 * rmse * math.sqrt(k + 1) for k in range(h)]
	return {"method": best, "forecast": fc, "low": [max(f - b, 0.0) for f, b in zip(fc, band)], "high": [f + b for f, b in zip(fc, band)], "rmse": rmse,
		"wape": scores[best][2], "scores": {k: {"rmse": v[0], "wape": v[2]} for k, v in scores.items()}, "warning": None if scores[best][2] < 0.5 else "high error: treat as a rough guide"}
