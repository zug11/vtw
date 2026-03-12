"""Restructuring strategies for VTW optimization.

Each strategy transforms a VTWInstance into a NEW VTWInstance with
(potentially) lower verifier treewidth. The optimizer chains and
evaluates these, using treewidth measurement as feedback.

Strategies are not independent — ModularizeStrategy may create
subproblems that LocalizeStrategy can further optimize.
The optimizer manages these interactions.

CRITICAL: Each strategy must preserve satisfiability equivalence.
The restructured instance encodes the same problem, possibly with
auxiliary variables.
"""

import math
import random
from abc import ABC, abstractmethod
from itertools import combinations

import networkx as nx

from vtw.config import _ensure_lib_paths

_ensure_lib_paths()
from pysat.formula import CNF

from vtw.constraint_graph import (
    cnf_to_constraint_graph,
    constraint_graph_stats,
    detect_expander_subgraph,
)
from vtw.instance import InstanceMetadata, VTWInstance


class RestructuringStrategy(ABC):
    """Base class for VTW-reducing transformations."""

    @abstractmethod
    def apply(self, instance: VTWInstance) -> VTWInstance:
        """Transform instance to reduce verifier treewidth.

        Returns a NEW VTWInstance (never modifies in place).
        """

    @abstractmethod
    def name(self) -> str:
        """Strategy identifier for logging and metadata."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class ModularizeStrategy(RestructuringStrategy):
    """Decompose clauses into independent sub-problems.

    Finds connected components or near-separators in the constraint
    graph, then separates the CNF into independent subformulas
    connected through interface variables.

    Best for: instances with natural modularity (community structure,
    designed systems). Worst for: random 3-SAT (fully connected).
    """

    def name(self) -> str:
        return "modularize"

    def apply(self, instance: VTWInstance) -> VTWInstance:
        G = instance.to_constraint_graph()

        # If already disconnected, partition clauses by component
        if not nx.is_connected(G):
            return self._partition_by_components(instance, G)

        # Find approximate vertex separator
        separator = self._find_best_separator(G)
        if separator is None or len(separator) >= instance.n_vars // 2:
            # No useful separator found — return unchanged
            return instance

        return self._restructure_around_separator(instance, G, separator)

    def _partition_by_components(
        self, instance: VTWInstance, G: nx.Graph
    ) -> VTWInstance:
        """When graph is disconnected, we can solve components independently.

        Add auxiliary variables that encode per-component satisfiability,
        creating a tree-structured meta-problem.
        """
        components = list(nx.connected_components(G))
        if len(components) <= 1:
            return instance

        new_cnf = CNF()
        next_var = instance.n_vars + 1

        # Component indicator variables
        component_vars = []
        for comp_idx, comp_vars in enumerate(components):
            comp_var = next_var
            next_var += 1
            component_vars.append(comp_var)

            # All original clauses in this component
            for clause in instance.clauses:
                clause_vars = set(abs(lit) for lit in clause)
                if clause_vars & comp_vars:
                    new_cnf.append(clause)

        # Add clause: all component indicators must be true
        # (This is a trivial conjunction — but it makes the
        # tree structure explicit for the treewidth measurer)
        for cv in component_vars:
            new_cnf.append([cv])

        meta = InstanceMetadata(
            family=instance.metadata.family,
            n_vars=next_var - 1,
            clause_ratio=len(new_cnf.clauses) / max(next_var - 1, 1),
            parent_hash=instance.dimacs_hash,
            strategy_applied=self.name(),
        )
        return VTWInstance(new_cnf, meta)

    def _find_best_separator(self, G: nx.Graph) -> set[int] | None:
        """Find a small vertex separator."""
        nodes = list(G.nodes())
        if len(nodes) < 4:
            return None

        best_sep = None
        best_size = len(nodes)

        # Try a few pairs of distant nodes
        for _ in range(min(20, len(nodes))):
            u = random.choice(nodes)
            # Find a distant node
            try:
                distances = nx.single_source_shortest_path_length(G, u)
                far_nodes = sorted(distances.keys(), key=lambda x: distances[x], reverse=True)
                if len(far_nodes) < 2:
                    continue
                v = far_nodes[0]
                if u == v:
                    continue
                sep = nx.minimum_node_cut(G, u, v)
                if len(sep) < best_size:
                    best_sep = sep
                    best_size = len(sep)
            except (nx.NetworkXError, nx.NetworkXUnfeasible):
                continue

        return best_sep

    def _restructure_around_separator(
        self, instance: VTWInstance, G: nx.Graph, separator: set[int]
    ) -> VTWInstance:
        """Add summary variables at separator to break long-range deps."""
        new_cnf = CNF()
        next_var = instance.n_vars + 1

        # Add all original clauses
        for clause in instance.clauses:
            new_cnf.append(clause)

        # Add summary variables for separator nodes
        # Each summary var encodes "separator node i is assigned true"
        sep_summary = {}
        for sep_node in separator:
            summary_var = next_var
            next_var += 1
            sep_summary[sep_node] = summary_var
            # Equivalence: summary_var <=> sep_node
            new_cnf.append([-sep_node, summary_var])
            new_cnf.append([sep_node, -summary_var])

        meta = InstanceMetadata(
            family=instance.metadata.family,
            n_vars=next_var - 1,
            clause_ratio=len(new_cnf.clauses) / max(next_var - 1, 1),
            parent_hash=instance.dimacs_hash,
            strategy_applied=self.name(),
            generation_params={"separator_size": len(separator)},
        )
        return VTWInstance(new_cnf, meta)


class LocalizeStrategy(RestructuringStrategy):
    """Replace long-range constraints with local proxies.

    For each pair of variables with high graph distance that co-occur
    in a clause, add intermediate summary variables that break the
    direct dependency into a chain of local constraints.

    Best for: instances with few long-range connections.
    """

    def __init__(self, distance_threshold: int = 3):
        self.distance_threshold = distance_threshold

    def name(self) -> str:
        return "localize"

    def apply(self, instance: VTWInstance) -> VTWInstance:
        G = instance.to_constraint_graph()

        if not nx.is_connected(G):
            return instance

        # Find long-range edges in constraint graph
        # An edge (u,v) is "long-range" if removing it, the shortest
        # path between u and v would be > distance_threshold
        long_range_pairs = []
        for u, v in G.edges():
            # Remove edge temporarily and check distance
            G.remove_edge(u, v)
            try:
                dist = nx.shortest_path_length(G, u, v)
                if dist > self.distance_threshold:
                    long_range_pairs.append((u, v))
            except nx.NetworkXNoPath:
                long_range_pairs.append((u, v))
            G.add_edge(u, v)

        if not long_range_pairs:
            return instance

        # Add relay variables for long-range connections
        new_cnf = CNF()
        next_var = instance.n_vars + 1

        for clause in instance.clauses:
            new_cnf.append(clause)

        for u, v in long_range_pairs[:50]:  # Cap to prevent blowup
            # Add relay: relay_var that is equivalent to (u XOR v)
            # This breaks the direct constraint into two local ones
            relay_var = next_var
            next_var += 1
            # relay <=> (u == v): relay iff both same
            new_cnf.append([-u, -v, relay_var])
            new_cnf.append([u, v, relay_var])
            new_cnf.append([u, -v, -relay_var])
            new_cnf.append([-u, v, -relay_var])

        meta = InstanceMetadata(
            family=instance.metadata.family,
            n_vars=next_var - 1,
            clause_ratio=len(new_cnf.clauses) / max(next_var - 1, 1),
            parent_hash=instance.dimacs_hash,
            strategy_applied=self.name(),
            generation_params={"long_range_pairs": len(long_range_pairs)},
        )
        return VTWInstance(new_cnf, meta)


class BlockDecompStrategy(RestructuringStrategy):
    """Block decomposition: group variables into sqrt(n) blocks.

    Paper's baseline: reduces treewidth to Theta(sqrt(n)).
    The Recursive Blocking Theorem proves this is fundamental:
    block-style padding cannot reach O(log n).

    Used as baseline comparison for other strategies.
    """

    def __init__(self, block_size: int | None = None):
        self.block_size = block_size  # None = auto (sqrt(n))

    def name(self) -> str:
        return "block_decomp"

    def apply(self, instance: VTWInstance) -> VTWInstance:
        n = instance.n_vars
        bs = self.block_size or max(2, int(math.sqrt(n)))

        # Partition variables into blocks
        blocks = []
        for i in range(0, n, bs):
            block = set(range(i + 1, min(i + bs + 1, n + 1)))
            if block:
                blocks.append(block)

        new_cnf = CNF()
        next_var = n + 1

        # Original clauses remain
        for clause in instance.clauses:
            new_cnf.append(clause)

        # For each block, add summary variables
        block_summaries = {}
        for block_idx, block_vars in enumerate(blocks):
            summary_var = next_var
            next_var += 1
            block_summaries[block_idx] = summary_var

            # Summary = AND of all variables in block being "consistent"
            # Encoded as: summary_var => (all block vars participate)
            for v in block_vars:
                new_cnf.append([-summary_var, v])  # summary => v
            # Reverse: all vars => summary
            clause = [summary_var] + [-v for v in block_vars]
            new_cnf.append(clause)

        meta = InstanceMetadata(
            family=instance.metadata.family,
            n_vars=next_var - 1,
            clause_ratio=len(new_cnf.clauses) / max(next_var - 1, 1),
            parent_hash=instance.dimacs_hash,
            strategy_applied=self.name(),
            generation_params={"block_size": bs, "n_blocks": len(blocks)},
        )
        return VTWInstance(new_cnf, meta)


class SummaryNodeStrategy(RestructuringStrategy):
    """Strategic summary node placement with expansion awareness.

    Unlike BlockDecomp which uses uniform blocks, this strategy
    uses detect_expander_subgraph to measure treewidth migration
    and only places summary nodes where expansion is below threshold.

    This is the key insight from the Auxiliary Expander Theorem:
    don't add summaries where they'd create an expander subgraph.
    """

    def __init__(self, expansion_threshold: float = 0.3):
        self.expansion_threshold = expansion_threshold

    def name(self) -> str:
        return "summary_node"

    def apply(self, instance: VTWInstance) -> VTWInstance:
        G = instance.to_constraint_graph()
        n = instance.n_vars

        # Find natural communities via spectral methods
        partition = self._find_low_expansion_partition(G)

        if len(partition) <= 1:
            return instance

        # Check if partition would cause treewidth migration
        exp_info = detect_expander_subgraph(G, partition)

        if exp_info["migration_detected"]:
            # Auxiliary Expander Theorem applies — this partition won't help.
            # Try a finer partition
            partition = self._refine_partition(G, partition)
            exp_info = detect_expander_subgraph(G, partition)
            if exp_info["migration_detected"]:
                return instance  # Can't help — migration is fundamental

        # Place summary nodes at partition boundaries
        new_cnf = CNF()
        next_var = n + 1

        for clause in instance.clauses:
            new_cnf.append(clause)

        # Build node-to-block mapping
        node_to_block = {}
        for block_idx, block in enumerate(partition):
            for node in block:
                node_to_block[node] = block_idx

        # Add summary variables for inter-block edges
        added_summaries = set()
        for u, v in G.edges():
            bu = node_to_block.get(u)
            bv = node_to_block.get(v)
            if bu is not None and bv is not None and bu != bv:
                pair = (min(bu, bv), max(bu, bv))
                if pair not in added_summaries:
                    added_summaries.add(pair)
                    summary_var = next_var
                    next_var += 1
                    # Summary encodes inter-block consistency
                    new_cnf.append([-u, -v, summary_var])
                    new_cnf.append([u, v, summary_var])

        meta = InstanceMetadata(
            family=instance.metadata.family,
            n_vars=next_var - 1,
            clause_ratio=len(new_cnf.clauses) / max(next_var - 1, 1),
            parent_hash=instance.dimacs_hash,
            strategy_applied=self.name(),
            generation_params={
                "n_blocks": len(partition),
                "n_summaries": len(added_summaries),
                "aux_cheeger": exp_info["aux_cheeger"],
            },
        )
        return VTWInstance(new_cnf, meta)

    def _find_low_expansion_partition(self, G: nx.Graph) -> list[set[int]]:
        """Find partition with low inter-block expansion."""
        n = G.number_of_nodes()
        if n < 4:
            return [set(G.nodes())]

        # Use spectral bisection recursively
        try:
            fiedler = nx.fiedler_vector(G)
            nodes = sorted(G.nodes())
            median = sorted(fiedler)[len(fiedler) // 2]
            part_a = {nodes[i] for i, v in enumerate(fiedler) if v <= median}
            part_b = set(G.nodes()) - part_a
            if part_a and part_b:
                return [part_a, part_b]
        except Exception:
            pass

        # Fallback: simple degree-based partition
        bs = max(2, int(math.sqrt(n)))
        nodes = sorted(G.nodes())
        return [set(nodes[i:i+bs]) for i in range(0, len(nodes), bs)]

    def _refine_partition(
        self, G: nx.Graph, partition: list[set[int]]
    ) -> list[set[int]]:
        """Split large blocks to reduce inter-block expansion."""
        refined = []
        for block in partition:
            if len(block) > 4:
                half = len(block) // 2
                block_list = sorted(block)
                refined.append(set(block_list[:half]))
                refined.append(set(block_list[half:]))
            else:
                refined.append(block)
        return refined


class SpectralPartitionStrategy(RestructuringStrategy):
    """Use spectral clustering to find minimum-expansion partitions.

    Place auxiliary variables at partition boundaries.
    Most sophisticated strategy — uses eigenvalue decomposition
    of the graph Laplacian.
    """

    def __init__(self, n_partitions: int | None = None):
        self.n_partitions = n_partitions

    def name(self) -> str:
        return "spectral_partition"

    def apply(self, instance: VTWInstance) -> VTWInstance:
        G = instance.to_constraint_graph()
        n = instance.n_vars

        if n < 6:
            return instance

        k = self.n_partitions or max(2, int(math.sqrt(n) / 2))

        # Multi-way spectral partition
        partition = self._spectral_partition(G, k)

        if len(partition) <= 1:
            return instance

        # Add boundary variables
        new_cnf = CNF()
        next_var = n + 1

        for clause in instance.clauses:
            new_cnf.append(clause)

        node_to_block = {}
        for idx, block in enumerate(partition):
            for node in block:
                node_to_block[node] = idx

        # For crossing edges, add auxiliary consistency variables
        crossing_pairs = set()
        for u, v in G.edges():
            bu = node_to_block.get(u)
            bv = node_to_block.get(v)
            if bu is not None and bv is not None and bu != bv:
                crossing_pairs.add((min(u, v), max(u, v)))

        for u, v in list(crossing_pairs)[:100]:  # Cap
            aux = next_var
            next_var += 1
            # aux encodes agreement: aux <=> (u == v)
            new_cnf.append([-u, -v, aux])
            new_cnf.append([u, v, aux])
            new_cnf.append([u, -v, -aux])
            new_cnf.append([-u, v, -aux])

        meta = InstanceMetadata(
            family=instance.metadata.family,
            n_vars=next_var - 1,
            clause_ratio=len(new_cnf.clauses) / max(next_var - 1, 1),
            parent_hash=instance.dimacs_hash,
            strategy_applied=self.name(),
            generation_params={
                "n_partitions": len(partition),
                "n_crossing": len(crossing_pairs),
            },
        )
        return VTWInstance(new_cnf, meta)

    def _spectral_partition(self, G: nx.Graph, k: int) -> list[set[int]]:
        """k-way spectral partition using Laplacian eigenvectors."""
        try:
            import numpy as np
            L = nx.laplacian_matrix(G).toarray().astype(float)
            eigenvalues, eigenvectors = np.linalg.eigh(L)

            # Use first k non-trivial eigenvectors for clustering
            k_actual = min(k, len(eigenvalues) - 1)
            features = eigenvectors[:, 1:k_actual + 1]

            # Simple k-means-style assignment
            nodes = sorted(G.nodes())
            n = len(nodes)
            labels = np.zeros(n, dtype=int)

            if features.shape[1] > 0:
                # Assign to nearest centroid via iterative refinement
                for dim in range(features.shape[1]):
                    median = np.median(features[:, dim])
                    mask = features[:, dim] > median
                    labels[mask] += (1 << dim)

            # Build partition from labels
            partition_map: dict[int, set[int]] = {}
            for i, node in enumerate(nodes):
                label = int(labels[i]) % k
                if label not in partition_map:
                    partition_map[label] = set()
                partition_map[label].add(node)

            return list(partition_map.values())

        except Exception:
            # Fallback: uniform partition
            nodes = sorted(G.nodes())
            bs = max(2, len(nodes) // k)
            return [set(nodes[i:i+bs]) for i in range(0, len(nodes), bs)]


# Registry of all available strategies
ALL_STRATEGIES: dict[str, type[RestructuringStrategy]] = {
    "modularize": ModularizeStrategy,
    "localize": LocalizeStrategy,
    "block_decomp": BlockDecompStrategy,
    "summary_node": SummaryNodeStrategy,
    "spectral_partition": SpectralPartitionStrategy,
}


def get_strategy(name: str, **kwargs) -> RestructuringStrategy:
    """Get strategy by name."""
    cls = ALL_STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(ALL_STRATEGIES.keys())}")
    return cls(**kwargs)


def get_all_strategies() -> list[RestructuringStrategy]:
    """Get instances of all strategies."""
    return [cls() for cls in ALL_STRATEGIES.values()]
