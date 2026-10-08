import csv
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "cwru_features_16.npz"
ARTIFACTS_DIR = ROOT / "artifacts"

data = np.load(DATA_PATH, allow_pickle=True)

X = data["X"]
y = data["y"]
splits = data["split"]
file_ids = data["file_id"]

train_mask = splits == "train"
test_mask = splits == "test"

X_train = X[train_mask]
y_train = y[train_mask]
X_test = X[test_mask]
y_test = y[test_mask]
test_file_ids = file_ids[test_mask]

# Normalisasi hanya belajar dari data train.
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Seimbangkan train: semua normal + jumlah fault yang sama.
rng = np.random.default_rng(2026)

normal_idx = np.where(y_train == 0)[0]
fault_idx = np.where(y_train == 1)[0]

fault_selected = rng.choice(
    fault_idx,
    size=len(normal_idx),
    replace=False,
)

balanced_idx = np.concatenate([normal_idx, fault_selected])
rng.shuffle(balanced_idx)

X_train_balanced = X_train_scaled[balanced_idx]
y_train_balanced = y_train[balanced_idx]

# MLP float baseline: 16 input -> 16 hidden ReLU -> 1 output.
model = MLPClassifier(
    hidden_layer_sizes=(16,),
    activation="relu",
    solver="adam",
    alpha=1e-3,
    learning_rate_init=1e-3,
    batch_size=64,
    max_iter=500,
    early_stopping=True,
    validation_fraction=0.20,
    n_iter_no_change=30,
    random_state=2026,
)

model.fit(X_train_balanced, y_train_balanced)

prob_fault = model.predict_proba(X_test_scaled)[:, 1]
pred = (prob_fault >= 0.50).astype(np.int64)

tn, fp, fn, tp = confusion_matrix(y_test, pred, labels=[0, 1]).ravel()

metrics = {
    "train_windows_original": int(len(y_train)),
    "train_windows_balanced": int(len(y_train_balanced)),
    "test_windows": int(len(y_test)),
    "accuracy": float(accuracy_score(y_test, pred)),
    "precision": float(precision_score(y_test, pred, zero_division=0)),
    "recall": float(recall_score(y_test, pred, zero_division=0)),
    "f1": float(f1_score(y_test, pred, zero_division=0)),
    "specificity": float(tn / (tn + fp)) if (tn + fp) else 0.0,
    "roc_auc": float(roc_auc_score(y_test, prob_fault)),
    "confusion_matrix": {
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    },
}

ARTIFACTS_DIR.mkdir(exist_ok=True)

joblib.dump(model, ARTIFACTS_DIR / "cwru_mlp_float.joblib")

np.savez(
    ARTIFACTS_DIR / "feature_scaler_float.npz",
    mean=scaler.mean_,
    scale=scaler.scale_,
)

with open(ARTIFACTS_DIR / "metrics_float.json", "w") as file:
    json.dump(metrics, file, indent=2)

with open(
    ARTIFACTS_DIR / "test_predictions_float.csv",
    "w",
    newline="",
) as file:
    writer = csv.writer(file)
    writer.writerow(["file_id", "label", "prob_fault", "prediction"])

    for file_id, label, probability, prediction in zip(
        test_file_ids, y_test, prob_fault, pred
    ):
        writer.writerow([
            int(file_id),
            int(label),
            float(probability),
            int(prediction),
        ])

print("\nFloat MLP selesai")
print(f"Train awal     : {len(y_train)} window")
print(f"Train balanced : {len(y_train_balanced)} window")
print(f"Test           : {len(y_test)} window")

for name, value in metrics.items():
    print(f"{name}: {value}")
