module spi_slave (
    input  logic       clk,
    input  logic       rst_n,

    // SPI Interface (Mode 0)
    input  logic       spi_sclk,
    input  logic       spi_cs_n,
    input  logic       spi_mosi,
    output logic       spi_miso,

    // Byte Stream Interface
    output logic       cs_n_fall_out,
    output logic       rx_valid,
    output logic [7:0] rx_data,
    input  logic [7:0] tx_data
);

    // Oversampling registers for Clock Domain Crossing (CDC)
    // Resolves metastability since spi_* are asynchronous to clk
    logic [2:0] sclk_sync, cs_n_sync, mosi_sync;
    
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sclk_sync <= 3'b000;
            cs_n_sync <= 3'b111; // Active low, so default to 1
            mosi_sync <= 3'b000;
        end else begin
            sclk_sync <= {sclk_sync[1:0], spi_sclk};
            cs_n_sync <= {cs_n_sync[1:0], spi_cs_n};
            mosi_sync <= {mosi_sync[1:0], spi_mosi};
        end
    end

    // Edge detection for oversampled signals
    logic sclk_rise, sclk_fall, cs_n_active, cs_n_fall;
    assign sclk_rise   = ~sclk_sync[2] & sclk_sync[1];
    assign sclk_fall   =  sclk_sync[2] & ~sclk_sync[1];
    assign cs_n_active = ~cs_n_sync[1];
    assign cs_n_fall   =  cs_n_sync[2] & ~cs_n_sync[1];
    assign cs_n_fall_out = cs_n_fall;

    logic [2:0] bit_cnt;
    logic [7:0] rx_shift;
    logic [7:0] tx_shift;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bit_cnt  <= 3'd0;
            rx_shift <= 8'd0;
            tx_shift <= 8'd0;
            rx_valid <= 1'b0;
            rx_data  <= 8'd0;
            spi_miso <= 1'b0;
        end else begin
            rx_valid <= 1'b0; // Default: 1-cycle pulse

            if (cs_n_fall) begin
                // Initialize transmission on CS falling edge
                bit_cnt  <= 3'd0;
                tx_shift <= tx_data;
                spi_miso <= tx_data[7]; // Output MSB first
            end else if (cs_n_active) begin
                if (sclk_rise) begin
                    // Mode 0: Sample MOSI on rising edge
                    rx_shift <= {rx_shift[6:0], mosi_sync[1]};
                    
                    // If we just sampled the 8th bit (bit_cnt == 7)
                    if (bit_cnt == 3'd7) begin
                        rx_valid <= 1'b1;
                        rx_data  <= {rx_shift[6:0], mosi_sync[1]};
                    end
                end

                if (sclk_fall) begin
                    // Mode 0: Shift out new MISO on falling edge
                    bit_cnt <= bit_cnt + 3'd1;
                    
                    if (bit_cnt == 3'd7) begin
                        // Load next byte for subsequent bits
                        tx_shift <= tx_data;
                        spi_miso <= tx_data[7];
                    end else begin
                        tx_shift <= {tx_shift[6:0], 1'b0};
                        spi_miso <= tx_shift[6];
                    end
                end
            end else begin
                // CS_N is high (inactive)
                spi_miso <= 1'b0;
            end
        end
    end

endmodule
