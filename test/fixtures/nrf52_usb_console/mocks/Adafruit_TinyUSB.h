#pragma once
#include <stdint.h>
#include "class/cdc/cdc.h"
#define CFG_TUD_CDC 1
#define CFG_TUD_CDC_TX_BUFSIZE 64
bool tud_mounted();
bool tud_connect();
bool tud_disconnect();
bool tud_cdc_n_connected(uint8_t);
uint32_t tud_cdc_n_available(uint8_t);
void tud_cdc_n_read_flush(uint8_t);
uint32_t tud_cdc_n_write_available(uint8_t);
uint32_t tud_cdc_n_write(uint8_t, const void*, uint32_t);
uint32_t tud_cdc_n_write_flush(uint8_t);
uint32_t tud_cdc_n_write_clear(uint8_t);
void tud_cdc_get_line_coding(cdc_line_coding_t*);
void TinyUSB_Port_EnterDFU();
