`default_nettype none

module sparseguard (
    input  logic       clk,
    input  logic       rst_n,

    // Byte-stream interface from Host (SPI)
    input  logic       stream_valid,
    input  logic [7:0] stream_data,
    
    // Status outputs
    output logic       busy,
    output logic       done,
    output logic       alarm,
    output logic       integrity_fail,
    output logic [31:0] acc2_debug
);

    // FSM States
    typedef enum logic [2:0] {
        ST_BOOT,
        ST_VERIFY,
        ST_WAIT_FEAT,
        ST_INFER,
        ST_ERROR
    } top_state_t;
    top_state_t state, next_state;

    // Counters and Registers
    logic [9:0] rx_cnt, next_rx_cnt;
    logic [3:0] feat_cnt, next_feat_cnt;
    logic [31:0] word_buf;
    
    // Memory write signals
    logic        ram_we;
    logic [7:0]  ram_waddr;
    logic [31:0] ram_wdata;
    
    // Feature load signals
    logic        feat_load_en;
    logic [3:0]  feat_load_idx;
    
    // Crypto signals
    logic        hash_valid, hash_last, hash_ready, digest_valid;
    logic [255:0] digest, ref_digest;
    logic        weights_valid, integ_fail_internal;
    
    // Decoder signals
    logic        start_infer, dec_done, dec_alarm, dec_error;
    logic [7:0]  dec_pc;
    logic        dec_re;
    logic [31:0] dec_instr_data;
    logic        mac_en, mac_clear_acc, mac_load_bias;
    logic [31:0] mac_weights, mac_bias_val;
    logic [3:0]  feat_idx, hidden_idx;
    logic        hidden_we, is_layer2;
    logic [31:0] param_M, param_shift, param_thr;

    // Buffers and Datapath
    logic signed [7:0]  features [0:15];
    logic signed [7:0]  hidden_features [0:15];
    logic signed [31:0] acc_out, acc_out_reg;
    logic signed [7:0]  hq_out;

    assign acc2_debug = acc_out_reg;
    always_ff @(posedge clk) acc_out_reg <= acc_out;

    // 1. Memory (VPU RAM)
    vpu_ram ram (
        .clk(clk), .rst_n(rst_n),
        .we(ram_we), .waddr(ram_waddr), .wdata(ram_wdata),
        .re(dec_re), .raddr(dec_pc), .rdata(dec_instr_data)
    );

    // 2. VPU Decoder
    vpu_decoder decoder (
        .clk(clk), .rst_n(rst_n),
        .start_infer(start_infer), .done(dec_done), .alarm(dec_alarm), .error_flag(dec_error),
        .pc(dec_pc), .re(dec_re), .instr_data(dec_instr_data),
        .mac_en(mac_en), .mac_weights(mac_weights), .mac_clear_acc(mac_clear_acc),
        .mac_load_bias(mac_load_bias), .mac_bias_val(mac_bias_val),
        .feat_idx(feat_idx), .hidden_we(hidden_we), .hidden_idx(hidden_idx), .is_layer2(is_layer2),
        .quant_m(param_M), .quant_shift(param_shift), .threshold(param_thr)
    );

    // 3. Security
    sha256_core hash_core (
        .clk(clk), .rst_n(rst_n),
        .stream_valid(hash_valid), .stream_data(stream_data), .stream_last(hash_last),
        .hash_ready(hash_ready), .digest(digest), .digest_valid(digest_valid)
    );

    reference_digest refd (.ref_digest(ref_digest));

    integrity_boot boot_chk (
        .clk(clk), .rst_n(rst_n),
        .digest(digest), .digest_valid(digest_valid), .ref_digest(ref_digest),
        .weights_valid(weights_valid), .integrity_fail(integ_fail_internal)
    );

    // 4. Buffers
    feature_buf fbuf (
        .clk(clk), .rst_n(rst_n),
        .load_en(feat_load_en), .load_idx(feat_load_idx), .load_data(stream_data),
        .features(features)
    );

    hidden_buf hbuf (
        .clk(clk), .rst_n(rst_n),
        .load_en(hidden_we), .load_idx(hidden_idx), .load_data(hq_out),
        .hidden_features(hidden_features)
    );

    // 5. MAC Datapath Muxing
    logic        mac_v0, mac_v1, mac_v2, mac_v3;
    logic signed [7:0] mac_f0, mac_f1, mac_f2, mac_f3;
    logic signed [7:0] mac_w0, mac_w1, mac_w2, mac_w3;

    always_comb begin
        // Weights are packed 4x INT8 inside mac_weights (Little Endian)
        mac_w0 = mac_weights[7:0];
        mac_w1 = mac_weights[15:8];
        mac_w2 = mac_weights[23:16];
        mac_w3 = mac_weights[31:24];
        
        mac_v0 = mac_en; mac_v1 = mac_en; mac_v2 = mac_en; mac_v3 = mac_en;
        
        if (!is_layer2) begin
            // Layer 1 uses features
            mac_f0 = features[{feat_idx, 2'd0}];
            mac_f1 = features[{feat_idx, 2'd1}];
            mac_f2 = features[{feat_idx, 2'd2}];
            mac_f3 = features[{feat_idx, 2'd3}];
        end else begin
            // Layer 2 uses hidden_features (feat_idx works the same way!)
            mac_f0 = hidden_features[{feat_idx, 2'd0}];
            mac_f1 = hidden_features[{feat_idx, 2'd1}];
            mac_f2 = hidden_features[{feat_idx, 2'd2}];
            mac_f3 = hidden_features[{feat_idx, 2'd3}];
        end
    end

    mac_array mac (
        .clk(clk), .rst_n(rst_n),
        .acc_load(mac_load_bias), .acc_en(mac_en | mac_load_bias), .bias_val(mac_bias_val),
        .v0(mac_v0), .f0(mac_f0), .w0(mac_w0),
        .v1(mac_v1), .f1(mac_f1), .w1(mac_w1),
        .v2(mac_v2), .f2(mac_f2), .w2(mac_w2),
        .v3(mac_v3), .f3(mac_f3), .w3(mac_w3),
        .acc_out(acc_out)
    );

    relu_quant rq (
        .acc_in(acc_out_reg), .M(param_M), .shift(param_shift),
        .hq_out(hq_out)
    );

    output_cmp ocmp (
        .acc2(acc_out_reg), .thr(param_thr),
        .alarm(alarm)
    );

    // 6. Top FSM (Bootloader)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_BOOT;
            rx_cnt <= 10'd0;
            feat_cnt <= 4'd0;
            word_buf <= 32'd0;
            integrity_fail <= 1'b0;
        end else begin
            state <= next_state;
            rx_cnt <= next_rx_cnt;
            feat_cnt <= next_feat_cnt;
            
            // Shift register for assembling 32-bit words from 8-bit stream (Little Endian)
            if (state == ST_BOOT && stream_valid) begin
                if (rx_cnt[1:0] == 2'd0) word_buf[7:0]   <= stream_data;
                if (rx_cnt[1:0] == 2'd1) word_buf[15:8]  <= stream_data;
                if (rx_cnt[1:0] == 2'd2) word_buf[23:16] <= stream_data;
                if (rx_cnt[1:0] == 2'd3) word_buf[31:24] <= stream_data;
            end
            
            if (state == ST_VERIFY && integ_fail_internal) begin
                integrity_fail <= 1'b1;
            end
            if (state == ST_INFER && dec_error) begin
                integrity_fail <= 1'b1;
            end
        end
    end

    always_comb begin
        next_state = state;
        next_rx_cnt = rx_cnt;
        next_feat_cnt = feat_cnt;
        
        ram_we = 1'b0;
        ram_waddr = 8'd0;
        ram_wdata = 32'd0;
        
        hash_valid = 1'b0;
        hash_last = 1'b0;
        
        feat_load_en = 1'b0;
        feat_load_idx = feat_cnt;
        
        start_infer = 1'b0;
        busy = (state != ST_WAIT_FEAT);
        done = 1'b0;

        case (state)
            ST_BOOT: begin
                if (stream_valid) begin
                    hash_valid = 1'b1;
                    next_rx_cnt = rx_cnt + 10'd1;
                    
                    // Trigger RAM write every 4th byte
                    if (rx_cnt[1:0] == 2'd3) begin
                        ram_we = 1'b1;
                        ram_waddr = rx_cnt[9:2];
                        // Assemble the final word combination combinationally for immediate write
                        ram_wdata = {stream_data, word_buf[23:0]};
                    end
                    
                    if (rx_cnt == 10'd1023) begin
                        hash_last = 1'b1;
                        next_state = ST_VERIFY;
                    end
                end
            end
            
            ST_VERIFY: begin
                if (weights_valid) next_state = ST_WAIT_FEAT;
                else if (integ_fail_internal) next_state = ST_ERROR;
            end
            
            ST_WAIT_FEAT: begin
                if (stream_valid) begin
                    feat_load_en = 1'b1;
                    next_feat_cnt = feat_cnt + 4'd1;
                    if (feat_cnt == 4'd15) begin
                        next_state = ST_INFER;
                        start_infer = 1'b1;
                    end
                end
            end
            
            ST_INFER: begin
                if (dec_done) begin
                    done = 1'b1;
                    next_state = ST_WAIT_FEAT;
                end
                if (dec_error) begin
                    next_state = ST_ERROR;
                end
            end
            
            ST_ERROR: begin
                // Halt.
            end
        endcase
    end

endmodule
