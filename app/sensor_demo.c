/*
 * sensor_demo.c — 統合センサーデモアプリ
 *
 * GPIO:
 *   LED1 (GPIO18) — システム ON/OFF 状態表示
 *   LED2 (GPIO24) — RFID 検出時にフラッシュ
 *   Button (GPIO17) — システム ON/OFF 切替
 *
 * I2C-1:
 *   SSD1306 OLED (0x3C) — 状態と最後の UID を表示
 *   VL53L0X (0x29) — 距離測定
 *
 * SPI-0 (CE0):
 *   MFRC-522 (RFID) — ON のときのみスキャン
 *
 * 実機: そのまま動く
 * EC2:  gpio-sim + cuse_i2c でシミュレート
 */

#include "ssd1306.h"
#include "mfrc522.h"
#include "vl53l0x.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define GPIO_CHIP    "/dev/gpiochip0"
#define I2C_DEV      "/dev/i2c-1"
#define SPI_DEV      "/dev/spidev0.0"
#define OLED_ADDR    0x3C

#define LED1_LINE    18  /* status (system ON/OFF) */
#define LED2_LINE    24  /* activity (RFID detected flash) */
#define BTN_LINE     17

#ifndef GPIO_V2_GET_LINE_IOCTL
#ifndef _BITULL
#define _BITULL(x) (1ULL << (x))
#endif

#define GPIO_V2_LINES_MAX 64
#define GPIO_V2_LINE_NUM_ATTRS_MAX 10

#define GPIO_V2_LINE_FLAG_INPUT  _BITULL(2)
#define GPIO_V2_LINE_FLAG_OUTPUT _BITULL(3)

#define GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES 2

struct gpio_v2_line_values {
    __aligned_u64 bits;
    __aligned_u64 mask;
};

struct gpio_v2_line_attribute {
    __u32 id;
    __u32 padding;
    union {
        __aligned_u64 flags;
        __aligned_u64 values;
        __u32 debounce_period_us;
    };
};

struct gpio_v2_line_config_attribute {
    struct gpio_v2_line_attribute attr;
    __aligned_u64 mask;
};

struct gpio_v2_line_config {
    __aligned_u64 flags;
    __u32 num_attrs;
    __u32 padding[5];
    struct gpio_v2_line_config_attribute attrs[GPIO_V2_LINE_NUM_ATTRS_MAX];
};

struct gpio_v2_line_request {
    __u32 offsets[GPIO_V2_LINES_MAX];
    char consumer[GPIO_MAX_NAME_SIZE];
    struct gpio_v2_line_config config;
    __u32 num_lines;
    __u32 event_buffer_size;
    __u32 padding[5];
    __s32 fd;
};

#define GPIO_V2_GET_LINE_IOCTL _IOWR(0xB4, 0x07, struct gpio_v2_line_request)
#define GPIO_V2_LINE_GET_VALUES_IOCTL _IOWR(0xB4, 0x0E, struct gpio_v2_line_values)
#define GPIO_V2_LINE_SET_VALUES_IOCTL _IOWR(0xB4, 0x0F, struct gpio_v2_line_values)
#endif

static volatile int running = 1;
static void on_signal(int s) { (void)s; running = 0; }

/* ---- GPIO helpers ---- */
static int gpio_request_output(int chip, int line, int initial) {
    struct gpio_v2_line_request r = {0};
    r.offsets[0] = line;
    r.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
    r.config.num_attrs = 1;
    r.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
    r.config.attrs[0].attr.values = initial ? 1 : 0;
    r.config.attrs[0].mask = 1;
    r.num_lines = 1;
    strncpy(r.consumer, "sensor_demo", sizeof(r.consumer) - 1);
    return ioctl(chip, GPIO_V2_GET_LINE_IOCTL, &r) < 0 ? -1 : r.fd;
}

static int gpio_request_input(int chip, int line) {
    struct gpio_v2_line_request r = {0};
    r.offsets[0] = line;
    r.config.flags = GPIO_V2_LINE_FLAG_INPUT;
    r.num_lines = 1;
    strncpy(r.consumer, "sensor_demo", sizeof(r.consumer) - 1);
    return ioctl(chip, GPIO_V2_GET_LINE_IOCTL, &r) < 0 ? -1 : r.fd;
}

static void gpio_set(int hfd, int val) {
    struct gpio_v2_line_values d = {
        .bits = val ? 1 : 0,
        .mask = 1,
    };
    ioctl(hfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &d);
}

static int gpio_get(int hfd) {
    struct gpio_v2_line_values d = { .mask = 1 };
    ioctl(hfd, GPIO_V2_LINE_GET_VALUES_IOCTL, &d);
    return (d.bits & 1) ? 1 : 0;
}

/* ---- OLED render ---- */
static void render(
    int oled_fd,
    int system_on,
    const char *uid_text,
    int scan_count,
    int range_mm,
    int range_valid
) {
    char line[32];
    ssd1306_clear(oled_fd);
    ssd1306_put_centered(0, "SENSOR DEMO");
    ssd1306_put_text(0, 2, "System:");
    ssd1306_put_text(60, 2, system_on ? "ON " : "OFF");
    if (range_valid) {
        snprintf(line, sizeof(line), "Range: %d mm", range_mm);
    } else {
        snprintf(line, sizeof(line), "Range: -- mm");
    }
    ssd1306_put_text(0, 3, line);
    ssd1306_put_text(0, 4, "UID:");
    ssd1306_put_text(30, 4, uid_text);
    snprintf(line, sizeof(line), "Scans: %d", scan_count);
    ssd1306_put_text(0, 7, line);
    ssd1306_flush(oled_fd);
}

int main(void) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);

    /* GPIO 初期化 */
    int chip = open(GPIO_CHIP, O_RDWR);
    if (chip < 0) { perror(GPIO_CHIP); return 1; }
    int led1 = gpio_request_output(chip, LED1_LINE, 0);
    int led2 = gpio_request_output(chip, LED2_LINE, 0);
    int btn  = gpio_request_input(chip, BTN_LINE);
    if (led1 < 0 || led2 < 0 || btn < 0) {
        fprintf(stderr, "GPIO setup failed\n");
        return 1;
    }

    /* OLED 初期化 */
    int oled = ssd1306_open(I2C_DEV, OLED_ADDR);
    if (oled < 0) {
        fprintf(stderr, "OLED open failed (continuing without display)\n");
    } else {
        ssd1306_init(oled);
    }

    /* MFRC-522 初期化 */
    int rfid = mfrc522_open(SPI_DEV);
    if (rfid < 0) {
        fprintf(stderr, "MFRC-522 open failed (continuing without RFID)\n");
    } else {
        mfrc522_init(rfid);
    }

    /* VL53L0X 初期化 */
    int range = vl53l0x_open(I2C_DEV);
    if (range < 0) {
        fprintf(stderr, "VL53L0X open failed (continuing without range sensor)\n");
    }

    int system_on = 0;
    int prev_btn  = 0;
    int scan_count = 0;
    char uid_text[32] = "(none)";
    int range_mm = 0;
    int range_valid = 0;
    int range_tick = 0;
    int activity_blink = 0;

    if (oled >= 0) render(oled, system_on, uid_text, scan_count, range_mm, range_valid);

    printf("Sensor Demo started. Press Ctrl+C to quit.\n");
    printf("  LED1 (status)   = GPIO%d\n", LED1_LINE);
    printf("  LED2 (activity) = GPIO%d\n", LED2_LINE);
    printf("  Button          = GPIO%d\n", BTN_LINE);
    printf("  Range           = VL53L0X 0x29\n");

    while (running) {
        /* Button: 立ち上がりエッジで ON/OFF トグル */
        int b = gpio_get(btn);
        if (b && !prev_btn) {
            system_on = !system_on;
            gpio_set(led1, system_on);
            printf("[btn] System %s\n", system_on ? "ON" : "OFF");
            if (oled >= 0) render(oled, system_on, uid_text, scan_count, range_mm, range_valid);
        }
        prev_btn = b;

        /* Range: 500ms ごとに測定して OLED/ログへ反映 */
        if (range >= 0 && range_tick++ >= 5) {
            uint16_t measured = 0;
            range_tick = 0;
            if (vl53l0x_read_range(range, &measured) == 0) {
                range_mm = measured;
                range_valid = 1;
                printf("[range] %d mm\n", range_mm);
            } else {
                range_valid = 0;
                printf("[range] read failed\n");
            }
            if (oled >= 0) render(oled, system_on, uid_text, scan_count, range_mm, range_valid);
        }

        /* RFID スキャン (system_on のみ) */
        if (system_on && rfid >= 0) {
            uint8_t uid[MFRC522_UID_MAX];
            int len = mfrc522_read_uid(rfid, uid);
            if (len > 0) {
                snprintf(uid_text, sizeof(uid_text),
                    "%02X:%02X:%02X:%02X",
                    uid[0], uid[1], uid[2], uid[3]);
                scan_count++;
                printf("[rfid] %s (count=%d)\n", uid_text, scan_count);
                if (oled >= 0) render(oled, system_on, uid_text, scan_count, range_mm, range_valid);
                activity_blink = 6;  /* 6 ticks = 600ms */
            }
        }

        /* LED2 activity blink */
        if (activity_blink > 0) {
            gpio_set(led2, activity_blink & 1);
            activity_blink--;
        } else {
            gpio_set(led2, 0);
        }

        usleep(100000);  /* 100ms */
    }

    /* Cleanup */
    gpio_set(led1, 0);
    gpio_set(led2, 0);
    if (oled >= 0) {
        ssd1306_clear(oled);
        ssd1306_flush(oled);
        ssd1306_close(oled);
    }
    if (rfid >= 0) mfrc522_close(rfid);
    if (range >= 0) vl53l0x_close(range);
    close(led1); close(led2); close(btn); close(chip);
    printf("\nDone.\n");
    return 0;
}
