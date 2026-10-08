import csv
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = (
    ROOT / "artifacts" / "test_predictions_calibrated.csv"
)

groups = defaultdict(list)

with open(PREDICTIONS, newline="") as file:
    for row in csv.DictReader(file):
        groups[int(row["file_id"])].append(row)

print("Per-file test audit\n")

for file_id in sorted(groups):
    rows = groups[file_id]

    labels = [int(row["label"]) for row in rows]
    predictions = [int(row["prediction"]) for row in rows]
    probabilities = [
        float(row["prob_fault"])
        for row in rows
    ]

    correct = sum(
        label == prediction
        for label, prediction in zip(labels, predictions)
    )

    print(
        f"{file_id}.mat  "
        f"label={labels[0]}  "
        f"windows={len(rows)}  "
        f"correct={correct}/{len(rows)}  "
        f"prob[min/mean/max]="
        f"{min(probabilities):.4f}/"
        f"{np.mean(probabilities):.4f}/"
        f"{max(probabilities):.4f}"
    )
