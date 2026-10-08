import csv
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import confusion_matrix, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "cwru_features_16.npz"
ARTIFACTS_DIR = ROOT / "artifacts"

RANDOM_SEED = 2026
TRAIN_FRACTION = 0.70
CALIBRATION_START = 0.80


def calculate_metrics(y_true, probabilities, threshold):
    prediction = (probabilities >= threshold).astype(np.int64)

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
        "threshold": float(threshold),
        "accuracy": float((tp + tn) / len(y_true)),
        "precision": float(precision),
        "recall": float(recall),
        "specificity": float(specificity),
        "balanced_accuracy": float((recall + specificity) / 2),
        "f1": float(f1),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
    }


def balance_indices(indices, labels, rng):
    normal_idx = indices[labels[indices] == 0]
    fault_idx = indices[labels[indices] == 1]

    count = min(len(normal_idx), len(fault_idx))

    selected_normal = rng.choice(normal_idx, size=count, replace=False)
    selected_fault = rng.choice(fault_idx, size=count, replace=False)

    balanced = np.concatenate([selected_normal, selected_fault])
    rng.shuffle(balanced)
    return balanced


def write_predictions(path, file_ids, labels, probabilities, threshold):
    predictions = (probabilities >= threshold).astype(np.int64)

    with open(path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["file_id", "label", "prob_fault", "prediction"])

        for file_id, label, probability, prediction in zip(
            file_ids,
            labels,
            probabilities,
            predictions,
        ):
            writer.writerow([
                int(file_id),
                int(label),
                float(probability),
                int(prediction),
            ])


data = np.load(DATA_PATH, allow_pickle=True)

X = data["X"]
y = data["y"]
splits = data["split"]
file_ids = data["file_id"]

train_pool_idx = np.where(splits == "train")[0]
test_idx = np.where(splits == "test")[0]

# Pisahkan setiap file training secara berurutan:
# 0-70% = model train, 70-80% = gap, 80-100% = calibration.
model_train_idx = []
calibration_idx = []

for file_id in np.unique(file_ids[train_pool_idx]):
    file_idx = train_pool_idx[file_ids[train_pool_idx] == file_id]

    train_end = int(len(file_idx) * TRAIN_FRACTION)
    calibration_start = int(len(file_idx) * CALIBRATION_START)

    model_train_idx.extend(file_idx[:train_end])
    calibration_idx.extend(file_idx[calibration_start:])

model_train_idx = np.asarray(model_train_idx, dtype=np.int64)
calibration_idx = np.asarray(calibration_idx, dtype=np.int64)

rng = np.random.default_rng(RANDOM_SEED)

# Scale hanya dari bagian yang benar-benar dipakai melatih model.
scaler = StandardScaler()
X_model_train = scaler.fit_transform(X[model_train_idx])
X_calibration = scaler.transform(X[calibration_idx])
X_test = scaler.transform(X[test_idx])

# Balance hanya data training model, bukan calibration/test.
balanced_relative_idx = balance_indices(
    np.arange(len(model_train_idx)),
    y[model_train_idx],
    rng,
)

X_model_train_balanced = X_model_train[balanced_relative_idx]
y_model_train_balanced = y[model_train_idx][balanced_relative_idx]

model = MLPClassifier(
    hidden_layer_sizes=(16,),
    activation="relu",
    solver="adam",
    alpha=1e-3,
    learning_rate_init=1e-3,
    batch_size=64,
    max_iter=500,
    random_state=RANDOM_SEED,
)

model.fit(X_model_train_balanced, y_model_train_balanced)

calibration_prob = model.predict_proba(X_calibration)[:, 1]
test_prob = model.predict_proba(X_test)[:, 1]

# Cari threshold terbaik berdasarkan balanced accuracy.
# Cocok karena kelas normal dan fault tidak seimbang.
threshold_rows = []

for threshold in np.linspace(0.01, 0.99, 99):
    row = calculate_metrics(
        y[calibration_idx],
        calibration_prob,
        threshold,
    )
    threshold_rows.append(row)

best = max(
    threshold_rows,
    key=lambda row: (
        row["balanced_accuracy"],
        row["f1"],
        -abs(row["threshold"] - 0.50),
    ),
)

frozen_threshold = best["threshold"]

calibration_metrics = calculate_metrics(
    y[calibration_idx],
    calibration_prob,
    frozen_threshold,
)

test_metrics = calculate_metrics(
    y[test_idx],
    test_prob,
    frozen_threshold,
)

ARTIFACTS_DIR.mkdir(exist_ok=True)

joblib.dump(
    model,
    ARTIFACTS_DIR / "cwru_mlp_calibrated.joblib",
)

np.savez(
    ARTIFACTS_DIR / "feature_scaler_calibrated.npz",
    mean=scaler.mean_,
    scale=scaler.scale_,
)

with open(
    ARTIFACTS_DIR / "threshold_calibrated.json",
    "w",
) as file:
    json.dump(
        {
            "threshold": frozen_threshold,
            "objective": "balanced_accuracy",
            "calibration_rule": (
                "last 20 percent of each 0-1 HP training file; "
                "middle 10 percent excluded as temporal gap"
            ),
        },
        file,
        indent=2,
    )

with open(
    ARTIFACTS_DIR / "metrics_calibrated.json",
    "w",
) as file:
    json.dump(
        {
            "model_train_windows_balanced": int(
                len(y_model_train_balanced)
            ),
            "calibration_windows": int(len(calibration_idx)),
            "test_windows": int(len(test_idx)),
            "calibration_metrics": calibration_metrics,
            "test_metrics": test_metrics,
        },
        file,
        indent=2,
    )

with open(
    ARTIFACTS_DIR / "threshold_search_calibration.csv",
    "w",
    newline="",
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=[
            "threshold",
            "accuracy",
            "precision",
            "recall",
            "specificity",
            "balanced_accuracy",
            "f1",
            "roc_auc",
        ],
    )
    writer.writeheader()

    for row in threshold_rows:
        writer.writerow({
            key: row[key]
            for key in writer.fieldnames
        })

write_predictions(
    ARTIFACTS_DIR / "test_predictions_calibrated.csv",
    file_ids[test_idx],
    y[test_idx],
    test_prob,
    frozen_threshold,
)

print("\nThreshold calibration selesai")
print(f"Model train balanced : {len(y_model_train_balanced)}")
print(f"Calibration windows  : {len(calibration_idx)}")
print(f"Test windows         : {len(test_idx)}")
print(f"\nFrozen threshold    : {frozen_threshold:.2f}")
print("\nCalibration metrics:")
print(json.dumps(calibration_metrics, indent=2))
print("\nTest metrics:")
print(json.dumps(test_metrics, indent=2))
