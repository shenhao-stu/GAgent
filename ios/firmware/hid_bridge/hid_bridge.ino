// ESP32-S3 BLE/USB HID Bridge for GAgent iOS (MIT License).
// BLE HID + GATT control service share one board; power via any 5V USB power source.
#include <esp_task_wdt.h>
#include <esp_mac.h>
#include "hid_link.h"
#include "src/hid/serial_line.h"
#include "src/hid/command.h"
#include "ble_link.h"

#ifndef DEBUG_SERIAL
#define DEBUG_SERIAL 0
#endif

const int WATCHDOG_MS = 8000;
String statusJson(bool full);

static String boardSuffix() {
  uint8_t mac[6] = {};
  esp_read_mac(mac, ESP_MAC_BT);
  char suffix[5];
  snprintf(suffix, sizeof suffix, "%02X%02X", mac[4], mac[5]);
  return suffix;
}

const char *resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_TASK_WDT: case ESP_RST_INT_WDT: case ESP_RST_WDT: return "watchdog";
    case ESP_RST_PANIC: return "crash";
    case ESP_RST_SW: return "software";
    case ESP_RST_USB: return "usb";
    default: return "other";
  }
}

String board(const String &line, const String &id, uint32_t generation) {
  int sp = line.indexOf(' ');
  String cmd = sp < 0 ? line : line.substring(0, sp);
  String arg = sp < 0 ? "" : line.substring(sp + 1);
  if (cmd == "status" && !arg.length()) return "ok " + statusJson(true);
  if (cmd == "link" && !arg.length()) return "ok " + ble_link_info();
  if (cmd == "rest") return hid_rest(arg);
  if (cmd == "unpair") {
    ble_reply(id + " ok");
    ble_unpair();
    return "";
  }
  return hid_run(line, generation);
}

String statusJson(bool full) {
  char s[512];
  snprintf(s, sizeof s,
           "{\"hid_caps\":\"mouse,keyboard,consumer,settle\",\"up\":%lu,\"rst\":\"%s\",\"heap\":%u,\"psram\":%u,"
           "\"usb\":\"%s\",\"hid\":\"%s\",\"hid_ready\":%s,\"ble_hid\":\"%s\","
           "\"ble\":{\"mtu\":%u,\"phy\":%u,\"rdrop\":%lu,\"n\":%d}}",
           millis(), resetReason(), (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
           (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM), hid_usb_state(), hid_transport(),
           hid_ready() ? "true" : "false", hid_ble_state(),
           ble_mtu(), ble_phy(), (unsigned long)ble_reply_drops(), ble_peers());
  if (full) return s;
  snprintf(s, sizeof s,
           "{\"up\":%lu,\"usb\":\"%s\",\"hid\":\"%s\",\"hid_ready\":%s,\"ble_hid\":\"%s\",\"ble\":{\"mtu\":%u}}",
           millis(), hid_usb_state(), hid_transport(), hid_ready() ? "true" : "false", hid_ble_state(), ble_mtu());
  return s;
}

void statusTask(void *) {
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(1000));
    if (!ble_connected()) continue;
    ble_status(statusJson(true), statusJson(false));
  }
}

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(115200);
#if DEBUG_SERIAL
  for (int i = 0; i < 30 && !Serial; i++) delay(100);
#endif
  hid_begin();
  esp_task_wdt_config_t wdt = {.timeout_ms = WATCHDOG_MS, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(NULL);

  String name = "ESP32 Agent " + boardSuffix();
  ble_begin(name);
  xTaskCreatePinnedToCore(statusTask, "status", 4096, NULL, 1, NULL, 1);
  Serial.printf("boot %s: free internal heap %u (largest %u), PSRAM %u, reset %s\n", name.c_str(),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM), resetReason());
}

void loop() {
  esp_task_wdt_reset();
  hid_poll_stop();

  static SerialLine serial;
  if (serial.expire(millis())) Serial.println("0 err incomplete serial command discarded");
  String line;
  bool serialReady = false;
  while (Serial.available() && !serialReady) {
    auto result = serial.add((char)Serial.read(), millis());
    if (result == SerialLine::rejected) Serial.println("0 err invalid serial command discarded");
    if (result == SerialLine::complete) { line = serial.text(); serialReady = line.length() > 0; }
  }
  if (serialReady) {
    int sp = line.indexOf(' ');
    String id = sp < 0 ? line : line.substring(0, sp);
    String rest = sp < 0 ? "" : line.substring(sp + 1);
    uint32_t generation = hid_is_stop(rest.c_str()) ? hid_request_stop() : hid_generation();
    Serial.println(id + " " + board(rest, id, generation));
    return;
  }
  uint32_t generation;
  if (!ble_pop_cmd(line, generation, 50)) return;
  int sp = line.indexOf(' ');
  String id = sp < 0 ? line : line.substring(0, sp);
  String rest = sp < 0 ? "" : line.substring(sp + 1);
#if DEBUG_SERIAL
  unsigned long started = millis();
#endif
  String reply = id.toInt() || id == "0" ? board(rest, id, generation) : "err missing request id";
  if (reply.length()) ble_reply(id + " " + reply);
#if DEBUG_SERIAL
  Serial.printf("%s -> %s (%lu ms)\n", rest.startsWith("type ") ? "type [redacted]" : line.c_str(),
                reply.c_str(), millis() - started);
#endif
}
