#!/usr/bin/env python3
"""
Kuantisasi INT8 SparseGuard (MLP 16 -> 16 -> 1) + ekspor blob.

Letakkan di  ~/projects/SparseGuard/model/quantize_int8.py  lalu jalankan:
    python model/quantize_int8.py

Masukan (sama dengan select_pruning.py):
    data/processed/cwru_features_16.npz        kunci: X, y, split, file_id
    artifacts/feature_scaler_calibrated.npz    kunci: mean, scale
    artifacts/cwru_mlp_pruned_float.npz        kunci: w1, b1, w2, b2

Keluaran di artifacts/:
    model_blob.bin           blob model (352 byte)
    model_blob.sha256        digest SHA-256 (hex)
    quant_meta.json          layout blob, skala, pengali, parameter host
    quant_results.json       metrik float vs INT8, MAC, siklus
    int8_test_vectors.csv    vektor uji untuk cocotb (input INT8, skor, alarm)

Aritmetika (ini yang harus ditiru RTL bit-exact):
    Xq   = clip(round(X_std / sx), -127, 127)             int8
    acc1 = Xq @ W1q + b1q                                  int32
    h    = max(acc1, 0)
    hq   = clip((h * M + 2^(shift-1)) >> shift, 0, 127)    int8, M 16-bit, h*M muat 64-bit
    acc2 = hq @ W2q + b2q                                  int32
    alarm = (acc2 >= thr)                                  thr = 0 setara probabilitas 0,5
Layer 2 tidak direquantisasi: keputusan langsung dari akumulator.
"""
import csv
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "cwru_features_16.npz"
SCALER_PATH = ROOT / "artifacts" / "feature_scaler_calibrated.npz"
PRUNED_PATH = ROOT / "artifacts" / "cwru_mlp_pruned_float.npz"
OUT = ROOT / "artifacts"

N_IN, N_HID, LANES = 16, 16, 4
CALIBRATION_START = 0.80          # sama dengan select_pruning.py
PCT_CANDIDATES = [100.0, 99.9, 99.5]   # persentil untuk skala input/aktivasi
THRESHOLD_Q = 0                   # logit >= 0  <=>  probabilitas >= 0,5
N_TEST_VECTORS = 64


# ---------- metrik (tanpa sklearn) ----------
def auc(y, s):
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    allv = np.concatenate([pos, neg])
    order = allv.argsort()
    sv = allv[order]
    _, inv, counts = np.unique(sv, return_inverse=True, return_counts=True)
    avg = np.cumsum(counts) - (counts - 1) / 2
    ranks = np.empty(len(allv))
    ranks[order] = avg[inv]
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def metrics(y, pred, score):
    tp = int(((pred == 1) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    rec = tp / (tp + fn) if tp + fn else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    prec = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return dict(accuracy=(tp + tn) / len(y), recall=rec, specificity=spec,
                precision=prec, f1=f1, balanced_accuracy=(rec + spec) / 2,
                roc_auc=auc(y, score), tn=tn, fp=fp, fn=fn, tp=tp)


# ---------- model float dan INT ----------
def float_logits(X, w1, b1, w2, b2):
    return (np.maximum(0.0, X @ w1 + b1) @ w2 + b2).reshape(-1)


def quantize_input(Xstd, sx):
    return np.clip(np.round(Xstd / sx), -127, 127).astype(np.int8)


def fixed_point(ratio):
    """ratio ~= M / 2^shift dengan M 16-bit (2^15 <= M < 2^16)."""
    shift = 15 - int(np.floor(np.log2(ratio)))
    M = int(round(ratio * 2 ** shift))
    if M >= 2 ** 16:
        M >>= 1
        shift -= 1
    assert 0 < shift <= 31, f"shift di luar jangkauan: {shift}"
    return M, shift


def int_infer(Xq, p):
    acc1 = np.maximum(0, Xq.astype(np.int64) @ p["W1q"].astype(np.int64) + p["b1q"].astype(np.int64))
    hq = np.clip((acc1 * p["M"] + (1 << (p["shift"] - 1))) >> p["shift"], 0, 127)
    acc2 = (hq @ p["W2q"].astype(np.int64)).reshape(-1) + int(p["b2q"])
    return acc2, (acc2 >= p["thr"]).astype(np.int64)


def build_quant(w1, b1, w2, b2, Xref, pct):
    sx = float(np.percentile(np.abs(Xref), pct)) / 127
    sw1 = float(np.abs(w1).max()) / 127
    sw2 = float(np.abs(w2).max()) / 127
    W1q = np.clip(np.round(w1 / sw1), -127, 127).astype(np.int8)
    W2q = np.clip(np.round(w2 / sw2), -127, 127).astype(np.int8).reshape(-1)
    b1q = np.round(b1 / (sx * sw1)).astype(np.int64)
    Xq = quantize_input(Xref, sx)
    acc1 = np.maximum(0, Xq.astype(np.int64) @ W1q.astype(np.int64) + b1q)
    hmax = max(float(np.percentile(acc1, pct)), 1.0)
    M, shift = fixed_point(127.0 / hmax)
    sh = sx * sw1 / (M / 2 ** shift)          # skala efektif aktivasi hidden INT8
    b2q = int(np.round(b2[0] / (sh * sw2)))
    for name, arr in (("b1q", b1q), ("b2q", np.array([b2q]))):
        assert np.abs(arr).max() < 2 ** 31, f"{name} tidak muat int32"
    return dict(sx=sx, sw1=sw1, sw2=sw2, sh=sh, W1q=W1q, W2q=W2q, b1q=b1q,
                b2q=b2q, M=M, shift=shift, thr=THRESHOLD_Q, pct=pct)


# ---------- blob ----------
LAYOUT = [("W1", 0, 256), ("b1", 256, 64), ("W2", 320, 16), ("b2", 336, 4),
          ("M", 340, 4), ("shift", 344, 4), ("thr", 348, 4)]
BLOB_SIZE = 352


def pack_blob(p):
    blob = bytearray()
    blob += p["W1q"].T.astype(np.int8).tobytes()               # hidden-major [hidden j][masuk i]
    blob += p["b1q"].astype("<i4").tobytes()
    blob += p["W2q"].astype(np.int8).tobytes()
    blob += struct.pack("<i", int(p["b2q"]))
    blob += struct.pack("<i", int(p["M"]))
    blob += struct.pack("<i", int(p["shift"]))
    blob += struct.pack("<i", int(p["thr"]))
    assert len(blob) == BLOB_SIZE, f"ukuran blob {len(blob)} != {BLOB_SIZE}"
    return bytes(blob)


def parse_blob(blob):
    assert len(blob) == BLOB_SIZE
    return dict(
        W1q=np.frombuffer(blob[0:256], dtype=np.int8).reshape(N_HID, N_IN).T,
        b1q=np.frombuffer(blob[256:320], dtype="<i4").astype(np.int64),
        W2q=np.frombuffer(blob[320:336], dtype=np.int8),
        b2q=struct.unpack("<i", blob[336:340])[0],
        M=struct.unpack("<i", blob[340:344])[0],
        shift=struct.unpack("<i", blob[344:348])[0],
        thr=struct.unpack("<i", blob[348:352])[0],
    )


def mac_and_cycles(W1q):
    nnz_neuron = np.count_nonzero(W1q, axis=0)     # hidden j = kolom j
    total = int(nnz_neuron.sum())
    ceil = lambda a, b: -(-int(a) // b)
    l2 = ceil(N_HID, LANES)
    return dict(
        nnz_w1=total, mac_effective=total + N_HID, mac_dense=N_IN * N_HID + N_HID,
        nnz_per_neuron=[int(v) for v in nnz_neuron],
        cycles_dense=ceil(N_IN * N_HID, LANES) + l2,
        cycles_ideal_packing=ceil(total, LANES) + l2,
        cycles_per_neuron=int(sum(ceil(v, LANES) for v in nnz_neuron)) + l2,
    )


def main():
    data = np.load(DATA_PATH, allow_pickle=True)
    X, y, split, file_id = data["X"], data["y"].astype(np.int64), data["split"], data["file_id"]
    sc = np.load(SCALER_PATH)
    mean, scale = sc["mean"], sc["scale"]
    m = np.load(PRUNED_PATH, allow_pickle=True)
    w1, b1, w2, b2 = m["w1"], m["b1"], m["w2"], m["b2"]
    assert w1.shape == (N_IN, N_HID) and w2.shape == (N_HID, 1), "bentuk bobot tidak sesuai"

    train_pool = np.where(split == "train")[0]
    test_idx = np.where(split == "test")[0]
    cal = []
    for fid in np.unique(file_id[train_pool]):
        idx = train_pool[file_id[train_pool] == fid]
        cal.extend(idx[int(len(idx) * CALIBRATION_START):])
    cal_idx = np.asarray(cal, dtype=np.int64)

    std = lambda idx: (X[idx] - mean) / scale
    Xref, Xcal, Xtest = std(train_pool), std(cal_idx), std(test_idx)
    ycal, ytest = y[cal_idx], y[test_idx]

    # float setelah pruning (acuan)
    fl_cal, fl_test = float_logits(Xcal, w1, b1, w2, b2), float_logits(Xtest, w1, b1, w2, b2)
    float_res = dict(calibration=metrics(ycal, (fl_cal >= 0).astype(int), fl_cal),
                     test=metrics(ytest, (fl_test >= 0).astype(int), fl_test))

    # pilih persentil kalibrasi HANYA dari data kalibrasi
    best = None
    sweep = []
    for pct in PCT_CANDIDATES:
        p = build_quant(w1, b1, w2, b2, Xref, pct)
        s, pred = int_infer(quantize_input(Xcal, p["sx"]), p)
        mt = metrics(ycal, pred, s)
        sweep.append(dict(pct=pct, balanced_accuracy=mt["balanced_accuracy"], recall=mt["recall"],
                          fn=mt["fn"], fp=mt["fp"]))
        key = (mt["balanced_accuracy"], pct)
        if best is None or key > best[0]:
            best = (key, p)
    p = best[1]

    # blob adalah sumber kebenaran: jalankan inferensi dari blob hasil parse
    blob = pack_blob(p)
    pb = parse_blob(blob)
    s_direct, _ = int_infer(quantize_input(Xtest, p["sx"]), p)
    s_blob, pred_blob = int_infer(quantize_input(Xtest, p["sx"]), pb)
    assert np.array_equal(s_direct, s_blob), "parse blob tidak konsisten"

    s_cal, pred_cal = int_infer(quantize_input(Xcal, p["sx"]), pb)
    int_res = dict(calibration=metrics(ycal, pred_cal, s_cal), test=metrics(ytest, pred_blob, s_blob))
    agree = float(np.mean(pred_blob == (fl_test >= 0).astype(int)))

    cyc = mac_and_cycles(pb["W1q"])
    digest = hashlib.sha256(b"SPARSEGUARD_SEC!" + blob).hexdigest()

    OUT.mkdir(exist_ok=True)
    (OUT / "model_blob.bin").write_bytes(blob)
    (OUT / "model_blob.sha256").write_text(digest + "\n")

    sel = np.unique(np.linspace(0, len(test_idx) - 1, N_TEST_VECTORS).astype(int))
    Xq_t = quantize_input(Xtest[sel], p["sx"])
    s_t, a_t = int_infer(Xq_t, pb)
    with open(OUT / "int8_test_vectors.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"x{i}" for i in range(N_IN)] + ["acc2", "alarm", "label"])
        for k, i in enumerate(sel):
            w.writerow([int(v) for v in Xq_t[k]] + [int(s_t[k]), int(a_t[k]), int(ytest[i])])

    meta = dict(blob_size=BLOB_SIZE, sha256=digest,
                layout=[dict(name=n, offset=o, bytes=b) for n, o, b in LAYOUT],
                w1_order="hidden-major [hidden j][masuk i], indeks = j*16 + i (1 neuron = 16 byte berurutan)",
                sx=p["sx"], sw1=p["sw1"], sw2=p["sw2"], sh=p["sh"], M=p["M"], shift=p["shift"],
                threshold_q=p["thr"], calibration_percentile=p["pct"],
                host_mean=mean.tolist(), host_scale=scale.tolist(),
                note="Host harus menghitung X_std=(X-mean)/scale lalu Xq=clip(round(X_std/sx),-127,127).")
    (OUT / "quant_meta.json").write_text(json.dumps(meta, indent=2))
    (OUT / "quant_results.json").write_text(json.dumps(
        dict(float_pruned=float_res, int8=int_res, int8_vs_float_decision_agreement_test=agree,
             percentile_sweep_calibration=sweep, mac_cycles=cyc), indent=2))

    f_t, i_t = float_res["test"], int_res["test"]
    print(f"Persentil kalibrasi terpilih: {p['pct']}  (sweep: {sweep})")
    print(f"\nUJI (n={len(ytest)})          float-pruned   INT8")
    for k in ("accuracy", "recall", "specificity", "f1", "roc_auc"):
        print(f"  {k:<14}        {f_t[k]:.4f}       {i_t[k]:.4f}")
    print(f"  FN / FP                {f_t['fn']} / {f_t['fp']}          {i_t['fn']} / {i_t['fp']}")
    print(f"  kesesuaian keputusan INT8 vs float: {agree*100:.2f}%")
    print(f"\nKALIBRASI: float acc {float_res['calibration']['accuracy']:.4f} | INT8 acc {int_res['calibration']['accuracy']:.4f}")
    print(f"\nSparsity W1 (INT8): {100*(1-cyc['nnz_w1']/256):.2f}%  nnz={cyc['nnz_w1']}/256")
    print(f"MAC efektif: {cyc['mac_effective']}/{cyc['mac_dense']}")
    print(f"Siklus (4 lane): dense={cyc['cycles_dense']}  ideal={cyc['cycles_ideal_packing']}  per-neuron={cyc['cycles_per_neuron']}")
    print(f"nnz per neuron: {cyc['nnz_per_neuron']}")
    print(f"\nBlob: {BLOB_SIZE} byte, M={p['M']}, shift={p['shift']}, thr={p['thr']}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
