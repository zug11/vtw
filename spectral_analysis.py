"""Spectral-treewidth correspondence — Problem 9 from v9.

The Auxiliary Expander Theorem (v9) connects Cheeger constant h >= Omega(1)
to treewidth >= Omega(n^{1/2}/log n) via the Grohe-Marx bound:
  tw(G) >= Omega(h * n / log n)

The spectral Cheeger inequality refines this:
  lambda_2/2 <= h(G) <= sqrt(2*lambda_2)

where lambda_2 is the second smallest eigenvalue of the normalized Laplacian.

This module:
1. Computes the full Laplacian spectrum for constraint graphs
2. Tracks lambda_2 (spectral gap) as a function of n and padding strategy
3. Fits the spectral-treewidth correlation to extract the empirical constant
4. Tests whether lambda_2 >= Omega(1/n) implies tw >= Omega(sqrt(n))

Usage:
    python -m vtw spectral --n-max 150 --trials 10
"""

import math
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
import numpy as np


@dataclass
class SpectralMeasurement:
    """Full spectral profile of a constraint graph."""
    n: int
    strategy: str
    treewidth: int
    lambda_2: float             # Second smallest Laplacian eigenvalue (spectral gap)
    lambda_max: float           # Largest eigenvalue
    cheeger_lower: float        # lambda_2 / 2
    cheeger_upper: float        # sqrt(2 * lambda_2)
    cheeger_empirical: float    # From random-cut estimation
    tw_from_grohe_marx: float   # lambda_2 * n / (2 * log n)
    tw_over_grohe_marx: float   # Measured tw / Grohe-Marx lower bound
    algebraic_connectivity: float
    trial: int


@dataclass
class SpectralScan:
    """Collection of spectral measurements."""
    measurements: list[SpectralMeasurement] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["Spectral-Treewidth Correspondence Scan", "=" * 45]
        if not self.measurements:
            return "\n".join(lines + ["(No data)"])

        # Group by strategy
        by_strategy = {}
        for m in self.measurements:
            by_strategy.setdefault(m.strategy, []).append(m)

        for strat, items in sorted(by_strategy.items()):
            lines.append(f"\nStrategy: {strat}")
            ns = [m.n for m in items]
            ratios = [m.tw_over_grohe_marx for m in items if m.tw_over_grohe_marx > 0]
            if ratios:
                lines.append(
                    f"  tw / (lambda_2*n/2*log n): "
                    f"mean={np.mean(ratios):.2f} +/- {np.std(ratios):.2f} "
                    f"[n={min(ns)}..{max(ns)}]"
                )
            lambdas = [m.lambda_2 for m in items]
            lines.append(f"  lambda_2 range: [{min(lambdas):.4f}, {max(lambdas):.4f}]")

        # Overall correlation
        all_tw = [m.treewidth for m in self.measurements]
        all_gm = [m.tw_from_grohe_marx for m in self.measurements]
        if len(all_tw) > 3 and any(g > 0 for g in all_gm):
            valid = [(t, g) for t, g in zip(all_tw, all_gm) if g > 0]
            tw_vals = [v[0] for v in valid]
            gm_vals = [v[1] for v in valid]
            corr = float(np.corrcoef(tw_vals, gm_vals)[0, 1]) if len(valid) > 1 else 0.0
            lines.append(f"\nOverall tw ~ Grohe-Marx correlation: r = {corr:.3f}")

        return "\n".join(lines)


def compute_spectral_profile(
    G: nx.Graph,
    n_vars: int,
    strategy: str,
    treewidth: int,
    trial: int,
    cheeger_empirical: float = 0.0,
) -> SpectralMeasurement:
    """Compute full spectral profile for a constraint graph.

    Args:
        G: Constraint graph.
        n_vars: Number of certificate variables.
        strategy: Name of restructuring strategy applied (or "natural").
        treewidth: Measured treewidth.
        trial: Trial index.
        cheeger_empirical: Pre-computed empirical Cheeger estimate.

    Returns:
        SpectralMeasurement with full spectral profile.
    """
    n = G.number_of_nodes()

    # Default values for degenerate cases
    lambda_2 = 0.0
    lambda_max = 0.0
    alg_conn = 0.0

    if n >= 3 and G.number_of_edges() > 0:
        try:
            # Normalized Laplacian spectrum
            L = nx.normalized_laplacian_matrix(G).toarray()
            eigenvalues = sorted(np.real(np.linalg.eigvalsh(L)))
            lambda_2 = float(eigenvalues[1]) if len(eigenvalues) > 1 else 0.0
            lambda_max = float(eigenvalues[-1]) if eigenvalues else 0.0

            # Algebraic connectivity (Fiedler value of unnormalized Laplacian)
            if nx.is_connected(G):
                alg_conn = float(nx.algebraic_connectivity(G))
        except Exception:
            pass

    # Cheeger bounds from spectrum
    cheeger_lower = lambda_2 / 2.0
    cheeger_upper = math.sqrt(max(0.0, 2.0 * lambda_2))

    # Grohe-Marx lower bound estimate
    log_n = math.log(max(n, 2))
    grohe_marx_bound = lambda_2 * n / (2.0 * log_n) if log_n > 0 else 0.0

    # Ratio: how much does measured tw exceed the Grohe-Marx lower bound?
    tw_over_gm = (treewidth / grohe_marx_bound
                  if grohe_marx_bound > 0 else 0.0)

    return SpectralMeasurement(
        n=n_vars,
        strategy=strategy,
        treewidth=treewidth,
        lambda_2=lambda_2,
        lambda_max=lambda_max,
        cheeger_lower=cheeger_lower,
        cheeger_upper=cheeger_upper,
        cheeger_empirical=cheeger_empirical,
        tw_from_grohe_marx=grohe_marx_bound,
        tw_over_grohe_marx=tw_over_gm,
        algebraic_connectivity=alg_conn,
        trial=trial,
    )


class SpectralAnalysisExperiment:
    """Tracks spectral gap and treewidth across instances and strategies.

    Implements Problem 9 from v9: establish formal connections between
    spectral properties (spectral gap, expansion) and complexity classes.

    The key question: is lambda_2 >= Omega(1/n) a sufficient condition for
    treewidth >= Omega(sqrt(n))? If yes, spectral lower bounds could replace
    direct expansion arguments, potentially covering more padding strategies.
    """

    def __init__(self, config=None):
        try:
            from vtw.config import VTWConfig
            self.config = config or VTWConfig()
        except ImportError:
            self.config = None

    def run(
        self,
        n_values: list[int],
        trials_per_n: int = 10,
        strategies: Optional[list[str]] = None,
        verbose: bool = True,
    ) -> SpectralScan:
        """Run spectral analysis experiment.

        For each n and strategy, generates instances, measures treewidth,
        computes Laplacian spectrum, and logs the spectral-treewidth ratio.
        """
        try:
            from vtw.instance import VTWInstance
            from vtw.measurement import HybridMeasurement
            from vtw.constraint_graph import (
                constraint_graph_stats,
                _estimate_cheeger_random_cuts,
            )
            from vtw.strategies import get_strategy, get_all_strategies
        except ImportError:
            print("vtw modules not available")
            return SpectralScan()

        measurement = HybridMeasurement(self.config)

        strategy_list = ["natural"]
        if strategies:
            strategy_list += strategies
        else:
            strategy_list += [s.name() for s in get_all_strategies()]

        scan = SpectralScan()

        for n in n_values:
            for trial in range(trials_per_n):
                base = VTWInstance.random_3sat(n, clause_ratio=4.267, seed=trial * 1009 + n)

                for strat_name in strategy_list:
                    if strat_name == "natural":
                        instance = base
                    else:
                        try:
                            strategy = get_strategy(strat_name)
                            instance = strategy.apply(base)
                        except Exception:
                            continue

                    G = instance.to_constraint_graph()
                    meas = measurement.measure(instance)
                    tw = meas.treewidth

                    cheeger_emp = _estimate_cheeger_random_cuts(G, n_samples=50)

                    spec = compute_spectral_profile(
                        G, n_vars=n, strategy=strat_name,
                        treewidth=tw, trial=trial,
                        cheeger_empirical=cheeger_emp,
                    )
                    scan.measurements.append(spec)

                    if verbose:
                        print(
                            f"n={n:3d} {strat_name:20s} trial={trial}: "
                            f"tw={tw:4d} lambda_2={spec.lambda_2:.4f} "
                            f"h in [{spec.cheeger_lower:.3f},{spec.cheeger_upper:.3f}] "
                            f"gm_bound={spec.tw_from_grohe_marx:.1f}"
                        )

        if verbose:
            print()
            print(scan.summary())

        return scan
