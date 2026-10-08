import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@cocotb.test()
async def test_sparseguard(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    dut.rst_n.value = 0
    dut.stream_valid.value = 0
    dut.stream_data.value = 0
    await Timer(20, units="ns")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    
    blob_path = ROOT / "artifacts" / "vpu_blob.bin"
    blob_data = blob_path.read_bytes()
    
    dut._log.info("Phase 1: Streaming 1024-byte blob model to chip...")
    for b in blob_data:
        while dut.busy.value == 1:
            await RisingEdge(dut.clk)
        dut.stream_data.value = b
        dut.stream_valid.value = 1
        await RisingEdge(dut.clk)
    
    dut.stream_valid.value = 0
    
    dut._log.info("Phase 2: Waiting for SHA-256 verification...")
    cycles = 0
    while True:
        await RisingEdge(dut.clk)
        cycles += 1
        if dut.integrity_fail.value == 1:
            assert False, "Integrity Check Failed! Hash mismatch."
        
        if dut.ctrl.state.value == 3: 
            dut._log.info(f"Verification successful in {cycles} cycles! weights_valid is High.")
            break
        if cycles > 1000:
            assert False, "Timeout waiting for VERIFY phase"

    csv_path = ROOT / "artifacts" / "int8_test_vectors.csv"
    dut._log.info("Phase 3: Starting inference test vectors...")
    
    pass_count = 0
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            for j in range(16):
                x_val = int(row[f"x{j}"])
                if x_val < 0:
                    x_val += 256
                dut.stream_data.value = x_val
                dut.stream_valid.value = 1
                await RisingEdge(dut.clk)
            
            dut.stream_valid.value = 0
            
            infer_cycles = 0
            while True:
                await RisingEdge(dut.clk)
                
                if dut.ctrl.state.value == 8:
                    break
                infer_cycles += 1
                if infer_cycles > 500:
                    assert False, f"Timeout waiting for ST_DONE. state={dut.ctrl.state.value} l2={dut.ctrl.l2_cycle.value} rd_n={dut.ctrl.rd_neuron.value}"
            
            
            expected_acc2 = int(row["acc2"])
            expected_alarm = int(row["alarm"])            dut_acc2 = dut.acc2_debug.value.to_signed()
            dut_alarm = int(dut.alarm.value)            
            if dut_acc2 != expected_acc2 or dut_alarm != expected_alarm:
                dut._log.error(f"Mismatch at vector {i}! Expected acc2={expected_acc2}, alarm={expected_alarm}. Got acc2={dut_acc2}, alarm={dut_alarm}")
                assert False, "Test Failed."
            
            pass_count += 1
            if i == 0:
                dut._log.info(f"Vector 0 computed correctly!")
                
            await RisingEdge(dut.clk)

    dut._log.info(f"SUCCESS! All {pass_count} vectors passed bit-exact comparison with the Golden Model.")
