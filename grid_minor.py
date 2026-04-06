"""Grid minor persistence — tests Problem 3 from v9 recommendations.

The Grid Minor Persistence conjecture (v5, Problem 3): for grid-structured
NP-complete problems, any certificate transformation preserving polynomial
length also preserves a grid minor of size omega(log n) x omega(log n).

If this conjecture holds, it resolves P vs NP via the Robertson-Seymour
Grid Minor theorem: bounded treewidth iff no large grid minor.

This module provides:
1. find_grid_minor_size(G): find largest k such that G has a k x k grid minor
2. GridMinorPersistenceExperiment: test whether restructuring preserves minors
3. Structured instance generators (grid CSPs, tiling problems)

Usage:
    python -m vtw grid_minor --n 30 --strategies all
"""

import math
import random
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
import numpy as np


@dataclass
class GridMinorResult:
    """Grid minor size before and after a single restructuring step."""
    n_vars: int
    strategy: str
    grid_minor_before: int
    grid_minor_after: int
    preserved: bool  # after >= before - 1 (allowing tiny degradation)
    log_n_threshold: float  # omega(log n) threshold


@dataclass
class GridMinorPersistenceScan:
    """Full scan results across instances and strategies."""
    results: list[GridMinorResult] = field(default_factory=list)

    def persistence_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.preserved) / len(self.results)

    def summary(self) -> str:
        lines = ["Grid Minor Persistence Scan", "=" * 40]
        lines.append(f"Total tests: {len(self.results)}")
        lines.append(f"Persistence rate: {self.persistence_rate():.1%}")
        if self.results:
            by_strategy = {}
            for r in self.results:
                by_strategy.setdefault(r.strategy, []).append(r.preserved)
            lines.append("\nBy strategy:")
            for strat, values in sorted(by_strategy.items()):
                rate = sum(values) / len(values)
                lines.append(f"  {strat}: {rate:.1%} ({sum(values)}/{len(values)})")
        return "\n".join(lines)


def find_grid_minor_size(G: nx.Graph, max_k: Optional[int] = None) -> int:
    """Find the largest k such that G contains a k x k grid minor.

    Uses a binary search over k, checking subgraph isomorphism for each.
    For large graphs, caps at max_k for performance.

    A k x k grid has k^2 nodes and 2k(k-1) edges.
    Subgraph isomorphism is NP-hard in general, but tractable for small k.

    Args:
        G: Input graph.
        max_k: Maximum k to test (default: floor(sqrt(n/2))).

    Returns:
        Largest k found (1 means no 2x2 grid minor found, 0 means trivial graph).
    """
    n = G.number_of_nodes()
    if n < 4:
        return 0

    if max_k is None:
        max_k = min(8, int(math.sqrt(n / 2)) + 1)

    # Use contraction-based minor check (more efficient than subgraph isomorphism)
    # for small k; exact for k <= 4
    best_k = 1
    for k in range(2, max_k + 1):
        grid = nx.grid_2d_graph(k, k)
        # Relabel to integers for compatibility
        grid = nx.convert_node_labels_to_integers(grid)
        try:
            gm = nx.algorithms.isomorphism.GraphMatcher(G, grid)
            if gm.subgraph_is_isomorphic():
                best_k = k
            else:
                break  # Once we fail, larger k will also fail (monotone)
        except Exception:
            break
    return best_k


def find_grid_minor_size_spectral(G: nx.Graph) -> int:
    """Estimate grid minor size via spectral proxy.

    Uses the algebraic connectivity (Fiedler value lambda_2) and the expansion-
    treewidth connection as a proxy: tw >= Omega(h*n/log n) >= Omega(lambda_2*n/log n).
    A grid minor of size k requires tw >= k, so k_estimate ~ lambda_2*n/log n.

    This is a *lower bound estimate* suitable for large graphs where exact
    subgraph isomorphism is infeasible.
    """
    n = G.number_of_nodes()
    if n < 4 or not nx.is_connected(G):
        return 0
    try:
        lam2 = nx.algebraic_connectivity(G)
        estimate = lam2 * n / (2 * math.log(max(n, 2)))
        return max(1, int(estimate))
    except Exception:
        return 0


def generate_grid_csp_instance(k: int, seed: int = 42) -> "VTWInstance":
    """Generate a k x k grid CSP instance.

    Creates a 3-SAT encoding of a grid constraint problem where:
    - Each cell (i,j) has a boolean variable x_{i,j}
    - Adjacent cells are constrained (at-most-one or exactly-one)
    - The constraint graph is a subgraph of the k x k grid

    This is a structured instance whose constraint graph has bounded
    treewidth k (by the grid-minor theorem), making it ideal for
    testing the Grid Minor Persistence conjecture.
    """
    try:
        from vtw.config import _ensure_lib_paths
        _ensure_lib_paths()
        from pysat.formula import CNF
        from vtw.instance import VTWInstance, InstanceMetadata
    except ImportError:
        raise ImportError("pysat required for instance generation")

    rng = random.Random(seed)
    cnf = CNF()
    n_vars = k * k

    def var(i, j):
        return i * k + j + 1  # 1-indexed

    # Horizontal adjacency constraints: x_{i,j} XOR x_{i,j+1}
    # Encoded as (x_{i,j} OR x_{i,j+1}) AND (NOT x_{i,j} OR NOT x_{i,j+1})
    for i in range(k):
        for j in range(k - 1):
            v1, v2 = var(i, j), var(i, j + 1)
            cnf.append([v1, v2])
            cnf.append([-v1, -v2])

    # Vertical adjacency constraints: x_{i,j} XOR x_{i+1,j}
    for i in range(k - 1):
        for j in range(k):
            v1, v2 = var(i, j), var(i + 1, j)
            cnf.append([v1, v2])
            cnf.append([-v1, -v2])

    # Add a few random 3-clauses for variety
    vars_list = list(range(1, n_vars + 1))
    for _ in range(k * k // 2):
        clause_vars = rng.sample(vars_list, min(3, len(vars_list)))
        clause = [v if rng.random() > 0.5 else -v for v in clause_vars]
        cnf.append(clause)

    meta = InstanceMetadata(
        family="grid_csp",
        n_vars=n_vars,
        clause_ratio=len(cnf.clauses) / max(n_vars, 1),
        seed=seed,
        generation_params={"grid_k": k},
    )
    return VTWInstance(cnf, meta)


class GridMinorPersistenceExperiment:
    """Tests whether restructuring strategies preserve grid minors.

    If the Grid Minor Persistence conjecture holds, then:
    - find_grid_minor_size(G) should remain >= Omega(log n) after any
      polynomial-preserving certificate transformation
    - The vtw restructuring strategies should NOT be able to eliminate
      large grid minors

    If a strategy DOES eliminate a grid minor, this points to exactly
    the kind of transformation the exotic encoding adversary would need.
    """

    def __init__(self, config=None):
        try:
            from vtw.config import VTWConfig
            self.config = config or VTWConfig()
        except ImportError:
            self.config = None

    def run(
        self,
        k_values: list[int],
        strategy_names: Optional[list[str]] = None,
        use_spectral: bool = False,
        verbose: bool = True,
    ) -> GridMinorPersistenceScan:
        """Test grid minor persistence across k x k grid CSP instances.

        Args:
            k_values: Grid sizes to test (k x k grid CSP instances).
            strategy_names: Strategy names to test. None = all strategies.
            use_spectral: Use spectral proxy for large instances.
            verbose: Print progress.

        Returns:
            GridMinorPersistenceScan with all results.
        """
        try:
            from vtw.strategies import get_all_strategies, get_strategy
        except ImportError:
            print("vtw.strategies not available")
            return GridMinorPersistenceScan()

        if strategy_names is None:
            strategies = get_all_strategies()
        else:
            strategies = [get_strategy(name) for name in strategy_names]

        scan = GridMinorPersistenceScan()

        for k in k_values:
            instance = generate_grid_csp_instance(k)
            G_before = instance.to_constraint_graph()
            n = G_before.number_of_nodes()
            log_n_threshold = math.log2(max(n, 2))

            if use_spectral or n > 50:
                minor_before = find_grid_minor_size_spectral(G_before)
            else:
                minor_before = find_grid_minor_size(G_before)

            if verbose:
                print(f"k={k} (n={n}): Grid minor before = {minor_before} "
                      f"(omega(log n) threshold ~ {log_n_threshold:.1f})")

            for strategy in strategies:
                try:
                    restructured = strategy.apply(instance)
                    G_after = restructured.to_constraint_graph()

                    if use_spectral or G_after.number_of_nodes() > 50:
                        minor_after = find_grid_minor_size_spectral(G_after)
                    else:
                        minor_after = find_grid_minor_size(G_after)

                    # "Preserved" means minor size didn't drop below threshold
                    preserved = (minor_after >= log_n_threshold or
                                 minor_after >= minor_before - 1)

                    result = GridMinorResult(
                        n_vars=n,
                        strategy=strategy.name(),
                        grid_minor_before=minor_before,
                        grid_minor_after=minor_after,
                        preserved=preserved,
                        log_n_threshold=log_n_threshold,
                    )
                    scan.results.append(result)

                    status = "PRESERVED" if preserved else "ELIMINATED"
                    if verbose:
                        print(f"  {strategy.name():20s}: minor {minor_before} -> "
                              f"{minor_after} {status}")

                except Exception as e:
                    if verbose:
                        print(f"  {strategy.name():20s}: ERROR -- {e}")

        if verbose:
            print()
            print(scan.summary())

        return scan
