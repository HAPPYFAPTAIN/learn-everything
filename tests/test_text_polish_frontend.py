import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for frontend behavior tests")
def test_polish_lifecycle_preserves_inputs_and_rejects_stale_responses():
    completed = subprocess.run(
        [NODE, str(ROOT / "tests" / "text_polish_frontend.cjs")],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "bridgeDelay": True,
        "explicitAdoption": True,
        "attachmentIdentity": True,
        "safeUndo": True,
        "staleEdit": True,
        "navigation": True,
        "timeout": True,
        "singleFlight": True,
        "detachedCleanup": True,
        "dynamicKind": True,
        "plainTextPreview": True,
        "sensitiveInputsExcluded": True,
    }
