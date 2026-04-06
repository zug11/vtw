# VTW — Verifier Treewidth Optimization Engine

**The compiler already wrote the code. This tool measures how hard it is to read.**

A computational framework for the [Verifier Treewidth](https://en.wikipedia.org/wiki/Treewidth) approach to P vs NP. Based on the paper *"The Compiler Already Wrote the Code: Verifier Treewidth, the Topology of Hardness, and the Boundaries of Retrocausal Computation"* (Klugman, 2026).

---

## The Idea

P vs NP asks: can every problem whose solutions are quickly *checkable* also be quickly *solved*?

The VTW framework flips this around. A polynomial-time verifier is a compact circuit that perfectly partitions candidate solutions into valid and invalid. The partition *is* the solution — encoded in the verifier's constraint structure. The question becomes: **under what conditions can we read the solution out of the verifier?**

The answer is topological. Build the **constraint graph** of the verifier circuit — edge (i,j) whenever certificate bits i and j co-occur in some gate's input cone. The **treewidth** of this graph measures how entangled the verification is.

**Theorem (VTW Equivalence).** *P = NP if and only if every NP language has a verifier whose constraint graph has treewidth O(log n).*

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

The engine reproduces the paper's key empirical findings:

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

## Gap-Attack Experiments

The VTW engine includes experimental infrastructure for attacking the 4 highest-priority open problems from the v9 paper. These experiments probe the boundaries of the VTW framework — each targets a specific theoretical gap where a counterexample or tighter bound would advance the P vs NP question.

### Problem 1: Product Bound (`product_bound`)

**Theorem 3.12 (v6):** k * m >= Omega(n log n) for any verifier with treewidth k and certificate length m.

**Goal:** Empirically test whether the exponent is actually higher — Omega(n^{1+epsilon}) — by padding certificates to length m = n^alpha and measuring the resulting treewidth.

```bash
python3 -m vtw product_bound --n-values 10,20,30,50 --trials 5
```

Outputs a fitted exponent beta from log-log regression of k*m vs n. If beta > 1.05, the data supports a stronger-than-logarithmic product bound.

### Problem 2: NOT-Gate Invariance (`not_gate`)

**Theorem 3.11 (v6):** VTW_monotone(k-CLIQUE) >= Omega(n^{1/4} / log n).

**Goal:** Test whether NOT gates can reduce constraint-graph treewidth. The constraint graph depends on variable co-occurrence, not polarity — so treewidth should be invariant under polarity transforms (double negation, De Morgan, random flip).

```bash
python3 -m vtw not_gate --n-values 10,20,30 --trials 50
```

Any violation (treewidth change after a polarity transform) would identify an algebrizing adversary — a critical finding for the monotone-to-general extension.

### Problem 3: Grid Minor Persistence (`grid_minor`)

**Conjecture (v5, Problem 3):** Any certificate transformation preserving polynomial length also preserves grid minors of size omega(log n) x omega(log n).

**Goal:** Test whether the 5 restructuring strategies can eliminate large grid minors from grid-structured CSP instances. If the conjecture holds, bounded treewidth implies no large grid minor (Robertson-Seymour), resolving P vs NP.

```bash
python3 -m vtw grid_minor --k-values 4,5,6,7 --strategies all
```

Reports per-strategy persistence rates. A strategy that eliminates a grid minor would point to the exotic encoding adversary.

### Problem 9: Spectral-Treewidth Correspondence (`spectral`)

**Auxiliary Expander Theorem (v9):** h >= Omega(1) implies tw >= Omega(n^{1/2}/log n) via the Grohe-Marx bound tw(G) >= Omega(h * n / log n).

**Goal:** Track the spectral gap lambda_2 and its correlation with measured treewidth across instances and restructuring strategies. Tests whether lambda_2 >= Omega(1/n) is a sufficient condition for tw >= Omega(sqrt(n)).

```bash
python3 -m vtw spectral --n-values 10,20,30,50,80 --trials 10
```

Reports lambda_2 ranges, Cheeger bounds, Grohe-Marx lower bounds, and the tw ~ Grohe-Marx correlation coefficient.

### Open Problems Reference

| # | Problem | Module | Status |
|---|---|---|---|
| 1 | Strengthen product bound k*m >= Omega(n^{1+epsilon}) | `product_bound` | Empirical |
| 2 | NOT-gate treewidth invariance | `circuit_transform` | Empirical |
| 3 | Grid minor persistence conjecture | `grid_minor` | Empirical |
| 9 | Spectral-treewidth correspondence | `spectral_analysis` | Empirical |

All experiment results are saved as CSV to `empirical_data/`.

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
| `algebraic_certificate.py` | ~370 | Algebraic witness construction (P=NP claim experiment) |

## The Remaining Gap

The VTW framework establishes that for random 3-SAT, every concrete verification strategy produces constraint graphs with superlogarithmic treewidth:

| Verifier Class | VTW Lower Bound | Status |
|---|---|---|
| Natural certificate (m = n) | Ω(log n) | Proven |
| Monotone verifiers | Ω(n^{1/4} / log n) | Proven |
| Oblivious verifiers | Ω(n / log n) | Proven |
| Single-pass verifiers | Θ(n) | Proven |
| PCP verifiers | Ω(poly(n) / log n) | Proven |
| Block-padded (cert n^c) | Ω(n^{1/c}) | Proven |
| Aux-containing padded | Ω(n^δ) | Proven |
| All verifiers (ETH) | ω(log n) | Conditional |
| All verifiers (SETH) | Θ(n) | Conditional |
| General exotic encoding | ??? | **Open — this is P vs NP** |

The one remaining adversary: a non-monotone, adaptive verifier whose certificate does not contain the variable assignment in any recognizable form, using an exotic encoding that reconstructs satisfaction through a fundamentally different computational pathway. Every natural strategy fails. Every padding strategy fails. The conditional results say it does not exist. The empirical data shows no hint of it.

But we cannot rule it out without solving circuit complexity.

## The P=NP Claim: Algebraic Witness Construction

**Status: Research CLAIM — not a proven result.**

The `algebraic_certificate` module implements the most aggressive attack on the VTW gap: instead of presenting a raw variable assignment as the verification certificate, it encodes the assignment algebraically using multilinear extensions evaluated over a tree-structured point set.

### The Construction

1. **Multilinear Extension**: Given a satisfying assignment `a ∈ {0,1}^n`, compute its unique multilinear extension `ã: F_p^n → F_p`:

   ```
   ã(y) = Σ_{x ∈ {0,1}^n} a(x) · Π_i (y_i·x_i + (1-y_i)·(1-x_i))
   ```

2. **Tree-Structured Evaluation**: Build a balanced binary tree of depth `⌈log₂ n⌉`. Assign variables to leaves. Each internal node stores `ã(y)` evaluated at a tree-determined point. The certificate consists of these `O(n)` field evaluations.

3. **Constraint Graph**: Each clause check becomes a low-degree polynomial identity. The tree structure means clause verifications only touch nodes along root-to-leaf paths, creating a constraint graph whose treewidth is bounded by `O(depth × query_complexity)`.

4. **The Claim**: If the resulting constraint graph has treewidth `O(log² n)`, then SAT ∈ P via the VTW equivalence theorem, establishing P = NP.

### What Would Need to Hold

The claim depends on the **Local Decoding Lemma** (unproven):

> *For any 3-SAT clause involving variables assigned to leaves `l₁, l₂, l₃` in the tree, the algebraic verification of that clause through the multilinear extension requires only evaluations on the paths from each `lᵢ` to the root, plus O(1) auxiliary evaluations per tree level.*

If this lemma holds, the constraint graph has treewidth `O(log² n)` because:
- Each clause touches `O(log n)` tree nodes (3 root-to-leaf paths)
- The tree structure ensures bounded bag sizes in the tree decomposition
- The total treewidth is `O(depth × max_path_overlap) = O(log n × log n)`

### Running the Experiment

```bash
# Default: n=6,8,...,18 with 5 trials each
python -m vtw algebraic --n-max 18 --trials 5

# Larger experiment
python -m vtw algebraic --n-max 20 --trials 10 --output-dir empirical_data
```

The experiment generates planted (satisfiable) 3-SAT instances, finds assignments by brute force (n ≤ 20), builds tree certificates, and compares `tree_cert_tw / log²(n)` against `natural_tw / n`. If the ratio `cert_tw / log²(n)` stays bounded as n grows, it supports the claim.

### Python API

```python
from vtw.algebraic_certificate import (
    AlgebraicCertificate,
    AlgebraicTWExperiment,
    multilinear_extension,
    find_satisfying_assignment,
    next_prime_after,
)

# Build a certificate for a known assignment
assignment = [True, False, True, True, False]
clauses = [[1, -2, 3], [-1, 4, -5], [2, 3, 5]]
cert = AlgebraicCertificate(assignment, clauses)
vtw_instance = cert.build()
print(f"Certificate treewidth structure: {vtw_instance}")

# Run the full experiment
experiment = AlgebraicTWExperiment()
results = experiment.run(n_values=[8, 10, 12, 14], trials=5)
```

### Interpretation

- If `cert_tw / log²(n) → constant` as n grows: empirically consistent with O(log² n), supports P=NP
- If `cert_tw / log²(n) → ∞`: the algebraic encoding does not achieve the bound, does NOT disprove P=NP (other encodings may work)
- The brute-force n ≤ 20 limit means this experiment cannot test asymptotic behavior — it only checks small-n consistency

## Acknowledgments

Paper: *"The Compiler Already Wrote the Code"* — Zac Klugman (Zug), March 2026.

External solvers: [twalgor](https://github.com/TCS-Meiji/twalgor) (Tamaki), [Jdrasil](https://github.com/maxbannach/Jdrasil) (Bannach, Berndt, Ehlers), [CaDiCaL](https://github.com/arminbiere/cadical) (Biere), [Kissat](https://github.com/arminbiere/kissat) (Biere), [networkx](https://github.com/networkx/networkx), [pysat](https://github.com/pysathq/pysat).

## License

MIT
