// BLE GATT link to the GAgent iOS app: cmd/reply, status heartbeat, and encrypted pairing characteristic.
// Host: h2zero NimBLE-Arduino; build with ios/firmware/flash.sh (force-includes nimble_cfg.h).
#pragma once
#include <Arduino.h>

void ble_begin(const String &name);
bool ble_connected();
bool ble_control_connected(); // app reply subscription; system HID alone is not a controller
bool ble_drained();           // every notification sent so far has been acknowledged by its peer
bool ble_pop_cmd(String &line, uint32_t &generation, uint32_t wait_ms);
void ble_reply(const String &line);
void ble_status(const String &full, const String &compact);
void ble_unpair();

uint16_t ble_mtu();
uint8_t ble_phy();
String ble_link_info();
uint32_t ble_reply_drops();
int ble_peers();
