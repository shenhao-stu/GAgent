#pragma once
#include <Arduino.h>
class NimBLEServer;
void hid_begin();
void hid_ble_begin(NimBLEServer *server);
void hid_ble_disconnect(uint16_t handle);
uint32_t hid_request_stop();
uint32_t hid_generation();
void hid_release_all();
void hid_poll_stop();
String hid_run(const String &line, uint32_t generation);
String hid_select(const String &arg);
String hid_rest(const String &arg);  // "HOME_MS PRESS_MS" sets, "" reports: rests before position-dependent reports
const char *hid_transport();
const char *hid_usb_state();
const char *hid_ble_state();
bool hid_ready();
