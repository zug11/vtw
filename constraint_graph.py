"""Constraint graph construction and topological analysis.

The constraint graph is the central object in the VTW framework:
edge (i,j) exists iff variables i and j co-occur in any clause.
Its treewidth IS the verifier treewidth.

This module also provides expansion detection — critical for the
optimizer to distinguish genuine treewidth reduction from migration.
"""

from itertools import combinations

import networkx as nx
import numpy as np


def cnf_to_constraint_graph(clauses: list[list[int]], n_vars: int) -> nx.Graph:
    """Build variable co-occurrence graph from CNF clauses.

    Edge (i,j) iff variables i and j appear in the same clause.
    Nodes are variable indices 1..n_vars.

    Args:
        clauses: List of clauses, each a list of signed literals.
        n_vars: Number of variables (largest variable index).

    Returns:
        Undirected networkx graph with integer node labels.
    """
    G = nx.Graph()
    G.add_nodes_from(range(1, n_vars + 1))
    for clause in clauses:
        variables = sorted(set(abs(lit) for lit in clause))
        for i, j in combinations(variables, 2):
            G.add_edge(i, j)
    return G


def constraint_graph_stats(G: nx.Graph) -> dict:
    """Compute topological statistics of a constraint graph.

    Returns dict with:
        n_nodes, n_edges, density, avg_degree, max_degree,
        n_components, algebraic_connectivity (Fiedler value),
        cheeger_estimate (spectral lower bound).
    """
    n = G.number_of_nodes()
    m = G.number_of_edges()

    if n == 0:
        return {
            "n_nodes": 0, "n_edges": 0, "density": 0.0,
            "avg_degree": 0.0, "max_degree": 0, "n_components": 0,
            "algebraic_connectivity": 0.0, "cheeger_estimate": 0.0,
        }

    degrees = [d for _, d in G.degree()]
    stats = {
        "n_nodes": n,
        "n_edges": m,
        "density": nx.density(G),
        "avg_degree": sum(degrees) / n,
        "max_degree": max(degrees),
        "n_components": nx.number_connected_components(G),
    }

    # Algebraic connectivity (Fiedler value) — spectral gap
    # Only meaningful for connected graphs
    if nx.is_connected(G) and n > 2:
        try:
            stats["algebraic_connectivity"] = nx.algebraic_connectivity(G)
            # Cheeger inequality: h(G) >= lambda_2 / 2
            stats["cheeger_estimate"] = stats["algebraic_connectivity"] / 2.0
        except Exception:
            stats["algebraic_connectivity"] = 0.0
            stats["cheeger_estimate"] = 0.0
    else:
        stats["algebraic_connectivity"] = 0.0
        stats["cheeger_estimate"] = 0.0

    return stats


def detect_expander_subgraph(
    G: nx.Graph, partition: list[set[int]]
) -> dict:
    """Measure auxiliary subgraph expansion for a block partition.

    Given a partition of G's nodes into blocks, the auxiliary subgraph
    captures inter-block connectivity. If this subgraph is an expander
    (high Cheeger constant), then treewidth MIGRATED to the auxiliary
    structure rather than being reduced.

    This is the computational implementation of the paper's Auxiliary
    Expander Theorem and Treewidth Migration Principle.

    Args:
        G: The constraint graph.
        partition: List of sets, each set containing variable indices
                   forming a block.

    Returns:
        Dict with aux_n_edges, aux_cheeger, aux_density,
        aux_treewidth_estimate, migration_detected (bool).
    """
    n_blocks = len(partition)
    if n_blocks <= 1:
        return {
            "aux_n_edges": 0, "aux_cheeger": 0.0, "aux_density": 0.0,
            "aux_treewidth_estimate": 0, "migration_detected": False,
        }

    # Build node-to-block mapping
    node_to_block = {}
    for block_idx, block in enumerate(partition):
        for node in block:
            node_to_block[node] = block_idx

    # Build auxiliary graph: edge between blocks i,j if any
    # variable in block i is connected to any variable in block j
    aux = nx.Graph()
    aux.add_nodes_from(range(n_blocks))
    crossing_edges = 0
    for u, v in G.edges():
        bu = node_to_block.get(u)
        bv = node_to_block.get(v)
        if bu is not None and bv is not None and bu != bv:
            aux.add_edge(bu, bv)
            crossing_edges += 1

    aux_stats = constraint_graph_stats(aux)

    # Estimate Cheeger constant via random cut sampling
    cheeger = _estimate_cheeger_random_cuts(aux, n_samples=100)

    # Heuristic treewidth estimate for the auxiliary graph
    if aux.number_of_nodes() > 2 and aux.number_of_edges() > 0:
        from networkx.algorithms.approximation.treewidth import treewidth_min_degree
        aux_tw, _ = treewidth_min_degree(aux)
    else:
        aux_tw = 0

    # Migration detected if auxiliary graph has substantial expansion
    # Paper shows h ≈ 0.56 for random 3-SAT block decomposition
    migration_detected = cheeger > 0.1 and aux_tw > np.log2(max(n_blocks, 2))

    return {
        "aux_n_edges": aux.number_of_edges(),
        "aux_crossing_edges": crossing_edges,
        "aux_cheeger": cheeger,
        "aux_density": aux_stats["density"],
        "aux_treewidth_estimate": aux_tw,
        "aux_algebraic_connectivity": aux_stats["algebraic_connectivity"],
        "migration_detected": migration_detected,
    }


def _estimate_cheeger_random_cuts(G: nx.Graph, n_samples: int = 100) -> float:
    r"""Estimate Cheeger constant via random balanced cuts.

    h(G) = min_{S: |S| <= n/2} |E(S, V\\S)| / |S|

    We approximate by random sampling.
    """
    n = G.number_of_nodes()
    if n <= 1:
        return 0.0

    nodes = list(G.nodes())
    rng = np.random.default_rng(42)
    min_ratio = float("inf")

    for _ in range(n_samples):
        # Random subset of size between 1 and n/2
        size = rng.integers(1, max(n // 2, 2))
        subset = set(rng.choice(nodes, size=size, replace=False))
        complement = set(nodes) - subset

        # Count crossing edges
        cut_size = sum(1 for u, v in G.edges() if (u in subset) != (v in subset))
        ratio = cut_size / len(subset)
        min_ratio = min(min_ratio, ratio)

    return min_ratio if min_ratio != float("inf") else 0.0


def constraint_graph_laplacian_stats(G: nx.Graph) -> dict:
    """Compute Laplacian spectral statistics for a constraint graph.

    Returns dict with lambda_2 (spectral gap), lambda_max,
    cheeger_lower (lambda_2/2), cheeger_upper (sqrt(2*lambda_2)),
    and grohe_marx_tw_lower (lambda_2*n/2*log(n)).

    These provide a spectral-theoretic lower bound on treewidth
    via the Grohe-Marx bound: tw >= Omega(h*n/log n) >= Omega(lambda_2*n/2*log n).
    """
    n = G.number_of_nodes()
    if n < 3 or G.number_of_edges() == 0:
        return {
            "lambda_2": 0.0, "lambda_max": 0.0,
            "cheeger_lower": 0.0, "cheeger_upper": 0.0,
            "grohe_marx_tw_lower": 0.0,
        }
    try:
        import math
        L = nx.normalized_laplacian_matrix(G).toarray()
        eigenvalues = sorted(np.real(np.linalg.eigvalsh(L)))
        lam2 = float(eigenvalues[1]) if len(eigenvalues) > 1 else 0.0
        lam_max = float(eigenvalues[-1]) if eigenvalues else 0.0
        log_n = math.log(max(n, 2))
        return {
            "lambda_2": lam2,
            "lambda_max": lam_max,
            "cheeger_lower": lam2 / 2.0,
            "cheeger_upper": math.sqrt(max(0.0, 2.0 * lam2)),
            "grohe_marx_tw_lower": lam2 * n / (2.0 * log_n),
        }
    except Exception:
        return {
            "lambda_2": 0.0, "lambda_max": 0.0,
            "cheeger_lower": 0.0, "cheeger_upper": 0.0,
            "grohe_marx_tw_lower": 0.0,
        }


def find_separators(G: nx.Graph, min_size: int = 1) -> list[set[int]]:
    """Find vertex separators in the constraint graph.

    Useful for the optimizer: separators identify where the graph
    can be decomposed with minimal interface.
    """
    separators = []
    if not nx.is_connected(G):
        return separators

    # Find minimum vertex cut for each pair of high-degree nodes
    nodes_by_degree = sorted(G.nodes(), key=lambda n: G.degree(n), reverse=True)
    checked = set()

    for u in nodes_by_degree[:min(10, len(nodes_by_degree))]:
        for v in nodes_by_degree[:min(10, len(nodes_by_degree))]:
            if u >= v or (u, v) in checked:
                continue
            checked.add((u, v))
            if not G.has_edge(u, v):
                try:
                    sep = nx.minimum_node_cut(G, u, v)
                    if len(sep) >= min_size:
                        separators.append(sep)
                except nx.NetworkXError:
                    continue

    return separators
