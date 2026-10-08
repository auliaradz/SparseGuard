from pathlib import Path

import numpy as np
from scipy.io import loadmat


FILE_IDS = [
    97, 98, 99, 100,       # normal
    105, 106, 107, 108,    # inner race 0.007
    118, 119, 120, 121,    # ball 0.007
    130, 131, 132, 133,    # outer race @6:00, 0.007
]

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

ok_count = 0

for file_id in FILE_IDS:
    file_path = RAW_DIR / f"{file_id}.mat"
    expected_key = f"X{file_id:03d}_DE_time"

    if not file_path.exists():
        print(f"ERROR: file tidak ditemukan: {file_path.name}")
        continue

    mat = loadmat(file_path)

    if expected_key not in mat:
        available = [
            key for key in mat
            if key.endswith("_DE_time")
        ]
        print(
            f"ERROR: {file_path.name} tidak punya key {expected_key}. "
            f"DE key tersedia: {available}"
        )
        continue

    signal = np.asarray(mat[expected_key]).reshape(-1)

    print(
        f"OK  {file_path.name:7} "
        f"key={expected_key:14} "
        f"samples={len(signal):7} "
        f"mean={signal.mean(): .5f} "
        f"std={signal.std(): .5f}"
    )
    ok_count += 1

print(f"\nValid: {ok_count}/{len(FILE_IDS)} file")
