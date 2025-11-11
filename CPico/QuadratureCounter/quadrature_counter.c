
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "quadrature.pio.h"

#define PIN_A 2
#define PIN_B 3
#define PPR 2400

volatile int32_t position = 0;
uint8_t last_state = 0xFF;

void decode_quadrature(uint8_t state) {
    static const int8_t transition_table[16] = {
        0, -1,  1,  0,
        1,  0,  0, -1,
       -1,  0,  0,  1,
        0,  1, -1,  0
    };

    if (last_state == 0xFF) {
        last_state = state;
        return;
    }

    uint8_t index = (last_state << 2) | state;
    position += transition_table[index];
    last_state = state;
}

int main() {
    
    const uint LED_PIN = 25;
    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);
    // stdio_init_all();
    stdio_usb_init();
    sleep_ms(100);
    printf("Iniciando...\n");

    PIO pio = pio0;
    uint offset = pio_add_program(pio, &quadrature_counter_program);
    // uint offset = pio_add_program(pio, &quadrature_counter_program);
    uint sm = pio_claim_unused_sm(pio, true);

    pio_sm_config c = quadrature_counter_program_get_default_config(offset);
    sm_config_set_in_pins(&c, PIN_A);
    sm_config_set_in_shift(&c, true, false, 2); // Auto-push cada 2 bits
    pio_sm_set_consecutive_pindirs(pio, sm, PIN_A, 2, false);
    pio_sm_init(pio, sm, offset, &c);
    pio_sm_set_enabled(pio, sm, true);


    int32_t last_position = 0;
    absolute_time_t last_time = get_absolute_time();
    absolute_time_t last_blink = get_absolute_time();
    bool led_state = false;
    gpio_put(LED_PIN, 1);
    gpio_pull_up(PIN_A);
    gpio_pull_up(PIN_B);


    while (true) {
        // if (!pio_sm_is_rx_fifo_empty(pio, sm)) {
        //     uint8_t state = pio_sm_get(pio, sm) & 0x03;
        //     decode_quadrature(state);
        // }
        while (!pio_sm_is_rx_fifo_empty(pio, sm)) {
            uint8_t state = pio_sm_get(pio, sm) & 0x03;
            printf("Estado leído: %u\n", state);
            decode_quadrature(state);
        }

        if (absolute_time_diff_us(last_time, get_absolute_time()) >= 100000) {
            int32_t delta = position - last_position;
            float rpm = (delta / (float)PPR) * 60.0f * 10.0f;
            printf("Posición: %ld, RPM: %.2f\n", position, rpm);
            last_position = position;
            last_time = get_absolute_time();
        }

        if (absolute_time_diff_us(last_blink, get_absolute_time()) >= 100000) {
            led_state = !led_state;
            gpio_put(LED_PIN, led_state);
            last_blink = get_absolute_time();
        }
    }
}
