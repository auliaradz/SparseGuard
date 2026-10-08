`default_nettype none

module vpu_ram (
    input  logic        clk,
    input  logic        rst_n,
    
    // Write port (from SPI / Boot loader)
    input  logic        we,
    input  logic [7:0]  waddr, // 256 depth requires 8-bit address
    input  logic [31:0] wdata,
    
    // Read port (from VPU Decoder)
    input  logic        re,
    input  logic [7:0]  raddr,
    output logic [31:0] rdata
);

    // M10K BRAM Inference: 256 x 32-bit = 8,192 bits
    logic [31:0] mem [0:255];

    always_ff @(posedge clk) begin
        if (we) begin
            mem[waddr] <= wdata;
        end
        if (re) begin
            rdata <= mem[raddr];
        end
    end

endmodule
