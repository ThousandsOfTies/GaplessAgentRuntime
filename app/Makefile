CC     = gcc
CFLAGS = -Wall -O2
BIN    = sensor_demo
OBJS   = sensor_demo.o ssd1306.o ssd1306_font.o mfrc522.o vl53l0x.o

# ARM build from this subdirectory: make CC=aarch64-linux-gnu-gcc

$(BIN): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(BIN) $(OBJS)

.PHONY: clean
