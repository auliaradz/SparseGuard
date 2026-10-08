import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

@cocotb.test()
async def debug_test(dut):
    clock = Clock(dut.clk, 10, units='ns')
    cocotb.start_soon(clock.start())
    dut.rst_n.value = 0
    await Timer(20, units='ns')
    dut.rst_n.value = 1
    await Timer(20, units='ns')
    
    dut._log.info('Starting boot sequence debug...')
    dut.spi_sclk.value = 0
    dut.spi_cs_n.value = 1
    dut.spi_mosi.value = 0
    
    with open('../artifacts/vpu_blob.bin', 'rb') as f:
        blob_data = list(f.read())
        
    spi_period = 200
    dut.spi_cs_n.value = 0
    await Timer(spi_period, units='ns')
    
    for i, b in enumerate(blob_data):
        for bit in range(7, -1, -1):
            dut.spi_mosi.value = (b >> bit) & 1
            await Timer(spi_period // 2, units='ns')
            dut.spi_sclk.value = 1
            await Timer(spi_period // 2, units='ns')
            dut.spi_sclk.value = 0
            
        if i == 1023:
            dut._log.info(f'Sent byte 1023. rx_cnt={dut.u_core.rx_cnt.value}')
            await Timer(200, units='ns')
            dut._log.info(f'hash_last={dut.u_core.hash_last.value}, hash_valid={dut.u_core.hash_valid.value}')
            dut._log.info(f'state={dut.u_core.state.value}')
            
    dut.spi_cs_n.value = 1
    
    for _ in range(200):
        await RisingEdge(dut.clk)
        if dut.u_core.digest_valid.value:
            dut._log.info('digest_valid is HIGH!')
            dut._log.info(f'digest={dut.u_core.digest.value}')
            dut._log.info(f'ref_digest={dut.u_core.ref_digest.value}')
            dut._log.info(f'weights_valid={dut.u_core.weights_valid.value}')
            break
            
