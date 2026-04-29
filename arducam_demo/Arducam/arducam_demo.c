#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/i2c.h"
#include "hardware/spi.h"
#include "pico/binary_info.h"
#include "src/arducam.h"
int main() {
    uint8_t id_H, id_L, spiTestVal;
    arducam.systemInit();
    sleep_ms(2000); // Wait for USB serial to enumerate
    printf("\n\n=== ArduCAM Demo Starting ===\n");
    if(arducam.busDetect()){
        printf("ERROR: SPI bus detection failed!\n");
        return 1;
    }
    printf("SPI bus OK\n");
    if(arducam.cameraProbe()){
        printf("ERROR: Camera probe failed!\n");
        return 1;
    }
    printf("Camera detected, initializing...\n");
    arducam.cameraInit();
    arducam.setJpegSize(res_320x240);
    printf("Camera initialized at 320x240 JPEG\n");
    printf("Starting capture loop...\n");
    while (true) {
         singleCapture();
    }
    return 0;
}
