# SparseGuard: Secure AI Edge Accelerator 🛡️🧠

**SparseGuard** is an Edge AI accelerator designed for the **PERURI Chip Hackathon 2026**. It features a hybrid architecture combining a high-throughput Neural Network Vector Processing Unit (VPU) with a hardware-based cryptographic security layer (Integrity Boot) to prevent the execution of manipulated or malicious neural network models.

## 🚀 Key Features

*   **Integrity Boot (Hardware Security):** Implements an on-the-fly SHA-256 hash verification module. As the model weights and instructions are streamed via SPI, the hardware calculates the cryptographic digest and cross-checks it with a trusted reference.
*   **High-Throughput VPU:** Features a 4-lane 8-bit Integer (INT8) Multiply-Accumulate (MAC) Array utilizing FPGA DSP blocks for parallel computation.
*   **Edge-Optimized Footprint:** Extremely lightweight resource utilization. Designed to fit comfortably alongside other SoC components on a Cyclone V FPGA (DE10-Nano).
*   **Low Latency:** Cryptographic hashing runs in parallel with memory loading, effectively hiding the boot latency.

## 📁 Repository Structure

*   `rtl/` - SystemVerilog source codes for the SparseGuard hardware.
    *   `sparseguard_top.sv` - Top-level wrapper (SPI to Core).
    *   `sparseguard.sv` - Main FSM and VPU integration.
    *   `mac_array.sv` - 4-lane DSP-based MAC datapath.
    *   `integrity_boot.sv` & `sha256_core.sv` - Cryptographic verification.
*   `tb/` - Python/Cocotb testbenches for automated RTL verification.
*   `model/` - Python scripts for the Neural Network golden model, training, quantization (INT8), and pruning.
*   `data/` - Datasets and raw features used for training and evaluation.
*   `docs/` - System block diagrams and related documentation.

## 🛠️ Simulation & Verification

The project uses **Cocotb** (Coroutine based cosimulation library for writing VHDL and Verilog testbenches in Python) to verify the RTL against the Python Golden Model.

### Prerequisites
*   Python 3.12+
*   `cocotb` and `pytest`
*   Verilator or Questa/ModelSim

### Running the Tests
To run the automated tests and verify the functional accuracy and security features:
```bash
cd tb
pytest test_top.py
```
*(Ensure your virtual environment `.venv` is activated)*

## 📊 Synthesis Results (Intel Quartus Prime)

The project has been successfully synthesized and verified for the **Cyclone V (DE10-Nano)** FPGA. The Quartus project files and reports are available in the `quartus/` directory.

### 1. Resource Utilization (Map Summary)
The design is extremely lightweight, occupying less than 1% of the total FPGA resources, leaving ample room for other Edge SoC components.
```text
Analysis & Synthesis Status : Successful
Family : Cyclone V
Top-level Entity Name : sparseguard_top
Logic utilization (in ALMs) : N/A
Total registers : 2769
Total block memory bits : 8,192
Total DSP Blocks : 7
```
*(From `sparseguard.map.summary`)*

### 2. Timing Analysis (STA Summary)
The 4-lane MAC Array datapath meets all timing constraints effortlessly, ensuring stable parallel execution at a positive slack.
```text
Type  : Slow 1100mV 100C Model Setup 'clk'
Slack : 0.977
TNS   : 0.000

Type  : Fast 1100mV 100C Model Setup 'clk'
Slack : 10.641
TNS   : 0.000
```
*(From `sparseguard.sta.summary`)*

---
*Developed for the PERURI Chip Hackathon 2026 - Category: AI Edge Accelerator.*
