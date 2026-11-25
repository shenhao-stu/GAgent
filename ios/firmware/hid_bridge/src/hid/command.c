#include "command.h"
#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

bool hid_ascii(uint8_t ch, uint8_t *usage, uint8_t *modifiers) {
  *modifiers = 0;
  if (ch >= 'a' && ch <= 'z') { *usage = ch - 'a' + 4; return true; }
  if (ch >= 'A' && ch <= 'Z') { *usage = ch - 'A' + 4; *modifiers = 2; return true; }
  if (ch >= '1' && ch <= '9') { *usage = ch - '1' + 30; return true; }
  if (ch == '0') { *usage = 39; return true; }
  if (ch == '\n' || ch == '\r') { *usage = 40; return true; }
  if (ch == '\t') { *usage = 43; return true; }
  if (ch == ' ') { *usage = 44; return true; }
  static const char plain[] = "-=[]\\;'`,./";
  static const char shifted[] = "_+{}|:\"~<>?";
  static const uint8_t codes[] = {45, 46, 47, 48, 49, 51, 52, 53, 54, 55, 56};
  for (unsigned i = 0; i < sizeof(codes); i++) {
    if (ch == plain[i] || ch == shifted[i]) {
      *usage = codes[i]; *modifiers = ch == shifted[i] ? 2 : 0; return true;
    }
  }
  static const char digits[] = "!@#$%^&*()";
  const char *digit = ch ? strchr(digits, ch) : NULL;
  if (digit) { *usage = 30 + (uint8_t)(digit - digits); *modifiers = 2; return true; }
  return false;
}

bool hid_ascii_text(const char *text) {
  uint8_t usage, modifiers;
  for (; *text; text++) if (!hid_ascii((uint8_t)*text, &usage, &modifiers)) return false;
  return true;
}

bool hid_combo(const char *combo, uint8_t report[8]) {
  static const struct { const char *name; uint8_t usage, modifier; } keys[] = {
    {"cmd", 0, 8}, {"ctrl", 0, 1}, {"alt", 0, 4}, {"shift", 0, 2},
    {"enter", 40, 0}, {"esc", 41, 0}, {"backspace", 42, 0}, {"tab", 43, 0},
    {"space", 44, 0}, {"right", 79, 0}, {"left", 80, 0}, {"down", 81, 0}, {"up", 82, 0}
  };
  memset(report, 0, 8);
  int count = 0;
  while (*combo) {
    const char *end = strchr(combo, '+');
    size_t n = end ? (size_t)(end - combo) : strlen(combo);
    uint8_t usage = 0, modifier = 0;
    bool found = false;
    if (n == 1) found = hid_ascii((uint8_t)*combo, &usage, &modifier);
    for (unsigned i = 0; !found && i < sizeof(keys) / sizeof(keys[0]); i++) {
      if (strlen(keys[i].name) == n && !memcmp(combo, keys[i].name, n)) {
        usage = keys[i].usage; modifier = keys[i].modifier; found = true;
      }
    }
    if (!found) return false;
    report[0] |= modifier;
    if (usage) {
      bool duplicate = false;
      for (int i = 0; i < count; i++) duplicate |= report[i + 2] == usage;
      if (!duplicate) {
        if (count == 6) return false;
        report[2 + count++] = usage;
      }
    }
    if (!end) return true;
    combo = end + 1;
  }
  return false; // empty or trailing '+' must not partially press a key
}

bool hid_pair(const char *arg, long limit, long *a, long *b) {
  char *end;
  errno = 0;
  *a = strtol(arg, &end, 10);
  if (end == arg || !isspace((unsigned char)*end) || errno) return false;
  arg = end;
  *b = strtol(arg, &end, 10);
  if (end == arg || errno) return false;
  while (isspace((unsigned char)*end)) end++;
  return !*end && *a >= -limit && *a <= limit && *b >= -limit && *b <= limit;
}

bool hid_is_stop(const char *command) {
  return !strcmp(command, "stop") || !strncmp(command, "stop ", 5);
}
