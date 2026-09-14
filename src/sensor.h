#ifndef SENSOR
#define SENSOR

#define GLOVE_IMUS 16

int sensor_scan(void);
int init_shift_reg(void);
void set_all_high(const struct gpio_dt_spec *dsb, const struct gpio_dt_spec *cp);
void shift_cs(const struct gpio_dt_spec *dsb, const struct gpio_dt_spec *cp);
void set_cs4_low(const struct gpio_dt_spec *dsb, const struct gpio_dt_spec *cp);

#endif