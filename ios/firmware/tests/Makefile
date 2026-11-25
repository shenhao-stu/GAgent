# Host unit tests for the ESP32-S3 HID bridge's pure C/C++ logic. Usage: make -C ios/firmware/tests
SRC = ../hid_bridge/src
CFLAGS = -std=c11 -Wall -Wextra -g -fsanitize=address,undefined
CXXFLAGS = -std=c++17 -Wall -Wextra -g -fsanitize=address,undefined

all: test_hid_command test_hid_state test_hid_input
	./test_hid_command
	./test_hid_state
	./test_hid_input

test_hid_command: test_hid_command.c $(SRC)/hid/command.c
	$(CC) $(CFLAGS) -o $@ $^

test_hid_state: test_hid_state.cpp $(SRC)/hid/state.h
	$(CXX) $(CXXFLAGS) -o $@ $<

test_hid_input: test_hid_input.cpp $(SRC)/hid/serial_line.h $(SRC)/hid/report_send.h
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -rf test_hid_command test_hid_state test_hid_input *.dSYM

.PHONY: all clean
