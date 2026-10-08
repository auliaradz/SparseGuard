import csv
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import confusion_matrix, roc_auc_score


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "cwru_features_16.npz"
MODEL_PATH = ROOT / "artifacts" / "cwru_mlp_calibrated.joblib"
SCALER_PATH = ROOT / "artifacts" / "feature_scaler_calibrated.npz"
ARTIFACTS_DIR = ROOT / "artifacts"

TRAIN_FRACTION = 0.70
CALIBRATION_START = 0.80

# Kandidat sparsity W1: 0% sampai 90% bobot W1 dibuat nol.
CANDIDATES = [0.00, 0.25, 0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90]


def sigmoid(values):
    values = np.clip(values, -30, 30)
    return 1.0 / (1.0 + np.exp(-values))


def forward_probability(X, w1, b1, w2, b2):
    hidden = np.maximum(0.0, X @ w1 + b1)
    logits = hidden @ w2 + b2
    return sigmoid(logits.reshape(-1))


def calculate_metrics(y_true, probability, threshold=0.50):
    prediction = (probability >= threshold).astype(np.int64)

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        prediction,
        labels=[0, 1],
    ).ravel()

    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    return {
        "accuracy": float((tn + tp) / len(y_true)),
        "precision": float(precision),
        "recall": float(recall),
        "specificity": float(specificity),
        "balanced_accuracy": float((recall + specificity) / 2),
        "f1": float(f1),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def prune_w1_by_magnitude(w1, ratio):
    result = w1.copy()
    count = int(round(ratio * result.size))

    if count == 0:
        return result

    smallest = np.argsort(
        np.abs(result).reshape(-1),
        kind="stable",
    )[:count]

    result.reshape(-1)[smallest] = 0.0
    return result


data = np.load(DATA_PATH, allow_pickle=True)

X = data["X"]
y = data["y"]
splits = data["split"]
file_ids = data["file_id"]

train_pool_idx = np.where(splits == "train")[0]
test_idx = np.where(splits == "test")[0]

# Ambil bagian akhir setiap file train sebagai calibration set.
calibration_idx = []

for file_id in np.unique(file_ids[train_pool_idx]):
    file_idx = train_pool_idx[file_ids[train_pool_idx] == file_id]
    start = int(len(file_idx) * CALIBRATION_START)
    calibration_idx.extend(file_idx[start:])

calibration_idx = np.asarray(calibration_idx, dtype=np.int64)

model = joblib.load(MODEL_PATH)
scaler_data = np.load(SCALER_PATH)

mean = scaler_data["mean"]
scale = scaler_data["scale"]

X_calibration = (X[calibration_idx] - mean) / scale
X_test = (X[test_idx] - mean) / scale

w1 = model.coefs_[0]
b1 = model.intercepts_[0]
w2 = model.coefs_[1]
b2 = model.intercepts_[1]

base_calibration_prob = forward_probability(
    X_calibration,
    w1,
    b1,
    w2,
    b2,
)

baseline = calculate_metrics(
    y[calibration_idx],
    base_calibration_prob,
)

rows = []

for ratio in CANDIDATES:
    pruned_w1 = prune_w1_by_magnitude(w1, ratio)

    calibration_prob = forward_probability(
        X_calibration,
        pruned_w1,
        b1,
        w2,
        b2,
    )

    metrics = calculate_metrics(
        y[calibration_idx],
        calibration_prob,
    )

    nonzero_w1 = int(np.count_nonzero(pruned_w1))

    rows.append({
        "pruning_ratio": ratio,
        "nonzero_w1": nonzero_w1,
        "mac_effective": nonzero_w1 + 16,
        **metrics,
    })

# Pilih sparsity tertinggi yang kehilangan maksimal:
# 1% balanced accuracy dan 2% recall pada calibration set.
eligible = [
    row for row in rows
    if row["balanced_accuracy"]
    >= baseline["balanced_accuracy"] - 0.01
    and row["recall"]
    >= baseline["recall"] - 0.02
]

selected = max(
    eligible,
    key=lambda row: row["pruning_ratio"],
)

selected_w1 = prune_w1_by_magnitude(
    w1,
    selected["pruning_ratio"],
)

# Test dievaluasi satu kali setelah pruning dipilih dari calibration.
test_probability = forward_probability(
    X_test,
    selected_w1,
    b1,
    w2,
    b2,
)

test_metrics = calculate_metrics(
    y[test_idx],
    test_probability,
)

ARTIFACTS_DIR.mkdir(exist_ok=True)

np.savez(
    ARTIFACTS_DIR / "cwru_mlp_pruned_float.npz",
    w1=selected_w1,
    b1=b1,
    w2=w2,
    b2=b2,
    pruning_ratio=selected["pruning_ratio"],
    nonzero_w1=selected["nonzero_w1"],
    threshold_probability=0.50,
)

with open(
    ARTIFACTS_DIR / "pruning_candidates_calibration.csv",
    "w",
    newline="",
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=list(rows[0].keys()),
    )
    writer.writeheader()
    writer.writerows(rows)

with open(
    ARTIFACTS_DIR / "pruning_selection.json",
    "w",
) as file:
    json.dump(
        {
            "selection_rule": (
                "maksimum sparsity dengan penurunan balanced accuracy "
                "maksimal 0.01 dan recall maksimal 0.02 pada calibration"
            ),
            "baseline_calibration": baseline,
            "selected": selected,
            "test_metrics_after_selection": test_metrics,
        },
        file,
        indent=2,
    )

print("\nPruning selection selesai")
print("\nBaseline calibration:")
print(json.dumps(baseline, indent=2))
print("\nSelected pruning:")
print(json.dumps(selected, indent=2))
print("\nTest metrics setelah pruning:")
print(json.dumps(test_metrics, indent=2))
