module output_cmp (
    input  logic signed [31:0] acc2,
    input  logic signed [31:0] thr,
    
    output logic               alarm
);
    // Menghasilkan alarm jika skor >= threshold
    assign alarm = (acc2 >= thr);
endmodule
