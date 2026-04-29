#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "arducam/arducam.h"
#include "pico/cyw43_arch.h"
#include "lwip/udp.h"
#include "lwip/pbuf.h"
#include "lwip/ip4_addr.h"

// Define the target IP address of the Wooden Mirror Pico.
// 255.255.255.255 broadcasts to the entire subnet.
#define TARGET_IP "10.48.23.243"
#define TARGET_PORT 8888
#define WIFI_SSID "RedRover"
#define WIFI_PASSWORD ""

uint8_t image_buf[324*324];
uint8_t image_tmp[162*162];
uint8_t image[96*96];

int main() {
	stdio_init_all();

	if (cyw43_arch_init()) {
		printf("WiFi init failed\n");
		return -1;
	}

	cyw43_arch_enable_sta_mode();
	printf("Connecting to WiFi '%s'...\n", WIFI_SSID);
	
	// Fast blink while connecting
	while (cyw43_arch_wifi_connect_timeout_ms(WIFI_SSID, WIFI_PASSWORD, CYW43_AUTH_OPEN, 10000) != 0) {
		printf("Failed to connect, retrying...\n");
		cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);
		sleep_ms(100);
		cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 0);
		sleep_ms(100);
	}
	printf("Connected to WiFi!\n");
	cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, 1);
	
	struct udp_pcb *udp = udp_new();
	ip_addr_t dest_ip;
	ipaddr_aton(TARGET_IP, &dest_ip);

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
	bool led_state = true;

	while (true) {
		cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, led_state);
		led_state = !led_state;
		
		cyw43_arch_poll();

		// Custom capture with timeouts
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
		if (time_reached(timeout)) success = false;

		if (success) {
			// Wait for VSYNC high
			timeout = make_timeout_time_ms(2000);
			while (gpio_get(config.pin_vsync) == false && !time_reached(timeout));
			if (time_reached(timeout)) success = false;
		}

		if (success) {
			dma_channel_start(config.dma_channel);
			pio_sm_set_enabled(config.pio, config.pio_sm, true);

			timeout = make_timeout_time_ms(2000);
			while (dma_channel_is_busy(config.dma_channel) && !time_reached(timeout));

			pio_sm_set_enabled(config.pio, config.pio_sm, false);

			if (time_reached(timeout)) {
				dma_channel_abort(config.dma_channel);
				success = false;
			}
		}

		if (!success) {
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

		static uint8_t frame_id = 0;
		frame_id++;
		
		// Send 96x96 frame in 7 UDP chunks (max UDP payload is ~1472 bytes)
		for (int i = 0; i < 7; i++) {
			int offset = i * 1400;
			int length = 1400;
			if (offset + length > 9216) length = 9216 - offset;
			
			// Payload: 0x55, 0xAA header + frame_id + chunk_index + chunk_data
			uint8_t payload[1404];
			payload[0] = 0x55;
			payload[1] = 0xAA;
			payload[2] = frame_id;
			payload[3] = i; // Chunk index 0 to 6
			memcpy(&payload[4], &image[offset], length);
			
			struct pbuf *p = pbuf_alloc(PBUF_TRANSPORT, length + 4, PBUF_RAM);
			if (p) {
				memcpy(p->payload, payload, length + 4);
				cyw43_arch_lwip_begin();
				udp_sendto(udp, p, &dest_ip, TARGET_PORT);
				cyw43_arch_lwip_end();
				pbuf_free(p);
			}
			// Tiny delay to prevent slamming the WiFi chip and losing packets
			sleep_us(100);
		}
	}

	return 0;
}
