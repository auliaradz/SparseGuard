SIM ?= verilator
TOPLEVEL_LANG ?= verilog

RTL_DIR = /mnt/d/SparseGuard/rtl

VERILOG_SOURCES += $(RTL_DIR)/mask_gen.sv
VERILOG_SOURCES += $(RTL_DIR)/sparse_sched.sv
VERILOG_SOURCES += $(RTL_DIR)/ctrl_fsm.sv
VERILOG_SOURCES += $(RTL_DIR)/feature_buf.sv
VERILOG_SOURCES += $(RTL_DIR)/hidden_buf.sv
VERILOG_SOURCES += $(RTL_DIR)/integrity_boot.sv
VERILOG_SOURCES += $(RTL_DIR)/mac_array.sv
VERILOG_SOURCES += $(RTL_DIR)/output_cmp.sv
VERILOG_SOURCES += $(RTL_DIR)/param_reg.sv
VERILOG_SOURCES += $(RTL_DIR)/reference_digest.sv
VERILOG_SOURCES += $(RTL_DIR)/relu_quant.sv
VERILOG_SOURCES += $(RTL_DIR)/sha256_core.sv
VERILOG_SOURCES += $(RTL_DIR)/sparseguard.sv
VERILOG_SOURCES += $(RTL_DIR)/weight_sram.sv

TOPLEVEL = sparseguard_top
MODULE = test_top

# Verilator specific flags
EXTRA_ARGS += --trace-fst --trace-structs -Wno-fatal
VERILOG_SOURCES += $(RTL_DIR)/spi_slave.sv
VERILOG_SOURCES += $(RTL_DIR)/sparseguard_top.sv



include $(shell cocotb-config --makefiles)/Makefile.sim
