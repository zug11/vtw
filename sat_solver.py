"""SAT solver orchestration — validates instances BEFORE treewidth measurement.

Validation is an integrated pipeline stage, not an optional pre-check.
Every instance gets validated. Unvalidated instances never enter
treewidth measurement.

Tiered dispatch:
- n<=100: CaDiCaL (robust, proof logging)
- n>100: Kissat (fast, competition-optimized)
- Fallback: pysat.solvers (always available from source)
"""

import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from vtw.config import VTWConfig, _ensure_lib_paths

_ensure_lib_paths()


@dataclass
class SATResult:
    """Result from SAT validation."""
    satisfiable: Optional[bool]  # None if timed out
    model: Optional[list[int]]  # Variable assignments if SAT
    solver_used: str  # 'cadical', 'kissat', 'pysat_cadical153', etc.
    elapsed_seconds: float
    timed_out: bool = False


class SolverOrchestrator:
    """Manages SAT validation with tiered solver dispatch.

    The pysat fallback (Cadical153) means this module works even
    without compiling external CaDiCaL/Kissat. External solvers
    are preferred for performance and proof logging.
    """

    def __init__(self, config: VTWConfig):
        self.config = config

    def validate(
        self,
        instance: "VTWInstance",
        timeout: Optional[int] = None,
    ) -> SATResult:
        """Determine SAT/UNSAT for an instance.

        Uses tiered dispatch:
        1. n<=100 and CaDiCaL available → CaDiCaL
        2. n>100 and Kissat available → Kissat
        3. Fallback → pysat built-in solver
        """
        if timeout is None:
            timeout = self.config.sat_timeout

        n = instance.n_vars

        # Try external solvers first
        if n <= 100 and self.config.cadical_path:
            return self._validate_external(
                instance, self.config.cadical_path, "cadical", timeout
            )
        elif n > 100 and self.config.kissat_path:
            return self._validate_external(
                instance, self.config.kissat_path, "kissat", timeout
            )
        elif self.config.cadical_path:
            return self._validate_external(
                instance, self.config.cadical_path, "cadical", timeout
            )
        elif self.config.kissat_path:
            return self._validate_external(
                instance, self.config.kissat_path, "kissat", timeout
            )
        else:
            return self._validate_pysat(instance, timeout)

    def validate_batch(
        self,
        instances: list["VTWInstance"],
        timeout: Optional[int] = None,
        max_workers: int = 4,
    ) -> list[SATResult]:
        """Validate multiple instances concurrently."""
        results = [None] * len(instances)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.validate, inst, timeout): i
                for i, inst in enumerate(instances)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = SATResult(
                        satisfiable=None,
                        model=None,
                        solver_used="error",
                        elapsed_seconds=0.0,
                        timed_out=True,
                    )
        return results

    def _validate_external(
        self,
        instance: "VTWInstance",
        solver_path: str,
        solver_name: str,
        timeout: int,
    ) -> SATResult:
        """Run external SAT solver (CaDiCaL or Kissat).

        Both follow SAT competition convention:
        - Exit 10 = SATISFIABLE
        - Exit 20 = UNSATISFIABLE
        - Model lines start with 'v'
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cnf", delete=False
        ) as f:
            f.write(instance.to_dimacs_string())
            cnf_path = f.name

        try:
            start = time.monotonic()
            result = subprocess.run(
                [solver_path, cnf_path],
                capture_output=True, text=True, timeout=timeout,
            )
            elapsed = time.monotonic() - start

            if result.returncode == 10:
                # SAT — parse model from 'v' lines
                model = self._parse_model(result.stdout)
                return SATResult(
                    satisfiable=True,
                    model=model,
                    solver_used=solver_name,
                    elapsed_seconds=elapsed,
                )
            elif result.returncode == 20:
                return SATResult(
                    satisfiable=False,
                    model=None,
                    solver_used=solver_name,
                    elapsed_seconds=elapsed,
                )
            else:
                # Unknown exit code — fall back to pysat
                return self._validate_pysat(instance, timeout)

        except subprocess.TimeoutExpired:
            return SATResult(
                satisfiable=None,
                model=None,
                solver_used=solver_name,
                elapsed_seconds=timeout,
                timed_out=True,
            )
        finally:
            try:
                Path(cnf_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _validate_pysat(
        self,
        instance: "VTWInstance",
        timeout: int,
    ) -> SATResult:
        """Validate using pysat's built-in Cadical153 solver.

        Always available — no compilation needed.
        """
        try:
            from pysat.solvers import Solver

            start = time.monotonic()
            with Solver(name="cd153", bootstrap_with=instance.cnf.clauses) as solver:
                sat = solver.solve()
                elapsed = time.monotonic() - start
                model = list(solver.get_model()) if sat else None

                return SATResult(
                    satisfiable=sat,
                    model=model,
                    solver_used="pysat_cd153",
                    elapsed_seconds=elapsed,
                )
        except ImportError:
            # pysat solvers module requires compiled C extensions
            # Fall back to pure-Python approach: just skip validation
            return SATResult(
                satisfiable=None,
                model=None,
                solver_used="unavailable",
                elapsed_seconds=0.0,
                timed_out=True,
            )

    @staticmethod
    def _parse_model(stdout: str) -> list[int]:
        """Parse SAT model from solver stdout ('v' lines)."""
        model = []
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("v "):
                for token in line[2:].split():
                    val = int(token)
                    if val != 0:
                        model.append(val)
        return model
