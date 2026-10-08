# SparseGuard: Secure AI Edge Accelerator 🛡️🧠

**SparseGuard** is an Edge AI accelerator designed for the **PERURI Chip Hackathon 2026**. It features a hybrid architecture combining a high-throughput Neural Network Vector Processing Unit (VPU) with a hardware-based cryptographic security layer (Integrity Boot) to prevent the execution of manipulated or malicious neural network models.

## 🚀 ASIP & Security Design

### Application-Specific Instruction-set Processor (ASIP)
The design adopts an ASIP methodology with a custom 32-bit Instruction Set Architecture (ISA). The baseline implementation is targeted purely for FPGA devices, utilizing M10K BRAM abstractions without ASIC technology node limitations.

### Secure Boot & Hardware Hash
Security validation in SparseGuard targets the mitigation of Man-in-the-Middle (MitM) vulnerabilities and architecture injection during SPI payload handovers (Firmware Over-The-Air). 
The protocol operates in two strict phases:
1. **STREAM Phase:** The hardware bootloader receives 1024 bytes of bytecode and forwards it to the hardware hash computation unit (`sha256_core`) on-the-fly.
2. **VERIFY Phase:** The Digest value is bitwise compared with a hardcoded ROM constant. Instruction Fetching by the VPU Decoder is electrically locked and rejected if verification fails (`integrity_fail` active). 
*(Note: Every payload is time-locked via a `CHECK_NONCE` instruction to reject Replay Attacks).*

## 📁 RTL Module Details

| Module | Function | Notes |
| :--- | :--- | :--- |
| `sparseguard_top.sv` | Top-Level IO Wrapper | Maps physical I/O (SPI, LEDs) for the DE10-Nano board. |
| `sparseguard.sv` | Core Orchestrator FSM | Manages BOOT, VERIFY, INFER, WAIT_FEAT states. Assembles 8-bit SPI streams into 32-bit Words for BRAM. |
| `spi_slave.sv` | Serial Host Interface | Receives serial data from host via SPI clock (`sclk`). |
| `sha256_core.sv` | Hardware Hash Cryptography | Computes SHA-256 digest from uploaded bytecode on-the-fly. |
| `reference_digest.sv` | Key Storage ROM | Hardcoded 256-bit trusted reference hash (immune to runtime manipulation). |
| `integrity_boot.sv` | Security Comparator | Synchronizes and compares `sha256_core` output with `reference_digest`. Asserts `integrity_fail` on mismatch. |
| `vpu_ram.sv` | Main Memory (1 KB) | Inferred as 1 M10K BRAM block (256 depth x 32-bit). Stores VPU bytecode. |
| `vpu_decoder.sv` | Vector Processing Unit | Main ASIP Core (Fetch-Decode-Execute). Translates custom 32-bit ISA like `MAC_EXEC` and `MAC_SKIP`. |
| `mac_array.sv` | 4-Lane Multiply-Accumulate | Parallel datapath performing four INT8 dot-products and accumulations per clock cycle. |
| `relu_quant.sv` | Activation & Quantization | Applies ReLU and scales the 32-bit accumulator back to INT8 resolution. |
| `output_cmp.sv` | Anomaly Detector | Final comparator matching inference scores against a threshold to trigger alarms. |

## 🛠️ Simulation & Verification

The project uses **Cocotb** to verify the RTL against the Python Golden Model using the CWRU dataset.
```bash
cd tb
pytest test_top.py
```
*   **Functional Verification:** Achieved bit-exact behavior on 64 INT8 feature vectors, verifying saturation, hardware sparsity, and pipeline management.
*   **Security Injection Test:** Modifying a single random bit in the 1024-byte payload instantly locks the system and triggers `integrity_fail`.

## 📊 Synthesis Results (Intel Quartus Prime 25.1)
Target Device: **Cyclone V (5CSEBA6U23I7) / DE10-Nano**

The design exhibits extreme silicon efficiency, consuming very minimal resources:
*   **Logic Utilization (ALMs):** 2,027 / 41,910 ALMs (5%)
*   **Registers:** 2,901 / 415,000
*   **Block RAM (M10K):** 1 Block (8,192 bits) / 5,570 Kbits
*   **DSP Blocks:** 7 / 112 DSP
*   **Timing / Power:** Achieves an Fmax of **52.57 MHz**, comfortably passing the 50 MHz constraint. Combined with a 5% area footprint, dynamic power consumption is significantly reduced, making it ideal for IoT Edge Nodes.

---
*Developed by Aulia Radzaky Aria & Raihan Ata Putra for the PERURI Chip Hackathon 2026.*
