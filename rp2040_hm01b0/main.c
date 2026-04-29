#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "tusb.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "arducam/arducam.h"
#include "pico/cyw43_arch.h"

uint8_t image_buf[324*324];
uint8_t image_tmp[162*162];
uint8_t image[96*96];

int main() {
	stdio_init_all();

	if (cyw43_arch_init()) {
		printf("WiFi init failed\n");
		return -1;
	}

	// Wait for USB CDC to connect
	while (!tud_cdc_connected()) {
		cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);
		sleep_ms(250);
		cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0);
		sleep_ms(250);
	}
	cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);
	sleep_ms(500);

	struct arducam_config config;
	config.sccb = i2c0;
	config.sccb_mode = I2C_MODE_16_8;
	config.sensor_address = 0x24;
	config.pin_sioc = PIN_CAM_SIOC;
	config.pin_siod = PIN_CAM_SIOD;
	config.pin_resetb = PIN_CAM_RESETB;
	config.pin_xclk = PIN_CAM_XCLK;
	config.pin_vsync = PIN_CAM_VSYNC;
	config.pin_y2_pio_base = PIN_CAM_Y2_PIO_BASE;
	config.pio = pio0;
	config.pio_sm = 0;
	config.dma_channel = 0;
	config.image_buf = image_buf;
	config.image_buf_size = 324 * 244;

	printf("Initializing camera...\n");
	arducam_init(&config);
	printf("Camera initialized. Starting capture...\n");

	uint16_t x, y, index;
	int frame_count = 0;
	bool led_state = true;

	while (true) {
		cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, led_state);
		led_state = !led_state;

		// Drain incoming serial data so the RX buffer doesn't fill up and hang the USB CDC
		while (getchar_timeout_us(0) != PICO_ERROR_TIMEOUT) {
			// Discard
		}

		// Custom capture with timeouts to avoid hard hangs
		dma_channel_config c = dma_channel_get_default_config(config.dma_channel);
		channel_config_set_read_increment(&c, false);
		channel_config_set_write_increment(&c, true);
		channel_config_set_dreq(&c, pio_get_dreq(config.pio, config.pio_sm, false));
		channel_config_set_transfer_data_size(&c, DMA_SIZE_8);
		
		dma_channel_configure(config.dma_channel, &c, config.image_buf,
			&config.pio->rxf[config.pio_sm], config.image_buf_size, false);

		absolute_time_t timeout;
		bool success = true;

		// Wait for VSYNC low
		timeout = make_timeout_time_ms(2000);
		while (gpio_get(config.pin_vsync) == true && !time_reached(timeout));
		if (time_reached(timeout)) {
			printf("ERROR: Timeout waiting for VSYNC low\n");
			success = false;
		}

		if (success) {
			// Wait for VSYNC high
			timeout = make_timeout_time_ms(2000);
			while (gpio_get(config.pin_vsync) == false && !time_reached(timeout));
			if (time_reached(timeout)) {
				printf("ERROR: Timeout waiting for VSYNC high\n");
				success = false;
			}
		}

		if (success) {
			dma_channel_start(config.dma_channel);
			pio_sm_set_enabled(config.pio, config.pio_sm, true);

			timeout = make_timeout_time_ms(2000);
			while (dma_channel_is_busy(config.dma_channel) && !time_reached(timeout));

			pio_sm_set_enabled(config.pio, config.pio_sm, false);

			if (time_reached(timeout)) {
				printf("ERROR: DMA timeout (got partial frame)\n");
				// Abort DMA
				dma_channel_abort(config.dma_channel);
				success = false;
			}
		}

		if (!success) {
			// If camera failed, wait a bit and re-init
			sleep_ms(1000);
			arducam_init(&config);
			continue;
		}

		// Downsample 324x244 -> 162x122
		index = 0;
		for(y = 0; y < 244; y += 2){
			for(x = (1+y)%2; x < 324; x += 2){
				image_tmp[index++] = config.image_buf[y*324+x];
			}
		}
		// Crop center 96x96
		index = 0;
		for(y = 13; y < 109; y++){
			for(x = 33; x < 129; x++){
				image[index++] = image_tmp[y*162+x];
			}
		}

		// Send frame: 0x55 0xAA header + 96*96 grayscale bytes
		putchar_raw(0x55);
		putchar_raw(0xAA);
		for(int j = 0; j < 96*96; j++){
			putchar_raw(image[j]);
		}
		stdio_flush();

		frame_count++;
		sleep_ms(1);
	}

	return 0;
}
