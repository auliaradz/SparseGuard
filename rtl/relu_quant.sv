module relu_quant (
    input  logic signed [31:0] acc_in,
    input  logic signed [31:0] M,
    input  logic signed [31:0] shift,
    
    output logic signed [7:0]  hq_out
);
    logic signed [31:0] relu_val;
    logic signed [63:0] scaled_val; // Butuh 64-bit karena perkalian dua 32-bit (acc * M)
    logic signed [63:0] shifted_val;
    logic signed [31:0] quant_val;
    
    always_comb begin
        // 1. ReLU: max(acc, 0)
        relu_val = (acc_in > 32'sd0) ? acc_in : 32'sd0;
        
        // 2. Skala: h_relu * M + 2^(shift-1)
        // Pembulatan asimetris dengan penambahan 2^(shift-1)
        scaled_val = (64'(relu_val) * 64'(M)) + (64'sd1 << (shift - 32'sd1));
        
        // 3. Shift Right (>> shift)
        shifted_val = scaled_val >>> shift;
        
        // 4. Saturasi ke INT8 (min(val, 127), tidak bisa kurang dari 0 karena ReLU)
        quant_val = 32'(shifted_val);
        if (quant_val > 32'sd127) begin
            hq_out = 8'sd127;
        end else begin
            hq_out = 8'(quant_val);
        end
    end
endmodule
