import subprocess
from pathlib import Path


def test_golden_model_reference_vector():
    script = Path(__file__).with_name("golden_int8.py")

    result = subprocess.run(
        ["python3", str(script)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "score       : 5" in result.stdout
    assert "alarm       : 0" in result.stdout
    assert "MAC efektif : 161" in result.stdout
    assert "MAC dense   : 272" in result.stdout
