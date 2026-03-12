"""PACE format I/O bridge for treewidth solvers.

Both twalgor and Jdrasil use the PACE challenge format:
- .gr: graph input (p tw N M header, then u v edge lines, 1-indexed)
- .td: tree decomposition output (s td nb width+1 n, then bags and tree edges)

This module is the single conversion point between networkx graphs
and the external solver format.
"""

from dataclasses import dataclass, field
import networkx as nx


@dataclass
class TreeDecomposition:
    """Parsed tree decomposition from PACE .td format."""
    width: int
    n_bags: int
    n_vertices: int
    bags: dict[int, frozenset[int]] = field(default_factory=dict)  # bag_id → vertex set
    tree_edges: list[tuple[int, int]] = field(default_factory=list)

    def to_networkx(self) -> nx.Graph:
        """Convert to networkx tree for analysis."""
        T = nx.Graph()
        for bag_id, vertices in self.bags.items():
            T.add_node(bag_id, vertices=vertices)
        T.add_edges_from(self.tree_edges)
        return T


def networkx_to_pace_gr(G: nx.Graph) -> str:
    """Convert networkx graph to PACE .gr format string.

    PACE format is 1-indexed. Networkx nodes can be any hashable;
    we create a mapping to 1..N.
    """
    nodes = sorted(G.nodes())
    node_to_id = {n: i + 1 for i, n in enumerate(nodes)}
    n = len(nodes)
    edges = list(G.edges())
    m = len(edges)

    lines = [f"p tw {n} {m}"]
    for u, v in edges:
        lines.append(f"{node_to_id[u]} {node_to_id[v]}")
    return "\n".join(lines) + "\n"


def pace_gr_to_networkx(gr_text: str) -> nx.Graph:
    """Parse PACE .gr format string into networkx graph."""
    G = nx.Graph()
    for line in gr_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            n = int(parts[2])
            for i in range(1, n + 1):
                G.add_node(i)
        else:
            parts = line.split()
            u, v = int(parts[0]), int(parts[1])
            G.add_edge(u, v)
    return G


def parse_pace_td(td_text: str) -> TreeDecomposition:
    """Parse PACE .td format string into TreeDecomposition.

    Format:
      s td <num_bags> <bag_size> <n_vertices>   (bag_size = treewidth + 1)
      b <bag_id> <v1> <v2> ...                  (1-indexed vertices)
      <bag_id_1> <bag_id_2>                      (tree edges)
    """
    td = TreeDecomposition(width=0, n_bags=0, n_vertices=0)

    for line in td_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        parts = line.split()
        if parts[0] == "s":
            # s td <nb> <width+1> <n>
            td.n_bags = int(parts[2])
            td.width = int(parts[3]) - 1  # bag_size - 1 = treewidth
            td.n_vertices = int(parts[4])
        elif parts[0] == "b":
            # b <bag_id> <v1> <v2> ...
            bag_id = int(parts[1])
            vertices = frozenset(int(v) for v in parts[2:])
            td.bags[bag_id] = vertices
        else:
            # tree edge: <id1> <id2>
            try:
                u, v = int(parts[0]), int(parts[1])
                td.tree_edges.append((u, v))
            except (ValueError, IndexError):
                continue

    return td


def tree_decomposition_to_pace_td(td: TreeDecomposition) -> str:
    """Serialize TreeDecomposition to PACE .td format string."""
    lines = [f"s td {td.n_bags} {td.width + 1} {td.n_vertices}"]
    for bag_id in sorted(td.bags.keys()):
        vertices = " ".join(str(v) for v in sorted(td.bags[bag_id]))
        lines.append(f"b {bag_id} {vertices}")
    for u, v in td.tree_edges:
        lines.append(f"{u} {v}")
    return "\n".join(lines) + "\n"
