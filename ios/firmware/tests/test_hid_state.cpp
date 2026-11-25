#include <cstdio>
#include "../hid_bridge/src/hid/state.h"

static int failures;
#define CHECK(c) do { if (!(c)) { failures++; std::printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); } } while (0)

static void latest_stop_is_the_only_resume_boundary() {
  HidStopState state;
  const auto running = state.generation();
  CHECK(!state.cancelled(running));
  const auto stop1 = state.request();
  const auto queuedClick = state.generation();
  const auto stop2 = state.request();
  const auto nextClick = state.generation();
  CHECK(state.cancelled(running));
  CHECK(!state.acknowledge(stop1));
  int presses = 0;
  if (!state.cancelled(queuedClick)) presses++;
  CHECK(presses == 0); // queue [stop1, click, stop2] must never emit the intervening click
  CHECK(state.cancelled(nextClick));
  CHECK(state.acknowledge(stop2));
  if (!state.cancelled(nextClick)) presses++;
  CHECK(presses == 1); // a new command after the newest stop may resume
  CHECK(state.cancelled(queuedClick));
  CHECK(!state.acknowledge(stop1)); // out-of-order old stop cannot revoke a completed newer stop
  CHECK(!state.cancelled(nextClick));
}

static void disconnect_and_rejected_stop_stay_stopped() {
  HidStopState state;
  const auto first = state.request();
  const auto disconnect = state.request();
  CHECK(!state.acknowledge(first));
  CHECK(state.cancelled(disconnect));
  CHECK(state.takeRelease()); // also releases a press while no command is running
  CHECK(!state.takeRelease());
  const auto rejected = state.request(); // stop arrived, but the command queue was full
  CHECK(state.cancelled(rejected));
  CHECK(state.takeRelease());
  CHECK(!state.takeRelease());
  const auto reset = state.request();
  CHECK(state.acknowledge(reset));
  CHECK(!state.cancelled(reset));
  CHECK(state.takeRelease());
  CHECK(!state.takeRelease());
}

static void last_unsubscribe_releases_host_ownership() {
  HidHostState state;
  CHECK(state.snapshot().owner() == -1);
  for (unsigned report = 0; report < 3; report++) CHECK(!state.subscribe(10, report, true));
  state.suspend(10, true);
  CHECK(state.snapshot().suspended());
  CHECK(!state.subscribe(20, 0, true));
  CHECK(state.snapshot().owner() == 10);
  CHECK(!state.subscribe(10, 0, false));
  CHECK(!state.subscribe(10, 1, false));
  CHECK(state.snapshot().owner() == 10 && state.snapshot().subscribed(2));
  CHECK(state.subscribe(10, 2, false)); // signals a stop even though A's app GATT remains connected
  CHECK(state.snapshot().owner() == -1 && !state.snapshot().suspended());
  for (unsigned report = 0; report < 3; report++) CHECK(!state.subscribe(20, report, true));
  CHECK(state.snapshot().owner() == 20);
  for (unsigned report = 0; report < 3; report++) CHECK(state.snapshot().subscribed(report));
  CHECK(!state.subscribe(10, 2, false)); // late A callbacks must not touch B
  CHECK(!state.disconnect(10));
  state.suspend(10, true);
  CHECK(state.snapshot().owner() == 20 && !state.snapshot().suspended());
  CHECK(state.disconnect(20));
  CHECK(state.snapshot().owner() == -1);
  CHECK(!state.subscribe(0xffff, 0, true));
  CHECK(!state.subscribe(30, 3, true));
  CHECK(state.snapshot().owner() == -1);
}

int main() {
  latest_stop_is_the_only_resume_boundary();
  disconnect_and_rejected_stop_stay_stopped();
  last_unsubscribe_releases_host_ownership();
  std::printf(failures ? "%d HID state tests FAILED\n" : "HID stop/owner state tests passed\n", failures);
  return failures != 0;
}
