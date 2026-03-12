"""VTWInstance — the single source of truth for any verification task.

Every module in the VTW engine operates ON a VTWInstance.
The optimizer returns a NEW VTWInstance (restructured).
The optimization loop is:
  instance → measure(instance) → restructure(instance) → new_instance → compare
"""

import hashlib
import random
from dataclasses import dataclass, field
from io import StringIO
from typing import Optional

import networkx as nx

from vtw.config import _ensure_lib_paths

_ensure_lib_paths()
from pysat.formula import CNF

from vtw.constraint_graph import cnf_to_constraint_graph


@dataclass
class InstanceMetadata:
    """Generation parameters and provenance."""
    family: str = "unknown"  # random, planted, community, imported
    n_vars: int = 0
    clause_ratio: float = 0.0
    seed: Optional[int] = None
    parent_hash: Optional[str] = None  # Hash of instance this was derived from
    strategy_applied: Optional[str] = None  # Optimization strategy that created this
    generation_params: dict = field(default_factory=dict)


class VTWInstance:
    """Single source of truth for a SAT instance / verification task.

    Wraps pysat CNF with VTW-specific methods: constraint graph construction,
    format conversion, and metadata tracking.
    """

    def __init__(self, cnf: CNF, metadata: Optional[InstanceMetadata] = None):
        self._cnf = cnf
        self.metadata = metadata or InstanceMetadata()
        self._constraint_graph: Optional[nx.Graph] = None  # Cached
        self._dimacs_hash: Optional[str] = None

    # ── Properties ────────────────────────────────────────────

    @property
    def n_vars(self) -> int:
        return self._cnf.nv

    @property
    def n_clauses(self) -> int:
        return len(self._cnf.clauses)

    @property
    def clause_density(self) -> float:
        if self.n_vars == 0:
            return 0.0
        return self.n_clauses / self.n_vars

    @property
    def clauses(self) -> list[list[int]]:
        return self._cnf.clauses

    @property
    def cnf(self) -> CNF:
        return self._cnf

    @property
    def dimacs_hash(self) -> str:
        """SHA256 of DIMACS representation for reproducibility."""
        if self._dimacs_hash is None:
            self._dimacs_hash = hashlib.sha256(
                self.to_dimacs_string().encode()
            ).hexdigest()[:16]
        return self._dimacs_hash

    # ── Core Transforms ───────────────────────────────────────

    def to_constraint_graph(self) -> nx.Graph:
        """Build or return cached constraint graph.

        Edge (i,j) iff variables i and j co-occur in any clause.
        This is THE central object in the VTW framework.
        """
        if self._constraint_graph is None:
            self._constraint_graph = cnf_to_constraint_graph(
                self._cnf.clauses, self._cnf.nv
            )
        return self._constraint_graph

    def to_dimacs_string(self) -> str:
        """Serialize to DIMACS CNF format string."""
        buf = StringIO()
        self._cnf.to_fp(buf)
        return buf.getvalue()

    def to_dimacs_file(self, path: str):
        """Write DIMACS CNF format to file."""
        self._cnf.to_file(path)

    def invalidate_cache(self):
        """Clear cached constraint graph (call after modification)."""
        self._constraint_graph = None
        self._dimacs_hash = None

    # ── Factory Methods (Distribution Sampler) ────────────────

    @classmethod
    def random_3sat(
        cls,
        n: int,
        clause_ratio: float = 4.267,
        seed: Optional[int] = None,
    ) -> "VTWInstance":
        """Generate uniform random 3-SAT instance.

        Args:
            n: Number of variables.
            clause_ratio: Clauses per variable (4.267 = phase transition).
            seed: Random seed for reproducibility.
        """
        rng = random.Random(seed)
        m = int(n * clause_ratio)
        cnf = CNF()

        for _ in range(m):
            # Pick 3 distinct variables, random polarity
            variables = rng.sample(range(1, n + 1), 3)
            clause = [v * rng.choice([-1, 1]) for v in variables]
            cnf.append(clause)

        meta = InstanceMetadata(
            family="random",
            n_vars=n,
            clause_ratio=clause_ratio,
            seed=seed,
            generation_params={"k": 3, "m": m},
        )
        return cls(cnf, meta)

    @classmethod
    def planted_3sat(
        cls,
        n: int,
        clause_ratio: float = 4.267,
        seed: Optional[int] = None,
    ) -> "VTWInstance":
        """Generate planted 3-SAT instance (guaranteed satisfiable).

        Generates a random assignment, then creates clauses satisfied by it
        with polarity adjustment to match the planted solution.
        """
        rng = random.Random(seed)
        m = int(n * clause_ratio)
        cnf = CNF()

        # Plant a random assignment
        assignment = [rng.choice([-1, 1]) for _ in range(n + 1)]  # 1-indexed

        for _ in range(m):
            variables = rng.sample(range(1, n + 1), 3)
            # Ensure at least one literal satisfied by assignment
            clause = []
            for v in variables:
                # With probability 0.5, align with assignment
                if rng.random() < 0.5:
                    clause.append(v * assignment[v])  # Satisfied literal
                else:
                    clause.append(v * rng.choice([-1, 1]))

            # Guarantee satisfaction: if no literal satisfied, flip one
            if not any(
                (lit > 0 and assignment[abs(lit)] > 0) or
                (lit < 0 and assignment[abs(lit)] < 0)
                for lit in clause
            ):
                idx = rng.randrange(len(clause))
                v = abs(clause[idx])
                clause[idx] = v * assignment[v]

            cnf.append(clause)

        meta = InstanceMetadata(
            family="planted",
            n_vars=n,
            clause_ratio=clause_ratio,
            seed=seed,
            generation_params={"k": 3, "m": m},
        )
        return cls(cnf, meta)

    @classmethod
    def community_3sat(
        cls,
        n: int,
        n_communities: int = 4,
        inter_ratio: float = 0.1,
        clause_ratio: float = 4.267,
        seed: Optional[int] = None,
    ) -> "VTWInstance":
        """Generate community-structured 3-SAT instance.

        Variables are partitioned into communities. Most clauses are
        intra-community; inter_ratio controls cross-community clauses.
        This creates instances with natural modular structure.
        """
        rng = random.Random(seed)
        m = int(n * clause_ratio)
        cnf = CNF()

        # Partition variables into communities
        vars_list = list(range(1, n + 1))
        rng.shuffle(vars_list)
        community_size = n // n_communities
        communities = []
        for i in range(n_communities):
            start = i * community_size
            end = start + community_size if i < n_communities - 1 else n
            communities.append(vars_list[start:end])

        all_vars = list(range(1, n + 1))
        for _ in range(m):
            if rng.random() < inter_ratio:
                # Inter-community clause: pick from different communities
                variables = rng.sample(all_vars, 3)
            else:
                # Intra-community clause: pick from same community
                comm = rng.choice(communities)
                if len(comm) >= 3:
                    variables = rng.sample(comm, 3)
                else:
                    variables = rng.sample(all_vars, 3)

            clause = [v * rng.choice([-1, 1]) for v in variables]
            cnf.append(clause)

        meta = InstanceMetadata(
            family="community",
            n_vars=n,
            clause_ratio=clause_ratio,
            seed=seed,
            generation_params={
                "k": 3, "m": m,
                "n_communities": n_communities,
                "inter_ratio": inter_ratio,
            },
        )
        return cls(cnf, meta)

    @classmethod
    def from_dimacs(cls, path: str) -> "VTWInstance":
        """Load instance from DIMACS CNF file."""
        cnf = CNF(from_file=path)
        meta = InstanceMetadata(
            family="imported",
            n_vars=cnf.nv,
            clause_ratio=len(cnf.clauses) / max(cnf.nv, 1),
            generation_params={"source": path},
        )
        return cls(cnf, meta)

    @classmethod
    def from_cnf(cls, cnf: CNF, metadata: Optional[InstanceMetadata] = None) -> "VTWInstance":
        """Wrap an existing pysat CNF object."""
        return cls(cnf, metadata)

    def __repr__(self) -> str:
        return (
            f"VTWInstance(n_vars={self.n_vars}, n_clauses={self.n_clauses}, "
            f"density={self.clause_density:.3f}, family={self.metadata.family})"
        )
