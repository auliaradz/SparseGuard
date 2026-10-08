module feature_buf (
    input  logic              clk,
    input  logic              rst_n,

    // Interface pengisian (saat INFER atau iterasi)
    input  logic              load_en,
    input  logic [3:0]        load_idx,    // indeks 0-15
    input  logic signed [7:0] load_data,

    // Interface pembacaan konkuren (akses 16 byte sekaligus untuk MUX)
    output logic signed [7:0] features [0:15]
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

    assign features = mem;
endmodule
