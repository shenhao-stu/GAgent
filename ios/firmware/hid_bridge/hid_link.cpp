#include "hid_link.h"
#include "ble_link.h"
#include <atomic>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include "USB.h"
#include "USBHIDMouse.h"
#include "USBHIDKeyboard.h"
#include "USBHIDConsumerControl.h"
#include "tusb.h"
#include "src/hid/command.h"
#include "src/hid/state.h"
#include "src/hid/report_send.h"
#include "nimble/nimble/host/include/host/ble_hs.h"

// One report per characteristic: IDs occur in the map/reference, never in notify payloads.
enum { MOUSE, KEYBOARD, CONSUMER, REPORTS };
static uint8_t reportMap[] = {
  TUD_HID_REPORT_DESC_MOUSE(HID_REPORT_ID(1)),
  TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(2)),
  TUD_HID_REPORT_DESC_CONSUMER(HID_REPORT_ID(3))
};
static const uint8_t usbReportIDs[] = {HID_REPORT_ID_MOUSE, HID_REPORT_ID_KEYBOARD, HID_REPORT_ID_CONSUMER_CONTROL};
static USBHIDMouse usbMouse;
static USBHIDKeyboard usbKeyboard;
static USBHIDConsumerControl usbConsumer;
static USBHID usb;
static NimBLEServer *bleServer;
static NimBLECharacteristic *reports[REPORTS];
static HidHostState host;
static HidStopState stopState;
static uint32_t activeGeneration; // main-loop command only; BLE callbacks update stopState
static std::atomic<bool> useBLE{true};
static uint8_t buttons;
static Preferences prefs;

class HidCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *c, NimBLEConnInfo &ci, uint16_t sub) override {
    for (int i = 0; i < REPORTS; i++) {
      if (c != reports[i]) continue;
      if (host.subscribe(ci.getConnHandle(), i, sub & 1)) hid_request_stop();
#if DEBUG_SERIAL
      Serial.printf("hid: conn %u report %d subscribed=%u encrypted=%d bonded=%d\n",
                    ci.getConnHandle(), i + 1, sub & 1, ci.isEncrypted(), ci.isBonded());
#endif
    }
  }
  void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &ci) override {
    if (!ci.isEncrypted()) return;
    auto value = c->getValue();
    if (value.size() == 1) host.suspend(ci.getConnHandle(), value[0] == 0); // HID Control Point: suspend / exit suspend
  }
};
static HidCallbacks hidCallbacks;

void hid_begin() {
  prefs.begin("hid", false);
  useBLE = prefs.getBool("ble", true); // power-only USB must not redirect input to a computer
  usbMouse.begin(); usbKeyboard.begin(); usbConsumer.begin();
  USB.productName("HID Bridge");
  USB.begin();
}

void hid_ble_begin(NimBLEServer *server) {
  bleServer = server;
  auto *device = new NimBLEHIDDevice(server);
  device->setManufacturer("ESP32 Agent");
  device->setPnp(2, 0x303a, 0x4001, 0x0100);
  device->setHidInfo(0, 2);
  device->setReportMap(reportMap, sizeof reportMap);
  device->setBatteryLevel(100); // external supply; no battery gauge
  for (int i = 0; i < REPORTS; i++) {
    reports[i] = device->getInputReport(i + 1);
    reports[i]->setCallbacks(&hidCallbacks);
    const uint8_t empty[8] = {};
    reports[i]->setValue(empty, i == MOUSE ? 5 : i == KEYBOARD ? 8 : 2);
  }
  device->getOutputReport(2); // keyboard LEDs (host writes; no physical LEDs on this bridge)
  device->getHidControl()->setCallbacks(&hidCallbacks);
}

void hid_ble_disconnect(uint16_t handle) {
  if (host.disconnect(handle)) hid_request_stop();
}

static bool bleReady(int report) {
  auto state = host.snapshot();
  if (state.owner() < 0 || !bleServer || state.suspended() || !state.subscribed(report)) return false;
  auto ci = bleServer->getPeerInfoByHandle(state.owner());
  return ci.isEncrypted() && ci.isBonded();
}

const char *hid_transport() { return useBLE ? "ble" : "usb"; }
const char *hid_usb_state() { return !tud_mounted() ? "off" : tud_suspended() ? "asleep" : "ok"; }
const char *hid_ble_state() {
  return bleReady(MOUSE) && bleReady(KEYBOARD) && bleReady(CONSUMER) ? "ready" : host.snapshot().owner() >= 0 ? "pairing" : "off";
}
bool hid_ready() { return useBLE ? !strcmp(hid_ble_state(), "ready") : tud_mounted() && !tud_suspended(); }
uint32_t hid_request_stop() { return stopState.request(); }
uint32_t hid_generation() { return stopState.generation(); }
static bool interrupted() { return stopState.cancelled(activeGeneration); }

static bool sendReport(int report, const uint8_t *data, size_t size, bool release = false) {
  if (!release && interrupted()) return false;
  esp_task_wdt_reset();
  if (!useBLE) return tud_mounted() && !tud_suspended() && usb.SendReport(usbReportIDs[report], data, size, 100);
  if (!bleReady(report)) return false;
  const int h = host.snapshot().owner();
  const uint32_t started = millis();
  int rc = 0;
  bool sent = hid_send_report([&] {
    os_mbuf *buffer = ble_hs_mbuf_from_flat(data, size);
    rc = buffer ? ble_gatts_notify_custom(h, reports[report]->getHandle(), buffer) : BLE_HS_ENOMEM;
    if (rc == 0) return HidReportAttempt::accepted; // notify consumes the buffer on success and failure
    return rc == BLE_HS_ENOMEM || rc == BLE_HS_EBUSY ? HidReportAttempt::congested : HidReportAttempt::failed;
  }, [&] { return (release || !interrupted()) && host.snapshot().owner() == h && bleReady(report); },
     [] { return millis(); }, [] { delay(5); esp_task_wdt_reset(); });
  if (!sent)
    Serial.printf("hid: report failed report=%d rc=%d elapsed=%lu free=%d owner=%d ready=%d stopped=%d release=%d\n",
                  report + 1, rc, (unsigned long)(millis() - started), os_msys_num_free(),
                  host.snapshot().owner(), bleReady(report), interrupted(), release);
  return sent;
}

static bool mouseReport(int8_t x = 0, int8_t y = 0, int8_t wheel = 0, int8_t pan = 0, bool release = false) {
  uint8_t report[] = {buttons, (uint8_t)x, (uint8_t)y, (uint8_t)wheel, (uint8_t)pan};
  return sendReport(MOUSE, report, sizeof report, release);
}

// ms the pointer rests after `home` and before a button goes down; `rest` changes them until the next boot.
static uint32_t homeRest = 100, pressRest = 60;

// Lets the phone take in every report sent so far before one that depends on where the pointer is.
static bool settle(uint32_t rest_ms) {
  return hid_settle([] { return !useBLE || ble_drained(); }, [] { return !interrupted(); },
                    [] { return (uint32_t)millis(); }, [] { delay(2); esp_task_wdt_reset(); }, rest_ms);
}

String hid_rest(const String &arg) {
  long home = 0, press = 0;
  if (arg.length()) {
    if (sscanf(arg.c_str(), "%ld %ld", &home, &press) != 2 || home < 0 || press < 0 || home > 2000 || press > 2000)
      return "err usage: rest HOME_MS PRESS_MS (0-2000)";
    homeRest = home;
    pressRest = press;
  }
  return String("ok ") + homeRest + " " + pressRest;
}

void hid_release_all() {
  buttons = 0;
  const uint8_t empty[8] = {};
  mouseReport(0, 0, 0, 0, true);
  sendReport(KEYBOARD, empty, 8, true);
  sendReport(CONSUMER, empty, 2, true);
}

void hid_poll_stop() {
  if (stopState.takeRelease()) hid_release_all();
}

String hid_select(const String &arg) {
  if (!arg.length()) return String("ok ") + hid_transport();
  if (arg != "ble" && arg != "usb") return "err usage: hid ble|usb";
  bool selected = arg == "ble";
  if (selected != useBLE) {
    hid_release_all();
    if (prefs.putBool("ble", selected) != 1) return "err cannot save hid transport";
    useBLE = selected;
  }
  return String("ok ") + hid_transport();
}

static String failure() {
  hid_release_all();
  return interrupted() ? "err stopped" : "err hid report failed (state may be partial; do not retry)";
}

// The phone did not take in the earlier reports in time, so the one that depends on them was not sent.
static String stalled() {
  hid_release_all();
  return interrupted() ? "err stopped" : "err link stalled (earlier reports not delivered; pointer position unknown)";
}

String hid_run(const String &line, uint32_t generation) {
  activeGeneration = generation;
  int space = line.indexOf(' ');
  String cmd = space < 0 ? line : line.substring(0, space);
  String arg = space < 0 ? "" : line.substring(space + 1);
  if (cmd == "ping") return "ok";
  if (cmd == "stop") { hid_release_all(); stopState.acknowledge(generation); return "ok"; }
  if (cmd == "hid" && !arg.length()) return hid_select(arg);
  if (interrupted()) return "err stopped (send stop to reset)";
  if (cmd == "hid") return hid_select(arg);
  long a = 0, b = 0;
  uint8_t keys[8] = {}, empty[8] = {};
  int report = MOUSE;
  long step = 10;  // units per 8 ms report; flick may go faster ("flick dx dy step")
  if (cmd == "move" || cmd == "scroll" || cmd == "flick") {
    int third = arg.indexOf(' ', arg.indexOf(' ') + 1);
    if (cmd == "flick" && third > 0) {
      step = arg.substring(third + 1).toInt();
      if (step < 1 || step > 60) return "err flick step must be 1-60";
      arg = arg.substring(0, third);
    }
    if (!hid_pair(arg.c_str(), cmd == "scroll" ? 127 : 4000, &a, &b)) return "err invalid movement (dx dy required)";
  } else if (cmd == "type") {
    if (arg.length() > 480 || !hid_ascii_text(arg.c_str())) return "err type requires ASCII (max 480 bytes)";
    report = KEYBOARD;
  } else if (cmd == "key") {
    if (!hid_combo(arg.c_str(), keys)) return "err invalid key combo";
    report = KEYBOARD;
  } else if (cmd == "homescreen") report = CONSUMER;
  else if (cmd != "home" && cmd != "press" && cmd != "release" && cmd != "click") return "err unknown command";
  if (useBLE && !bleReady(report)) return "err ble hid not ready (pair in iOS Bluetooth; enable AssistiveTouch)";
  if (!useBLE && tud_suspended()) {
    tud_remote_wakeup();
    for (int i = 0; i < 50 && tud_suspended() && !interrupted(); i++) delay(10);
  }
  if (!useBLE && (!tud_mounted() || tud_suspended())) return "err phone usb asleep (connect and unlock phone)";
  if (cmd == "home") {
    for (int i = 0; i < 50; i++) {
      if (interrupted() || !mouseReport(-127, -127)) return failure();
      delay(8);
    }
    if (!settle(homeRest)) return stalled();  // or the corner swallows the start of the next move
  } else if (cmd == "move" || cmd == "flick") {
    // flick: press, move and release in one command, so no link round trip pauses the finger before
    // lifting; iOS reads a pause at the end of an edge swipe as hold (App Switcher instead of Home).
    if (cmd == "flick") {
      if (!settle(pressRest)) return stalled();
      buttons = 1;
      if (!mouseReport()) return failure();
      delay(8);
    }
    while (a || b) {
      int x = constrain(a, -step, step), y = constrain(b, -step, step);
      if (interrupted() || !mouseReport(x, y)) return failure();
      a -= x; b -= y; delay(8);
    }
    if (cmd == "flick") { buttons = 0; if (!mouseReport()) return failure(); }
  } else if (cmd == "scroll") { if (!mouseReport(0, 0, a, b)) return failure(); }
  else if (cmd == "press" || cmd == "release" || cmd == "click") {
    if (cmd != "release" && !settle(pressRest)) return stalled();  // or the press lands before the last moves
    buttons = cmd == "release" ? 0 : 1;
    if (!mouseReport()) return failure();
    if (cmd == "click") {
      delay(60); buttons = 0;
      if (!mouseReport() || interrupted()) return failure();
    }
  } else if (cmd == "type") {
    for (size_t i = 0; i < arg.length(); i++) {
      hid_ascii(arg[i], &keys[2], &keys[0]);
      if (interrupted() || !sendReport(KEYBOARD, keys, 8)) {
        Serial.printf("hid: type failed index=%u length=%u phase=down\n", (unsigned)i, arg.length());
        return failure();
      }
      delay(8);
      if (!sendReport(KEYBOARD, empty, 8)) {
        Serial.printf("hid: type failed index=%u length=%u phase=up\n", (unsigned)i, arg.length());
        return failure();
      }
      delay(8);
    }
  } else if (cmd == "key") {
    if (!sendReport(KEYBOARD, keys, 8)) return failure();
    delay(30);
    if (!sendReport(KEYBOARD, empty, 8) || interrupted()) return failure();
  } else if (cmd == "homescreen") {
    const uint8_t home[] = {0x23, 0x02};
    if (!sendReport(CONSUMER, home, 2)) return failure();
    delay(40);
    if (!sendReport(CONSUMER, empty, 2) || interrupted()) return failure();
  }
  return "ok";
}
