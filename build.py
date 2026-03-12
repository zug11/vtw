"""Build system for external solvers.

Compiles twalgor, Jdrasil, CaDiCaL, and Kissat from source.
Detects what's already compiled and skips redundant builds.
"""

import os
import subprocess
import sys
from pathlib import Path

from vtw.config import (
    TWALGOR_PATH, JDRASIL_PATH, CADICAL_PATH, KISSAT_PATH,
    _detect_twalgor_classpath, _detect_jdrasil_jar,
    _detect_cadical_binary, _detect_kissat_binary,
)


def build_twalgor(force: bool = False) -> bool:
    """Compile twalgor Java exact treewidth solver.

    No build file exists — manual javac compilation.
    """
    if not force and _detect_twalgor_classpath():
        print("[twalgor] Already compiled, skipping.")
        return True

    src_dir = TWALGOR_PATH / "src"
    bin_dir = TWALGOR_PATH / "bin"

    if not src_dir.is_dir():
        print(f"[twalgor] Source not found at {src_dir}")
        return False

    bin_dir.mkdir(exist_ok=True)

    # Find all Java source files
    java_files = list(src_dir.rglob("*.java"))
    if not java_files:
        print("[twalgor] No .java files found")
        return False

    print(f"[twalgor] Compiling {len(java_files)} Java files...")
    try:
        result = subprocess.run(
            ["javac", "-d", str(bin_dir)] + [str(f) for f in java_files],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"[twalgor] Compilation failed:\n{result.stderr[:500]}")
            return False
        print("[twalgor] Compiled successfully.")
        return True
    except FileNotFoundError:
        print("[twalgor] javac not found. Install JDK.")
        return False
    except subprocess.TimeoutExpired:
        print("[twalgor] Compilation timed out.")
        return False


def build_jdrasil(force: bool = False) -> bool:
    """Compile Jdrasil tree decomposition library via Gradle."""
    if not force and _detect_jdrasil_jar():
        print("[jdrasil] Already compiled, skipping.")
        return True

    if not JDRASIL_PATH.is_dir():
        print(f"[jdrasil] Source not found at {JDRASIL_PATH}")
        return False

    gradlew = JDRASIL_PATH / "gradlew"
    if not gradlew.is_file():
        print("[jdrasil] gradlew not found")
        return False

    print("[jdrasil] Building with Gradle...")
    try:
        # Make gradlew executable
        os.chmod(str(gradlew), 0o755)
        result = subprocess.run(
            [str(gradlew), "assemble"],
            cwd=str(JDRASIL_PATH),
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"[jdrasil] Build failed:\n{result.stderr[:500]}")
            # Try manual javac as fallback
            return _build_jdrasil_manual()
        print("[jdrasil] Built successfully.")
        return True
    except FileNotFoundError:
        print("[jdrasil] Gradle not available, trying manual javac...")
        return _build_jdrasil_manual()
    except subprocess.TimeoutExpired:
        print("[jdrasil] Build timed out.")
        return False


def _build_jdrasil_manual() -> bool:
    """Fallback: compile Jdrasil with javac directly."""
    src_dir = JDRASIL_PATH / "subprojects" / "core" / "src" / "main" / "java"
    bin_dir = JDRASIL_PATH / "bin"

    if not src_dir.is_dir():
        print("[jdrasil] Source directory not found for manual compilation")
        return False

    bin_dir.mkdir(exist_ok=True)
    java_files = list(src_dir.rglob("*.java"))

    if not java_files:
        print("[jdrasil] No .java files found")
        return False

    print(f"[jdrasil] Manual compilation of {len(java_files)} files...")
    try:
        result = subprocess.run(
            ["javac", "-d", str(bin_dir)] + [str(f) for f in java_files],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"[jdrasil] Manual compilation failed:\n{result.stderr[:500]}")
            return False
        print("[jdrasil] Manual compilation succeeded.")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[jdrasil] Manual compilation error: {e}")
        return False


def build_cadical(force: bool = False) -> bool:
    """Compile CaDiCaL SAT solver."""
    if not force and _detect_cadical_binary():
        print("[cadical] Already compiled, skipping.")
        return True

    if not CADICAL_PATH.is_dir():
        print(f"[cadical] Source not found at {CADICAL_PATH}")
        return False

    print("[cadical] Configuring and building...")
    try:
        configure = subprocess.run(
            ["./configure"],
            cwd=str(CADICAL_PATH),
            capture_output=True, text=True, timeout=60,
        )
        if configure.returncode != 0:
            print(f"[cadical] Configure failed:\n{configure.stderr[:500]}")
            return False

        make = subprocess.run(
            ["make", "-j4"],
            cwd=str(CADICAL_PATH),
            capture_output=True, text=True, timeout=300,
        )
        if make.returncode != 0:
            print(f"[cadical] Make failed:\n{make.stderr[:500]}")
            return False

        print("[cadical] Built successfully.")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[cadical] Build error: {e}")
        return False


def build_kissat(force: bool = False) -> bool:
    """Compile Kissat SAT solver."""
    if not force and _detect_kissat_binary():
        print("[kissat] Already compiled, skipping.")
        return True

    if not KISSAT_PATH.is_dir():
        print(f"[kissat] Source not found at {KISSAT_PATH}")
        return False

    print("[kissat] Configuring and building...")
    try:
        configure = subprocess.run(
            ["./configure"],
            cwd=str(KISSAT_PATH),
            capture_output=True, text=True, timeout=60,
        )
        if configure.returncode != 0:
            print(f"[kissat] Configure failed:\n{configure.stderr[:500]}")
            return False

        make = subprocess.run(
            ["make", "-j4"],
            cwd=str(KISSAT_PATH),
            capture_output=True, text=True, timeout=300,
        )
        if make.returncode != 0:
            print(f"[kissat] Make failed:\n{make.stderr[:500]}")
            return False

        print("[kissat] Built successfully.")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[kissat] Build error: {e}")
        return False


def build_all(force: bool = False) -> dict[str, bool]:
    """Build all external solvers. Returns status dict."""
    results = {
        "twalgor": build_twalgor(force),
        "jdrasil": build_jdrasil(force),
        "cadical": build_cadical(force),
        "kissat": build_kissat(force),
    }
    print("\nBuild summary:")
    for name, ok in results.items():
        mark = "+" if ok else "FAILED"
        print(f"  [{mark}] {name}")
    return results


if __name__ == "__main__":
    force = "--force" in sys.argv
    build_all(force)
