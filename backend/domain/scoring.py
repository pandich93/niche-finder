"""Backwards-compatible shim. The real formulas moved to metrics.py, which also
carries the median baseline, age adjustment, velocity and revenue models.
Kept so older imports (and the NexLev-parity score) keep working.
"""
from domain.metrics import avg_channel_views, outlier_score  # noqa: F401
