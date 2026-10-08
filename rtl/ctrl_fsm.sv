module ctrl_fsm (
    input  logic        clk,
    input  logic        rst_n,

    // Host Stream Interface (Byte Stream)
    input  logic        stream_valid,
    input  logic [7:0]  stream_data,
    
    output logic        busy,
    output logic        done,
    output logic        alarm_out,
    output logic        integrity_fail_out,

    // Memory Write (STREAM phase)
    output logic        w1_byte_valid,
    output logic        weight_wr_en,
    output logic [3:0]  weight_wr_neuron,
    output logic [3:0]  weight_wr_byte,
    
    output logic        param_wr_en,
    output logic [6:0]  param_wr_addr,
    output logic        write_lock,
    
    // SHA-256 Hash Interface
    output logic        hash_stream_valid,
    output logic        hash_stream_last,
    input  logic        weights_valid,
    input  logic        integrity_fail,
    
    // Feature Buffer Write (INFER phase)
    output logic        feat_load_en,
    output logic [3:0]  feat_load_idx,
    
    // Datapath Control
    output logic [3:0]  rd_neuron, // Ke weight_sram & mask_gen
    input  logic [15:0] rd_mask,   // Dari mask_gen
    
    output logic [15:0] sched_mask, // Ke sparse_sched
    input  logic [15:0] rem_mask,   // Dari sparse_sched
    
    output logic        mac_acc_load,
    output logic        mac_acc_en,
    output logic [1:0]  layer_idx, // 0 = L1, 1 = L2
    output logic [1:0]  l2_cycle,  // 0-3 untuk L2
    
    output logic        hidden_load_en,
    output logic [3:0]  hidden_wr_idx,
    input  logic        alarm_in,
    input  logic        hash_ready
);

    typedef enum logic [3:0] {
        ST_IDLE,
        ST_STREAM,
        ST_VERIFY,
        ST_WAIT_INFER,
        ST_INFER_RECV,
        ST_L1_FETCH,
        ST_L1_LOAD,
        ST_L1_CALC,
        ST_L2,
        ST_DONE,
        ST_ERROR
    } state_t;
    
    state_t state, next_state;
    
    logic [8:0] byte_cnt;
    logic [15:0] current_mask;
    
    // Aliases for counters
    assign weight_wr_neuron = byte_cnt[7:4]; // byte_cnt / 16 (for 0-255)
    assign weight_wr_byte   = byte_cnt[3:0]; // byte_cnt % 16
    assign param_wr_addr    = byte_cnt[6:0]; // byte_cnt - 256
    assign feat_load_idx    = byte_cnt[3:0];
    
    assign sched_mask = (state == ST_L1_LOAD) ? rd_mask : current_mask;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_IDLE;
            byte_cnt <= 9'd0;
            write_lock <= 1'b0;
            rd_neuron <= 4'd0;
            current_mask <= 16'd0;
            l2_cycle <= 2'd0;
            alarm_reg <= 1'b0;
        end else begin
            case (state)
                ST_IDLE: begin
                    if (stream_valid && hash_ready) begin
                        state <= ST_STREAM;
                        byte_cnt <= 9'd1;
                    end
                end
                
                ST_STREAM: begin
                    if (stream_valid && hash_ready) begin
                        if (byte_cnt == 9'd351) begin
                            state <= ST_VERIFY;
                        end else begin
                            byte_cnt <= byte_cnt + 9'd1;
                        end
                    end
                end
                
                ST_VERIFY: begin
                    if (integrity_fail) begin
                        state <= ST_ERROR;
                    end else if (weights_valid) begin
                        write_lock <= 1'b1;
                        state <= ST_WAIT_INFER;
                        byte_cnt <= 9'd0;
                    end
                end
                
                ST_WAIT_INFER: begin
                    if (stream_valid) begin
                        state <= ST_INFER_RECV;
                        byte_cnt <= 9'd1;
                    end
                end
                
                ST_INFER_RECV: begin
                    if (stream_valid) begin
                        if (byte_cnt == 9'd15) begin
                            state <= ST_L1_FETCH;
                            rd_neuron <= 4'd0;
                            // Wait for 1 cycle memory read? 
                            // mask_gen rd_mask is async!
                        end else begin
                            byte_cnt <= byte_cnt + 9'd1;
                        end
                    end
                end
                
                ST_L1_FETCH: begin
                    // Wait 1 cycle for synchronous BRAM read
                    state <= ST_L1_LOAD;
                end
                ST_L1_LOAD: begin
                    // State di mana rd_mask valid
                    // Kita load mask dari mask_gen, atau langsung pakai bila kombinasional
                    if (rd_mask == 16'd0) begin
                        // 0 MAC cycle
                        if (rd_neuron == 4'd15) begin
                            state <= ST_L2;
                            l2_cycle <= 2'd0;
                        end else begin
                            rd_neuron <= rd_neuron + 4'd1;
                        end
                    end else begin
                        current_mask <= rem_mask; // sisa dari sched (yg masuk sched_mask=rd_mask via mux async)
                        if (rem_mask == 16'd0) begin
                            // Selesai dalam 1 siklus
                            if (rd_neuron == 4'd15) begin
                                state <= ST_L2;
                                l2_cycle <= 2'd0;
                            end else begin
                                rd_neuron <= rd_neuron + 4'd1;
                            end
                        end else begin
                            state <= ST_L1_CALC;
                        end
                    end
                end
                
                ST_L1_CALC: begin
                    current_mask <= rem_mask;
                    if (rem_mask == 16'd0) begin
                        if (rd_neuron == 4'd15) begin
                            state <= ST_L2;
                            l2_cycle <= 2'd0;
                        end else begin
                            state <= ST_L1_FETCH;
                            rd_neuron <= rd_neuron + 4'd1;
                        end
                    end
                end
                
                ST_L2: begin
                    if (l2_cycle == 2'd3) begin
                        state <= ST_DONE;
                    end else begin
                        l2_cycle <= l2_cycle + 2'd1;
                    end
                end
                
                ST_DONE: begin
                    state <= ST_WAIT_INFER; // siap terima inferensi lagi
                    byte_cnt <= 9'd0;
                    alarm_reg <= alarm_in;
                end
                
                ST_ERROR: begin
                    // Terkunci
                end
            endcase
        end
    end
    
    // Output Logic Kombinasional
    logic alarm_reg;
    assign alarm_out = (state == ST_DONE) ? alarm_in : alarm_reg;

    always_comb begin
        busy = (state == ST_STREAM && !hash_ready) || (state == ST_VERIFY) || (state >= ST_L1_FETCH && state <= ST_L2);
        done = (state == ST_DONE);
        integrity_fail_out = (state == ST_ERROR);
        
        w1_byte_valid = 1'b0;
        weight_wr_en = 1'b0;
        param_wr_en = 1'b0;
        hash_stream_valid = 1'b0;
        hash_stream_last = 1'b0;
        
        if (state == ST_IDLE && stream_valid && hash_ready) begin
            w1_byte_valid = 1'b1;
            weight_wr_en = 1'b1;
            hash_stream_valid = 1'b1;
        end else if (state == ST_STREAM && stream_valid && hash_ready) begin
            hash_stream_valid = 1'b1;
            if (byte_cnt < 256) begin
                w1_byte_valid = 1'b1;
                weight_wr_en = 1'b1;
            end else begin
                param_wr_en = 1'b1;
            end
            if (byte_cnt == 9'd351) begin
                hash_stream_last = 1'b1;
            end
        end
        
        feat_load_en = 1'b0;
    if (state == ST_WAIT_INFER && stream_valid) feat_load_en = 1'b1;
    if (state == ST_INFER_RECV && stream_valid) feat_load_en = 1'b1;
    
    mac_acc_load = (state == ST_L1_LOAD) || (state == ST_L2 && l2_cycle == 2'd0);
    mac_acc_en = (state >= ST_L1_FETCH && state <= ST_L2);
    
    layer_idx = (state == ST_L2) ? 2'd1 : 2'd0;
end

// Pipeline hidden_load_en by 1 cycle so acc_reg has the final sum
logic hidden_wr_en_pipe1, hidden_wr_en_pipe2;
  logic [3:0] hidden_wr_idx_pipe1, hidden_wr_idx_pipe2;
  always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
          hidden_wr_en_pipe1 <= 1'b0; hidden_wr_en_pipe2 <= 1'b0;
          hidden_wr_idx_pipe1 <= 4'd0; hidden_wr_idx_pipe2 <= 4'd0;
      end else begin
          hidden_wr_en_pipe1 <= 1'b0;
          hidden_wr_idx_pipe1 <= rd_neuron;
          
          if (state == ST_L1_LOAD && (rd_mask == 16'd0 || rem_mask == 16'd0)) begin
              hidden_wr_en_pipe1 <= 1'b1;
          end else if (state == ST_L1_CALC && rem_mask == 16'd0) begin
              hidden_wr_en_pipe1 <= 1'b1;
          end
          
          // Pipeline stage 2
          hidden_wr_en_pipe2 <= hidden_wr_en_pipe1;
          hidden_wr_idx_pipe2 <= hidden_wr_idx_pipe1;
      end
  end
  assign hidden_load_en = hidden_wr_en_pipe2;
  assign hidden_wr_idx = hidden_wr_idx_pipe2;

endmodule
