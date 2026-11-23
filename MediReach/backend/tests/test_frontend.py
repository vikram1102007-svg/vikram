import shutil
import subprocess
from pathlib import Path

import pytest


def test_frontend_node_suite():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed; frontend tests run in GitHub Actions.")
    test_file = Path(__file__).resolve().parents[2] / "tests" / "frontend.test.cjs"
    assert test_file.is_file(), "MediReach frontend test suite is missing"
    result = subprocess.run(
        [node, "--test", str(test_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

