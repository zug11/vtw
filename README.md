# VTW — Verifier Treewidth Research Toolkit

**The compiler already wrote the code. This tool measures how hard it is to read.**

A Python research toolkit and experimental engine for the [Verifier Treewidth](https://en.wikipedia.org/wiki/Treewidth) (VTW) approach to computational complexity. Companion to the paper *"The Compiler Already Wrote the Code: Verifier Treewidth, the Topology of Hardness, and the Boundaries of Retrocausal Computation"* (Klugman, 2026).

---

## What Is This?

VTW is an **experimental toolkit** for measuring and restructuring the constraint-graph treewidth of polynomial-time verifiers. It implements a complete computational workflow:

```
Instance → Build constraint graph → Measure treewidth → Restructure → Re-measure → Compare
```

You can use it to generate SAT instances, construct their constraint graphs, compute treewidth (exactly or heuristically), apply restructuring strategies, and study how treewidth responds. The toolkit is designed for researchers and practitioners interested in the structural complexity of verification.

## The Idea

P vs NP asks: can every problem whose solutions are quickly *checkable* also be quickly *solved*?

The VTW framework approaches this from a structural angle. A polynomial-time verifier is a compact circuit that perfectly partitions candidate solutions into valid and invalid. The partition *is* the solution — encoded in the verifier's constraint structure. The question becomes: **under what conditions can we read the solution out of the verifier?**

The answer may be topological. Build the **constraint graph** of the verifier circuit — edge (i,j) whenever certificate bits i and j co-occur in some gate's input cone. The **treewidth** of this graph measures how entangled the verification is.

**The central hypothesis of the VTW framework:** P = NP if and only if every NP language has a verifier whose constraint graph has treewidth O(log n). This toolkit was built to experimentally probe this hypothesis — measuring treewidth at scale, testing restructuring strategies, and mapping out where they succeed or fail.

This tool measures that treewidth, analyzes the constraint topology, and attempts to restructure it.

## What This Tool Does

```
Instance → Measure(treewidth) → Analyze(topology) → Restructure → Re-measure → Compare
```

The **optimization loop** is the core. VTW is both diagnostic and design target:

1. **Generate** SAT instances (random, planted, community-structured)
2. **Validate** satisfiability (CaDiCaL, Kissat, pysat)
3. **Measure** constraint-graph treewidth (exact via twalgor/Jdrasil, heuristic via networkx)
4. **Analyze** expansion, migration, separators, topology
5. **Restructure** using strategies (modularize, localize, spectral partition, block decomposition)
6. **Detect migration** — the Auxiliary Expander Theorem predicts when restructuring moves treewidth rather than reducing it

## Empirical Results

The engine reproduces the paper's key empirical measurements. These are experimental observations from the toolkit's output, not formal complexity-theoretic proofs:

| Measurement | Value | Significance |
|---|---|---|
| tw/n ratio (random 3-SAT, α=4.27) | **≈ 0.69** | Linear growth, not logarithmic |
| Power-law exponent | **0.985** | tw ≈ n^0.985 (R² > 0.999) |
| Parity/clause padding | **Zero reduction** | Information-preserving transforms don't help |
| Block decomposition | **tw → Θ(√n)** | Structural padding helps, but not enough |
| Auxiliary Cheeger constant | **h ≈ 0.56** | Auxiliary subgraph is an expander |
| Planted vs random tw | **Ratio ≈ 1.0** | Constraint graph depends on structure, not polarity |
| Community structure tw/n | **≈ 0.17** | Designed systems have dramatically lower VTW |

The last row is the practical punchline: **low treewidth in real systems is an engineering achievement, not a distributional gift.** Modular schemas, separation of concerns, and test-driven development work because they minimize verification treewidth.

## Installation

```bash
git clone https://github.com/zug11/vtw.git
cd vtw
```

### Dependencies

**Python** (3.10+):
```bash
pip install numpy scipy
```

**External solver sources** (place alongside `vtw/` in a parent directory):
- [networkx](https://github.com/networkx/networkx) → `networkx-main/`
- [pysat](https://github.com/pysathq/pysat) → `pysat-master/`
- [twalgor](https://github.com/TCS-Meiji/twalgor) → `tw-master/` (Java, exact treewidth)
- [Jdrasil](https://github.com/maxbannach/Jdrasil) → `Jdrasil-master/` (Java, exact treewidth)
- [CaDiCaL](https://github.com/arminbiere/cadical) → `cadical-master/` (C++, SAT solver)
- [Kissat](https://github.com/arminbiere/kissat) → `kissat-master/` (C, SAT solver)

**Java** (JDK 8+) for exact treewidth solvers.

### Build External Solvers

```bash
export PYTHONPATH=".:networkx-main:pysat-master"
python3 -m vtw build
```

This compiles twalgor (javac), Jdrasil (gradle), CaDiCaL (make), and Kissat (make). Check status:

```bash
python3 -m vtw status
```

## Usage

### Quick Start

```bash
export PYTHONPATH=".:networkx-main:pysat-master"

# Measure a DIMACS CNF file
python3 -m vtw measure --dimacs instance.cnf

# Full diagnostic
python3 -m vtw analyze --dimacs instance.cnf

# Run the optimization loop
python3 -m vtw optimize --dimacs instance.cnf
```

### Batch Experiments

```bash
# Random 3-SAT, n=10 to 50, exact+heuristic measurement
python3 -m vtw run-experiment \
    --n-range 10,50 \
    --samples 10 \
    --family random \
    --solver-suite exact+heuristic \
    --output-dir empirical_data/v2

# With optimization strategies applied
python3 -m vtw run-experiment \
    --n-range 10,30 \
    --strategies block_decomp,spectral_partition,modularize \
    --output-dir empirical_data/optimization_sweep \
    --csv results.csv
```

Instance families: `random`, `planted`, `community`

### Calibrate Error Model

Train the heuristic→exact correction from small instances:

```bash
python3 -m vtw calibrate --n-range 5,30 --samples 20
```

### Cross-Validate Exact Solvers

```bash
python3 -m vtw validate-solvers
```

Runs twalgor vs Jdrasil on n=5..25 and reports agreement.

### Python API

```python
from vtw.instance import VTWInstance
from vtw.optimizer import VTWOptimizer
from vtw.config import VTWConfig

# Generate an instance at the phase transition
inst = VTWInstance.random_3sat(n=30, clause_ratio=4.267, seed=42)

# Full analysis
optimizer = VTWOptimizer(VTWConfig())
analysis = optimizer.analyze(inst)

print(f"tw = {analysis.measurement.treewidth}")
print(f"tw/n = {analysis.measurement.tw_over_n:.3f}")
print(f"migration = {analysis.expansion_info['migration_detected']}")
print(f"recommended = {analysis.recommended_strategies}")

# Compare random vs designed structure
random = VTWInstance.random_3sat(50, seed=1)
community = VTWInstance.community_3sat(50, n_communities=5, inter_ratio=0.05, seed=1)
# community.tw/n ≈ 0.17 vs random.tw/n ≈ 0.70
```

## Architecture

```
VTWOptimizer (the feedback loop)
    ├── Measure
    │   ├── HeuristicMeasurer (networkx: min_degree, min_fill_in)
    │   ├── ExactSolver (twalgor + Jdrasil, unified)
    │   └── SolverOrchestrator (CaDiCaL/Kissat/pysat)
    └── Restructure
        ├── ModularizeStrategy (separator-based decomposition)
        ├── LocalizeStrategy (break long-range constraints)
        ├── BlockDecompStrategy (√n blocks — baseline)
        ├── SummaryNodeStrategy (expansion-aware placement)
        └── SpectralPartitionStrategy (Laplacian eigenvector clustering)
```

**Confidence tiers**: Exact (n ≤ 50, provably correct) → Calibrated heuristic (error model applied) → Raw heuristic (upper bound only).

**Migration detection**: Before applying any strategy, the engine checks the Cheeger constant of the auxiliary subgraph. If expansion is detected (h > 0.1), the strategy would migrate treewidth rather than reduce it — the Auxiliary Expander Theorem in action.

## Modules

| Module | Lines | Role |
|---|---|---|
| `instance.py` | 277 | VTWInstance: pysat CNF wrapper + distribution samplers |
| `constraint_graph.py` | 214 | Graph construction + expansion detection + Cheeger estimation |
| `strategies.py` | 568 | 5 restructuring strategies with migration awareness |
| `optimizer.py` | 313 | Core feedback loop: measure → analyze → restructure → verify |
| `__main__.py` | 312 | Unified CLI with 8 commands |
| `exact.py` | 248 | Unified twalgor + Jdrasil exact solver with cross-validation |
| `experiment.py` | 241 | Batch runner with SQLite storage |
| `measurement.py` | 231 | Hybrid cascade + ErrorModel calibration |
| `build.py` | 223 | Automated compilation of 4 external solvers |
| `sat_solver.py` | 219 | CaDiCaL/Kissat/pysat orchestrator with tiered dispatch |
| `db.py` | 176 | SQLite experiment database |
| `formats.py` | 114 | PACE .gr/.td format bridge (shared by both Java solvers) |
| `heuristic.py` | 92 | networkx treewidth heuristics |
| `config.py` | 128 | Auto-detecting solver configuration |

## The Remaining Gap

The VTW framework, as developed in the companion paper, derives lower bounds on treewidth for various classes of verifiers applied to random 3-SAT. The toolkit's empirical results are consistent with these bounds:

| Verifier Class | VTW Lower Bound | Source |
|---|---|---|
| Natural certificate (m = n) | Ω(log n) | Paper, §3 |
| Monotone verifiers | Ω(n^{1/4} / log n) | Paper, §4 |
| Oblivious verifiers | Ω(n / log n) | Paper, §4 |
| Single-pass verifiers | Θ(n) | Paper, §4 |
| PCP verifiers | Ω(poly(n) / log n) | Paper, §5 |
| Block-padded (cert n^c) | Ω(n^{1/c}) | Paper, §5 |
| Aux-containing padded | Ω(n^δ) | Paper, §5 |
| All verifiers (ETH) | ω(log n) | Conditional on ETH |
| All verifiers (SETH) | Θ(n) | Conditional on SETH |
| General exotic encoding | ??? | **Open — this is P vs NP** |

Every natural restructuring strategy studied by this toolkit moves or fails to reduce treewidth for random instances. The conditional results (assuming ETH/SETH) suggest the exotic adversary does not exist — but ruling it out unconditionally requires resolving P vs NP itself.

The empirical data shows no hint of an exotic low-treewidth encoding. Whether that gap can be closed is the open question the framework is designed to sharpen.

## Acknowledgments

Paper: *"The Compiler Already Wrote the Code"* — Zac Klugman (Zug), March 2026.

External solvers: [twalgor](https://github.com/TCS-Meiji/twalgor) (Tamaki), [Jdrasil](https://github.com/maxbannach/Jdrasil) (Bannach, Berndt, Ehlers), [CaDiCaL](https://github.com/arminbiere/cadical) (Biere), [Kissat](https://github.com/arminbiere/kissat) (Biere), [networkx](https://github.com/networkx/networkx), [pysat](https://github.com/pysathq/pysat).

## License

MIT
