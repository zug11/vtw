"""VTWExperiment — batch experiment runner.

Encapsulates full experimental runs: generation -> validation ->
measurement -> optimization -> storage. Replaces scattered scripts
with a unified, reproducible experiment pipeline.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from vtw.config import VTWConfig
from vtw.constraint_graph import constraint_graph_stats
from vtw.db import ExperimentDB
from vtw.instance import VTWInstance
from vtw.measurement import HybridMeasurement
from vtw.optimizer import VTWOptimizer
from vtw.sat_solver import SolverOrchestrator
from vtw.strategies import get_all_strategies, get_strategy


@dataclass
class ExperimentConfig:
    """Configuration for a batch experiment."""
    n_range: tuple[int, int] = (10, 50)
    n_values: Optional[list[int]] = None  # Override n_range with specific values
    samples_per_n: int = 10
    clause_ratio: float = 4.267
    instance_family: str = "random"  # random, planted, community
    solver_suite: str = "exact+heuristic"  # exact, heuristic, exact+heuristic
    strategies: Optional[list[str]] = None  # None = skip optimization
    output_dir: str = "empirical_data"
    db_name: str = "vtw_experiments.db"

    def to_dict(self) -> dict:
        return {
            "n_range": list(self.n_range),
            "n_values": self.n_values,
            "samples_per_n": self.samples_per_n,
            "clause_ratio": self.clause_ratio,
            "instance_family": self.instance_family,
            "solver_suite": self.solver_suite,
            "strategies": self.strategies,
        }


class VTWExperiment:
    """Unified experiment runner."""

    def __init__(self, exp_config: ExperimentConfig, vtw_config: Optional[VTWConfig] = None):
        self.exp_config = exp_config
        self.vtw_config = vtw_config or VTWConfig()

        # Set up output directory
        out_dir = Path(exp_config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.db = ExperimentDB(str(out_dir / exp_config.db_name))
        self.orchestrator = SolverOrchestrator(self.vtw_config)
        self.measurement = HybridMeasurement(self.vtw_config)
        self.optimizer = (
            VTWOptimizer(self.vtw_config, self.measurement)
            if exp_config.strategies
            else None
        )

    def run(self, verbose: bool = True) -> int:
        """Full experimental pipeline. Returns experiment_id."""
        exp_id, run_id = self.db.create_experiment(self.exp_config.to_dict())

        if verbose:
            print(f"Experiment {run_id} started")
            print(f"  Family: {self.exp_config.instance_family}")
            print(f"  Solver: {self.exp_config.solver_suite}")

        # Determine n values to test
        if self.exp_config.n_values:
            n_values = self.exp_config.n_values
        else:
            n_min, n_max = self.exp_config.n_range
            n_values = list(range(n_min, n_max + 1))

        total_instances = len(n_values) * self.exp_config.samples_per_n
        completed = 0

        for n in n_values:
            for sample_idx in range(self.exp_config.samples_per_n):
                try:
                    self._run_single(exp_id, n, sample_idx, verbose)
                except Exception as e:
                    if verbose:
                        print(f"  [!] n={n} sample={sample_idx} failed: {e}")

                completed += 1
                if verbose and completed % 10 == 0:
                    print(f"  Progress: {completed}/{total_instances}")

        if verbose:
            print(f"Experiment {run_id} complete: {completed} instances")

        return exp_id

    def _run_single(self, exp_id: int, n: int, sample_idx: int, verbose: bool):
        """Run pipeline for a single instance."""
        # Step 1: Generate instance
        instance = self._generate_instance(n, sample_idx)

        # Step 2: Validate (SAT/UNSAT)
        sat_result = self.orchestrator.validate(instance)

        # Step 3: Measure treewidth
        tw_result = self.measurement.measure(instance)

        # Step 4: Graph statistics
        stats = tw_result.graph_stats or {}

        # Step 5: Store baseline result
        self.db.insert_result(
            experiment_id=exp_id,
            n_vars=instance.n_vars,
            n_clauses=instance.n_clauses,
            clause_density=instance.clause_density,
            instance_family=instance.metadata.family,
            sample_idx=sample_idx,
            is_satisfiable=sat_result.satisfiable,
            treewidth=tw_result.treewidth,
            tw_confidence=tw_result.confidence,
            tw_lower_bound=tw_result.lower_bound,
            tw_upper_bound=tw_result.upper_bound,
            tw_over_n=tw_result.tw_over_n,
            cheeger_constant=stats.get("cheeger_estimate", 0.0),
            graph_density=stats.get("density", 0.0),
            avg_degree=stats.get("avg_degree", 0.0),
            solver_time_sat=sat_result.elapsed_seconds,
            solver_time_tw=tw_result.elapsed_seconds,
            dimacs_hash=instance.dimacs_hash,
        )

        # Step 6: Optimization (if configured)
        if self.optimizer and self.exp_config.strategies:
            for strategy_name in self.exp_config.strategies:
                try:
                    strategy = get_strategy(strategy_name)
                    optimized = strategy.apply(instance)
                    opt_tw = self.measurement.measure(optimized)

                    ratio = opt_tw.treewidth / max(tw_result.treewidth, 1)
                    opt_stats = opt_tw.graph_stats or {}

                    self.db.insert_result(
                        experiment_id=exp_id,
                        n_vars=optimized.n_vars,
                        n_clauses=optimized.n_clauses,
                        clause_density=optimized.clause_density,
                        instance_family=instance.metadata.family,
                        sample_idx=sample_idx,
                        is_satisfiable=sat_result.satisfiable,
                        treewidth=opt_tw.treewidth,
                        tw_confidence=opt_tw.confidence,
                        tw_lower_bound=opt_tw.lower_bound,
                        tw_upper_bound=opt_tw.upper_bound,
                        tw_over_n=opt_tw.tw_over_n,
                        cheeger_constant=opt_stats.get("cheeger_estimate", 0.0),
                        graph_density=opt_stats.get("density", 0.0),
                        avg_degree=opt_stats.get("avg_degree", 0.0),
                        solver_time_sat=0.0,
                        solver_time_tw=opt_tw.elapsed_seconds,
                        dimacs_hash=optimized.dimacs_hash,
                        strategy_applied=strategy_name,
                        tw_reduction_ratio=ratio,
                    )
                except Exception as e:
                    if verbose:
                        print(f"    Strategy {strategy_name} failed: {e}")

        if verbose and n <= 30:
            sat_str = "SAT" if sat_result.satisfiable else "UNSAT" if sat_result.satisfiable is not None else "?"
            print(
                f"  n={n:3d} s={sample_idx} tw={tw_result.treewidth:3d} "
                f"tw/n={tw_result.tw_over_n:.3f} [{tw_result.confidence}] {sat_str}"
            )

    def _generate_instance(self, n: int, sample_idx: int) -> VTWInstance:
        """Generate instance based on experiment config."""
        seed = n * 10000 + sample_idx
        family = self.exp_config.instance_family

        if family == "random":
            return VTWInstance.random_3sat(n, self.exp_config.clause_ratio, seed)
        elif family == "planted":
            return VTWInstance.planted_3sat(n, self.exp_config.clause_ratio, seed)
        elif family == "community":
            return VTWInstance.community_3sat(
                n, n_communities=max(2, n // 10),
                inter_ratio=0.1, clause_ratio=self.exp_config.clause_ratio, seed=seed,
            )
        else:
            return VTWInstance.random_3sat(n, self.exp_config.clause_ratio, seed)

    def analyze(self) -> dict:
        """Analyze experiment results."""
        tw_by_n = self.db.query_tw_by_n()

        if not tw_by_n:
            return {"error": "No data"}

        n_values = [r["n_vars"] for r in tw_by_n]
        tw_values = [r["avg_tw"] for r in tw_by_n]
        ratios = [r["avg_ratio"] for r in tw_by_n]

        # Power-law fit: tw = a * n^b
        if len(n_values) >= 3:
            log_n = np.log(n_values)
            log_tw = np.log([max(t, 0.1) for t in tw_values])
            coeffs = np.polyfit(log_n, log_tw, 1)
            exponent = coeffs[0]
            coefficient = np.exp(coeffs[1])
        else:
            exponent = 0.0
            coefficient = 0.0

        return {
            "n_values": n_values,
            "avg_treewidth": tw_values,
            "avg_tw_over_n": ratios,
            "power_law_exponent": float(exponent),
            "power_law_coefficient": float(coefficient),
            "mean_tw_over_n": float(np.mean(ratios)) if ratios else 0.0,
            "optimization_results": self.db.query_optimization_results(),
        }

    def export_csv(self, path: str, experiment_id: Optional[int] = None):
        """Export results to CSV."""
        self.db.export_csv(path, experiment_id)

    def close(self):
        self.db.close()
