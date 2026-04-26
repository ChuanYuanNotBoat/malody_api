import subprocess
import sys
from pathlib import Path


def test_utils_selector_import_from_parent_workspace():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", "import malody_api.utils.selector as s; print(s.MCSelector.__name__)"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "MCSelector" in result.stdout
