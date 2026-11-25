#pragma once
#include <cstdint>

enum class HidReportAttempt { accepted, congested, failed };

// Only a report refused by the host may be retried. Admission is not proof of delivery to the phone.
template<class Send, class Valid, class Clock, class Wait>
bool hid_send_report(Send send, Valid valid, Clock clock, Wait wait) {
  const uint32_t started = clock();
  for (;;) {
    if (!valid()) return false;
    switch (send()) {
      case HidReportAttempt::accepted: return true;
      case HidReportAttempt::failed: return false;
      case HidReportAttempt::congested: break;
    }
    if (clock() - started >= 1500) return false;
    wait();
  }
}

// A report whose effect depends on where the pointer is (a button press, the first move after `home`) must
// not reach the phone together with the moves before it. Measured on iOS 26.6: a press that arrives with
// moves lands where the pointer was before them, and `home`'s last reports are clamped to the screen corner
// together with a move that arrives with them. So wait until the phone has acknowledged everything sent so
// far, then rest. False when the link stays busy for `limit_ms` or `valid` turns false: nothing was sent.
template<class Drained, class Valid, class Clock, class Wait>
bool hid_settle(Drained drained, Valid valid, Clock clock, Wait wait, uint32_t rest_ms, uint32_t limit_ms = 5000) {
  const uint32_t started = clock();
  while (!drained()) {
    if (!valid() || clock() - started >= limit_ms) return false;
    wait();
  }
  const uint32_t rested = clock();
  while (clock() - rested < rest_ms) {
    if (!valid()) return false;
    wait();
  }
  return valid();
}
