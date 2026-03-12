"""Central configuration for the VTW optimization engine.

Auto-detects compiled solver paths, manages thresholds,
and provides graceful degradation when external solvers are missing.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Root of the alphageometry-main project
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Library source paths
NETWORKX_PATH = PROJECT_ROOT / "networkx-main"
PYSAT_PATH = PROJECT_ROOT / "pysat-master"
TWALGOR_PATH = PROJECT_ROOT / "tw-master"
JDRASIL_PATH = PROJECT_ROOT / "Jdrasil-master"
CADICAL_PATH = PROJECT_ROOT / "cadical-master"
KISSAT_PATH = PROJECT_ROOT / "kissat-master"


def _ensure_lib_paths():
    """Add networkx and pysat source trees to sys.path if not installed."""
    import sys
    nx_src = str(NETWORKX_PATH)
    pysat_src = str(PYSAT_PATH)
    if nx_src not in sys.path:
        sys.path.insert(0, nx_src)
    if pysat_src not in sys.path:
        sys.path.insert(0, pysat_src)


_ensure_lib_paths()


def _detect_twalgor_classpath() -> str | None:
    bin_dir = TWALGOR_PATH / "bin"
    if bin_dir.is_dir() and any(bin_dir.rglob("*.class")):
        return str(bin_dir)
    return None


def _detect_jdrasil_jar() -> str | None:
    build_libs = JDRASIL_PATH / "subprojects" / "core" / "build" / "libs"
    if build_libs.is_dir():
        jars = list(build_libs.glob("*.jar"))
        if jars:
            return str(jars[0])
    # Also check for a manually-placed jar
    for jar in JDRASIL_PATH.rglob("*.jar"):
        if "core" in jar.name.lower() or "jdrasil" in jar.name.lower():
            return str(jar)
    return None


def _detect_cadical_binary() -> str | None:
    candidate = CADICAL_PATH / "build" / "cadical"
    if candidate.is_file() and os.access(str(candidate), os.X_OK):
        return str(candidate)
    return None


def _detect_kissat_binary() -> str | None:
    candidate = KISSAT_PATH / "build" / "kissat"
    if candidate.is_file() and os.access(str(candidate), os.X_OK):
        return str(candidate)
    return None


def _detect_java() -> str | None:
    return shutil.which("java")


@dataclass
class VTWConfig:
    """Configuration for the VTW optimization engine."""

    # Solver paths (auto-detected, overridable)
    java_path: str | None = field(default_factory=_detect_java)
    twalgor_classpath: str | None = field(default_factory=_detect_twalgor_classpath)
    jdrasil_jar: str | None = field(default_factory=_detect_jdrasil_jar)
    cadical_path: str | None = field(default_factory=_detect_cadical_binary)
    kissat_path: str | None = field(default_factory=_detect_kissat_binary)

    # Measurement thresholds
    exact_n_max: int = 50  # Use exact solver for n <= this
    heuristic_escalation_margin: float = 0.1  # Escalate if near threshold
    exact_timeout: int = 300  # seconds
    sat_timeout: int = 60  # seconds

    # Optimization
    max_optimization_iterations: int = 10
    convergence_threshold: float = 0.01  # Stop if tw reduction < this ratio

    # Experiment defaults
    default_clause_ratio: float = 4.267  # Near 3-SAT phase transition
    default_samples_per_n: int = 10

    @property
    def has_exact_solver(self) -> bool:
        return self.java_path is not None and (
            self.twalgor_classpath is not None or self.jdrasil_jar is not None
        )

    @property
    def has_external_sat_solver(self) -> bool:
        return self.cadical_path is not None or self.kissat_path is not None

    def status(self) -> dict:
        """Report availability of all components."""
        return {
            "java": self.java_path is not None,
            "twalgor": self.twalgor_classpath is not None,
            "jdrasil": self.jdrasil_jar is not None,
            "cadical": self.cadical_path is not None,
            "kissat": self.kissat_path is not None,
            "pysat_fallback": True,  # Always available from source
            "networkx": True,  # Always available from source
        }

    def print_status(self):
        """Print human-readable solver status."""
        s = self.status()
        for name, available in s.items():
            mark = "+" if available else "-"
            print(f"  [{mark}] {name}")
