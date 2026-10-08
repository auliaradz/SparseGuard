from pathlib import Path

import numpy as np
from scipy.io import loadmat
from scipy.signal import resample_poly


RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

WINDOW_SIZE = 2048
HOP_SIZE = 1024

FEATURE_NAMES = [
    "mean",
    "std",
    "rms",
    "abs_mean",
    "minimum",
    "maximum",
    "peak_to_peak",
    "variance",
    "skewness",
    "kurtosis",
    "crest_factor",
    "shape_factor",
    "impulse_factor",
    "clearance_factor",
    "mean_square",
    "zero_crossing_rate",
]


def add_records(records, ids, label, split, sample_rate):
    for file_id in ids:
        records.append(
            {
                "id": file_id,
                "label": label,
                "split": split,
                "sample_rate": sample_rate,
            }
        )


def extract_features(window):
    eps = 1e-12
    mean = float(np.mean(window))
    std = float(np.std(window))
    rms = float(np.sqrt(np.mean(window ** 2)))
    abs_mean = float(np.mean(np.abs(window)))
    minimum = float(np.min(window))
    maximum = float(np.max(window))
    peak_to_peak = maximum - minimum
    variance = float(np.var(window))

    normalized = (window - mean) / (std + eps)
    skewness = float(np.mean(normalized ** 3))
    kurtosis = float(np.mean(normalized ** 4))

    peak = float(np.max(np.abs(window)))
    crest_factor = peak / (rms + eps)
    shape_factor = rms / (abs_mean + eps)
    impulse_factor = peak / (abs_mean + eps)
    clearance_factor = peak / (np.mean(np.sqrt(np.abs(window))) ** 2 + eps)
    mean_square = float(np.mean(window ** 2))
    zero_crossing_rate = float(
        np.mean(window[:-1] * window[1:] < 0)
    )

    return [
        mean,
        std,
        rms,
        abs_mean,
        minimum,
        maximum,
        peak_to_peak,
        variance,
        skewness,
        kurtosis,
        crest_factor,
        shape_factor,
        impulse_factor,
        clearance_factor,
        mean_square,
        zero_crossing_rate,
    ]


records = []

# Normal = 0; baseline 48 kHz akan diturunkan menjadi 12 kHz.
add_records(records, [97, 98], 0, "train", 48000)
add_records(records, [99, 100], 0, "test", 48000)

# Fault = 1; seluruh file berikut adalah 12 kHz.
add_records(records, [105, 106], 1, "train", 12000)  # inner race
add_records(records, [118, 119], 1, "train", 12000)  # ball
add_records(records, [130, 131], 1, "train", 12000)  # outer race @6

add_records(records, [107, 108], 1, "test", 12000)
add_records(records, [120, 121], 1, "test", 12000)
add_records(records, [132, 133], 1, "test", 12000)

all_features = []
all_labels = []
all_splits = []
all_file_ids = []

for record in records:
    file_id = record["id"]
    mat_path = RAW_DIR / f"{file_id}.mat"
    key = f"X{file_id:03d}_DE_time"

    mat = loadmat(mat_path)
    signal = np.asarray(mat[key], dtype=np.float64).reshape(-1)

    # Normal baseline: 48 kHz -> 12 kHz.
    if record["sample_rate"] == 48000:
        signal = resample_poly(signal, up=1, down=4)

    window_count = 0

    for start in range(0, len(signal) - WINDOW_SIZE + 1, HOP_SIZE):
        window = signal[start:start + WINDOW_SIZE]
        all_features.append(extract_features(window))
        all_labels.append(record["label"])
        all_splits.append(record["split"])
        all_file_ids.append(file_id)
        window_count += 1

    print(
        f"{file_id}.mat  split={record['split']:5} "
        f"label={record['label']}  windows={window_count}"
    )

OUT_DIR.mkdir(parents=True, exist_ok=True)

X = np.asarray(all_features, dtype=np.float32)
y = np.asarray(all_labels, dtype=np.int64)
splits = np.asarray(all_splits)
file_ids = np.asarray(all_file_ids, dtype=np.int64)

out_path = OUT_DIR / "cwru_features_16.npz"

np.savez_compressed(
    out_path,
    X=X,
    y=y,
    split=splits,
    file_id=file_ids,
    feature_names=np.asarray(FEATURE_NAMES),
)

print("\nSaved:", out_path)
print("X shape:", X.shape)
print("Train windows:", int(np.sum(splits == "train")))
print("Test windows :", int(np.sum(splits == "test")))
print("Feature count:", X.shape[1])
