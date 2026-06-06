/*
 * vl53l0x.c — VL53L0X I2C distance sensor driver
 *
 * Real VL53L0X hardware needs the common ST/Pololu-style setup sequence before
 * single-shot measurements work.  The register-only path remains as a fallback
 * for the lightweight CUSE simulator.
 */

#include "vl53l0x.h"

#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define VL53L0X_ADDR            0x29
#define REG_SYSRANGE_START      0x00
#define REG_SYSTEM_SEQUENCE     0x01
#define REG_SYSTEM_INT_CONFIG   0x0A
#define REG_INT_CLEAR           0x0B
#define REG_RESULT_INT_STATUS   0x13
#define REG_RESULT_RANGE_STATUS 0x14
#define REG_RANGE_HIGH          0x1E
#define REG_RANGE_LOW           0x1F
#define REG_GPIO_HV_MUX         0x84
#define REG_MODEL_ID            0xC0
#define REG_REVISION_ID         0xC2
#define REG_FINAL_RATE_LIMIT    0x44
#define REG_MSRC_CONFIG_CONTROL 0x60

struct reg_pair {
    uint8_t reg;
    uint8_t val;
};

static uint8_t stop_variable = 0;
static int full_init_ok = 0;

static int write_reg(int fd, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = {reg, val};
    return write(fd, buf, 2) == 2 ? 0 : -1;
}

static int write_reg16(int fd, uint8_t reg, uint16_t val) {
    uint8_t buf[3] = {reg, (uint8_t)(val >> 8), (uint8_t)(val & 0xFF)};
    return write(fd, buf, 3) == 3 ? 0 : -1;
}

static int write_pairs(int fd, const struct reg_pair *pairs, size_t count) {
    for (size_t i = 0; i < count; i++) {
        if (write_reg(fd, pairs[i].reg, pairs[i].val) != 0) return -1;
    }
    return 0;
}

static int read_reg_checked(int fd, uint8_t reg, uint8_t *val) {
    struct i2c_msg msgs[2] = {
        {.addr = VL53L0X_ADDR, .flags = 0, .len = 1, .buf = &reg},
        {.addr = VL53L0X_ADDR, .flags = I2C_M_RD, .len = 1, .buf = val},
    };
    struct i2c_rdwr_ioctl_data data = {.msgs = msgs, .nmsgs = 2};
    return ioctl(fd, I2C_RDWR, &data) == 2 ? 0 : -1;
}

static uint8_t read_reg(int fd, uint8_t reg) {
    uint8_t val = 0;
    (void)read_reg_checked(fd, reg, &val);
    return val;
}

static int read_multi(int fd, uint8_t reg, uint8_t *buf, size_t len) {
    struct i2c_msg msgs[2] = {
        {.addr = VL53L0X_ADDR, .flags = 0, .len = 1, .buf = &reg},
        {.addr = VL53L0X_ADDR, .flags = I2C_M_RD, .len = (uint16_t)len, .buf = buf},
    };
    struct i2c_rdwr_ioctl_data data = {.msgs = msgs, .nmsgs = 2};
    return ioctl(fd, I2C_RDWR, &data) == 2 ? 0 : -1;
}

static int wait_reg_bits(
    int fd, uint8_t reg, uint8_t mask, uint8_t expected, int tries, int sleep_us
) {
    for (int i = 0; i < tries; i++) {
        uint8_t val = 0;
        if (read_reg_checked(fd, reg, &val) != 0) return -1;
        if ((val & mask) == expected) return 0;
        usleep(sleep_us);
    }
    return -1;
}

static int wait_reg_nonzero(int fd, uint8_t reg, uint8_t mask, int tries, int sleep_us) {
    for (int i = 0; i < tries; i++) {
        uint8_t val = 0;
        if (read_reg_checked(fd, reg, &val) != 0) return -1;
        if (val & mask) return 0;
        usleep(sleep_us);
    }
    return -1;
}

static int poll_interrupt(int fd, int max_tries) {
    for (int i = 0; i < max_tries; i++) {
        if (read_reg(fd, REG_RESULT_INT_STATUS) & 0x07) return 1;
        usleep(10000);
    }
    return 0;
}

static int get_spad_info(int fd, uint8_t *count, int *is_aperture) {
    static const struct reg_pair enter[] = {
        {0x80, 0x01}, {0xFF, 0x01}, {0x00, 0x00}, {0xFF, 0x06},
    };
    static const struct reg_pair setup[] = {
        {0xFF, 0x07}, {0x81, 0x01}, {0x80, 0x01}, {0x94, 0x6B}, {0x83, 0x00},
    };
    static const struct reg_pair leave[] = {
        {0x81, 0x00}, {0xFF, 0x06},
    };
    static const struct reg_pair exit_seq[] = {
        {0xFF, 0x01}, {0x00, 0x01}, {0xFF, 0x00}, {0x80, 0x00},
    };

    int ok = -1;
    if (write_pairs(fd, enter, sizeof(enter) / sizeof(enter[0])) != 0) goto out;
    if (write_reg(fd, 0x83, read_reg(fd, 0x83) | 0x04) != 0) goto out;
    if (write_pairs(fd, setup, sizeof(setup) / sizeof(setup[0])) != 0) goto out;
    if (wait_reg_nonzero(fd, 0x83, 0xFF, 100, 10000) != 0) goto out;
    if (write_reg(fd, 0x83, 0x01) != 0) goto out;

    uint8_t tmp = read_reg(fd, 0x92);
    *count = tmp & 0x7F;
    *is_aperture = (tmp & 0x80) != 0;
    ok = 0;

out:
    (void)write_pairs(fd, leave, sizeof(leave) / sizeof(leave[0]));
    (void)write_reg(fd, 0x83, read_reg(fd, 0x83) & ~0x04);
    (void)write_pairs(fd, exit_seq, sizeof(exit_seq) / sizeof(exit_seq[0]));
    return ok;
}

static int perform_single_ref_calibration(int fd, uint8_t vhv_init_byte) {
    if (write_reg(fd, REG_SYSRANGE_START, (uint8_t)(0x01 | vhv_init_byte)) != 0) return -1;
    if (wait_reg_nonzero(fd, REG_RESULT_INT_STATUS, 0x07, 100, 10000) != 0) return -1;
    if (write_reg(fd, REG_INT_CLEAR, 0x01) != 0) return -1;
    return write_reg(fd, REG_SYSRANGE_START, 0x00);
}

static int vl53l0x_full_init(int fd) {
    static const struct reg_pair pre_spad[] = {
        {0x88, 0x00}, {0x80, 0x01}, {0xFF, 0x01}, {0x00, 0x00},
    };
    static const struct reg_pair post_stop[] = {
        {0x00, 0x01}, {0xFF, 0x00}, {0x80, 0x00},
    };
    static const struct reg_pair spad_setup[] = {
        {0xFF, 0x01}, {0x4F, 0x00}, {0x4E, 0x2C}, {0xFF, 0x00}, {0xB6, 0xB4},
    };
    static const struct reg_pair tuning[] = {
        {0xFF, 0x01}, {0x00, 0x00}, {0xFF, 0x00}, {0x09, 0x00},
        {0x10, 0x00}, {0x11, 0x00}, {0x24, 0x01}, {0x25, 0xFF},
        {0x75, 0x00}, {0xFF, 0x01}, {0x4E, 0x2C}, {0x48, 0x00},
        {0x30, 0x20}, {0xFF, 0x00}, {0x30, 0x09}, {0x54, 0x00},
        {0x31, 0x04}, {0x32, 0x03}, {0x40, 0x83}, {0x46, 0x25},
        {0x60, 0x00}, {0x27, 0x00}, {0x50, 0x06}, {0x51, 0x00},
        {0x52, 0x96}, {0x56, 0x08}, {0x57, 0x30}, {0x61, 0x00},
        {0x62, 0x00}, {0x64, 0x00}, {0x65, 0x00}, {0x66, 0xA0},
        {0xFF, 0x01}, {0x22, 0x32}, {0x47, 0x14}, {0x49, 0xFF},
        {0x4A, 0x00}, {0xFF, 0x00}, {0x7A, 0x0A}, {0x7B, 0x00},
        {0x78, 0x21}, {0xFF, 0x01}, {0x23, 0x34}, {0x42, 0x00},
        {0x44, 0xFF}, {0x45, 0x26}, {0x46, 0x05}, {0x40, 0x40},
        {0x0E, 0x06}, {0x20, 0x1A}, {0x43, 0x40}, {0xFF, 0x00},
        {0x34, 0x03}, {0x35, 0x44}, {0xFF, 0x01}, {0x31, 0x04},
        {0x4B, 0x09}, {0x4C, 0x05}, {0x4D, 0x04}, {0xFF, 0x00},
        {0x44, 0x00}, {0x45, 0x20}, {0x47, 0x08}, {0x48, 0x28},
        {0x67, 0x00}, {0x70, 0x04}, {0x71, 0x01}, {0x72, 0xFE},
        {0x76, 0x00}, {0x77, 0x00}, {0xFF, 0x01}, {0x0D, 0x01},
        {0xFF, 0x00}, {0x80, 0x01}, {0x01, 0xF8}, {0xFF, 0x01},
        {0x8E, 0x01}, {0x00, 0x01}, {0xFF, 0x00}, {0x80, 0x00},
    };

    if (write_pairs(fd, pre_spad, sizeof(pre_spad) / sizeof(pre_spad[0])) != 0) return -1;
    stop_variable = read_reg(fd, 0x91);
    if (write_pairs(fd, post_stop, sizeof(post_stop) / sizeof(post_stop[0])) != 0) return -1;
    if (write_reg(fd, REG_MSRC_CONFIG_CONTROL, read_reg(fd, REG_MSRC_CONFIG_CONTROL) | 0x12) != 0) return -1;
    if (write_reg16(fd, REG_FINAL_RATE_LIMIT, 32) != 0) return -1;
    if (write_reg(fd, REG_SYSTEM_SEQUENCE, 0xFF) != 0) return -1;

    uint8_t spad_count = 0;
    int spad_is_aperture = 0;
    if (get_spad_info(fd, &spad_count, &spad_is_aperture) != 0) return -1;

    uint8_t ref_spad_map[6] = {0};
    if (read_multi(fd, 0xB0, ref_spad_map, sizeof(ref_spad_map)) != 0) return -1;
    if (write_pairs(fd, spad_setup, sizeof(spad_setup) / sizeof(spad_setup[0])) != 0) return -1;

    uint8_t first_spad = spad_is_aperture ? 12 : 0;
    uint8_t enabled = 0;
    for (uint8_t i = 0; i < 48; i++) {
        uint8_t byte_index = i / 8;
        uint8_t bit = (uint8_t)(1u << (i % 8));
        if (i < first_spad || enabled == spad_count) {
            ref_spad_map[byte_index] &= (uint8_t)~bit;
        } else if (ref_spad_map[byte_index] & bit) {
            enabled++;
        }
    }

    uint8_t map_write[7] = {0xB0, ref_spad_map[0], ref_spad_map[1], ref_spad_map[2],
                            ref_spad_map[3], ref_spad_map[4], ref_spad_map[5]};
    if (write(fd, map_write, sizeof(map_write)) != (ssize_t)sizeof(map_write)) return -1;

    if (write_pairs(fd, tuning, sizeof(tuning) / sizeof(tuning[0])) != 0) return -1;
    if (write_reg(fd, REG_SYSTEM_INT_CONFIG, 0x04) != 0) return -1;
    if (write_reg(fd, REG_GPIO_HV_MUX, read_reg(fd, REG_GPIO_HV_MUX) & ~0x10) != 0) return -1;
    if (write_reg(fd, REG_INT_CLEAR, 0x01) != 0) return -1;
    if (write_reg(fd, REG_SYSTEM_SEQUENCE, 0xE8) != 0) return -1;
    if (write_reg(fd, REG_SYSTEM_SEQUENCE, 0x01) != 0) return -1;
    if (perform_single_ref_calibration(fd, 0x40) != 0) return -1;
    if (write_reg(fd, REG_SYSTEM_SEQUENCE, 0x02) != 0) return -1;
    if (perform_single_ref_calibration(fd, 0x00) != 0) return -1;
    return write_reg(fd, REG_SYSTEM_SEQUENCE, 0xE8);
}

static int start_single_measurement(int fd) {
    if (!full_init_ok) return write_reg(fd, REG_SYSRANGE_START, 0x01);

    static const struct reg_pair start_prefix[] = {
        {0x80, 0x01}, {0xFF, 0x01}, {0x00, 0x00},
    };
    static const struct reg_pair start_suffix[] = {
        {0x00, 0x01}, {0xFF, 0x00}, {0x80, 0x00}, {REG_SYSRANGE_START, 0x01},
    };

    if (write_pairs(fd, start_prefix, sizeof(start_prefix) / sizeof(start_prefix[0])) != 0) return -1;
    if (write_reg(fd, 0x91, stop_variable) != 0) return -1;
    if (write_pairs(fd, start_suffix, sizeof(start_suffix) / sizeof(start_suffix[0])) != 0) return -1;
    return wait_reg_bits(fd, REG_SYSRANGE_START, 0x01, 0x00, 100, 10000);
}

int vl53l0x_open(const char *i2c_dev) {
    int fd = open(i2c_dev, O_RDWR);
    if (fd < 0) return -1;
    if (ioctl(fd, I2C_SLAVE, VL53L0X_ADDR) < 0) {
        close(fd);
        return -1;
    }

    uint8_t model_id = read_reg(fd, REG_MODEL_ID);
    uint8_t rev_id = read_reg(fd, REG_REVISION_ID);
    if (model_id != 0xEE) {
        fprintf(stderr, "VL53L0X unexpected ID: model=0x%02X revision=0x%02X\n", model_id, rev_id);
        close(fd);
        return -1;
    }

    full_init_ok = (vl53l0x_full_init(fd) == 0);
    if (!full_init_ok) {
        fprintf(stderr, "VL53L0X full init failed; using legacy register-only mode\n");
    }
    return fd;
}

void vl53l0x_close(int fd) {
    if (fd >= 0) close(fd);
}

int vl53l0x_read_range(int fd, uint16_t *range_mm) {
    if (fd < 0 || !range_mm) return -1;
    if (start_single_measurement(fd) != 0) return -1;
    if (!poll_interrupt(fd, 100)) return -1;

    uint8_t hi = read_reg(fd, REG_RANGE_HIGH);
    uint8_t lo = read_reg(fd, REG_RANGE_LOW);
    (void)read_reg(fd, REG_RESULT_RANGE_STATUS);
    *range_mm = ((uint16_t)hi << 8) | lo;
    (void)write_reg(fd, REG_INT_CLEAR, 0x01);
    return 0;
}
