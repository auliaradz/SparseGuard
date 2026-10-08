import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly
import csv

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

async def wait_until_busy_low(dut, spi_period=200):
    while True:
        await Timer(spi_period, units="ns")
        busy = dut.led_busy.value
        integrity_fail = dut.led_error.value
        
        if integrity_fail:
            assert False, "Integrity Check Failed! Hash mismatch."
        
        if not busy:
            return

@cocotb.test()
async def test_sparseguard_top(dut):
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
        blob_data = list(f.read())
    
    dut._log.info("Phase 1: Streaming 1024-byte blob model via SPI...")
    await spi_exchange(dut, blob_data)
    
    dut._log.info("Phase 2: Waiting for SHA-256 verification...")
    await wait_until_busy_low(dut)
    dut._log.info("Verification successful! weights_valid is High.")
    
    dut._log.info("Phase 3: Streaming test vectors via SPI...")
    pass_count = 0
    
    with open('../artifacts/int8_test_vectors.csv', 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            x_vals = [int(row[f"x{j}"]) for j in range(16)]
            x_bytes = [(val if val >= 0 else val + 256) for val in x_vals]
            
            await spi_exchange(dut, x_bytes)
            await wait_until_busy_low(dut)
            
            alarm = dut.led_alarm.value
            expected_alarm = int(row["alarm"])
            
            if alarm != expected_alarm:
                dut._log.error(f"Mismatch at vector {i}! Expected alarm={expected_alarm}. Got alarm={alarm}")
                assert False, "Test Failed."
            
            pass_count += 1
            
    dut._log.info(f"SUCCESS! All {pass_count} vectors passed SPI integration test.")
