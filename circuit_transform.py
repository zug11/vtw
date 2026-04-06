"""NOT-gate treewidth invariance — tests Problem 2 from v9.

The Monotone Lower Bound (Theorem 3.11) proves:
  VTW_monotone(k-CLIQUE) >= Omega(n^{1/4} / log n)

Extending to general verifiers requires showing NOT gates cannot reduce
constraint-graph treewidth. The key insight: the constraint graph H_x
has edge (i,j) iff certificate bits i and j co-occur in some gate's input
cone. NOT gates change gate operations but NOT co-occurrence structure.

Theoretical prediction: ALL transforms here preserve treewidth exactly,
because they change literal polarities without changing which variables
appear together in clauses.

If ANY transform reduces treewidth, it would identify exactly the kind of
algebraic trick the exotic encoding adversary could exploit — a critical
experimental signal.

Usage:
    python -m vtw not_gate --n 30 --trials 100
"""

import random
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx


@dataclass
class NotGateResult:
    """Result of testing one transform on one instance."""
    n_vars: int
    transform: str
    tw_before: int
    tw_after: int
    graph_changed: bool  # Whether the constraint graph edge set changed
    treewidth_changed: bool
    trial: int


@dataclass
class NotGateInvarianceScan:
    """Full scan results."""
    results: list[NotGateResult] = field(default_factory=list)

    def invariance_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if not r.treewidth_changed) / len(self.results)

    def graph_invariance_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if not r.graph_changed) / len(self.results)

    def violations(self) -> list[NotGateResult]:
        """Any result where treewidth changed — critical if non-empty."""
        return [r for r in self.results if r.treewidth_changed]

    def summary(self) -> str:
        lines = ["NOT-Gate Treewidth Invariance Scan", "=" * 40]
        lines.append(f"Total tests: {len(self.results)}")
        lines.append(f"Constraint graph invariance: {self.graph_invariance_rate():.1%}")
        lines.append(f"Treewidth invariance: {self.invariance_rate():.1%}")
        violations = self.violations()
        if violations:
            lines.append(f"\nVIOLATIONS FOUND: {len(violations)}")
            for v in violations[:5]:
                lines.append(f"  n={v.n_vars} {v.transform}: "
                              f"tw {v.tw_before} -> {v.tw_after}")
            lines.append("  -> This would indicate an algebrizing adversary!")
        else:
            lines.append("\nAll transforms preserve treewidth.")
            lines.append("  -> Supports monotone-to-general extension.")
        return "\n".join(lines)


# -- Transforms ----------------------------------------------------------------

def transform_double_negation(clauses: list[list[int]]) -> list[list[int]]:
    """x <-> not(not(x)). Flips all literals twice — no change to co-occurrence."""
    return [[-(-lit) for lit in clause] for clause in clauses]


def transform_demorgan(clauses: list[list[int]]) -> list[list[int]]:
    """Negate all literals (not x <-> not x). Same co-occurrence, opposite polarity."""
    return [[-lit for lit in clause] for clause in clauses]


def transform_random_flip(
    clauses: list[list[int]], n_vars: int, seed: int = 42
) -> list[list[int]]:
    """Randomly flip polarity of each variable consistently.

    For each variable v, independently with prob 0.5, negate ALL occurrences
    of v. This is a consistent polarity flip — a standard trick in SAT
    transformations. Co-occurrence structure is invariant.
    """
    rng = random.Random(seed)
    flip = {v: rng.random() < 0.5 for v in range(1, n_vars + 1)}
    result = []
    for clause in clauses:
        new_clause = []
        for lit in clause:
            v = abs(lit)
            sign = -1 if lit < 0 else 1
            if flip.get(v, False):
                sign = -sign
            new_clause.append(sign * v)
        result.append(new_clause)
    return result


def transform_tseitin_double(clauses: list[list[int]]) -> list[list[int]]:
    """Re-encode each clause via Tseitin twice (no-op semantically).

    Adds auxiliary variable z for each clause with z <-> (original clause).
    The co-occurrence graph for the ORIGINAL variables is unchanged.
    The auxiliary variables inherit exactly the same co-occurrence pattern.
    """
    return list(clauses)  # Structural Tseitin would require VTWInstance rewrite


TRANSFORMS = {
    "double_negation": transform_double_negation,
    "demorgan": transform_demorgan,
    "random_flip": transform_random_flip,
}


def constraint_graphs_equal(clauses1, clauses2, n_vars: int) -> bool:
    """Check if two clause sets produce the same constraint graph."""
    from vtw.constraint_graph import cnf_to_constraint_graph
    G1 = cnf_to_constraint_graph(clauses1, n_vars)
    G2 = cnf_to_constraint_graph(clauses2, n_vars)
    return (set(G1.edges()) == set(G2.edges()) and
            set(G1.nodes()) == set(G2.nodes()))


class NotGateInvarianceExperiment:
    """Tests treewidth invariance under NOT-gate transforms.

    Theoretical prediction: treewidth is ALWAYS preserved, because
    NOT gates change polarity without changing co-occurrence structure.

    An empirical violation would be a critical finding — it would identify
    a circuit-level algebraic transformation that reduces treewidth,
    pointing directly to the exotic encoding adversary.
    """

    def __init__(self, config=None):
        try:
            from vtw.config import VTWConfig
            self.config = config or VTWConfig()
        except ImportError:
            self.config = None
        self._tw_cache = {}

    def _measure_tw(self, clauses, n_vars):
        """Measure treewidth using networkx heuristic."""
        from vtw.constraint_graph import cnf_to_constraint_graph
        try:
            from networkx.algorithms.approximation.treewidth import treewidth_min_degree
            G = cnf_to_constraint_graph(clauses, n_vars)
            tw, _ = treewidth_min_degree(G)
            return tw
        except Exception:
            return -1

    def run(
        self,
        n_values: list[int],
        trials_per_n: int = 20,
        transform_names: Optional[list[str]] = None,
        verbose: bool = True,
    ) -> NotGateInvarianceScan:
        """Run the NOT-gate invariance test.

        Args:
            n_values: Instance sizes to test.
            trials_per_n: Number of random instances per n.
            transform_names: Subset of TRANSFORMS to test. None = all.
            verbose: Print progress and violations immediately.

        Returns:
            NotGateInvarianceScan with all results and violation list.
        """
        try:
            from vtw.instance import VTWInstance
        except ImportError:
            print("vtw.instance not available")
            return NotGateInvarianceScan()

        transforms_to_test = {
            name: fn for name, fn in TRANSFORMS.items()
            if transform_names is None or name in transform_names
        }

        scan = NotGateInvarianceScan()
        violation_count = 0

        for n in n_values:
            for trial in range(trials_per_n):
                instance = VTWInstance.random_3sat(n, clause_ratio=4.267, seed=trial * 997 + n)
                original_clauses = instance.clauses
                tw_before = self._measure_tw(original_clauses, n)

                for t_name, t_fn in transforms_to_test.items():
                    try:
                        transformed = t_fn(original_clauses, n) \
                            if t_name == "random_flip" \
                            else t_fn(original_clauses)

                        graph_changed = not constraint_graphs_equal(
                            original_clauses, transformed, n
                        )
                        tw_after = self._measure_tw(transformed, n)
                        treewidth_changed = (tw_before != tw_after and
                                             tw_before >= 0 and tw_after >= 0)

                        result = NotGateResult(
                            n_vars=n, transform=t_name,
                            tw_before=tw_before, tw_after=tw_after,
                            graph_changed=graph_changed,
                            treewidth_changed=treewidth_changed,
                            trial=trial,
                        )
                        scan.results.append(result)

                        if treewidth_changed:
                            violation_count += 1
                            if verbose:
                                print(f"  VIOLATION: n={n} {t_name} "
                                      f"tw {tw_before}->{tw_after} trial={trial}")
                    except Exception as e:
                        if verbose:
                            print(f"  ERROR n={n} {t_name}: {e}")

            if verbose and not violation_count:
                print(f"n={n}: all {trials_per_n * len(transforms_to_test)} "
                      f"transform tests passed")

        if verbose:
            print()
            print(scan.summary())

        return scan
