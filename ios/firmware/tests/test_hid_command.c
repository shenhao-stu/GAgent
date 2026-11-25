// Host unit tests for HID ASCII/key-combo/movement command parsing.
#include <stdio.h>
#include <stdint.h>
#include "../hid_bridge/src/hid/command.h"

static int fails;
#define CHECK(c) do { if (!(c)) { fails++; printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); } } while (0)

static void test_hid_input(void) {
  uint8_t usage = 0, modifiers = 0, report[8];
  CHECK(hid_ascii('a', &usage, &modifiers) && usage == 4 && modifiers == 0);
  CHECK(hid_ascii('A', &usage, &modifiers) && usage == 4 && modifiers == 2);
  CHECK(hid_ascii('0', &usage, &modifiers) && usage == 39 && modifiers == 0);
  CHECK(hid_ascii(')', &usage, &modifiers) && usage == 39 && modifiers == 2);
  CHECK(hid_ascii('?', &usage, &modifiers) && usage == 56 && modifiers == 2);
  CHECK(hid_ascii('\\', &usage, &modifiers) && usage == 49 && modifiers == 0);
  for (unsigned ch = 32; ch <= 126; ch++) CHECK(hid_ascii(ch, &usage, &modifiers));
  CHECK(!hid_ascii(0, &usage, &modifiers) && !hid_ascii(128, &usage, &modifiers));
  CHECK(hid_ascii_text("Hello, GAgent!\t2026"));
  CHECK(!hid_ascii_text("Hello 中文"));
  CHECK(hid_combo("cmd+h", report) && report[0] == 8 && report[2] == 11 && report[3] == 0);
  CHECK(hid_combo("shift+cmd+a", report) && report[0] == 10 && report[2] == 4);
  CHECK(hid_combo("a+a", report) && report[2] == 4 && report[3] == 0);
  CHECK(hid_combo("ctrl+alt+enter", report) && report[0] == 5 && report[2] == 40);
  CHECK(!hid_combo("", report) && !hid_combo("cmd+", report) && !hid_combo("+a", report));
  CHECK(!hid_combo("cmd+oops", report) && !hid_combo("a+b+c+d+e+f+g", report));
  CHECK(hid_is_stop("stop") && hid_is_stop("stop now"));
  CHECK(!hid_is_stop("stopping") && !hid_is_stop("type stop"));
  long x, y;
  CHECK(hid_pair("-4000 4000", 4000, &x, &y) && x == -4000 && y == 4000);
  CHECK(!hid_pair("-4001 0", 4000, &x, &y));
  CHECK(!hid_pair("1", 4000, &x, &y) && !hid_pair("1 ", 4000, &x, &y));
  CHECK(!hid_pair("1 2 garbage", 4000, &x, &y));
  CHECK(!hid_pair("1 9999999999999999999999999999999", 4000, &x, &y));
  CHECK(!hid_pair("1 128", 127, &x, &y));
}

int main(void) {
  test_hid_input();
  printf(fails ? "%d FAILED\n" : "HID command parser tests passed\n", fails);
  return fails != 0;
}
