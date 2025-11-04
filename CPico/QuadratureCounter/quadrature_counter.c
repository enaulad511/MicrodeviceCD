#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "quadrature_counter.pio.h"

#define PIN_A 2
#define PIN_B 3
int main() {
    stdio_init_all();

    PIO pio = pio0;
    uint offset = pio_add_program(pio, &quadrature_counter_program);
    uint sm = pio_claim_unused_sm(pio, true);

    quadrature_counter_program_init(pio, sm, offset, PIN_A);

    while (true) {
        // Leer el contador desde el registro x
        pio_sm_exec(pio, sm, pio_encode_mov(PIO_X, PIO_X)); // No hace nada, pero mantiene x
        pio_sm_exec(pio, sm, pio_encode_push(false, false)); // Push x a FIFO
        int32_t count = pio_sm_get(pio, sm);

        printf("Posición: %ld\n", count);
        sleep_ms(100);
    }
}