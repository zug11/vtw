"""Hybrid measurement cascade with confidence tiers.

The heuristic isn't a fallback — it's the first stage.
The exact solver doesn't replace it — it calibrates it.
The ErrorModel makes heuristic results more valuable.

Confidence tiers:
  'exact'                — n <= exact_threshold, exact solver ran
  'heuristic_calibrated' — n > threshold, error model applied
  'heuristic_raw'        — no error model available
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np

from vtw.config import VTWConfig
from vtw.constraint_graph import constraint_graph_stats
from vtw.exact import ExactSolver, ExactSolverResult
from vtw.heuristic import HeuristicMeasurer, HeuristicResult


@dataclass
class MeasurementResult:
    """Complete treewidth measurement with confidence metadata."""
    treewidth: int
    confidence: str  # 'exact', 'heuristic_calibrated', 'heuristic_raw'
    lower_bound: Optional[int]
    upper_bound: int
    tw_over_n: float  # Key VTW metric
    exact_result: Optional[ExactSolverResult] = None
    heuristic_result: Optional[HeuristicResult] = None
    graph_stats: Optional[dict] = None
    elapsed_seconds: float = 0.0


class ErrorModel:
    """Trained from (exact, heuristic) pairs on small instances.

    Learns the systematic bias of heuristic treewidth estimates
    and provides corrected confidence intervals.
    """

    def __init__(self):
        self.calibration_data: list[tuple[int, int, int]] = []  # (n_vars, exact_tw, heuristic_tw)
        self.mean_ratio: float = 1.0  # heuristic / exact
        self.std_ratio: float = 0.0
        self.fitted: bool = False

    def add_sample(self, n_vars: int, exact_tw: int, heuristic_tw: int):
        self.calibration_data.append((n_vars, exact_tw, heuristic_tw))

    def fit(self):
        """Compute error statistics from calibration data."""
        if len(self.calibration_data) < 3:
            self.fitted = False
            return

        ratios = []
        for n, exact, heur in self.calibration_data:
            if exact > 0:
                ratios.append(heur / exact)

        if ratios:
            self.mean_ratio = float(np.mean(ratios))
            self.std_ratio = float(np.std(ratios))
            self.fitted = True

    def predict_interval(
        self, heuristic_tw: int, n_vars: int
    ) -> tuple[float, float]:
        """Return (lower_estimate, upper_bound) with confidence.

        The heuristic gives an upper bound. The error model
        estimates how much it overestimates.
        """
        if not self.fitted or self.mean_ratio <= 0:
            return (0, heuristic_tw)

        # Corrected estimate: heuristic / mean_ratio
        corrected = heuristic_tw / self.mean_ratio

        # 95% confidence interval
        margin = 2 * self.std_ratio * corrected if self.std_ratio > 0 else 1.0
        lower = max(0, corrected - margin)
        upper = heuristic_tw  # Heuristic is always an upper bound

        return (lower, upper)

    def save(self, path: str):
        """Serialize error model to JSON."""
        data = {
            "calibration_data": self.calibration_data,
            "mean_ratio": self.mean_ratio,
            "std_ratio": self.std_ratio,
            "fitted": self.fitted,
        }
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str) -> "ErrorModel":
        """Load error model from JSON."""
        data = json.loads(Path(path).read_text())
        model = cls()
        model.calibration_data = [tuple(x) for x in data["calibration_data"]]
        model.mean_ratio = data["mean_ratio"]
        model.std_ratio = data["std_ratio"]
        model.fitted = data["fitted"]
        return model


class HybridMeasurement:
    """Confidence-tiered measurement cascade.

    1. Build constraint graph (once, reused)
    2. Heuristic measurement (always runs, fast)
    3. If n <= exact_threshold: exact measurement
    4. Return with confidence tier label
    """

    def __init__(
        self,
        config: VTWConfig,
        heuristic: Optional[HeuristicMeasurer] = None,
        exact: Optional[ExactSolver] = None,
        error_model: Optional[ErrorModel] = None,
    ):
        self.config = config
        self.heuristic = heuristic or HeuristicMeasurer()
        self.exact = exact or (ExactSolver(config) if config.has_exact_solver else None)
        self.error_model = error_model

    def measure(self, instance: "VTWInstance") -> MeasurementResult:
        """Full measurement cascade for a single instance."""
        start = time.monotonic()

        # Step 1: Build constraint graph (cached on instance)
        G = instance.to_constraint_graph()
        stats = constraint_graph_stats(G)

        # Step 2: Heuristic (always runs — it's fast)
        h_result = self.heuristic.measure(G)

        # Step 3: Exact if small enough and solver available
        e_result = None
        if (
            self.exact is not None
            and instance.n_vars <= self.config.exact_n_max
        ):
            try:
                e_result = self.exact.measure(G)
            except Exception:
                pass  # Graceful degradation

        elapsed = time.monotonic() - start

        # Determine confidence tier and best treewidth value
        if e_result is not None and not e_result.timed_out:
            tw = e_result.treewidth
            confidence = "exact"
            lower = tw
            upper = tw
        elif self.error_model is not None and self.error_model.fitted:
            lower, upper = self.error_model.predict_interval(
                h_result.treewidth_upper_bound, instance.n_vars
            )
            tw = h_result.treewidth_upper_bound
            confidence = "heuristic_calibrated"
            lower = int(lower)
        else:
            tw = h_result.treewidth_upper_bound
            confidence = "heuristic_raw"
            lower = None
            upper = tw

        tw_over_n = tw / instance.n_vars if instance.n_vars > 0 else 0.0

        return MeasurementResult(
            treewidth=tw,
            confidence=confidence,
            lower_bound=lower,
            upper_bound=upper,
            tw_over_n=tw_over_n,
            exact_result=e_result,
            heuristic_result=h_result,
            graph_stats=stats,
            elapsed_seconds=elapsed,
        )

    def calibrate(
        self,
        n_range: tuple[int, int] = (5, 30),
        samples_per_n: int = 10,
        clause_ratio: float = 4.267,
    ) -> ErrorModel:
        """Build error model from small instances with both exact and heuristic.

        Generates instances, runs both measurement methods, trains
        the error model from (exact, heuristic) pairs.
        """
        from vtw.instance import VTWInstance

        if self.exact is None:
            raise RuntimeError(
                "Exact solver required for calibration. Run `python -m vtw build`."
            )

        model = ErrorModel()

        for n in range(n_range[0], n_range[1] + 1):
            for trial in range(samples_per_n):
                instance = VTWInstance.random_3sat(n, clause_ratio, seed=n * 1000 + trial)
                G = instance.to_constraint_graph()

                h_result = self.heuristic.measure(G)

                try:
                    e_result = self.exact.measure(G, timeout=60)
                    if not e_result.timed_out:
                        model.add_sample(n, e_result.treewidth, h_result.treewidth_upper_bound)
                except Exception:
                    continue

        model.fit()
        self.error_model = model
        return model
