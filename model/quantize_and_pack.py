import numpy as np
import struct
import hashlib

def get_scale(tensor, max_val=127.0):
    return np.max(np.abs(tensor)) / max_val

def quantize_sym(tensor, scale):
    return np.clip(np.round(tensor / scale), -128, 127).astype(np.int8)

def main():
    # 1. Load float data (Asumsi file telah diproses di Langkah 1)
    try:
        d = np.load('artifacts/cwru_mlp_pruned_float.npz', allow_pickle=True)
    except FileNotFoundError:
        print("ERROR: File npz tidak ditemukan. Jalankan langkah 1 terlebih dahulu.")
        return

    W1 = d['w1']  # (16, 16)
    b1 = d['b1']  # (16,)
    W2 = d['w2']  # (16, 1)
    b2 = d['b2']  # (1,)
    
    # Asumsi data kalibrasi input & aktivasi (ganti dengan min/max dari X_train)
    # Ini adalah estimasi skalar untuk script agar berjalan; sesuaikan dengan distribusi asli
    scale_in = 1.0  
    scale_W1 = get_scale(W1)
    scale_a1 = 2.0  # max activation L1
    scale_W2 = get_scale(W2)
    scale_out = 1.0 # max activation L2
    
    # 2. Kuantisasi INT8 (Symmetric)
    W1_q = quantize_sym(W1, scale_W1)
    W2_q = quantize_sym(W2, scale_W2)
    
    # Bias dalam INT32 (Scale bias = Scale Input * Scale Weight)
    scale_b1 = scale_in * scale_W1
    scale_b2 = scale_a1 * scale_W2
    b1_q = np.round(b1 / scale_b1).astype(np.int32)
    b2_q = np.round(b2 / scale_b2).astype(np.int32)
    
    # 3. Hitung Multiplier & Shift (Requantization M = S_in * S_w / S_out)
    M1 = (scale_in * scale_W1) / scale_a1
    M2 = (scale_a1 * scale_W2) / scale_out
    
    # Representasi M = M0 * 2^-shift (Pendekatan sederhana M0 INT32)
    shift_1 = 16
    M1_int = int(np.round(M1 * (2**shift_1)))
    shift_2 = 16
    M2_int = int(np.round(M2 * (2**shift_2)))
    
    # Hitung Sparsity W1 aktual dari INT8
    nonzero_w1 = np.count_nonzero(W1_q)
    sparsity = 1.0 - (nonzero_w1 / W1_q.size)
    print(f"Target Pruning W1: 75.0%. Aktual Quantized INT8 Sparsity: {sparsity*100:.2f}%")
    print(f"MACs Efektif W1: {nonzero_w1}/256")
    
    # Threshold Output (Contoh 0.5 di-scale)
    threshold_float = 0.5
    threshold_q = int(np.round(threshold_float / scale_out))

    # 4. Packing Binary Blob
    blob = bytearray()
    blob.extend(W1_q.flatten().tobytes()) # 256 bytes
    blob.extend(b1_q.tobytes())           # 64 bytes
    blob.extend(W2_q.flatten().tobytes()) # 16 bytes
    blob.extend(b2_q.tobytes())           # 4 bytes
    blob.extend(struct.pack('<i', M1_int))   # 4 bytes
    blob.extend(struct.pack('<b', shift_1))  # 1 byte
    blob.extend(struct.pack('<i', M2_int))   # 4 bytes
    blob.extend(struct.pack('<b', shift_2))  # 1 byte
    blob.extend(struct.pack('<i', threshold_q)) # 4 bytes
    
    expected_size = 256 + 64 + 16 + 4 + 4 + 1 + 4 + 1 + 4
    assert len(blob) == expected_size, f"Blob size mismatch! Expected {expected_size}, got {len(blob)}"
    
    # 5. Generasi SHA-256
    digest = hashlib.sha256(blob).hexdigest()
    
    # 6. Export file
    with open('model_blob.bin', 'wb') as f:
        f.write(blob)
        
    print(f"Berhasil: model_blob.bin ({len(blob)} bytes)")
    print(f"SHA-256 Digest (Masukkan ke referensi_digest RTL): {digest}")

if __name__ == '__main__':
    main()
