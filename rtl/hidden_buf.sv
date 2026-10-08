module hidden_buf (
    input  logic              clk,
    input  logic              rst_n,

    // Interface pengisian (dari output layer 1)
    input  logic              load_en,
    input  logic [3:0]        load_idx,    // indeks 0-15
    input  logic signed [7:0] load_data,

    // Interface pembacaan (akses array untuk layer 2)
    output logic signed [7:0] hidden_features [0:15]
);
    logic signed [7:0] mem [0:15];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < 16; i++) begin
                mem[i] <= 8'sd0;
            end
        end else if (load_en) begin
            mem[load_idx] <= load_data;
        end
    end

    assign hidden_features = mem;
endmodule
