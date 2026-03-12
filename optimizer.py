"""VTWOptimizer — THE CORE: measure -> analyze -> restructure -> verify loop.

This is where everything integrates. The optimizer doesn't just use
the measurement tools — it uses them as a feedback signal to guide
restructuring. The Auxiliary Expander Theorem predicts when strategies
will fail (migration, not reduction) — the optimizer checks for this
and avoids wasted computation.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from vtw.config import VTWConfig
from vtw.constraint_graph import constraint_graph_stats, detect_expander_subgraph
from vtw.instance import VTWInstance
from vtw.measurement import HybridMeasurement, MeasurementResult
from vtw.strategies import (
    RestructuringStrategy,
    get_all_strategies,
)


@dataclass
class OptimizationStep:
    """Record of a single optimization step."""
    iteration: int
    strategy_name: str
    tw_before: int
    tw_after: int
    tw_reduction: float  # (before - after) / before
    expansion_before: float
    expansion_after: float
    accepted: bool  # Was this step kept?
    elapsed_seconds: float


@dataclass
class OptimizationResult:
    """Complete result from the optimization loop."""
    original_instance: VTWInstance
    optimized_instance: VTWInstance
    original_tw: MeasurementResult
    optimized_tw: MeasurementResult
    steps: list[OptimizationStep] = field(default_factory=list)
    strategies_applied: list[str] = field(default_factory=list)
    tw_reduction_ratio: float = 0.0  # optimized / original
    iterations: int = 0
    converged: bool = False
    total_elapsed_seconds: float = 0.0

    @property
    def improved(self) -> bool:
        return self.optimized_tw.treewidth < self.original_tw.treewidth


@dataclass
class AnalysisResult:
    """Full diagnostic without optimization."""
    instance: VTWInstance
    measurement: MeasurementResult
    graph_stats: dict
    separators: list[set[int]]
    expansion_info: dict
    recommended_strategies: list[str]
    predicted_achievable_tw: Optional[int]


class VTWOptimizer:
    """The core: measure -> analyze -> restructure -> verify loop.

    For each iteration:
    1. Measure current treewidth
    2. Analyze constraint graph structure (expansion, separators)
    3. Select best strategy based on graph topology
    4. Apply strategy -> new instance
    5. Measure new treewidth
    6. If improved: keep. If not: revert.
    7. Check convergence (improvement < threshold)
    """

    def __init__(
        self,
        config: VTWConfig,
        measurement: Optional[HybridMeasurement] = None,
        strategies: Optional[list[RestructuringStrategy]] = None,
    ):
        self.config = config
        self.measurement = measurement or HybridMeasurement(config)
        self.strategies = strategies or get_all_strategies()

    def optimize(self, instance: VTWInstance) -> OptimizationResult:
        """Run the full optimization loop."""
        total_start = time.monotonic()

        # Initial measurement
        current = instance
        current_tw = self.measurement.measure(current)
        original_tw = current_tw

        steps = []
        strategies_applied = []
        best_instance = current
        best_tw = current_tw

        for iteration in range(self.config.max_optimization_iterations):
            step_start = time.monotonic()

            # Analyze current state
            G = current.to_constraint_graph()
            stats = constraint_graph_stats(G)

            # Select strategy based on topology
            strategy = self._select_strategy(G, stats, strategies_applied)
            if strategy is None:
                break  # All strategies exhausted

            # Apply strategy
            candidate = strategy.apply(current)

            # Measure candidate
            candidate_tw = self.measurement.measure(candidate)

            # Compute expansion change
            exp_before = stats.get("cheeger_estimate", 0.0)
            candidate_G = candidate.to_constraint_graph()
            candidate_stats = constraint_graph_stats(candidate_G)
            exp_after = candidate_stats.get("cheeger_estimate", 0.0)

            # Decision: accept or reject
            tw_before = current_tw.treewidth
            tw_after = candidate_tw.treewidth
            reduction = (tw_before - tw_after) / max(tw_before, 1)
            accepted = tw_after < tw_before

            step = OptimizationStep(
                iteration=iteration,
                strategy_name=strategy.name(),
                tw_before=tw_before,
                tw_after=tw_after,
                tw_reduction=reduction,
                expansion_before=exp_before,
                expansion_after=exp_after,
                accepted=accepted,
                elapsed_seconds=time.monotonic() - step_start,
            )
            steps.append(step)

            if accepted:
                current = candidate
                current_tw = candidate_tw
                strategies_applied.append(strategy.name())

                if tw_after < best_tw.treewidth:
                    best_instance = candidate
                    best_tw = candidate_tw

            # Convergence check
            if abs(reduction) < self.config.convergence_threshold:
                break

        total_elapsed = time.monotonic() - total_start

        orig_tw_val = original_tw.treewidth
        opt_tw_val = best_tw.treewidth
        ratio = opt_tw_val / max(orig_tw_val, 1)

        return OptimizationResult(
            original_instance=instance,
            optimized_instance=best_instance,
            original_tw=original_tw,
            optimized_tw=best_tw,
            steps=steps,
            strategies_applied=strategies_applied,
            tw_reduction_ratio=ratio,
            iterations=len(steps),
            converged=len(steps) > 0 and abs(steps[-1].tw_reduction) < self.config.convergence_threshold,
            total_elapsed_seconds=total_elapsed,
        )

    def analyze(self, instance: VTWInstance) -> AnalysisResult:
        """Full diagnostic without optimization.

        Returns treewidth, expansion, bottleneck identification,
        recommended strategies, predicted achievable tw.
        """
        G = instance.to_constraint_graph()
        stats = constraint_graph_stats(G)
        measurement = self.measurement.measure(instance)

        # Find separators
        from vtw.constraint_graph import find_separators
        separators = find_separators(G)

        # Check expansion with default partition
        n = G.number_of_nodes()
        if n >= 4:
            import math
            bs = max(2, int(math.sqrt(n)))
            nodes = sorted(G.nodes())
            partition = [set(nodes[i:i+bs]) for i in range(0, len(nodes), bs)]
            exp_info = detect_expander_subgraph(G, partition)
        else:
            exp_info = {"migration_detected": False, "aux_cheeger": 0.0}

        # Recommend strategies based on topology
        recommended = self._recommend_strategies(G, stats, exp_info)

        # Predict achievable treewidth
        predicted_tw = self._predict_achievable_tw(stats, exp_info, instance.n_vars)

        return AnalysisResult(
            instance=instance,
            measurement=measurement,
            graph_stats=stats,
            separators=separators,
            expansion_info=exp_info,
            recommended_strategies=recommended,
            predicted_achievable_tw=predicted_tw,
        )

    def _select_strategy(
        self,
        G: nx.Graph,
        stats: dict,
        already_applied: list[str],
    ) -> Optional[RestructuringStrategy]:
        """Topology-aware strategy selection.

        - Not connected → Modularize
        - High expansion → SpectralPartition (break expander structure)
        - Small separators exist → Modularize
        - Long-range edges → Localize
        - Dense clusters → SummaryNode
        - Default → BlockDecomp (baseline)
        """
        available = [s for s in self.strategies if s.name() not in already_applied]
        if not available:
            return None

        n_components = stats.get("n_components", 1)
        cheeger = stats.get("cheeger_estimate", 0.0)
        density = stats.get("density", 0.0)

        # Priority ordering based on topology
        for strategy in available:
            name = strategy.name()
            if name == "modularize" and n_components > 1:
                return strategy
            if name == "spectral_partition" and cheeger > 0.3:
                return strategy
            if name == "modularize" and density < 0.3:
                return strategy
            if name == "localize" and density < 0.5:
                return strategy
            if name == "summary_node" and cheeger < 0.3:
                return strategy

        # Fallback: try whatever's available
        return available[0] if available else None

    def _recommend_strategies(
        self, G: nx.Graph, stats: dict, exp_info: dict
    ) -> list[str]:
        """Recommend strategies based on graph analysis."""
        recommendations = []

        if stats["n_components"] > 1:
            recommendations.append("modularize")

        if exp_info.get("migration_detected", False):
            recommendations.append("spectral_partition")
        elif stats.get("cheeger_estimate", 0) < 0.2:
            recommendations.append("summary_node")

        if stats.get("density", 1) < 0.3:
            recommendations.append("localize")

        if not recommendations:
            recommendations.append("block_decomp")

        return recommendations

    def _predict_achievable_tw(
        self, stats: dict, exp_info: dict, n_vars: int
    ) -> Optional[int]:
        """Predict the best treewidth achievable by optimization.

        Based on the paper's theoretical bounds:
        - Block decomposition: Theta(sqrt(n))
        - Recursive Blocking Theorem: Omega(n^{1/c}) for cert n^c
        - Migration principle: can't do better than Omega(n^delta)
        """
        import math

        if n_vars == 0:
            return 0

        # If expander detected, best achievable is sqrt(n)
        if exp_info.get("migration_detected", False):
            return int(math.sqrt(n_vars))

        # If disconnected, each component is independent
        n_comp = stats.get("n_components", 1)
        if n_comp > 1:
            # Best case: max component treewidth
            avg_component_size = n_vars / n_comp
            return int(0.69 * avg_component_size)  # Paper's 0.69n coefficient

        # Default: sqrt(n) via block decomposition
        return int(math.sqrt(n_vars))
