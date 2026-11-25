#pragma once
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Keyboard-page usages, US layout; no locale or IME assumptions beyond ASCII.
bool hid_ascii(uint8_t ch, uint8_t *usage, uint8_t *modifiers);
bool hid_combo(const char *combo, uint8_t report[8]);
bool hid_pair(const char *arg, long limit, long *a, long *b);
bool hid_ascii_text(const char *text);
bool hid_is_stop(const char *command);
#ifdef __cplusplus
}
#endif
