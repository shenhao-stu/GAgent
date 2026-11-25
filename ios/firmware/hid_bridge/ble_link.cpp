// BLE GATT link for the pure MIT HID bridge (see ble_link.h).
#include "ble_link.h"
#include <atomic>
#include <NimBLEDevice.h>
#include "nimble/nimble/host/include/host/ble_hs.h"
#include "hid_link.h"
#include "src/hid/command.h"

static_assert(MYNEWT_VAL(MSYS_1_BLOCK_COUNT) == 64 && MYNEWT_VAL(MSYS_1_BLOCK_SIZE) == 320,
              "nimble_cfg.h not applied: build with ios/firmware/flash.sh");
static_assert(MYNEWT_VAL(MSYS_2_BLOCK_COUNT) == 0 && MYNEWT_VAL(BLE_TRANSPORT_ACL_FROM_LL_COUNT) == 24, "nimble_cfg.h");
static_assert(MYNEWT_VAL(BLE_ATT_PREFERRED_MTU) == 517 && MYNEWT_VAL(BLE_HS_LOG_LVL) == 5, "nimble_cfg.h");

#define UUID(s) "6e400001-a9e8-4b1b-9c39-6d6f8a3c" s
const size_t CMD_MAX = 512;
const size_t TEXT_MAX = BLE_ATT_ATTR_MAX_LEN;
const uint32_t REPLY_TIMEOUT_MS = 3000;
const uint32_t STATUS_TIMEOUT_MS = 500;
const int MBUF_DATA = MYNEWT_VAL(MSYS_1_BLOCK_SIZE) - 16;
const int MAX_PEERS = 2;

enum { CH_REPLY, CH_STATUS, CH_COUNT };

struct Command {
  uint32_t generation;
  char line[CMD_MAX];
};

struct Text {
  uint16_t len;
  char s[TEXT_MAX];
};

struct StatusText {
  Text full, compact;
};

static NimBLEServer *server;
static NimBLECharacteristic *chars[CH_COUNT], *authChar;
static QueueHandle_t cmdQueue, replyQueue;
static SemaphoreHandle_t statusLock;
static StatusText statusText;
static bool statusDirty;
static std::atomic<int> ctrlPending;
static volatile int peers[MAX_PEERS] = {-1, -1};
static volatile bool subscribed[MAX_PEERS][CH_COUNT];
static std::atomic<uint32_t> replyDrops;

#if DEBUG_SERIAL
#define BLE_LOG(...) Serial.printf("ble: " __VA_ARGS__)
#else
#define BLE_LOG(...) ((void)0)
#endif

static int slotOf(int h) {
  for (int i = 0; i < MAX_PEERS; i++)
    if (peers[i] == h) return i;
  return -1;
}

static int slotFor(int h) {
  int i = slotOf(h);
  if (i < 0 && (i = slotOf(-1)) >= 0) {
    for (int c = 0; c < CH_COUNT; c++) subscribed[i][c] = false;
    peers[i] = h;
  }
  return i;
}

static int peerCount() {
  int n = 0;
  for (int i = 0; i < MAX_PEERS; i++) n += peers[i] >= 0;
  return n;
}

static int indexOf(NimBLECharacteristic *c) {
  for (int i = 0; i < CH_COUNT; i++)
    if (chars[i] == c) return i;
  return -1;
}

static uint16_t recipientMtu(int handle, int ch) {
  int slot = slotOf(handle);
  if (handle < 0 || slot < 0 || !subscribed[slot][ch]) return 0;
  if (ch != CH_STATUS) {
    auto ci = server->getPeerInfoByHandle(handle);
    if (!ci.isEncrypted() || !ci.isBonded()) return 0;
  }
  return server->getPeerMTU(handle);
}

static uint16_t channelMtu(int ch) {
  uint16_t mtu = 0;
  for (int i = 0; i < MAX_PEERS; i++) {
    uint16_t peerMtu = recipientMtu(peers[i], ch);
    if (peerMtu && (!mtu || peerMtu < mtu)) mtu = peerMtu;
  }
  return mtu;
}

static size_t notificationRoom(uint16_t mtu) {
  size_t room = mtu > 3 ? mtu - 3 : 0;
  return room < BLE_ATT_ATTR_MAX_LEN ? room : BLE_ATT_ATTR_MAX_LEN;
}

static void logConn(const char *what, NimBLEConnInfo &ci) {
  BLE_LOG("%s conn %u: interval %.2f ms, latency %u, timeout %u ms, mtu %u, %s\n", what, ci.getConnHandle(),
          ci.getConnInterval() * 1.25f, ci.getConnLatency(), ci.getConnTimeout() * 10u, ci.getMTU(),
          ci.isEncrypted() ? (ci.isBonded() ? "encrypted+bonded" : "encrypted") : "plain");
}

static void tuneLink(uint16_t h) {
  server->setDataLen(h, 251);
  server->updateConnParams(h, 12, 12, 0, 400);
}

class ServerCb : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *s, NimBLEConnInfo &ci) override {
    if (slotFor(ci.getConnHandle()) < 0) { s->disconnect(ci.getConnHandle()); return; }
    logConn("connect", ci);
    tuneLink(ci.getConnHandle());
    if (peerCount() < MAX_PEERS) NimBLEDevice::startAdvertising();
  }
  void onDisconnect(NimBLEServer *s, NimBLEConnInfo &ci, int reason) override {
    int i = slotOf(ci.getConnHandle());
    bool controlled = i >= 0 && subscribed[i][CH_REPLY];
    if (i >= 0) {
      for (int c = 0; c < CH_COUNT; c++) subscribed[i][c] = false;
      peers[i] = -1;
    }
    hid_ble_disconnect(ci.getConnHandle());
    if (controlled) hid_request_stop();
    BLE_LOG("disconnect conn %u, reason 0x%x\n", ci.getConnHandle(), reason);
    NimBLEDevice::startAdvertising();
  }
  void onMTUChange(uint16_t mtu, NimBLEConnInfo &ci) override { BLE_LOG("conn %u: mtu %u\n", ci.getConnHandle(), mtu); }
  void onConnParamsUpdate(NimBLEConnInfo &ci) override { logConn("params", ci); }
  void onPhyUpdate(NimBLEConnInfo &ci, uint8_t tx, uint8_t rx) override {
    BLE_LOG("conn %u: phy tx %uM rx %uM\n", ci.getConnHandle(), tx, rx);
  }
  void onAuthenticationComplete(NimBLEConnInfo &ci) override { logConn("security", ci); }
};

class CharCb : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &ci) override {
    if (c == authChar) return;
    const NimBLEAttValue &raw = c->getValue();
    String v(raw.c_str(), raw.length());
    if (!ci.isEncrypted() || !ci.isBonded()) return;
    if (raw.length() >= CMD_MAX || v.indexOf('\n') >= 0 || raw.length() != strlen(raw.c_str())) return;
    Command command{};
    char *line = command.line;
    strncpy(line, v.c_str(), CMD_MAX - 1);
    const char *sp = strchr(line, ' ');
    command.generation = sp && hid_is_stop(sp + 1) ? hid_request_stop() : hid_generation();
    if (line[0] && xQueueSend(cmdQueue, &command, 0) != pdTRUE) {
      String id = sp ? String(line).substring(0, sp - line) : "0";
      ble_reply(id + " err command queue full");
    }
  }
  void onRead(NimBLECharacteristic *c, NimBLEConnInfo &ci) override {
    if (c != authChar) return;
    static const char kConfig[] = "{\"mode\":\"ble\"}";
    c->setValue((const uint8_t *)kConfig, sizeof(kConfig) - 1);
  }
  void onSubscribe(NimBLECharacteristic *c, NimBLEConnInfo &ci, uint16_t sub) override {
    int i = indexOf(c), p = sub & 1 ? slotFor(ci.getConnHandle()) : slotOf(ci.getConnHandle());
    bool lostControl = i == CH_REPLY && p >= 0 && subscribed[p][CH_REPLY] && !(sub & 1);
    if (i >= 0 && p >= 0) subscribed[p][i] = sub & 1;
    if (lostControl) hid_request_stop();
    BLE_LOG("conn %u: %s %s\n", ci.getConnHandle(), sub & 1 ? "subscribed" : "unsubscribed",
            i == CH_REPLY ? "reply" : "status");
  }
};

static CharCb charCb;

extern "C" uint16_t ble_hs_hci_avail_pkts;
static uint16_t ctrlMax;

static int blocksFor(size_t n) { return (int)((n + 3 + 4 + 4 + 8 + MBUF_DATA - 1) / MBUF_DATA) + 1; }

static bool notifyOne(int slot, int ch, const uint8_t *p, size_t n, uint32_t start, uint32_t timeout_ms) {
  int need = blocksFor(n);
  const int h = peers[slot];
  for (;;) {
    uint16_t mtu = recipientMtu(h, ch);
    if (!mtu || n > notificationRoom(mtu)) return false;
    if (os_msys_num_free() >= need) {
      os_mbuf *om = ble_hs_mbuf_from_flat(p, n);
      int rc = om ? ble_gatts_notify_custom(h, chars[ch]->getHandle(), om) : BLE_HS_ENOMEM;
      if (rc == 0) return true;
      if (rc != BLE_HS_ENOMEM) {
        BLE_LOG("notify ch %d conn %d failed rc=%d\n", ch, h, rc);
        return false;
      }
    }
    if (millis() - start > timeout_ms) return false;
    vTaskDelay(1);
  }
}

static bool notifyRaw(int ch, const uint8_t *p, size_t n, uint32_t timeout_ms) {
  uint32_t start = millis();
  bool any = false;
  for (int i = 0; i < MAX_PEERS; i++) any |= notifyOne(i, ch, p, n, start, timeout_ms);
  return any;
}

static void sendReply(const Text &t) {
  size_t room = notificationRoom(channelMtu(CH_REPLY));
  if (!room) return;
  if (!notifyRaw(CH_REPLY, (const uint8_t *)t.s, t.len < room ? t.len : room, REPLY_TIMEOUT_MS) &&
      channelMtu(CH_REPLY)) {
    replyDrops++;
  }
}

static void sendStatus(const StatusText &status) {
  uint32_t start = millis();
  for (int i = 0; i < MAX_PEERS; i++) {
    size_t room = notificationRoom(recipientMtu(peers[i], CH_STATUS));
    const Text &text = status.full.len <= room ? status.full : status.compact;
    if (!room || text.len > room) continue;
    notifyOne(i, CH_STATUS, (const uint8_t *)text.s, text.len, start, STATUS_TIMEOUT_MS);
  }
}

static void txTask(void *) {
  static Text t;
  static StatusText status;
  for (;;) {
    if (xQueueReceive(replyQueue, &t, pdMS_TO_TICKS(20)) == pdTRUE) {
      sendReply(t);
      ctrlPending--;
    }
    xSemaphoreTake(statusLock, portMAX_DELAY);
    bool due = statusDirty;
    if (due) status = statusText;
    statusDirty = false;
    xSemaphoreGive(statusLock);
    if (due) {
      sendStatus(status);
      ctrlPending--;
    }
  }
}

static void toText(Text &t, const String &s) {
  t.len = s.length() < TEXT_MAX ? s.length() : TEXT_MAX;
  memcpy(t.s, s.c_str(), t.len);
}

void ble_begin(const String &name) {
  cmdQueue = xQueueCreate(6, sizeof(Command));
  replyQueue = xQueueCreate(8, sizeof(Text));
  statusLock = xSemaphoreCreateMutex();
  NimBLEDevice::init(name.c_str());
  NimBLEDevice::setMTU(517);
  NimBLEDevice::setPower(9);
  NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_1M_MASK, BLE_GAP_LE_PHY_1M_MASK);
  NimBLEDevice::setSecurityAuth(true, false, true);  // bonding, Just Works, LE Secure Connections
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
  NimBLEDevice::setSecurityInitKey(BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID);
  NimBLEDevice::setSecurityRespKey(BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID);

  server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCb());
  NimBLEService *svc = server->createService(UUID("0000"));
  NimBLECharacteristic *cmd = svc->createCharacteristic(UUID("0001"),
      NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR | NIMBLE_PROPERTY::WRITE_ENC);
  chars[CH_REPLY] = svc->createCharacteristic(UUID("0002"), NIMBLE_PROPERTY::NOTIFY);
  chars[CH_STATUS] = svc->createCharacteristic(UUID("0003"), NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ);
  // Characteristic 0005 triggers LE Secure Connections bonding when read by GAgent on iPhone.
  authChar = svc->createCharacteristic(UUID("0005"),
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::READ_ENC | NIMBLE_PROPERTY::WRITE_ENC);
  cmd->setCallbacks(&charCb);
  authChar->setCallbacks(&charCb);
  for (auto *c : chars) c->setCallbacks(&charCb);
  hid_ble_begin(server);
  server->start();

  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  NimBLEAdvertisementData data, scan;
  data.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
  data.setCompleteServices(NimBLEUUID(UUID("0000")));
  data.addServiceUUID(NimBLEUUID((uint16_t)0x1812));
  data.setAppearance(0x03c0);
  scan.setName(name.c_str());
  adv->setAdvertisementData(data);
  adv->setScanResponseData(scan);
  NimBLEDevice::startAdvertising();
  xTaskCreatePinnedToCore(txTask, "ble_tx", 3072, NULL, 3, NULL, 1);
  ctrlMax = ble_hs_hci_avail_pkts;
  Serial.printf("ble: %s, msys %d x %d (%d free), acl rx %d, controller acl tx %u, mtu %d\n",
                NimBLEDevice::getVersion(), os_msys_count(), MYNEWT_VAL(MSYS_1_BLOCK_SIZE), os_msys_num_free(),
                MYNEWT_VAL(BLE_TRANSPORT_ACL_FROM_LL_COUNT), ctrlMax, ble_att_preferred_mtu());
}

bool ble_connected() { return peerCount() > 0; }
bool ble_control_connected() { return channelMtu(CH_REPLY) != 0; }

bool ble_drained() {
  if (ble_hs_hci_avail_pkts > ctrlMax) ctrlMax = ble_hs_hci_avail_pkts;
  return ble_hs_hci_avail_pkts >= ctrlMax;
}

bool ble_pop_cmd(String &line, uint32_t &generation, uint32_t wait_ms) {
  Command command;
  if (xQueueReceive(cmdQueue, &command, pdMS_TO_TICKS(wait_ms)) != pdTRUE) return false;
  line = command.line;
  generation = command.generation;
  return true;
}

void ble_reply(const String &line) {
  if (!channelMtu(CH_REPLY)) return;
  Text t;
  toText(t, line);
  ctrlPending++;
  if (xQueueSend(replyQueue, &t, pdMS_TO_TICKS(200)) != pdTRUE) {
    ctrlPending--;
    replyDrops++;
  }
}

void ble_status(const String &full, const String &compact) {
  chars[CH_STATUS]->setValue((const uint8_t *)full.c_str(), full.length());
  if (!channelMtu(CH_STATUS)) return;
  xSemaphoreTake(statusLock, portMAX_DELAY);
  toText(statusText.full, full);
  toText(statusText.compact, compact);
  if (!statusDirty) ctrlPending++;
  statusDirty = true;
  xSemaphoreGive(statusLock);
}

uint32_t ble_reply_drops() { return replyDrops; }
int ble_peers() { return peerCount(); }

uint16_t ble_mtu() {
  uint16_t mtu = 0;
  for (int i = 0; i < MAX_PEERS; i++) {
    int h = peers[i];
    uint16_t m = h >= 0 ? server->getPeerMTU(h) : 0;
    if (m && (!mtu || m < mtu)) mtu = m;
  }
  return mtu ? mtu : 23;
}

uint8_t ble_phy() {
  uint8_t tx = 1, rx = 1;
  int h = peers[0] >= 0 ? peers[0] : peers[1];
  if (h >= 0) ble_gap_read_le_phy(h, &tx, &rx);
  return tx == BLE_GAP_LE_PHY_2M ? 2 : 1;
}

String ble_link_info() {
  String result = "[";
  for (int i = 0; i < MAX_PEERS; i++) {
    int h = peers[i];
    if (h < 0) continue;
    auto ci = server->getPeerInfoByHandle(h);
    uint8_t tx = 0, rx = 0;
    ble_gap_read_le_phy(h, &tx, &rx);
    char json[220];
    snprintf(json, sizeof json,
             "{\"handle\":%d,\"mtu\":%u,\"tx_phy\":%u,\"rx_phy\":%u,\"interval_ms\":%.2f,\"latency\":%u,\"timeout_ms\":%u,\"encrypted\":%s}",
             h, ci.getMTU(), tx, rx, ci.getConnInterval() * 1.25f, ci.getConnLatency(), ci.getConnTimeout() * 10u,
             ci.isEncrypted() ? "true" : "false");
    if (result.length() > 1) result += ',';
    result += json;
  }
  return result + ']';
}

void ble_unpair() {
  for (int i = 0; i < 100 && ctrlPending > 0; i++) vTaskDelay(pdMS_TO_TICKS(10));
  NimBLEDevice::deleteAllBonds();
  ble_store_clear();
  bool any = false;
  for (int i = 0; i < MAX_PEERS; i++)
    if (peers[i] >= 0) { server->disconnect(peers[i]); any = true; }
  if (!any) NimBLEDevice::startAdvertising();
}
