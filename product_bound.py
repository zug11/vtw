"""Product bound tracker — empirically tests k·m exponent.

Addresses Problem 1 from v9: "Strengthen the Product Bound."
Current bound: k·m >= Omega(n log n). Target: Omega(n^{1+epsilon}).

The information-complexity product bound (Theorem 3.12, v6) states:
  k * m >= Omega(n log n)
for any poly-time verifier for 3-SAT with treewidth k and certificate length m.

This module empirically tests whether the exponent is actually higher (Omega(n^2))
by generating instances with certificates padded to length m = n^alpha,
measuring treewidth k at each certificate length, and fitting log(k*m) vs log(n).

Usage:
    python -m vtw product_bound --n-max 100 --trials 5
"""

import math
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from vtw.config import VTWConfig
from vtw.instance import VTWInstance, InstanceMetadata
from vtw.measurement import HybridMeasurement, MeasurementResult
from vtw.constraint_graph import cnf_to_constraint_graph

try:
    from vtw.config import _ensure_lib_paths
    _ensure_lib_paths()
    from pysat.formula import CNF
except ImportError:
    CNF = None


@dataclass
class ProductBoundResult:
    """Single (n, m, k, k_times_m) data point."""
    n: int
    m: int
    cert_exponent: float
    treewidth: int
    product: int
    product_over_n_log_n: float
    confidence: str
    trial: int


@dataclass
class ProductBoundScan:
    """Results of a full product bound scan."""
    results: list[ProductBoundResult] = field(default_factory=list)
    fitted_exponent: Optional[float] = None
    fitted_coefficient: Optional[float] = None
    r_squared: Optional[float] = None

    def fit(self):
        """Fit log(k*m) = beta*log(n) + log(C) to extract empirical exponent."""
        if len(self.results) < 4:
            return
        ns = np.array([r.n for r in self.results], dtype=float)
        products = np.array([r.product for r in self.results], dtype=float)
        # Filter out zeros
        mask = (ns > 0) & (products > 0)
        if mask.sum() < 4:
            return
        log_n = np.log(ns[mask])
        log_p = np.log(products[mask])
        # Linear regression in log-log space
        coeffs = np.polyfit(log_n, log_p, 1)
        self.fitted_exponent = float(coeffs[0])
        self.fitted_coefficient = float(np.exp(coeffs[1]))
        # R-squared
        predicted = np.polyval(coeffs, log_n)
        ss_res = np.sum((log_p - predicted) ** 2)
        ss_tot = np.sum((log_p - np.mean(log_p)) ** 2)
        self.r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    def to_csv_rows(self) -> list[dict]:
        return [
            {
                "n": r.n, "m": r.m, "cert_exponent": r.cert_exponent,
                "treewidth_k": r.treewidth, "product_km": r.product,
                "product_over_nlogn": round(r.product_over_n_log_n, 4),
                "confidence": r.confidence, "trial": r.trial,
            }
            for r in self.results
        ]

    def summary(self) -> str:
        lines = ["Product Bound Scan Summary", "=" * 40]
        if self.fitted_exponent is not None:
            lines.append(f"Fitted exponent beta: {self.fitted_exponent:.4f}")
            lines.append(f"  -> k*m ~ {self.fitted_coefficient:.2f} * n^{self.fitted_exponent:.3f}")
            lines.append(f"  R^2 = {self.r_squared:.4f}")
            lines.append("")
            if self.fitted_exponent > 1.05:
                lines.append("RESULT: Empirical exponent > 1 -> supports Omega(n^{1+epsilon}) conjecture")
            elif self.fitted_exponent > 0.95:
                lines.append("RESULT: Empirical exponent ~ 1 -> consistent with Omega(n log n) bound")
            else:
                lines.append("RESULT: Empirical exponent < 1 -> anomalous, check measurement")
        else:
            lines.append("(Not enough data to fit)")
        if self.results:
            lines.append(f"\nTotal data points: {len(self.results)}")
        return "\n".join(lines)


def _pad_certificate_to_length(instance: "VTWInstance", target_m: int) -> "VTWInstance":
    """Extend certificate length to target_m by adding auxiliary parity bits.

    For each new auxiliary bit position i (n < i <= target_m),
    add clause [+i] (forcing the bit to true, adding it to the certificate
    without changing the constraint structure). This gives a verifier with
    certificate length target_m while preserving the original constraint graph
    topology.

    Note: This is a certificate-length extension, not a semantics-changing
    transformation. The constraint graph for bits 1..n is unchanged.
    The auxiliary bits (n+1..target_m) form an independent clique of size 1
    (no edges to existing bits), so treewidth is unaffected unless we add
    cross-connections. We deliberately add cross-connections to simulate
    verifiers that "use" the auxiliary bits for crossing clause checks.
    """
    if CNF is None:
        return instance

    current_m = instance.n_vars
    if target_m <= current_m:
        return instance

    new_cnf = CNF()
    for clause in instance.clauses:
        new_cnf.append(clause)

    # Add auxiliary bits that each "check" a random pair of original variables.
    # This simulates a verifier that uses auxiliary bits to mediate
    # crossing-clause verification — the scenario the Migration Principle analyzes.
    import random
    rng = random.Random(42)
    orig_vars = list(range(1, current_m + 1))

    for aux_idx in range(current_m + 1, target_m + 1):
        if len(orig_vars) >= 2:
            v1, v2 = rng.sample(orig_vars, 2)
            # aux_idx <=> (v1 AND v2): a standard Tseitin encoding
            # This creates edges (aux_idx, v1) and (aux_idx, v2)
            new_cnf.append([-aux_idx, v1])
            new_cnf.append([-aux_idx, v2])
            new_cnf.append([aux_idx, -v1, -v2])
        else:
            new_cnf.append([aux_idx])

    meta = InstanceMetadata(
        family=instance.metadata.family,
        n_vars=target_m,
        clause_ratio=len(new_cnf.clauses) / max(target_m, 1),
        parent_hash=instance.dimacs_hash,
        strategy_applied="pad_certificate",
        generation_params={"original_n": current_m, "target_m": target_m},
    )
    return VTWInstance(new_cnf, meta)


class ProductBoundExperiment:
    """Runs the product-bound tracking experiment.

    For each n in n_range, generates random 3-SAT instances,
    pads certificates to multiple lengths, measures treewidth,
    and computes the k*m product.
    """

    def __init__(self, config: Optional[VTWConfig] = None):
        self.config = config or VTWConfig()
        self.measurement = HybridMeasurement(self.config)

    def run(
        self,
        n_values: list[int],
        cert_exponents: tuple[float, ...] = (1.0, 1.5, 2.0),
        trials_per_n: int = 5,
        verbose: bool = True,
    ) -> ProductBoundScan:
        """Run the product bound scan.

        Args:
            n_values: Instance sizes to test.
            cert_exponents: Certificate length exponents alpha (m = n^alpha).
            trials_per_n: Number of random instances per n.
            verbose: Print progress.

        Returns:
            ProductBoundScan with fitted exponent and all data points.
        """
        scan = ProductBoundScan()

        for n in n_values:
            for trial in range(trials_per_n):
                # Generate base random 3-SAT instance
                base = VTWInstance.random_3sat(n, clause_ratio=4.267, seed=trial * 1000 + n)

                for alpha in cert_exponents:
                    target_m = max(n, int(n ** alpha))
                    padded = _pad_certificate_to_length(base, target_m)

                    meas = self.measurement.measure(padded)
                    k = meas.treewidth
                    m = padded.n_vars
                    product = k * m
                    n_log_n = n * math.log(max(n, 2))
                    ratio = product / n_log_n if n_log_n > 0 else 0.0

                    result = ProductBoundResult(
                        n=n, m=m, cert_exponent=alpha,
                        treewidth=k, product=product,
                        product_over_n_log_n=ratio,
                        confidence=meas.confidence,
                        trial=trial,
                    )
                    scan.results.append(result)

                    if verbose:
                        print(
                            f"  n={n:3d} alpha={alpha:.1f} m={m:5d} "
                            f"k={k:4d} k*m={product:7d} "
                            f"k*m/n*log(n)={ratio:.2f}"
                        )

        scan.fit()
        if verbose:
            print()
            print(scan.summary())

        return scan

    def save_csv(self, scan: ProductBoundScan, path: str):
        """Save results to CSV."""
        import csv
        rows = scan.to_csv_rows()
        if not rows:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved {len(rows)} rows to {path}")
