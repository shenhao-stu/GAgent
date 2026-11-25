#pragma once
#include <cstddef>
#include <cstdint>

// Serial is a byte stream: a timeout or overflow must never turn a prefix into a command.
class SerialLine {
  char bytes[512]{};
  size_t used = 0;
  uint32_t lastByte = 0;
  bool dropping = false;
public:
  enum Result { pending, complete, rejected };
  const char *text() const { return bytes; }
  void discard() { used = 0; dropping = true; }
  bool expire(uint32_t now) {
    if (!used || now - lastByte < 1000) return false;
    discard();
    return true;
  }
  Result add(char byte, uint32_t now) {
    lastByte = now;
    if (byte == '\n') {
      if (dropping) { dropping = false; used = 0; return rejected; }
      if (used && bytes[used - 1] == '\r') used--;
      bytes[used] = 0;
      used = 0;
      return complete;
    }
    if (dropping) return pending;
    if (byte == 0 || used == sizeof bytes - 1) { discard(); return pending; }
    bytes[used++] = byte;
    return pending;
  }
};
