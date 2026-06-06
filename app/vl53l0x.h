#ifndef VL53L0X_H
#define VL53L0X_H

#include <stdint.h>

int  vl53l0x_open(const char *i2c_dev);
void vl53l0x_close(int fd);
int  vl53l0x_read_range(int fd, uint16_t *range_mm);

#endif
