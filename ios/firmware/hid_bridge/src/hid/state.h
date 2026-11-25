#pragma once
#include <atomic>
#include <cstdint>

// Every queued command carries its arrival generation. Only the newest stop may resume input.
class HidStopState {
  std::atomic<uint32_t> requested{0}, acknowledged{0};
  uint32_t released{0}; // only the main loop acknowledges/releases commands
public:
  uint32_t request() { return requested.fetch_add(1) + 1; }
  uint32_t generation() const { return requested.load(); }
  bool takeRelease() {
    uint32_t current = requested.load();
    if (current == released) return false;
    released = current;
    return true;
  }
  bool acknowledge(uint32_t ticket) {
    if (ticket != requested.load()) return false;
    acknowledged = ticket;
    return true;
  }
  bool cancelled(uint32_t ticket) const {
    uint32_t current = requested.load();
    return ticket != current || acknowledged.load() != current;
  }
};

// One atomic snapshot prevents an unsubscribe from clearing a newly claimed owner's reports.
class HidHostState {
  static constexpr uint32_t NONE = 0xffff, MASK = 7u << 16, SUSPENDED = 1u << 19;
  std::atomic<uint32_t> state{NONE};
public:
  struct Snapshot {
    uint32_t value;
    int owner() const { return (value & NONE) == NONE ? -1 : (int)(value & NONE); }
    bool subscribed(unsigned report) const { return report < 3 && (value & (1u << (16 + report))); }
    bool suspended() const { return value & SUSPENDED; }
  };
  Snapshot snapshot() const { return {state.load()}; }

  // True means the last subscription was removed: the caller must interrupt active input.
  bool subscribe(uint16_t handle, unsigned report, bool enabled) {
    if (handle == NONE || report >= 3) return false;
    uint32_t before = state.load(), bit = 1u << (16 + report);
    for (;;) {
      int owner = Snapshot{before}.owner();
      if (owner != handle && !(owner < 0 && enabled)) return false;
      uint32_t after = owner < 0 ? handle : before;
      after = enabled ? after | bit : after & ~bit;
      if (!(after & MASK)) after = NONE;
      if (state.compare_exchange_weak(before, after)) return after == NONE;
    }
  }
  bool disconnect(uint16_t handle) {
    uint32_t before = state.load();
    while (Snapshot{before}.owner() == handle) {
      if (state.compare_exchange_weak(before, NONE)) return true;
    }
    return false;
  }
  void suspend(uint16_t handle, bool value) {
    uint32_t before = state.load();
    while (Snapshot{before}.owner() == handle) {
      uint32_t after = value ? before | SUSPENDED : before & ~SUSPENDED;
      if (state.compare_exchange_weak(before, after)) return;
    }
  }
};
