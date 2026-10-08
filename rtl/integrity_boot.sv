`default_nettype none
module integrity_boot (
    input  logic         clk,
    input  logic         rst_n,

    // Input dari sha256_core
    input  logic [255:0] digest,
    input  logic         digest_valid,
    
    // Input dari reference_digest
    input  logic [255:0] ref_digest,

    // Output ke sistem
    output logic         weights_valid,
    output logic         integrity_fail
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            weights_valid <= 1'b0;
            integrity_fail <= 1'b0;
        end else if (digest_valid) begin
            if (digest == ref_digest) begin
                weights_valid <= 1'b1;
                integrity_fail <= 1'b0;
            end else begin
                weights_valid <= 1'b0;
                integrity_fail <= 1'b1;
            end
        end
    end
endmodule
