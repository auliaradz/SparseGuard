module mac_array (
    input  logic              clk,
    input  logic              rst_n,

    // Control
    input  logic              acc_load,  // 1 = load bias, 0 = accumulate
    input  logic              acc_en,    // 1 = jalankan MAC dan simpan ke acc
    input  logic signed [31:0] bias_val, // Nilai bias saat load

    // Operand Lane 0
    input  logic              v0,
    input  logic signed [7:0] f0,
    input  logic signed [7:0] w0,

    // Operand Lane 1
    input  logic              v1,
    input  logic signed [7:0] f1,
    input  logic signed [7:0] w1,

    // Operand Lane 2
    input  logic              v2,
    input  logic signed [7:0] f2,
    input  logic signed [7:0] w2,

    // Operand Lane 3
    input  logic              v3,
    input  logic signed [7:0] f3,
    input  logic signed [7:0] w3,

    // Output
    output logic signed [31:0] acc_out
);
    logic signed [31:0] acc_reg;
    
    // Multipliers (akan infer ke blok DSP / multiplier logic)
    logic signed [15:0] prod0, prod1, prod2, prod3;
    
    always_comb begin
        prod0 = v0 ? (f0 * w0) : 16'sd0;
        prod1 = v1 ? (f1 * w1) : 16'sd0;
        prod2 = v2 ? (f2 * w2) : 16'sd0;
        prod3 = v3 ? (f3 * w3) : 16'sd0;
    end
    
    // Adder Tree
    logic signed [31:0] sum01, sum23, sum_all;
    always_comb begin
        sum01 = 32'(prod0) + 32'(prod1);
        sum23 = 32'(prod2) + 32'(prod3);
        sum_all = sum01 + sum23;
    end
    
    // Accumulator Register
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_reg <= 32'sd0;
        end else if (acc_en) begin
            if (acc_load) begin
                acc_reg <= bias_val + sum_all; // Langsung hitung produk di siklus load
            end else begin
                acc_reg <= acc_reg + sum_all;
            end
        end
    end
    
    assign acc_out = acc_reg;
endmodule
