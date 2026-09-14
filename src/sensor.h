#ifndef SENSOR
#define SENSOR

#define GLOVE_IMUS 16

int sensor_scan(void);
int init_shift_reg(void);
void shift_pattern(const struct gpio_dt_spec *dsb, const struct gpio_dt_spec *cp, uint8_t pattern);

#endif