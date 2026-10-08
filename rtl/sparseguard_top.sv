module sparseguard_top (
    input  logic clk,
    input  logic rst_n,

    // SPI Interface
    input  logic spi_sclk,
    input  logic spi_cs_n,
    input  logic spi_mosi,
    output logic spi_miso,

    // Optional Board Outputs (Status LEDs)
    output logic led_alarm,
    output logic led_busy,
    output logic led_done,
    output logic led_error
);

    // Internal wires connecting SPI to the Neural Network Core
    logic       stream_valid;
    logic [7:0] stream_data;
    logic [7:0] status_data;
    
    // Core status flags
    logic       busy;
    logic       done;
    logic       alarm;
    logic       integrity_fail;

    // Map status signals to the SPI return byte
    // Format: [7:4] reserved, [3] integrity_fail, [2] alarm, [1] done, [0] busy
    assign status_data = {4'b0000, integrity_fail, alarm, done, busy};

    // Drive LEDs for physical board
    assign led_alarm = alarm;
    assign led_busy  = busy;
    assign led_done  = done;
    assign led_error = integrity_fail;

    // SPI Slave Wrapper
    spi_slave u_spi (
        .clk(clk),
        .rst_n(rst_n),
        .spi_sclk(spi_sclk),
        .spi_cs_n(spi_cs_n),
        .spi_mosi(spi_mosi),
        .spi_miso(spi_miso),
        .rx_valid(stream_valid),
        .rx_data(stream_data),
        .tx_data(status_data)
    );

    // Main Neural Network & SHA-256 Core
    sparseguard u_core (
        .clk(clk),
        .rst_n(rst_n),
        .stream_valid(stream_valid),
        .stream_data(stream_data),
        .busy(busy),
        .done(done),
        .alarm(alarm),
        .integrity_fail(integrity_fail),
        .acc2_debug() // Left unconnected in top-level
    );

endmodule
