import numpy as np
import struct
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/home/aulia/projects/SparseGuard')
DATA_PATH = ROOT / 'data/processed/cwru_features_16.npz'
SCALER_PATH = ROOT / 'artifacts/feature_scaler_calibrated.npz'
PRUNED_PATH = ROOT / 'artifacts/cwru_mlp_pruned_float.npz'
OUT = ROOT / 'artifacts'

N_IN = 16
N_HID = 16
LANES = 4
MAX_RAM_WORDS = 256 # 1KB total

OP_CHECK_NONCE = 0x01
OP_LOAD_BIAS   = 0x02
OP_LOAD_PARAMS = 0x03
OP_MAC_EXEC    = 0x04
OP_MAC_SKIP    = 0x05
OP_SWITCH_L2   = 0x06
OP_FINISH      = 0x07
OP_NEXT_NEURON = 0x08

def build_instruction(opcode, operand=0):
    return ((opcode & 0xFF) << 24) | (operand & 0xFFFFFF)

def fixed_point(scale):
    shift = 0
    while scale < 0.5 and shift < 31:
        scale *= 2.0
        shift += 1
    M = int(round(scale * 32768))
    if M == 32768:
        M = 32767
    return M, shift + 15

def build_quant(w1, b1, w2, b2, Xref, pct):
    sx = float(np.percentile(np.abs(Xref), pct)) / 127
    sw1 = float(np.abs(w1).max()) / 127
    sw2 = float(np.abs(w2).max()) / 127
    W1q = np.clip(np.round(w1 / sw1), -127, 127).astype(np.int8)
    W2q = np.clip(np.round(w2 / sw2), -127, 127).astype(np.int8).reshape(-1)
    b1q = np.round(b1 / (sx * sw1)).astype(np.int64)
    
    Xq = np.clip(np.round(Xref / sx), -127, 127)
    acc1 = np.maximum(0, Xq.astype(np.int64) @ W1q.astype(np.int64) + b1q)
    hmax = max(float(np.percentile(acc1, pct)), 1.0)
    
    M, shift = fixed_point(127.0 / hmax)
    sh = sx * sw1 / (M / 2 ** shift)
    b2q = int(np.round(b2[0] / (sh * sw2)))
    
    return dict(sx=sx, sw1=sw1, sw2=sw2, sh=sh, W1q=W1q, W2q=W2q, b1q=b1q,
                b2q=b2q, M=M, shift=shift, thr=0, pct=pct)

def compile_vpu(p, nonce=1):
    stream = []
    
    stream.append(build_instruction(OP_CHECK_NONCE, nonce))
    
    stream.append(build_instruction(OP_LOAD_BIAS, 17))
    for b in p['b1q']:
        stream.append(int(b) & 0xFFFFFFFF)
    stream.append(int(p['b2q']) & 0xFFFFFFFF)
    
    stream.append(build_instruction(OP_LOAD_PARAMS, 3))
    stream.append(int(p['M']) & 0xFFFFFFFF)
    stream.append(int(p['shift']) & 0xFFFFFFFF)
    stream.append(int(p['thr']) & 0xFFFFFFFF)
    
    W1q = p['W1q']
    mac_cycles = 0
    for j in range(N_HID):
        w_neuron = W1q[:, j]
        blocks = len(w_neuron) // LANES
        for b in range(blocks):
            w_block = w_neuron[b*LANES : (b+1)*LANES]
            if np.all(w_block == 0):
                stream.append(build_instruction(OP_MAC_SKIP, 1))
            else:
                stream.append(build_instruction(OP_MAC_EXEC, 1))
                packed = 0
                for k in range(4):
                    val = int(w_block[k]) & 0xFF
                    packed |= (val << (k*8))
                stream.append(packed)
                mac_cycles += 1
        stream.append(build_instruction(OP_NEXT_NEURON, 0))
    
    stream.append(build_instruction(OP_SWITCH_L2, 0))
    
    W2q = p['W2q']
    blocks_l2 = len(W2q) // LANES
    stream.append(build_instruction(OP_MAC_EXEC, blocks_l2))
    for b in range(blocks_l2):
        w_block = W2q[b*LANES : (b+1)*LANES]
        packed = 0
        for k in range(4):
            val = int(w_block[k]) & 0xFF
            packed |= (val << (k*8))
        stream.append(packed)
        mac_cycles += 1
        
    stream.append(build_instruction(OP_FINISH, 0))
    
    words_used = len(stream)
    assert words_used <= MAX_RAM_WORDS, f'Program too large! {words_used} words > {MAX_RAM_WORDS}'
    
    while len(stream) < MAX_RAM_WORDS:
        stream.append(0)
        
    blob = bytearray()
    for word in stream:
        blob += struct.pack('<I', word)
        
    assert len(blob) == MAX_RAM_WORDS * 4
    
    digest = hashlib.sha256(b'SPARSEGUARD_SEC!' + blob).hexdigest()
    
    return bytes(blob), digest, words_used, mac_cycles

def main():
    try:
        data = np.load(DATA_PATH, allow_pickle=True)
        sc = np.load(SCALER_PATH)
        m = np.load(PRUNED_PATH, allow_pickle=True)
    except FileNotFoundError:
        print('Model files not found. Are you in the right directory?')
        return

    X, y, split, file_id = data['X'], data['y'].astype(np.int64), data['split'], data['file_id']
    mean, scale = sc['mean'], sc['scale']
    w1, b1, w2, b2 = m['w1'], m['b1'], m['w2'], m['b2']
    
    train_pool = np.where(split == 'train')[0]
    Xref = (X[train_pool] - mean) / scale
    
    p = build_quant(w1, b1, w2, b2, Xref, 99)
    
    blob, digest, words_used, mac_cycles = compile_vpu(p, nonce=123)
    
    OUT.mkdir(exist_ok=True)
    (OUT / 'vpu_blob.bin').write_bytes(blob)
    (OUT / 'vpu_blob.sha256').write_text(digest + '\n')
    
    print('=== VPU Compilation Successful ===')
    print(f'Total Words Used: {words_used} / {MAX_RAM_WORDS} ({(words_used/MAX_RAM_WORDS)*100:.1f}%)')
    print(f'Total Bytes: {len(blob)}')
    print(f'Active MAC Cycles: {mac_cycles}')
    print(f'SHA-256 Digest: {digest}')
    
if __name__ == '__main__':
    main()
