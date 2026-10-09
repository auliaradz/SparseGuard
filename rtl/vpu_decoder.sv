`default_nettype none

module vpu_decoder (
    input  logic        clk,
    input  logic        rst_n,

    // Global Control
    input  logic        start_infer,
    output logic        done,
    output logic        alarm,
    output logic        error_flag,

    // Memory Interface (to vpu_ram)
    output logic [7:0]  pc,
    output logic        re,
    input  logic [31:0] instr_data,

    // MAC Array Control
    output logic        mac_en,
    output logic [31:0] mac_weights,
    output logic        mac_load_bias,
    output logic [31:0] mac_bias_val,

    // Buffer Control
    output logic [3:0]  feat_idx,     // 0 to 3 (Selects block of 4 features)
    output logic        hidden_we,
    output logic [3:0]  hidden_idx,   // 0 to 15
    output logic        is_layer2,

    // Quantization & Threshold
    output logic [31:0] quant_m,
    output logic [31:0] quant_shift,
    output logic [31:0] threshold
);

    // Opcodes
    localparam OP_CHECK_NONCE = 8'h01;
    localparam OP_LOAD_BIAS   = 8'h02;
    localparam OP_LOAD_PARAMS = 8'h03;
    localparam OP_MAC_EXEC    = 8'h04;
    localparam OP_MAC_SKIP    = 8'h05;
    localparam OP_SWITCH_L2   = 8'h06;
    localparam OP_FINISH      = 8'h07;
    localparam OP_NEXT_NEURON = 8'h08;

    // FSM States
    typedef enum logic [3:0] {
        ST_IDLE,
        ST_FETCH_ADDR,
        ST_FETCH_DATA,
        ST_DECODE,
        ST_LOAD_BIAS_ADDR,
        ST_LOAD_BIAS_DATA,
        ST_LOAD_PARAM_ADDR,
        ST_LOAD_PARAM_DATA,
        ST_MAC_EXEC_ADDR,
        ST_MAC_EXEC_DATA,
        ST_ERROR,
        ST_DONE
    } state_t;
    state_t state, next_state;

    // Internal Registers
    logic [7:0]  pc_reg, next_pc;
    logic [7:0]  loop_cnt, next_loop_cnt;
    logic [3:0]  n_idx, next_n_idx; // Neuron index
    logic [3:0]  f_idx, next_f_idx; // Feature block index
    logic        is_l2, next_is_l2;
    logic [7:0]  param_idx, next_param_idx;

    // Nonce (Hardcoded expected for Anti-Replay for now)
    localparam [23:0] EXPECTED_NONCE = 24'd123;

    // Internal Parameter Storage
    logic [31:0] b1_reg [0:15];
    logic [31:0] b2_reg;
    logic [31:0] m_reg, shift_reg, thr_reg;

    // Combinational assignments
    assign pc = pc_reg;
    assign feat_idx = f_idx;
    assign hidden_idx = n_idx;
    assign is_layer2 = is_l2;
    assign quant_m = m_reg;
    assign quant_shift = shift_reg;
    assign threshold = thr_reg;

    // Sequential State Update
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            pc_reg <= 8'd0;
            loop_cnt <= 8'd0;
            n_idx <= 4'd0;
            f_idx <= 4'd0;
            is_l2 <= 1'b0;
            param_idx <= 8'd0;
        end else begin
            state <= next_state;
            pc_reg <= next_pc;
            loop_cnt <= next_loop_cnt;
            n_idx <= next_n_idx;
            f_idx <= next_f_idx;
            is_l2 <= next_is_l2;
            param_idx <= next_param_idx;
        end
    end

    // Parameter Loading (Synchronous)
    always_ff @(posedge clk) begin
        if (state == ST_LOAD_BIAS_DATA) begin
            if (param_idx < 16) b1_reg[param_idx[3:0]] <= instr_data;
            else if (param_idx == 16) b2_reg <= instr_data;
        end
        if (state == ST_LOAD_PARAM_DATA) begin
            if (param_idx == 0) m_reg <= instr_data;
            if (param_idx == 1) shift_reg <= instr_data;
            if (param_idx == 2) thr_reg <= instr_data;
        end
    end

    // Next State & Output Logic
    always_comb begin
        next_state = state;
        next_pc = pc_reg;
        next_loop_cnt = loop_cnt;
        next_n_idx = n_idx;
        next_f_idx = f_idx;
        next_is_l2 = is_l2;
        next_param_idx = param_idx;

        re = 1'b0;
        done = 1'b0;
        alarm = 1'b0;
        error_flag = 1'b0;

        mac_en = 1'b0;
        mac_weights = 32'd0;
        mac_load_bias = 1'b0;
        mac_bias_val = 32'd0;
        hidden_we = 1'b0;

        case (state)
            ST_IDLE: begin
                next_pc = 8'd0;
                next_n_idx = 4'd0;
                next_f_idx = 4'd0;
                next_is_l2 = 1'b0;
                next_param_idx = 8'd0;
                if (start_infer) next_state = ST_FETCH_ADDR;
            end

            ST_FETCH_ADDR: begin
                re = 1'b1;
                next_state = ST_FETCH_DATA;
            end

            ST_FETCH_DATA: begin
                next_state = ST_DECODE;
            end

            ST_DECODE: begin
                logic [7:0]  opcode = instr_data[31:24];
                logic [23:0] operand = instr_data[23:0];

                next_pc = pc_reg + 8'd1; // Default advance

                case (opcode)
                    OP_CHECK_NONCE: begin
                        if (operand != EXPECTED_NONCE) next_state = ST_ERROR;
                        else next_state = ST_FETCH_ADDR;
                    end
                    OP_LOAD_BIAS: begin
                        next_loop_cnt = operand[7:0];
                        next_param_idx = 8'd0;
                        next_state = ST_LOAD_BIAS_ADDR;
                    end
                    OP_LOAD_PARAMS: begin
                        next_loop_cnt = operand[7:0];
                        next_param_idx = 8'd0;
                        next_state = ST_LOAD_PARAM_ADDR;
                    end
                    OP_MAC_EXEC: begin
                        next_loop_cnt = operand[7:0];
                        next_state = ST_MAC_EXEC_ADDR;
                    end
                    OP_MAC_SKIP: begin
                        next_f_idx = f_idx + operand[3:0];
                        next_state = ST_FETCH_ADDR;
                    end
                    OP_SWITCH_L2: begin
                        hidden_we = 1'b1; // Write last L1 neuron to hidden buf
                        // Pre-load L2 bias into MAC accumulator
                        mac_en = 1'b1;
                        mac_weights = 32'd0;
                        mac_load_bias = 1'b1;
                        mac_bias_val = b2_reg;

                        next_is_l2 = 1'b1;
                        next_n_idx = 4'd0;
                        next_f_idx = 4'd0;
                        next_state = ST_FETCH_ADDR;
                    end
                    OP_NEXT_NEURON: begin
                        hidden_we = 1'b1; // Write finished L1 neuron to hidden buf
                        // Pre-load L1 bias for next neuron into MAC accumulator
                        mac_en = 1'b1;
                        mac_weights = 32'd0;
                        mac_load_bias = 1'b1;
                        mac_bias_val = b1_reg[n_idx + 1];

                        next_n_idx = n_idx + 4'd1;
                        next_f_idx = 4'd0;
                        next_state = ST_FETCH_ADDR;
                    end
                    OP_FINISH: begin
                        next_state = ST_DONE;
                    end
                    default: next_state = ST_ERROR;
                endcase
            end

            // --- LOAD BIAS ---
            ST_LOAD_BIAS_ADDR: begin
                if (loop_cnt == 0) begin
                    next_state = ST_FETCH_ADDR;
                end else begin
                    re = 1'b1;
                    next_state = ST_LOAD_BIAS_DATA;
                end
            end
            ST_LOAD_BIAS_DATA: begin
                next_param_idx = param_idx + 1;
                next_pc = pc_reg + 8'd1;
                next_loop_cnt = loop_cnt - 8'd1;
                next_state = ST_LOAD_BIAS_ADDR;
            end

            // --- LOAD PARAMS ---
            ST_LOAD_PARAM_ADDR: begin
                if (loop_cnt == 0) begin
                    next_state = ST_FETCH_ADDR;
                    // When params finish loading, we are ready to start L1.
                    // Pre-load very first L1 bias (Neuron 0) into accumulator!
                    mac_en = 1'b1;
                    mac_weights = 32'd0;
                    mac_load_bias = 1'b1;
                    mac_bias_val = b1_reg[0];
                end else begin
                    re = 1'b1;
                    next_state = ST_LOAD_PARAM_DATA;
                end
            end
            ST_LOAD_PARAM_DATA: begin
                next_param_idx = param_idx + 1;
                next_pc = pc_reg + 8'd1;
                next_loop_cnt = loop_cnt - 8'd1;
                next_state = ST_LOAD_PARAM_ADDR;
            end

            // --- MAC EXEC ---
            ST_MAC_EXEC_ADDR: begin
                if (loop_cnt == 0) begin
                    next_state = ST_FETCH_ADDR;
                end else begin
                    re = 1'b1;
                    next_state = ST_MAC_EXEC_DATA;
                end
            end
            ST_MAC_EXEC_DATA: begin
                mac_en = 1'b1;
                mac_weights = instr_data;
                // DO NOT load bias here, just accumulate

                next_f_idx = f_idx + 4'd1;
                next_pc = pc_reg + 8'd1;
                next_loop_cnt = loop_cnt - 8'd1;
                next_state = ST_MAC_EXEC_ADDR;
            end

            ST_ERROR: begin
                error_flag = 1'b1;
            end


            ST_DONE: begin
                done = 1'b1;
                next_state = ST_IDLE;
            end

            default: begin
                next_state = ST_ERROR;
                error_flag = 1'b1;
                alarm = 1'b1;
            end

        endcase

    end

endmodule

