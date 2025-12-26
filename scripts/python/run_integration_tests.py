#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

def main() -> None:
    """Runs all integration tests under tests/integration/."""
    root = Path(__file__).resolve().parents[1]
    test_dir = root / "tests" / "integration"
    if not test_dir.exists():
        print(f"No integration tests directory at {test_dir}")
        sys.exit(0)

    # Ensure PYTHONPATH includes the agents package
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(root))

    print(f"Running integration tests in {test_dir}...")
    result = subprocess.run([sys.executable, "-m", "pytest", str(test_dir)], env=env)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
