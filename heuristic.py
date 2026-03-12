"""Heuristic treewidth measurement via networkx.

Not a fallback — the first stage of an intelligent measurement cascade.
The exact solver calibrates these results via the ErrorModel, making
heuristic values more valuable, not less relevant.
"""

import time
from dataclasses import dataclass
from typing import Optional

import networkx as nx
from networkx.algorithms.approximation.treewidth import (
    treewidth_min_degree,
    treewidth_min_fill_in,
)


@dataclass
class HeuristicResult:
    """Result from heuristic treewidth measurement."""
    treewidth_upper_bound: int
    heuristic_used: str  # 'min_degree', 'min_fill_in', or 'best_of_both'
    decomposition: Optional[nx.Graph]  # Tree decomposition
    elapsed_seconds: float
    min_degree_tw: Optional[int] = None
    min_fill_in_tw: Optional[int] = None


class HeuristicMeasurer:
    """Fast treewidth upper bounds via networkx heuristics.

    Runs both min_degree (O(V^2)) and min_fill_in (O(V^3)),
    returns the tighter (lower) upper bound.
    """

    def __init__(self, use_both: bool = True, max_n_for_fill_in: int = 500):
        self.use_both = use_both
        self.max_n_for_fill_in = max_n_for_fill_in

    def measure(self, G: nx.Graph) -> HeuristicResult:
        """Compute heuristic treewidth upper bound.

        For small graphs, runs both heuristics and returns the best.
        For large graphs (n > max_n_for_fill_in), uses only min_degree.
        """
        n = G.number_of_nodes()
        if n == 0:
            return HeuristicResult(
                treewidth_upper_bound=0,
                heuristic_used="empty",
                decomposition=None,
                elapsed_seconds=0.0,
            )

        start = time.monotonic()

        # Always run min_degree (fast)
        tw_md, decomp_md = treewidth_min_degree(G)

        tw_mfi = None
        decomp_mfi = None

        if self.use_both and n <= self.max_n_for_fill_in:
            tw_mfi, decomp_mfi = treewidth_min_fill_in(G)

        elapsed = time.monotonic() - start

        # Return the better (lower) upper bound
        if tw_mfi is not None and tw_mfi < tw_md:
            return HeuristicResult(
                treewidth_upper_bound=tw_mfi,
                heuristic_used="min_fill_in",
                decomposition=decomp_mfi,
                elapsed_seconds=elapsed,
                min_degree_tw=tw_md,
                min_fill_in_tw=tw_mfi,
            )
        else:
            return HeuristicResult(
                treewidth_upper_bound=tw_md,
                heuristic_used="min_degree",
                decomposition=decomp_md,
                elapsed_seconds=elapsed,
                min_degree_tw=tw_md,
                min_fill_in_tw=tw_mfi,
            )

    def measure_with_decomposition(self, G: nx.Graph) -> tuple[int, nx.Graph]:
        """Return (treewidth, tree_decomposition) for optimizer analysis."""
        result = self.measure(G)
        return result.treewidth_upper_bound, result.decomposition
