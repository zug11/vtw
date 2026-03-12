"""SQLite experiment database for VTW measurements.

Replaces scattered CSVs with a queryable, reproducible experiment store.
All data flows through VTWExperiment into this unified schema.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class ExperimentDB:
    """SQLite-backed experiment storage."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                config_json TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER REFERENCES experiments(id),
                n_vars INTEGER NOT NULL,
                n_clauses INTEGER,
                clause_density REAL,
                instance_family TEXT,
                sample_idx INTEGER,
                is_satisfiable INTEGER,
                treewidth INTEGER,
                tw_confidence TEXT,
                tw_lower_bound INTEGER,
                tw_upper_bound INTEGER,
                tw_over_n REAL,
                cheeger_constant REAL,
                graph_density REAL,
                avg_degree REAL,
                solver_time_sat REAL,
                solver_time_tw REAL,
                dimacs_hash TEXT,
                strategy_applied TEXT,
                tw_reduction_ratio REAL,
                extra_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_results_n_vars ON results(n_vars);
            CREATE INDEX IF NOT EXISTS idx_results_family ON results(instance_family);
            CREATE INDEX IF NOT EXISTS idx_results_experiment ON results(experiment_id);
        """)
        self.conn.commit()

    def create_experiment(self, config_dict: dict) -> tuple[int, str]:
        """Create a new experiment run. Returns (experiment_id, run_id)."""
        run_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()
        cursor = self.conn.execute(
            "INSERT INTO experiments (run_id, created_at, config_json) VALUES (?, ?, ?)",
            (run_id, now, json.dumps(config_dict)),
        )
        self.conn.commit()
        return cursor.lastrowid, run_id

    def insert_result(
        self,
        experiment_id: int,
        n_vars: int,
        n_clauses: int,
        clause_density: float,
        instance_family: str,
        sample_idx: int,
        is_satisfiable: Optional[bool],
        treewidth: int,
        tw_confidence: str,
        tw_lower_bound: Optional[int],
        tw_upper_bound: int,
        tw_over_n: float,
        cheeger_constant: float,
        graph_density: float,
        avg_degree: float,
        solver_time_sat: float,
        solver_time_tw: float,
        dimacs_hash: str,
        strategy_applied: Optional[str] = None,
        tw_reduction_ratio: Optional[float] = None,
        extra: Optional[dict] = None,
    ):
        """Insert a single measurement result."""
        now = datetime.utcnow().isoformat()
        sat_int = None if is_satisfiable is None else int(is_satisfiable)
        self.conn.execute(
            """INSERT INTO results (
                experiment_id, n_vars, n_clauses, clause_density,
                instance_family, sample_idx, is_satisfiable,
                treewidth, tw_confidence, tw_lower_bound, tw_upper_bound,
                tw_over_n, cheeger_constant, graph_density, avg_degree,
                solver_time_sat, solver_time_tw, dimacs_hash,
                strategy_applied, tw_reduction_ratio, extra_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment_id, n_vars, n_clauses, clause_density,
                instance_family, sample_idx, sat_int,
                treewidth, tw_confidence, tw_lower_bound, tw_upper_bound,
                tw_over_n, cheeger_constant, graph_density, avg_degree,
                solver_time_sat, solver_time_tw, dimacs_hash,
                strategy_applied, tw_reduction_ratio,
                json.dumps(extra) if extra else None, now,
            ),
        )
        self.conn.commit()

    def query_tw_by_n(self, family: Optional[str] = None) -> list[dict]:
        """Get average treewidth grouped by n_vars."""
        if family:
            rows = self.conn.execute(
                """SELECT n_vars, AVG(treewidth) as avg_tw, AVG(tw_over_n) as avg_ratio,
                   COUNT(*) as samples, MIN(treewidth) as min_tw, MAX(treewidth) as max_tw
                   FROM results WHERE instance_family = ?
                   GROUP BY n_vars ORDER BY n_vars""",
                (family,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT n_vars, AVG(treewidth) as avg_tw, AVG(tw_over_n) as avg_ratio,
                   COUNT(*) as samples, MIN(treewidth) as min_tw, MAX(treewidth) as max_tw
                   FROM results GROUP BY n_vars ORDER BY n_vars""",
            ).fetchall()
        return [dict(r) for r in rows]

    def query_optimization_results(self) -> list[dict]:
        """Get optimization results (before/after comparisons)."""
        rows = self.conn.execute(
            """SELECT n_vars, instance_family, strategy_applied,
                      treewidth, tw_reduction_ratio, cheeger_constant
               FROM results WHERE strategy_applied IS NOT NULL
               ORDER BY n_vars, strategy_applied""",
        ).fetchall()
        return [dict(r) for r in rows]

    def export_csv(self, path: str, experiment_id: Optional[int] = None):
        """Export results to CSV."""
        import csv
        if experiment_id:
            rows = self.conn.execute(
                "SELECT * FROM results WHERE experiment_id = ? ORDER BY n_vars, sample_idx",
                (experiment_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM results ORDER BY n_vars, sample_idx",
            ).fetchall()

        if not rows:
            return

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(tuple(row))

    def close(self):
        self.conn.close()
