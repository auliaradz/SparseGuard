module sha256_core (
    input  logic        clk,
    input  logic        rst_n,

    // Streaming input (1 byte/cycle)
    input  logic        stream_valid,
    input  logic [7:0]  stream_data,
    input  logic        stream_last,

    // Output
    output logic [255:0] digest,
    output logic         digest_valid,
    output logic         hash_ready,
    input  logic [63:0]  nonce,
    input  logic         nonce_ready
);
    // Hash Values (H0..H7)
    logic [31:0] H [0:7];

    // Registers A..H for the compression round
    logic [31:0] A_reg, B_reg, C_reg, D_reg, E_reg, F_reg, G_reg, H_reg;

    // Message Block Buffer (64 bytes)
    logic [7:0] block_buf [0:63];
    logic [5:0] byte_cnt; // 0 to 63
    logic [4:0] sec_idx;
    `include "secret_key.svh"
    logic [63:0] total_bits;

    // FSM States
    typedef enum logic [3:0] {
        ST_INJECT_SEC,
        ST_IDLE,
        ST_RECV,     // Receiving bytes from stream
        ST_PAD,      // Adding padding to buffer (0x80, 0x00, and length)
        ST_COMPRESS, // Running 64 rounds of compression
        ST_DONE      // Finished
    } state_t;
    state_t state;

    logic [6:0] round_cnt; // 0 to 64
    logic       last_block;
    logic       length_written;

    // W Schedule Shift Register
    logic [31:0] W_reg [0:15];
    logic [31:0] W_val;
    logic [31:0] W_s0, W_s1;
    logic [31:0] K_val;

    // --- Padding Logic ---
    logic need_len;
    logic [63:0] pad_len_shift;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_INJECT_SEC;
            sec_idx <= 5'd0;
            byte_cnt <= 6'd0;
            total_bits <= 64'd0;
            digest_valid <= 1'b0;
            last_block <= 1'b0;
            need_len <= 1'b0;
            length_written <= 1'b0;
            pad_len_shift <= 64'd0;
            round_cnt <= 7'd0;

            // SHA-256 Initial Hash Values
            H[0] <= 32'h6a09e667; H[1] <= 32'hbb67ae85; H[2] <= 32'h3c6ef372; H[3] <= 32'ha54ff53a;
            H[4] <= 32'h510e527f; H[5] <= 32'h9b05688c; H[6] <= 32'h1f83d9ab; H[7] <= 32'h5be0cd19;

            for (int i=0; i<64; i++) block_buf[i] <= 8'd0;
        end else begin
            case (state)
                ST_INJECT_SEC: begin
                    if (nonce_ready) begin
                        if (sec_idx < 5'd16) begin
                            block_buf[byte_cnt] <= SECRET_KEY[ (15 - sec_idx[3:0])*8 +: 8 ];
                        end else begin
                            block_buf[byte_cnt] <= nonce[ (7 - sec_idx[2:0])*8 +: 8 ];
                        end
                        byte_cnt <= byte_cnt + 6'd1;
                        total_bits <= total_bits + 64'd8;
                        sec_idx <= sec_idx + 5'd1;
                        if (sec_idx == 5'd23) state <= ST_IDLE;
                    end
                end
                ST_IDLE: begin
                    if (stream_valid) begin
                        block_buf[byte_cnt] <= stream_data;
                        byte_cnt <= byte_cnt + 6'd1;
                        total_bits <= total_bits + 64'd8;
                        state <= ST_RECV;
                        if (stream_last) begin
                            last_block <= 1'b1; // We hit the last byte exactly on the first byte?
                            // Wait, padding logic handled in RECV
                        end
                    end
                end

                ST_RECV: begin
                    if (stream_valid) begin
                        block_buf[byte_cnt] <= stream_data;
                        byte_cnt <= byte_cnt + 6'd1;
                        total_bits <= total_bits + 64'd8;

                        if (stream_last) begin
                            last_block <= 1'b1;
                            state <= ST_PAD;
                        end else if (byte_cnt == 6'd63) begin
                            state <= ST_COMPRESS;
                            round_cnt <= 7'd0;
                        end
                    end else if (last_block) begin
                        // If stream_last was asserted but we are waiting for buffer to process?
                        // No, if stream_last was asserted, we go to ST_PAD immediately
                        state <= ST_PAD;
                    end
                end

                ST_PAD: begin
                    // Append 0x80
                    if (!need_len) begin
                        block_buf[byte_cnt] <= 8'h80;
                        byte_cnt <= byte_cnt + 6'd1;
                        need_len <= 1'b1;
                        pad_len_shift <= total_bits;

                        if (byte_cnt == 6'd63) begin
                            state <= ST_COMPRESS; // Need another block for length
                            round_cnt <= 7'd0;
                        end
                    end else begin
                        if (byte_cnt < 6'd56) begin
                            block_buf[byte_cnt] <= 8'h00;
                            byte_cnt <= byte_cnt + 6'd1;
                        end else begin
                            // Append 64-bit length (big-endian)
                            // byte_cnt is 56 to 63
                            case (byte_cnt)
                                6'd56: block_buf[56] <= pad_len_shift[63:56];
                                6'd57: block_buf[57] <= pad_len_shift[55:48];
                                6'd58: block_buf[58] <= pad_len_shift[47:40];
                                6'd59: block_buf[59] <= pad_len_shift[39:32];
                                6'd60: block_buf[60] <= pad_len_shift[31:24];
                                6'd61: block_buf[61] <= pad_len_shift[23:16];
                                6'd62: block_buf[62] <= pad_len_shift[15:8];
                                6'd63: begin
                                    block_buf[63] <= pad_len_shift[7:0];
                                    state <= ST_COMPRESS;
                                    round_cnt <= 7'd0;
                                    length_written <= 1'b1;
                                end
                                default: begin
                                    state <= ST_DONE;
                                    digest_valid <= 1'b0;
                                end
                            endcase
                            byte_cnt <= byte_cnt + 6'd1;
                        end

                        if (byte_cnt == 6'd63 && state != ST_COMPRESS) begin
                            // Padded with zeros up to 63, need another block
                            state <= ST_COMPRESS;
                            round_cnt <= 7'd0;
                            // last_block stays 1
                        end
                    end
                end

                ST_COMPRESS: begin
                    if (round_cnt == 7'd0) begin
                        // Initialize Working Variables
                        A_reg <= H[0]; B_reg <= H[1]; C_reg <= H[2]; D_reg <= H[3];
                        E_reg <= H[4]; F_reg <= H[5]; G_reg <= H[6]; H_reg <= H[7];
                        round_cnt <= round_cnt + 7'd1;

                        // Also initialize W_reg for first 16 words?
                        // No, W_val is combinational and shifts every round_cnt >= 1
                    end else if (round_cnt <= 7'd64) begin
                        // Round Update (borrowed from xeniarose/tt07-sha256)
                        A_reg <= temp1 + temp2;
                        B_reg <= A_reg;
                        C_reg <= B_reg;
                        D_reg <= C_reg;
                        E_reg <= D_reg + temp1;
                        F_reg <= E_reg;
                        G_reg <= F_reg;
                        H_reg <= G_reg;

                        // Shift W_reg
                        for (int i=0; i<15; i++) W_reg[i] <= W_reg[i+1];
                        W_reg[15] <= W_val;

                        round_cnt <= round_cnt + 7'd1;
                    end else if (round_cnt == 7'd65) begin
                        // Update Hash Values
                        H[0] <= H[0] + A_reg;
                        H[1] <= H[1] + B_reg;
                        H[2] <= H[2] + C_reg;
                        H[3] <= H[3] + D_reg;
                        H[4] <= H[4] + E_reg;
                        H[5] <= H[5] + F_reg;
                        H[6] <= H[6] + G_reg;
                        H[7] <= H[7] + H_reg;

                        byte_cnt <= 6'd0;
                        if (length_written) begin
                            state <= ST_DONE;
                            digest_valid <= 1'b1;
                        end else if (last_block) begin
                            // Length was not padded yet
                            state <= ST_PAD;
                        end else begin
                            state <= ST_RECV;
                        end
                    end
                end


                ST_DONE: begin
                    // Stay done
                end

                default: begin
                    state <= ST_DONE;
                    digest_valid <= 1'b0;
                end
            endcase

        end
    end

    // --- Message Schedule W Logic ---
    // Accessing block_buf as big-endian 32-bit words
    logic [31:0] buf_word;
    logic [3:0] word_idx;
    assign word_idx = round_cnt[3:0] - 4'd1; // round_cnt is 1 to 64
    assign buf_word = {block_buf[{word_idx, 2'd0}], block_buf[{word_idx, 2'd1}],
                       block_buf[{word_idx, 2'd2}], block_buf[{word_idx, 2'd3}]};

    // W operations
    assign W_s0 = {W_reg[1][6:0],   W_reg[1][31:7]}  ^
                  {W_reg[1][17:0],  W_reg[1][31:18]} ^
                  (W_reg[1] >> 3);

    assign W_s1 = {W_reg[14][16:0], W_reg[14][31:17]} ^
                  {W_reg[14][18:0], W_reg[14][31:19]} ^
                  (W_reg[14] >> 10);

    always_comb begin
        if (round_cnt >= 7'd1 && round_cnt <= 7'd16) begin
            W_val = buf_word;
        end else begin
            W_val = W_reg[0] + W_s0 + W_reg[9] + W_s1;
        end
    end

    // --- TT07 SHA-256 Round Function Core (xeniarose) ---
    logic [31:0] s1, ch, temp1, s0, maj, temp2;

    assign s1 = {E_reg[5:0],  E_reg[31:6]}  ^
                {E_reg[10:0], E_reg[31:11]} ^
                {E_reg[24:0], E_reg[31:25]};

    assign ch = (E_reg & F_reg) ^ ((~E_reg) & G_reg);

    assign temp1 = H_reg + s1 + ch + K_val + W_val;

    assign s0 = {A_reg[1:0],  A_reg[31:2]}  ^
                {A_reg[12:0], A_reg[31:13]} ^
                {A_reg[21:0], A_reg[31:22]};

    assign maj = (A_reg & B_reg) ^ (A_reg & C_reg) ^ (B_reg & C_reg);

    assign temp2 = s0 + maj;

    // --- K Constants ROM ---
    always_comb begin
        case (round_cnt - 7'd1)
            7'd0: K_val = 32'h428a2f98;
            7'd1: K_val = 32'h71374491;
            7'd2: K_val = 32'hb5c0fbcf;
            7'd3: K_val = 32'he9b5dba5;
            7'd4: K_val = 32'h3956c25b;
            7'd5: K_val = 32'h59f111f1;
            7'd6: K_val = 32'h923f82a4;
            7'd7: K_val = 32'hab1c5ed5;
            7'd8: K_val = 32'hd807aa98;
            7'd9: K_val = 32'h12835b01;
            7'd10: K_val = 32'h243185be;
            7'd11: K_val = 32'h550c7dc3;
            7'd12: K_val = 32'h72be5d74;
            7'd13: K_val = 32'h80deb1fe;
            7'd14: K_val = 32'h9bdc06a7;
            7'd15: K_val = 32'hc19bf174;
            7'd16: K_val = 32'he49b69c1;
            7'd17: K_val = 32'hefbe4786;
            7'd18: K_val = 32'h0fc19dc6;
            7'd19: K_val = 32'h240ca1cc;
            7'd20: K_val = 32'h2de92c6f;
            7'd21: K_val = 32'h4a7484aa;
            7'd22: K_val = 32'h5cb0a9dc;
            7'd23: K_val = 32'h76f988da;
            7'd24: K_val = 32'h983e5152;
            7'd25: K_val = 32'ha831c66d;
            7'd26: K_val = 32'hb00327c8;
            7'd27: K_val = 32'hbf597fc7;
            7'd28: K_val = 32'hc6e00bf3;
            7'd29: K_val = 32'hd5a79147;
            7'd30: K_val = 32'h06ca6351;
            7'd31: K_val = 32'h14292967;
            7'd32: K_val = 32'h27b70a85;
            7'd33: K_val = 32'h2e1b2138;
            7'd34: K_val = 32'h4d2c6dfc;
            7'd35: K_val = 32'h53380d13;
            7'd36: K_val = 32'h650a7354;
            7'd37: K_val = 32'h766a0abb;
            7'd38: K_val = 32'h81c2c92e;
            7'd39: K_val = 32'h92722c85;
            7'd40: K_val = 32'ha2bfe8a1;
            7'd41: K_val = 32'ha81a664b;
            7'd42: K_val = 32'hc24b8b70;
            7'd43: K_val = 32'hc76c51a3;
            7'd44: K_val = 32'hd192e819;
            7'd45: K_val = 32'hd6990624;
            7'd46: K_val = 32'hf40e3585;
            7'd47: K_val = 32'h106aa070;
            7'd48: K_val = 32'h19a4c116;
            7'd49: K_val = 32'h1e376c08;
            7'd50: K_val = 32'h2748774c;
            7'd51: K_val = 32'h34b0bcb5;
            7'd52: K_val = 32'h391c0cb3;
            7'd53: K_val = 32'h4ed8aa4a;
            7'd54: K_val = 32'h5b9cca4f;
            7'd55: K_val = 32'h682e6ff3;
            7'd56: K_val = 32'h748f82ee;
            7'd57: K_val = 32'h78a5636f;
            7'd58: K_val = 32'h84c87814;
            7'd59: K_val = 32'h8cc70208;
            7'd60: K_val = 32'h90befffa;
            7'd61: K_val = 32'ha4506ceb;
            7'd62: K_val = 32'hbef9a3f7;
            7'd63: K_val = 32'hc67178f2;
            default: K_val = 32'h0;
        endcase
    end

    // --- Final Digest ---
    // H0 to H7 appended
    assign hash_ready = (state == ST_IDLE || state == ST_RECV);
    assign digest = {H[0], H[1], H[2], H[3], H[4], H[5], H[6], H[7]};

endmodule
