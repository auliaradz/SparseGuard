import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly
import csv
import struct
import hashlib
import random
import os

def golden_acc2():
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    words = struct.unpack(f'<{len(blob)//4}I', blob)

    # Extract params
    b1q = []
    b2q = 0
    M = 0
    shift = 0
    thr = 0

    W1q = [[0]*16 for _ in range(16)] # [neuron][feature]
    W2q = [0]*16 # [neuron]

    pc = 0
    layer = 1
    neuron_idx = 0
    mac_idx = 0

    while pc < len(words):
        inst = words[pc]
        pc += 1
        opcode = inst >> 24
        operand = inst & 0xFFFFFF

        if opcode == 0x01: # CHECK_NONCE
            pass
        elif opcode == 0x02: # LOAD_BIAS
            for _ in range(16):
                val = struct.unpack('<i', struct.pack('<I', words[pc]))[0]
                b1q.append(val)
                pc += 1
            b2q = struct.unpack('<i', struct.pack('<I', words[pc]))[0]
            pc += 1
        elif opcode == 0x03: # LOAD_PARAMS
            M = struct.unpack('<i', struct.pack('<I', words[pc]))[0]
            shift = struct.unpack('<i', struct.pack('<I', words[pc+1]))[0]
            thr = struct.unpack('<i', struct.pack('<I', words[pc+2]))[0]
            pc += 3
        elif opcode == 0x04: # MAC_EXEC
            for _ in range(operand):
                w_packed = words[pc]
                pc += 1
                w_bytes = struct.unpack('<4b', struct.pack('<I', w_packed))
                if layer == 1:
                    for i in range(4):
                        W1q[neuron_idx][mac_idx*4 + i] = w_bytes[i]
                else:
                    for i in range(4):
                        W2q[mac_idx*4 + i] = w_bytes[i]
                mac_idx += 1
        elif opcode == 0x05: # MAC_SKIP
            mac_idx += operand
        elif opcode == 0x06: # SWITCH_L2
            layer = 2
            mac_idx = 0
        elif opcode == 0x07: # FINISH
            break
        elif opcode == 0x08: # NEXT_NEURON
            neuron_idx += 1
            mac_idx = 0

    acc2_list = []
    with open('../artifacts/int8_test_vectors.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            x = [int(row[f"x{j}"]) for j in range(16)]

            # Layer 1
            h = []
            for j in range(16):
                acc = sum(x[k] * W1q[j][k] for k in range(16)) + b1q[j]
                if acc < 0: acc_relu = 0
                else: acc_relu = acc
                hq = ((acc_relu * M) + (1 << (shift - 1))) >> shift
                if hq > 127: hq = 127
                if hq < -128: hq = -128
                h.append(hq)
            acc2 = sum(h[k] * W2q[k] for k in range(16)) + b2q
            acc2_list.append(acc2)

    return acc2_list

async def spi_exchange(dut, tx_bytes, spi_period=200):
    rx_bytes = []
    dut.spi_cs_n.value = 0
    await Timer(spi_period, units="ns")

    for b in tx_bytes:
        rx_byte = 0
        for i in range(7, -1, -1):
            dut.spi_mosi.value = (b >> i) & 1
            await Timer(spi_period // 2, units="ns")
            dut.spi_sclk.value = 1
            rx_bit = int(dut.spi_miso.value)
            rx_byte = (rx_byte << 1) | rx_bit
            await Timer(spi_period // 2, units="ns")
            dut.spi_sclk.value = 0
        rx_bytes.append(rx_byte)

    await Timer(spi_period, units="ns")
    dut.spi_cs_n.value = 1
    await Timer(spi_period, units="ns")

    return rx_bytes

async def secure_load(dut, blob, key, tag=None):
    # Phase Nonce
    tx_nonce = [0xA5] + [0x00] * 9
    rx = await spi_exchange(dut, tx_nonce)
    N = bytes(rx[1:9])

    rtl_nonce = int(dut.u_core.nonce_reg.value)
    assert N.hex() == f"{rtl_nonce:016x}", "MISO nonce doesn't match RTL nonce_reg!"

    if tag is None:
        tag = hashlib.sha256(key + N + blob).digest()

    # Phase Boot (Blob + Tag)
    await spi_exchange(dut, list(blob) + list(tag))
    return N, tag

async def wait_until_busy_low(dut, spi_period=200):
    for _ in range(10000):
        await Timer(spi_period, units="ns")
        busy = dut.led_busy.value
        integrity_fail = dut.led_error.value
        if integrity_fail:
            return False
        if not busy:
            return True
    assert False, "Timeout waiting for busy low"

@cocotb.test()
async def test_acc2_bit_exact(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(20, units="ns")

    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")

    N, tag = await secure_load(dut, blob, KEY)

    await Timer(500, units="ns")

    success = await wait_until_busy_low(dut)
    assert success, "Integrity check failed on valid blob!"

    goldens = golden_acc2()

    with open('../artifacts/int8_test_vectors.csv', 'r') as f:
        reader = list(csv.DictReader(f))

    for i, row in enumerate(reader):
        x_vals = [int(row[f"x{j}"]) for j in range(16)]
        x_bytes = [(val if val >= 0 else val + 256) for val in x_vals]

        await spi_exchange(dut, x_bytes)
        await wait_until_busy_low(dut)

        acc2_rtl = int(dut.u_core.acc2_debug.value.to_signed())

        alarm_rtl = int(dut.led_alarm.value)
        expected_alarm = int(row["alarm"])

        assert acc2_rtl == goldens[i], f"Mismatch at {i}! RTL={acc2_rtl}, Golden={goldens[i]}"
        assert alarm_rtl == expected_alarm, f"Alarm mismatch at {i}!"

@cocotb.test()
async def test_tamper_single_bit(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob_orig = f.read()

    tamper_pos = [0, 1, 2, 3, 4, 200, 1023, 500, 100, 750]

    for pos in tamper_pos:
        dut.rst_n.value = 0
        dut.spi_sclk.value = 0
        dut.spi_cs_n.value = 1
        dut.spi_mosi.value = 0
        await Timer(20, units="ns")
        dut.rst_n.value = 1
        await Timer(20, units="ns")

        # Tamper blob
        blob_tampered = bytearray(blob_orig)
        blob_tampered[pos] ^= 0x01

        # tag dihitung dari blob ASLI
        tx_nonce = [0xA5] + [0x00] * 9
        rx = await spi_exchange(dut, tx_nonce)
        N = bytes(rx[1:9])

        tag = hashlib.sha256(KEY + N + blob_orig).digest()

        await spi_exchange(dut, list(blob_tampered) + list(tag))
        success = await wait_until_busy_low(dut)

        assert not success, f"Tamper at byte {pos} undetected!"
        assert int(dut.led_error.value) == 1

        # led_done tidak boleh naik walau fitur dikirim
        x_bytes = [0]*16
        await spi_exchange(dut, x_bytes)
        await Timer(2000, units="ns")
        assert int(dut.led_done.value) == 0

@cocotb.test()
async def test_replay(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    # Sesi 1
    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(1000, units="ns")

    N1, tag1 = await secure_load(dut, blob, KEY)
    assert await wait_until_busy_low(dut)

    # Sesi 2
    dut.rst_n.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1

    # Wait some specific amount of time to let free_cnt increment differently
    await Timer(7000, units="ns")

    tx_nonce = [0xA5] + [0x00] * 9
    rx = await spi_exchange(dut, tx_nonce)
    N2 = bytes(rx[1:9])

    rtl_nonce = int(dut.u_core.nonce_reg.value)
    assert N2.hex() == f"{rtl_nonce:016x}", "MISO nonce doesn't match RTL nonce_reg!"

    assert N2 != N1, "Nonce is not changing!"

    # Kirim dengan tag lama
    await spi_exchange(dut, list(blob) + list(tag1))
    success = await wait_until_busy_low(dut)
    assert not success, "Replay attack succeeded!"

    # Reset dan kirim valid
    dut.rst_n.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(3500, units="ns")

    N3, tag3 = await secure_load(dut, blob, KEY)
    assert await wait_until_busy_low(dut)

@cocotb.test()
async def test_wrong_key(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    WRONG_KEY = bytes.fromhex("FF112233445566778899AABBCCDDEEFF")
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(20, units="ns")

    tx_nonce = [0xA5] + [0x00] * 9
    rx = await spi_exchange(dut, tx_nonce)
    N = bytes(rx[1:9])

    tag = hashlib.sha256(WRONG_KEY + N + blob).digest()

    await spi_exchange(dut, list(blob) + list(tag))
    success = await wait_until_busy_low(dut)
    assert not success, "Wrong key undetected!"

@cocotb.test()
async def test_host_starts_late(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1

    # Wait 20000 ns BEFORE SPI starts
    await Timer(20000, units="ns")

    N, tag = await secure_load(dut, blob, KEY)
    success = await wait_until_busy_low(dut)
    assert success, "Integrity check failed on host_starts_late!"

@cocotb.test()
async def test_tamper_tag(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(100, units="ns")

    tx_nonce = [0xA5] + [0x00] * 9
    rx = await spi_exchange(dut, tx_nonce)
    N = bytes(rx[1:9])

    tag = bytearray(hashlib.sha256(KEY + N + blob).digest())
    tag[0] ^= 0x01 # Flip 1 bit of tag

    await spi_exchange(dut, list(blob) + list(tag))
    success = await wait_until_busy_low(dut)
    assert not success, "Tampered tag should fail!"

@cocotb.test()
async def test_tamper_nonce(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    KEY = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob = f.read()

    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(100, units="ns")

    tx_nonce = [0xA5] + [0x00] * 9
    rx = await spi_exchange(dut, tx_nonce)
    N = bytes(rx[1:9])

    tampered_N = bytearray(N)
    tampered_N[0] ^= 0x01 # Host uses wrong nonce

    tag = hashlib.sha256(KEY + bytes(tampered_N) + blob).digest()

    await spi_exchange(dut, list(blob) + list(tag))
    success = await wait_until_busy_low(dut)
    assert not success, "Tampered nonce should fail!"

@cocotb.test()
async def test_nonce_latch_once(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst_n.value = 0
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await Timer(100, units="ns")

    await spi_exchange(dut, [0xA5, 0x00, 0x00])      # baru 3 dari 10 byte, FSM masih ST_NONCE
    nonce1 = int(dut.u_core.nonce_reg.value)
    assert nonce1 != 0

    await Timer(5000, units="ns")                    # free_cnt terus berjalan

    dut.spi_cs_n.value = 0                           # CS turun kedua, masih di ST_NONCE
    await Timer(400, units="ns")
    nonce2 = int(dut.u_core.nonce_reg.value)
    dut.spi_cs_n.value = 1
    assert nonce1 == nonce2, "Nonce berubah saat CS turun kedua!"
