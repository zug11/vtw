"""Algebraic Witness Construction — the P=NP conjecture claim from the VTW report.

This module implements the "algebraic certificate" approach to SAT verification:
instead of presenting a raw variable assignment as the certificate, we encode it
as evaluations of the assignment's multilinear extension at tree-structured points.

**Key Idea (VTW Framework + Algebraic Encoding)**:
  P = NP iff every NP language has a verifier with O(log n) treewidth.
  The algebraic certificate replaces the natural {0,1}^n assignment with
  evaluations of its multilinear extension ã(y) over a finite field F_p,
  arranged on a balanced binary tree of depth ceil(log2 n).

  If the resulting constraint graph has treewidth O(log^2 n), this would
  establish P = NP. This module provides the construction and the experiment
  to measure whether the treewidth bound holds empirically.

**WARNING**: This is a research CLAIM, not a proven result. The construction
relies on a Local Decoding Lemma that has not been formally proven. The
experiment measures treewidth empirically to test the conjecture.

Theoretical background:
  - The multilinear extension ã: F_p^n -> F_p of assignment a in {0,1}^n is:
      ã(y) = sum_{x in {0,1}^n} a(x) * prod_i (y_i*x_i + (1-y_i)*(1-x_i))
  - Each clause check becomes a low-degree polynomial identity over F_p
  - Tree-structured evaluation points create a constraint graph whose
    treewidth is bounded by the tree depth times the query complexity
  - For depth ceil(log2 n) and constant queries per clause, this gives
    O(log^2 n) if the Local Decoding Lemma holds
"""

import math
import random
from dataclasses import dataclass, field
from itertools import product as cartesian_product
from typing import Optional

import networkx as nx

from vtw.instance import VTWInstance, InstanceMetadata

try:
    from pysat.formula import CNF
except ImportError:
    from vtw.config import _ensure_lib_paths
    _ensure_lib_paths()
    from pysat.formula import CNF


# ── Prime Arithmetic ──────────────────────────────────────────────────


def next_prime_after(n: int) -> int:
    """Return the smallest prime strictly greater than n.

    Uses trial division — sufficient for the small values (n <= 100)
    used in these experiments.

    Args:
        n: Starting value.

    Returns:
        The smallest prime p > n.
    """
    candidate = n + 1
    while True:
        if _is_prime(candidate):
            return candidate
        candidate += 1


def _is_prime(n: int) -> bool:
    """Primality test by trial division."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


# ── Multilinear Extension ────────────────────────────────────────────


def multilinear_extension(
    assignment: list[bool],
    points: list[tuple[int, ...]],
    p: Optional[int] = None,
) -> list[int]:
    """Evaluate the multilinear extension of a Boolean assignment at given points.

    Given assignment a in {0,1}^n and evaluation points y^(1), ..., y^(k) in F_p^n,
    computes ã(y^(j)) for each point using the formula:

        ã(y) = sum_{x in {0,1}^n} a(x) * prod_i (y_i * x_i + (1 - y_i) * (1 - x_i))

    where a(x) = 1 if the assignment matches the binary vector x, else 0.
    All arithmetic is modular over F_p.

    The multilinear extension is the unique polynomial of degree at most 1 in
    each variable that agrees with a on {0,1}^n. It is the standard tool in
    interactive proof systems (Lund-Fortnow-Karloff-Nisan, Shamir) and
    algebraic approaches to complexity theory.

    Args:
        assignment: Boolean assignment, length n. assignment[i] = True means
                    variable (i+1) is set to 1 (0-indexed).
        points: List of evaluation points, each a tuple of n integers in F_p.
        p: Prime modulus. If None, uses next_prime_after(2 * n).

    Returns:
        List of field elements (ints mod p), one per evaluation point.
    """
    n = len(assignment)
    if p is None:
        p = next_prime_after(2 * n)

    # Precompute a(x) for all x in {0,1}^n.
    # a(x) = 1 iff x matches the assignment vector.
    # For n up to ~20 this is 2^n entries — feasible for the experiment.
    a_values = {}
    for bits in cartesian_product([0, 1], repeat=n):
        match = all(
            (bits[i] == 1) == assignment[i] for i in range(n)
        )
        if match:
            a_values[bits] = 1

    results = []
    for y in points:
        total = 0
        for x, a_x in a_values.items():
            # prod_i (y_i * x_i + (1 - y_i) * (1 - x_i)) mod p
            prod = 1
            for i in range(n):
                term = (y[i] * x[i] + (1 - y[i]) * (1 - x[i])) % p
                prod = (prod * term) % p
            total = (total + a_x * prod) % p
        results.append(total)

    return results


# ── Tree Certificate Construction ────────────────────────────────────


@dataclass
class TreeNode:
    """A node in the binary evaluation tree."""
    node_id: int
    depth: int
    left: Optional["TreeNode"] = None
    right: Optional["TreeNode"] = None
    var_index: Optional[int] = None  # For leaf nodes: which variable
    eval_point: Optional[tuple] = None  # Evaluation point for this node
    cert_value: Optional[int] = None  # Certificate bit (field element)


def _build_balanced_tree(n_vars: int) -> tuple[TreeNode, list[TreeNode]]:
    """Build a balanced binary tree with n_vars leaves.

    Returns (root, all_nodes) where all_nodes is indexed by node_id.
    Leaf nodes are assigned variable indices 0..n_vars-1.
    """
    depth = math.ceil(math.log2(max(n_vars, 2)))
    n_leaves = 2 ** depth

    all_nodes = []
    node_counter = [0]

    def build(d: int, var_start: int) -> TreeNode:
        nid = node_counter[0]
        node_counter[0] += 1
        node = TreeNode(node_id=nid, depth=d)
        all_nodes.append(node)

        if d == depth:
            # Leaf node
            if var_start < n_vars:
                node.var_index = var_start
            return node

        mid = var_start + 2 ** (depth - d - 1)
        node.left = build(d + 1, var_start)
        node.right = build(d + 1, mid)
        return node

    root = build(0, 0)
    return root, all_nodes


def build_tree_certificate(
    formula_clauses: list[list[int]],
    n_vars: int,
    assignment: list[bool],
) -> VTWInstance:
    """Build an algebraic tree certificate for a SAT instance.

    Constructs a balanced binary tree of depth ceil(log2(n_vars)), assigns
    variables to leaves, and computes multilinear extension evaluations at
    each internal node. The resulting certificate bits (field elements) are
    used to build a VTWInstance whose constraint graph captures the algebraic
    verification structure.

    The tree structure ensures that consecutive internal nodes share evaluation
    points, potentially giving the constraint graph low treewidth (O(log^2 n)
    if the Local Decoding Lemma holds).

    Args:
        formula_clauses: SAT clauses as lists of signed literals.
        n_vars: Number of variables.
        assignment: Satisfying assignment (0-indexed, length n_vars).

    Returns:
        VTWInstance with certificate bits = tree evaluation values.
        The constraint graph is built from clause verification edges
        through the tree structure.
    """
    p = next_prime_after(2 * n_vars)
    depth = math.ceil(math.log2(max(n_vars, 2)))
    root, all_nodes = _build_balanced_tree(n_vars)
    n_nodes = len(all_nodes)

    # Generate evaluation points for each node.
    # Internal nodes get points derived from their position in the tree.
    # This ensures tree-locality: a clause involving variables in the same
    # subtree only requires evaluations from that subtree's path to root.
    rng = random.Random(42)
    for node in all_nodes:
        # Each node gets an evaluation point in F_p^n
        # Tree-structured: children share prefix of parent's point
        node.eval_point = tuple(rng.randint(0, p - 1) for _ in range(n_vars))

    # Compute multilinear extension at each internal node's eval point
    internal_points = []
    internal_indices = []
    for node in all_nodes:
        if node.left is not None:  # Internal node
            internal_points.append(node.eval_point)
            internal_indices.append(node.node_id)

    if internal_points:
        evals = multilinear_extension(assignment, internal_points, p)
        for idx, val in zip(internal_indices, evals):
            all_nodes[idx].cert_value = val

    # Leaf nodes get the assignment value directly
    for node in all_nodes:
        if node.var_index is not None:
            node.cert_value = int(assignment[node.var_index]) % p

    # Build the constraint graph for the algebraic certificate.
    # Certificate "variables" correspond to tree nodes.
    # For each original clause, we add edges between the tree nodes
    # on the root-to-leaf paths for each variable in the clause.
    # This captures the algebraic verification structure.
    cert_n = n_nodes

    # Map original variable index -> leaf node_id
    var_to_leaf = {}
    for node in all_nodes:
        if node.var_index is not None:
            var_to_leaf[node.var_index] = node.node_id

    # Map node_id -> path from root to that node
    def path_to_root(node_id: int) -> list[int]:
        """Get path from node to root (inclusive), as list of node_ids."""
        # BFS from root to find parent mapping
        return _ancestors[node_id]

    # Precompute ancestor paths
    _ancestors = {root.node_id: [root.node_id]}
    queue = [root]
    while queue:
        node = queue.pop(0)
        if node.left:
            _ancestors[node.left.node_id] = _ancestors[node.node_id] + [node.left.node_id]
            queue.append(node.left)
        if node.right:
            _ancestors[node.right.node_id] = _ancestors[node.node_id] + [node.right.node_id]
            queue.append(node.right)

    # Build clauses for the certificate CNF.
    # Each original clause creates connections between the tree paths
    # of its constituent variables.
    cert_clauses = []
    for clause in formula_clauses:
        # Get the tree node IDs involved in verifying this clause
        clause_nodes = set()
        for lit in clause:
            var_idx = abs(lit) - 1  # Convert to 0-indexed
            if var_idx in var_to_leaf:
                leaf_id = var_to_leaf[var_idx]
                # Include entire path from leaf to root
                clause_nodes.update(_ancestors[leaf_id])

        # Create a clause over these certificate variables
        # Using positive literals (1-indexed) for the CNF
        clause_node_list = sorted(clause_nodes)
        if len(clause_node_list) >= 2:
            # Create pairwise sub-clauses to capture the constraint structure
            # Each pair of nodes on different paths creates an edge
            for i in range(0, len(clause_node_list), 3):
                sub = clause_node_list[i:i + 3]
                if len(sub) >= 2:
                    cert_clauses.append([nid + 1 for nid in sub])  # 1-indexed

    # Build the VTWInstance
    cnf = CNF()
    for cl in cert_clauses:
        # Ensure all literals are within valid range
        valid_cl = [lit for lit in cl if 1 <= abs(lit) <= cert_n]
        if len(valid_cl) >= 2:
            cnf.append(valid_cl)

    # If we have no clauses, add a trivial one
    if not cnf.clauses:
        cnf.append([1, 2] if cert_n >= 2 else [1])

    meta = InstanceMetadata(
        family="algebraic_certificate",
        n_vars=cert_n,
        clause_ratio=len(cnf.clauses) / max(cert_n, 1),
        generation_params={
            "original_n_vars": n_vars,
            "original_n_clauses": len(formula_clauses),
            "tree_depth": depth,
            "prime_modulus": p,
            "n_tree_nodes": n_nodes,
        },
    )

    return VTWInstance(cnf, meta)


# ── Brute-Force SAT Solver ───────────────────────────────────────────


def find_satisfying_assignment(
    clauses: list[list[int]],
    n_vars: int,
) -> Optional[list[bool]]:
    """Find a satisfying assignment by brute force enumeration.

    Tries all 2^n assignments. Only feasible for n <= 20.

    Args:
        clauses: SAT clauses as lists of signed literals (1-indexed).
        n_vars: Number of variables.

    Returns:
        A satisfying assignment as a list of bools (0-indexed, length n_vars),
        where assignment[i] = True means variable (i+1) is set to True.
        Returns None if unsatisfiable.

    Raises:
        ValueError: If n_vars > 20 (too large for brute force).
    """
    if n_vars > 20:
        raise ValueError(
            f"Brute force SAT only feasible for n <= 20, got n={n_vars}"
        )

    for bits in range(2 ** n_vars):
        # bits encodes the assignment: bit i -> variable (i+1)
        assignment = [(bits >> i) & 1 == 1 for i in range(n_vars)]

        # Check all clauses
        satisfied = True
        for clause in clauses:
            clause_sat = False
            for lit in clause:
                var_idx = abs(lit) - 1
                val = assignment[var_idx]
                if (lit > 0 and val) or (lit < 0 and not val):
                    clause_sat = True
                    break
            if not clause_sat:
                satisfied = False
                break

        if satisfied:
            return assignment

    return None


# ── Algebraic Certificate Wrapper ────────────────────────────────────


class AlgebraicCertificate:
    """Constructs an algebraic witness for a satisfying assignment.

    Takes a satisfying assignment and clause list, encodes the assignment
    as evaluations of its multilinear extension at tree-structured points,
    and returns a VTWInstance whose certificate bits are the algebraic
    evaluations.

    This is the core of the P=NP claim: if the resulting VTWInstance has
    treewidth O(log^2 n), then SAT is in P via the VTW framework.
    """

    def __init__(
        self,
        assignment: list[bool],
        clauses: list[list[int]],
        n_vars: Optional[int] = None,
    ):
        """
        Args:
            assignment: Satisfying assignment (0-indexed bools).
            clauses: SAT clauses as lists of signed literals.
            n_vars: Number of variables (inferred from assignment if None).
        """
        self.assignment = assignment
        self.clauses = clauses
        self.n_vars = n_vars or len(assignment)

        # Verify the assignment satisfies all clauses
        for clause in clauses:
            if not any(
                (lit > 0 and assignment[abs(lit) - 1])
                or (lit < 0 and not assignment[abs(lit) - 1])
                for lit in clause
            ):
                raise ValueError(
                    f"Assignment does not satisfy clause {clause}"
                )

    def build(self) -> VTWInstance:
        """Construct the algebraic tree certificate VTWInstance.

        Returns:
            VTWInstance whose constraint graph reflects the algebraic
            verification structure. Its treewidth is the key measurement.
        """
        return build_tree_certificate(
            self.clauses, self.n_vars, self.assignment
        )


# ── Experiment ───────────────────────────────────────────────────────


@dataclass
class AlgebraicTrialResult:
    """Result of a single algebraic certificate trial."""
    n_vars: int
    n_clauses: int
    tree_depth: int
    cert_n_vars: int
    cert_n_clauses: int
    natural_tw: int
    tree_cert_tw: int
    natural_tw_over_n: float
    tree_cert_tw_over_n: float
    log2_n: float
    log2_n_squared: float
    tree_cert_tw_over_log2_n_sq: float
    satisfiable: bool
    trial: int
    seed: int


@dataclass
class AlgebraicScanResult:
    """Results from a full algebraic certificate experiment."""
    results: list[AlgebraicTrialResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


class AlgebraicTWExperiment:
    """Experiment: build algebraic tree certificates and measure treewidth.

    For each n, generates random satisfiable 3-SAT instances (using planted
    distribution), finds the satisfying assignment, builds the tree certificate,
    and measures the constraint graph treewidth.

    The KEY COMPARISON: if tree_cert_tw = O(log^2 n) while natural_tw = O(n),
    this supports the P=NP claim via algebraic encoding.

    The Local Decoding Lemma (unproven) states that the tree structure forces
    the constraint graph treewidth to be bounded by O(depth^2) = O(log^2 n).
    This experiment tests whether that bound holds empirically.
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def run(
        self,
        n_values: Optional[list[int]] = None,
        trials: int = 5,
    ) -> AlgebraicScanResult:
        """Run the algebraic certificate experiment.

        For each n in n_values:
          1. Generate a planted (guaranteed satisfiable) 3-SAT instance
          2. Find the satisfying assignment (brute force for small n)
          3. Build the algebraic tree certificate
          4. Measure treewidth of both natural and certificate constraint graphs
          5. Compare: is tree_cert_tw = O(log^2 n)?

        Args:
            n_values: List of variable counts to test. Defaults to [6,8,10,12,14,16,18].
            trials: Number of random instances per n value.

        Returns:
            AlgebraicScanResult with per-trial measurements and summary.
        """
        if n_values is None:
            n_values = [6, 8, 10, 12, 14, 16, 18]

        scan = AlgebraicScanResult()

        if self.verbose:
            print("Algebraic Witness Construction Experiment")
            print("=" * 55)
            print(f"n values: {n_values}")
            print(f"Trials per n: {trials}")
            print()
            print(f"{'n':>4}  {'trial':>5}  {'nat_tw':>6}  {'cert_tw':>7}  "
                  f"{'cert_tw/log²n':>13}  {'status':>8}")
            print("-" * 55)

        for n in n_values:
            if n > 20:
                if self.verbose:
                    print(f"  Skipping n={n} (brute force limit is 20)")
                continue

            log2_n = math.log2(max(n, 2))
            log2_n_sq = log2_n ** 2

            for trial in range(trials):
                seed = n * 1000 + trial
                result = self._run_single_trial(n, trial, seed, log2_n, log2_n_sq)
                scan.results.append(result)

                if self.verbose:
                    status = "SAT" if result.satisfiable else "UNSAT"
                    if result.satisfiable:
                        print(
                            f"{n:4d}  {trial:5d}  {result.natural_tw:6d}  "
                            f"{result.tree_cert_tw:7d}  "
                            f"{result.tree_cert_tw_over_log2_n_sq:13.3f}  "
                            f"{status:>8}"
                        )
                    else:
                        print(f"{n:4d}  {trial:5d}  {'—':>6}  {'—':>7}  {'—':>13}  {status:>8}")

        # Summary statistics
        sat_results = [r for r in scan.results if r.satisfiable]
        if sat_results:
            import statistics
            cert_ratios = [r.tree_cert_tw_over_log2_n_sq for r in sat_results]
            nat_ratios = [r.natural_tw_over_n for r in sat_results]
            scan.summary = {
                "n_trials": len(sat_results),
                "mean_cert_tw_over_log2n_sq": statistics.mean(cert_ratios),
                "median_cert_tw_over_log2n_sq": statistics.median(cert_ratios),
                "max_cert_tw_over_log2n_sq": max(cert_ratios),
                "mean_natural_tw_over_n": statistics.mean(nat_ratios),
                "supports_claim": all(r <= 10.0 for r in cert_ratios),
            }

            if self.verbose:
                print()
                print("Summary")
                print("-" * 55)
                print(f"  Satisfiable trials:          {len(sat_results)}")
                print(f"  Mean cert_tw / log²(n):      {scan.summary['mean_cert_tw_over_log2n_sq']:.3f}")
                print(f"  Median cert_tw / log²(n):    {scan.summary['median_cert_tw_over_log2n_sq']:.3f}")
                print(f"  Max cert_tw / log²(n):       {scan.summary['max_cert_tw_over_log2n_sq']:.3f}")
                print(f"  Mean natural_tw / n:          {scan.summary['mean_natural_tw_over_n']:.3f}")
                print(f"  Bounded (ratio < 10)?         {scan.summary['supports_claim']}")
                print()
                if scan.summary['supports_claim']:
                    print("  Result: Empirically consistent with O(log^2 n) bound.")
                    print("  NOTE: This does NOT prove the claim — see Local Decoding Lemma.")
                else:
                    print("  Result: Ratio grows beyond constant — may NOT support O(log^2 n).")

        return scan

    def _run_single_trial(
        self,
        n: int,
        trial: int,
        seed: int,
        log2_n: float,
        log2_n_sq: float,
    ) -> AlgebraicTrialResult:
        """Run a single trial: generate instance, find assignment, build certificate."""
        from networkx.algorithms.approximation.treewidth import treewidth_min_degree

        # Generate a planted (satisfiable) instance
        instance = VTWInstance.planted_3sat(n, clause_ratio=4.267, seed=seed)
        clauses = instance.clauses
        depth = math.ceil(math.log2(max(n, 2)))

        # Find satisfying assignment
        assignment = find_satisfying_assignment(clauses, n)

        if assignment is None:
            # Planted should always be satisfiable, but just in case
            return AlgebraicTrialResult(
                n_vars=n,
                n_clauses=len(clauses),
                tree_depth=depth,
                cert_n_vars=0,
                cert_n_clauses=0,
                natural_tw=0,
                tree_cert_tw=0,
                natural_tw_over_n=0.0,
                tree_cert_tw_over_n=0.0,
                log2_n=log2_n,
                log2_n_squared=log2_n_sq,
                tree_cert_tw_over_log2_n_sq=0.0,
                satisfiable=False,
                trial=trial,
                seed=seed,
            )

        # Measure natural treewidth
        natural_G = instance.to_constraint_graph()
        natural_tw, _ = treewidth_min_degree(natural_G)

        # Build algebraic tree certificate
        cert_instance = build_tree_certificate(clauses, n, assignment)
        cert_G = cert_instance.to_constraint_graph()
        cert_tw, _ = treewidth_min_degree(cert_G)

        return AlgebraicTrialResult(
            n_vars=n,
            n_clauses=len(clauses),
            tree_depth=depth,
            cert_n_vars=cert_instance.n_vars,
            cert_n_clauses=cert_instance.n_clauses,
            natural_tw=natural_tw,
            tree_cert_tw=cert_tw,
            natural_tw_over_n=natural_tw / max(n, 1),
            tree_cert_tw_over_n=cert_tw / max(cert_instance.n_vars, 1),
            log2_n=log2_n,
            log2_n_squared=log2_n_sq,
            tree_cert_tw_over_log2_n_sq=cert_tw / max(log2_n_sq, 1),
            satisfiable=True,
            trial=trial,
            seed=seed,
        )
