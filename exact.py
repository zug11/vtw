"""Exact treewidth computation via external Java solvers.

Two solvers unified as one validation layer:
- twalgor (Tamaki's contraction-recursive, file-based I/O)
- Jdrasil (Bodlaender's dynamic programming, stdin/stdout)

Discrepancies between solvers are data quality signals, not errors.
Cross-validation on n<=30 instances produces "solver agreement" metrics.
"""

import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx

from vtw.config import VTWConfig
from vtw.formats import (
    TreeDecomposition,
    networkx_to_pace_gr,
    parse_pace_td,
)


@dataclass
class ExactSolverResult:
    """Result from exact treewidth computation."""
    treewidth: int
    decomposition: Optional[TreeDecomposition]
    solver_used: str  # 'twalgor' or 'jdrasil'
    elapsed_seconds: float
    timed_out: bool = False


@dataclass
class CrossValidationResult:
    """Result from cross-validating two exact solvers."""
    twalgor_tw: Optional[int]
    jdrasil_tw: Optional[int]
    agree: bool
    twalgor_time: float = 0.0
    jdrasil_time: float = 0.0


class ExactSolver:
    """Unified interface over twalgor and Jdrasil.

    Both solvers use the PACE .gr/.td format — formats.py handles
    the conversion. The solver selection and cross-validation logic
    lives here.
    """

    def __init__(self, config: VTWConfig):
        self.config = config

    def measure(
        self,
        G: nx.Graph,
        timeout: Optional[int] = None,
        solver: str = "auto",
    ) -> ExactSolverResult:
        """Compute exact treewidth.

        Args:
            G: The constraint graph.
            timeout: Seconds before giving up. Default from config.
            solver: 'twalgor', 'jdrasil', or 'auto' (try twalgor first).

        Returns:
            ExactSolverResult with treewidth and decomposition.
        """
        if timeout is None:
            timeout = self.config.exact_timeout

        if solver == "auto":
            if self.config.twalgor_classpath:
                result = self._run_twalgor(G, timeout)
                if not result.timed_out:
                    return result
                # Fall through to jdrasil
            if self.config.jdrasil_jar or self._jdrasil_classpath():
                return self._run_jdrasil(G, timeout)
            raise RuntimeError(
                "No exact solver available. Run `python -m vtw build` first."
            )
        elif solver == "twalgor":
            return self._run_twalgor(G, timeout)
        elif solver == "jdrasil":
            return self._run_jdrasil(G, timeout)
        else:
            raise ValueError(f"Unknown solver: {solver}")

    def cross_validate(self, G: nx.Graph, timeout: int = 120) -> CrossValidationResult:
        """Run both solvers on same graph, compare treewidth values.

        For n<=30: this produces the "solver agreement" metric
        that strengthens reproducibility claims.
        """
        tw_a, time_a = None, 0.0
        tw_b, time_b = None, 0.0

        if self.config.twalgor_classpath:
            try:
                result_a = self._run_twalgor(G, timeout)
                if not result_a.timed_out:
                    tw_a = result_a.treewidth
                    time_a = result_a.elapsed_seconds
            except Exception:
                pass

        if self.config.jdrasil_jar or self._jdrasil_classpath():
            try:
                result_b = self._run_jdrasil(G, timeout)
                if not result_b.timed_out:
                    tw_b = result_b.treewidth
                    time_b = result_b.elapsed_seconds
            except Exception:
                pass

        agree = (tw_a is not None and tw_b is not None and tw_a == tw_b)

        return CrossValidationResult(
            twalgor_tw=tw_a,
            jdrasil_tw=tw_b,
            agree=agree,
            twalgor_time=time_a,
            jdrasil_time=time_b,
        )

    def _run_twalgor(self, G: nx.Graph, timeout: int) -> ExactSolverResult:
        """Run twalgor via subprocess.

        twalgor reads from file, writes to file:
          java -cp <classpath> io.github.twalgor.main.ExactTW <graph.gr> <output.td>
        """
        if not self.config.twalgor_classpath or not self.config.java_path:
            raise RuntimeError("twalgor not available")

        gr_content = networkx_to_pace_gr(G)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gr", delete=False
        ) as gr_file:
            gr_file.write(gr_content)
            gr_path = gr_file.name

        td_path = gr_path.replace(".gr", ".td")

        try:
            start = time.monotonic()
            result = subprocess.run(
                [
                    self.config.java_path,
                    "-cp", self.config.twalgor_classpath,
                    "io.github.twalgor.main.ExactTW",
                    gr_path, td_path,
                ],
                capture_output=True, text=True, timeout=timeout,
            )
            elapsed = time.monotonic() - start

            if result.returncode != 0:
                raise RuntimeError(
                    f"twalgor failed (exit {result.returncode}): {result.stderr[:200]}"
                )

            td_text = Path(td_path).read_text()
            td = parse_pace_td(td_text)

            return ExactSolverResult(
                treewidth=td.width,
                decomposition=td,
                solver_used="twalgor",
                elapsed_seconds=elapsed,
            )
        except subprocess.TimeoutExpired:
            return ExactSolverResult(
                treewidth=-1,
                decomposition=None,
                solver_used="twalgor",
                elapsed_seconds=timeout,
                timed_out=True,
            )
        finally:
            # Clean up temp files
            for p in [gr_path, td_path]:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass

    def _run_jdrasil(self, G: nx.Graph, timeout: int) -> ExactSolverResult:
        """Run Jdrasil via subprocess.

        Jdrasil reads from stdin, writes to stdout:
          java -cp <jar_or_classpath> jdrasil.Exact < graph.gr
        """
        classpath = self.config.jdrasil_jar or self._jdrasil_classpath()
        if not classpath or not self.config.java_path:
            raise RuntimeError("Jdrasil not available")

        gr_content = networkx_to_pace_gr(G)

        try:
            start = time.monotonic()
            result = subprocess.run(
                [
                    self.config.java_path,
                    "-cp", classpath,
                    "jdrasil.Exact",
                ],
                input=gr_content,
                capture_output=True, text=True, timeout=timeout,
            )
            elapsed = time.monotonic() - start

            if result.returncode != 0:
                raise RuntimeError(
                    f"Jdrasil failed (exit {result.returncode}): {result.stderr[:200]}"
                )

            td = parse_pace_td(result.stdout)

            return ExactSolverResult(
                treewidth=td.width,
                decomposition=td,
                solver_used="jdrasil",
                elapsed_seconds=elapsed,
            )
        except subprocess.TimeoutExpired:
            return ExactSolverResult(
                treewidth=-1,
                decomposition=None,
                solver_used="jdrasil",
                elapsed_seconds=timeout,
                timed_out=True,
            )

    def _jdrasil_classpath(self) -> Optional[str]:
        """Check for manually-compiled Jdrasil bin directory."""
        from vtw.config import JDRASIL_PATH
        bin_dir = JDRASIL_PATH / "bin"
        if bin_dir.is_dir() and any(bin_dir.rglob("*.class")):
            return str(bin_dir)
        return None
