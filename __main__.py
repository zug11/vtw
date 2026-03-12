"""VTW Optimization Engine — CLI entry point.

Usage:
    python -m vtw build                          # Compile all external solvers
    python -m vtw status                         # Show solver availability
    python -m vtw measure --dimacs f.cnf         # Measure single instance
    python -m vtw analyze --dimacs f.cnf         # Full diagnostic
    python -m vtw optimize --dimacs f.cnf        # Measure + optimize + report
    python -m vtw run-experiment --n-range 10,50 # Batch experiment
    python -m vtw calibrate --n-range 5,30       # Build error model
    python -m vtw validate-solvers               # Cross-validate exact solvers
"""

import argparse
import json
import sys
import time

from vtw.config import VTWConfig


def cmd_build(args):
    """Compile all external solvers."""
    from vtw.build import build_all
    build_all(force=args.force)


def cmd_status(args):
    """Show solver availability."""
    config = VTWConfig()
    print("VTW Optimization Engine — Solver Status")
    print("=" * 45)
    config.print_status()
    print()
    if config.has_exact_solver:
        print("Exact treewidth: AVAILABLE")
    else:
        print("Exact treewidth: UNAVAILABLE (run `python -m vtw build`)")
    if config.has_external_sat_solver:
        print("External SAT: AVAILABLE")
    else:
        print("External SAT: using pysat fallback")


def cmd_measure(args):
    """Measure treewidth of a single instance."""
    from vtw.instance import VTWInstance
    from vtw.measurement import HybridMeasurement

    config = VTWConfig()
    instance = VTWInstance.from_dimacs(args.dimacs)
    measurement = HybridMeasurement(config)
    result = measurement.measure(instance)

    print(f"Instance: {args.dimacs}")
    print(f"  Variables:  {instance.n_vars}")
    print(f"  Clauses:    {instance.n_clauses}")
    print(f"  Density:    {instance.clause_density:.3f}")
    print(f"  Treewidth:  {result.treewidth}")
    print(f"  tw/n:       {result.tw_over_n:.4f}")
    print(f"  Confidence: {result.confidence}")
    if result.lower_bound is not None:
        print(f"  Bounds:     [{result.lower_bound}, {result.upper_bound}]")
    print(f"  Time:       {result.elapsed_seconds:.3f}s")

    if result.graph_stats:
        stats = result.graph_stats
        print(f"  Graph density:   {stats.get('density', 0):.4f}")
        print(f"  Avg degree:      {stats.get('avg_degree', 0):.2f}")
        print(f"  Cheeger est:     {stats.get('cheeger_estimate', 0):.4f}")


def cmd_analyze(args):
    """Full diagnostic without optimization."""
    from vtw.instance import VTWInstance
    from vtw.optimizer import VTWOptimizer

    config = VTWConfig()
    instance = VTWInstance.from_dimacs(args.dimacs)
    optimizer = VTWOptimizer(config)
    result = optimizer.analyze(instance)

    print(f"VTW Analysis: {args.dimacs}")
    print("=" * 50)
    print(f"  Variables:         {instance.n_vars}")
    print(f"  Clauses:           {instance.n_clauses}")
    print(f"  Treewidth:         {result.measurement.treewidth}")
    print(f"  tw/n:              {result.measurement.tw_over_n:.4f}")
    print(f"  Confidence:        {result.measurement.confidence}")
    print()
    print(f"  Graph density:     {result.graph_stats.get('density', 0):.4f}")
    print(f"  Avg degree:        {result.graph_stats.get('avg_degree', 0):.2f}")
    print(f"  Components:        {result.graph_stats.get('n_components', 0)}")
    print(f"  Cheeger estimate:  {result.graph_stats.get('cheeger_estimate', 0):.4f}")
    print()
    print(f"  Migration detected: {result.expansion_info.get('migration_detected', False)}")
    print(f"  Aux Cheeger:        {result.expansion_info.get('aux_cheeger', 0):.4f}")
    print()
    print(f"  Separators found:   {len(result.separators)}")
    if result.separators:
        for i, sep in enumerate(result.separators[:3]):
            print(f"    Sep {i}: size {len(sep)}")
    print()
    print(f"  Recommended strategies: {', '.join(result.recommended_strategies)}")
    if result.predicted_achievable_tw is not None:
        print(f"  Predicted achievable tw: {result.predicted_achievable_tw}")


def cmd_optimize(args):
    """Measure + optimize + report."""
    from vtw.instance import VTWInstance
    from vtw.optimizer import VTWOptimizer

    config = VTWConfig()
    instance = VTWInstance.from_dimacs(args.dimacs)
    optimizer = VTWOptimizer(config)

    print(f"Optimizing: {args.dimacs}")
    print(f"  n={instance.n_vars}, m={instance.n_clauses}")

    result = optimizer.optimize(instance)

    print()
    print(f"  Original tw:    {result.original_tw.treewidth}")
    print(f"  Optimized tw:   {result.optimized_tw.treewidth}")
    print(f"  Reduction:      {1 - result.tw_reduction_ratio:.1%}")
    print(f"  Strategies:     {', '.join(result.strategies_applied) or 'none'}")
    print(f"  Iterations:     {result.iterations}")
    print(f"  Converged:      {result.converged}")
    print(f"  Time:           {result.total_elapsed_seconds:.3f}s")

    if result.steps:
        print()
        print("  Steps:")
        for step in result.steps:
            mark = "+" if step.accepted else "-"
            print(
                f"    [{mark}] {step.strategy_name}: "
                f"tw {step.tw_before} -> {step.tw_after} "
                f"({step.tw_reduction:+.1%})"
            )


def cmd_run_experiment(args):
    """Run batch experiment."""
    from vtw.experiment import ExperimentConfig, VTWExperiment

    n_min, n_max = map(int, args.n_range.split(","))

    exp_config = ExperimentConfig(
        n_range=(n_min, n_max),
        samples_per_n=args.samples,
        clause_ratio=args.clause_ratio,
        instance_family=args.family,
        solver_suite=args.solver_suite,
        strategies=args.strategies.split(",") if args.strategies else None,
        output_dir=args.output_dir,
    )

    experiment = VTWExperiment(exp_config)
    try:
        exp_id = experiment.run(verbose=True)

        print()
        analysis = experiment.analyze()
        print(f"Power-law exponent: {analysis.get('power_law_exponent', 0):.4f}")
        print(f"Mean tw/n:          {analysis.get('mean_tw_over_n', 0):.4f}")

        if args.csv:
            experiment.export_csv(args.csv, exp_id)
            print(f"Results exported to {args.csv}")
    finally:
        experiment.close()


def cmd_calibrate(args):
    """Build error model from exact/heuristic pairs."""
    from vtw.measurement import HybridMeasurement

    config = VTWConfig()
    if not config.has_exact_solver:
        print("Error: Exact solver required. Run `python -m vtw build` first.")
        sys.exit(1)

    measurement = HybridMeasurement(config)
    n_min, n_max = map(int, args.n_range.split(","))

    print(f"Calibrating error model (n={n_min}..{n_max}, {args.samples} samples/n)...")
    model = measurement.calibrate(
        n_range=(n_min, n_max),
        samples_per_n=args.samples,
    )

    output = args.output or "error_model.json"
    model.save(output)
    print(f"Error model saved to {output}")
    print(f"  Samples:     {len(model.calibration_data)}")
    print(f"  Mean ratio:  {model.mean_ratio:.4f} (heuristic / exact)")
    print(f"  Std ratio:   {model.std_ratio:.4f}")


def cmd_validate_solvers(args):
    """Cross-validate twalgor vs Jdrasil on small instances."""
    from vtw.exact import ExactSolver
    from vtw.instance import VTWInstance

    config = VTWConfig()
    if not config.has_exact_solver:
        print("Error: Exact solver required. Run `python -m vtw build` first.")
        sys.exit(1)

    solver = ExactSolver(config)
    n_range = range(5, 26)
    agreements = 0
    total = 0

    print("Cross-validating twalgor vs Jdrasil...")
    for n in n_range:
        instance = VTWInstance.random_3sat(n, seed=n * 42)
        G = instance.to_constraint_graph()
        result = solver.cross_validate(G, timeout=30)

        if result.twalgor_tw is not None and result.jdrasil_tw is not None:
            total += 1
            match = "=" if result.agree else "!"
            agreements += int(result.agree)
            print(
                f"  n={n:3d}: twalgor={result.twalgor_tw:3d} ({result.twalgor_time:.2f}s) "
                f" jdrasil={result.jdrasil_tw:3d} ({result.jdrasil_time:.2f}s) [{match}]"
            )
        else:
            tw_a = result.twalgor_tw if result.twalgor_tw is not None else "timeout"
            tw_b = result.jdrasil_tw if result.jdrasil_tw is not None else "timeout"
            print(f"  n={n:3d}: twalgor={tw_a}  jdrasil={tw_b}")

    if total > 0:
        print(f"\nAgreement: {agreements}/{total} ({agreements/total:.0%})")


def main():
    parser = argparse.ArgumentParser(
        prog="vtw",
        description="VTW Optimization Engine — Measure, Analyze, Restructure, Verify",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # build
    build_p = subparsers.add_parser("build", help="Compile external solvers")
    build_p.add_argument("--force", action="store_true", help="Force recompilation")

    # status
    subparsers.add_parser("status", help="Show solver availability")

    # measure
    measure_p = subparsers.add_parser("measure", help="Measure treewidth of instance")
    measure_p.add_argument("--dimacs", required=True, help="DIMACS CNF file")

    # analyze
    analyze_p = subparsers.add_parser("analyze", help="Full diagnostic")
    analyze_p.add_argument("--dimacs", required=True, help="DIMACS CNF file")

    # optimize
    optimize_p = subparsers.add_parser("optimize", help="Optimize instance")
    optimize_p.add_argument("--dimacs", required=True, help="DIMACS CNF file")

    # run-experiment
    exp_p = subparsers.add_parser("run-experiment", help="Batch experiment")
    exp_p.add_argument("--n-range", required=True, help="Min,max n (e.g., 10,50)")
    exp_p.add_argument("--samples", type=int, default=10, help="Samples per n")
    exp_p.add_argument("--clause-ratio", type=float, default=4.267)
    exp_p.add_argument("--family", choices=["random", "planted", "community"], default="random")
    exp_p.add_argument("--solver-suite", choices=["exact", "heuristic", "exact+heuristic"], default="exact+heuristic")
    exp_p.add_argument("--strategies", type=str, default=None, help="Comma-separated strategies")
    exp_p.add_argument("--output-dir", default="empirical_data", help="Output directory")
    exp_p.add_argument("--csv", default=None, help="Export CSV path")

    # calibrate
    cal_p = subparsers.add_parser("calibrate", help="Build error model")
    cal_p.add_argument("--n-range", default="5,30")
    cal_p.add_argument("--samples", type=int, default=10)
    cal_p.add_argument("--output", default=None, help="Output path for model")

    # validate-solvers
    subparsers.add_parser("validate-solvers", help="Cross-validate exact solvers")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "build": cmd_build,
        "status": cmd_status,
        "measure": cmd_measure,
        "analyze": cmd_analyze,
        "optimize": cmd_optimize,
        "run-experiment": cmd_run_experiment,
        "calibrate": cmd_calibrate,
        "validate-solvers": cmd_validate_solvers,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
