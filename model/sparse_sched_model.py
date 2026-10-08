#!/usr/bin/env python3
"""
Model perilaku (cycle-level) penjadwal sparse per-neuron SparseGuard.

    python model/sparse_sched_model.py

Membaca artifacts/model_blob.bin (W1 hidden-major) dan artifacts/int8_test_vectors.csv.
Integer Python murni; tidak memakai fungsi dari quantize_int8.py, sehingga
sekaligus menjadi cek independen terhadap golden model.

Perilaku yang dimodelkan (acuan untuk RTL):
  * mask_gen: bit mask[j][i] = (W1[j][i] != 0), 16 bit per neuron j.
  * Layer 1, untuk tiap neuron j:
      - acc <- b1[j]
      - selama mask_sisa != 0: priority encoder mengambil <=4 bit set terendah,
        lane k mendapat (x[i_k], W1[j][i_k]); lane tanpa indeks valid = idle
        (operand ditahan, tidak diakumulasi); acc += jumlah produk lane valid;
        bit yang terambil dihapus. 1 iterasi = 1 siklus MAC.
      - neuron dengan mask = 0 memakai 0 siklus MAC (acc = b1[j]).
      - hq[j] = min((max(acc,0)*M + 2^(shift-1)) >> shift, 127)
  * Layer 2 (W2 tidak dipruning): 16/4 = 4 siklus, lane k mendapat (hq[4c+k], W2[4c+k]).
  * alarm = acc2 >= thr.
Siklus yang dihitung = siklus MAC saja (tanpa latensi baca memori, requant, pipeline, I/O).
"""
import csv
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "artifacts"
LANES = 4


def load_blob(path):
    b = path.read_bytes()
    assert len(b) == 352, len(b)
    w1 = [[struct.unpack_from("b", b, j * 16 + i)[0] for i in range(16)] for j in range(16)]  # [j][i]
    return dict(
        W1=w1,
        b1=list(struct.unpack_from("<16i", b, 256)),
        W2=list(struct.unpack_from("<16b", b, 320)),
        b2=struct.unpack_from("<i", b, 336)[0],
        M=struct.unpack_from("<i", b, 340)[0],
        shift=struct.unpack_from("<i", b, 344)[0],
        thr=struct.unpack_from("<i", b, 348)[0],
    )


def mask_gen(W1):
    return [sum(1 << i for i in range(16) if W1[j][i] != 0) for j in range(16)]


def pick_lowest(mask, n):
    """Priority encoder: hingga n indeks bit set terendah."""
    out = []
    while mask and len(out) < n:
        low = mask & -mask
        out.append(low.bit_length() - 1)
        mask ^= low
    return out, mask


def run(x, p, masks, trace=False):
    cyc = 0
    busy_lane_slots = 0
    hq = []
    for j in range(16):
        acc = p["b1"][j]
        m = masks[j]
        while m:
            idx, m = pick_lowest(m, LANES)
            acc += sum(x[i] * p["W1"][j][i] for i in idx)
            busy_lane_slots += len(idx)
            if trace:
                print(f"  siklus {cyc:2d}: neuron {j:2d}, lane<-i {idx}")
            cyc += 1
        h = max(acc, 0)
        hq.append(min((h * p["M"] + (1 << (p["shift"] - 1))) >> p["shift"], 127))
    cyc_l1 = cyc
    acc2 = p["b2"]
    for c in range(16 // LANES):
        acc2 += sum(hq[c * LANES + k] * p["W2"][c * LANES + k] for k in range(LANES))
        busy_lane_slots += LANES
        cyc += 1
    return acc2, int(acc2 >= p["thr"]), cyc_l1, cyc, busy_lane_slots, hq


def main():
    p = load_blob(A / "model_blob.bin")
    masks = mask_gen(p["W1"])
    nnz = [bin(m).count("1") for m in masks]
    rows = list(csv.DictReader(open(A / "int8_test_vectors.csv")))
    bad = 0
    stats = set()
    for r in rows:
        x = [int(r[f"x{i}"]) for i in range(16)]
        acc2, al, c1, c, busy, _ = run(x, p, masks)
        stats.add((c1, c, busy))
        if acc2 != int(r["acc2"]) or al != int(r["alarm"]):
            bad += 1
    assert len(stats) == 1, "jumlah siklus harus tidak bergantung pada data input"
    c1, c, busy = stats.pop()
    print(f"nnz per neuron        : {nnz}  (total {sum(nnz)})")
    print(f"vektor uji            : {len(rows)}, mismatch acc2/alarm = {bad}")
    print(f"siklus MAC layer 1    : {c1}")
    print(f"siklus MAC total      : {c}  (dense = 256/4 + 16/4 = 68)")
    print(f"slot lane terpakai    : {busy} dari {c}*{LANES} = {c * LANES}  ({100 * busy / (c * LANES):.1f}%)")
    print('\njejak penjadwal, vektor pertama (layer 1):')
    _, _, _, _, _, hq = run(x0, p, masks, trace=True)
    print('hq=', hq)
    x0 = [int(rows[0][f"x{i}"]) for i in range(16)]
    run(x0, p, masks, trace=True)


if __name__ == "__main__":
    main()
