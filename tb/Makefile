SIM ?= verilator
TOPLEVEL_LANG ?= verilog

RTL_DIR = $(abspath ../rtl)

VERILOG_SOURCES += $(RTL_DIR)/vpu_decoder.sv
VERILOG_SOURCES += $(RTL_DIR)/vpu_ram.sv
VERILOG_SOURCES += $(RTL_DIR)/feature_buf.sv
VERILOG_SOURCES += $(RTL_DIR)/hidden_buf.sv
VERILOG_SOURCES += $(RTL_DIR)/integrity_boot.sv
VERILOG_SOURCES += $(RTL_DIR)/mac_array.sv
VERILOG_SOURCES += $(RTL_DIR)/output_cmp.sv
VERILOG_SOURCES += $(RTL_DIR)/reference_digest.sv
VERILOG_SOURCES += $(RTL_DIR)/relu_quant.sv
VERILOG_SOURCES += $(RTL_DIR)/sha256_core.sv
VERILOG_SOURCES += $(RTL_DIR)/sparseguard.sv
VERILOG_SOURCES += $(RTL_DIR)/spi_slave.sv
VERILOG_SOURCES += $(RTL_DIR)/sparseguard_top.sv

TOPLEVEL = sparseguard_top
MODULE = test_security

# Verilator specific flags
EXTRA_ARGS += --trace-fst --trace-structs -Wno-fatal -I$(RTL_DIR)

# Prepare secret key include file for simulation
$(shell cp -n $(RTL_DIR)/secret_key.svh.example $(RTL_DIR)/secret_key.svh)

include $(shell cocotb-config --makefiles)/Makefile.sim
