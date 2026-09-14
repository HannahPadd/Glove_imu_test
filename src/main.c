#include <zephyr/kernel.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(main_app, LOG_LEVEL_INF);

#define I2C21_NODE DT_NODELABEL(led_controller)

#define SW1_NODE DT_ALIAS(sw1)

#define ZEPHYR_USER_NODE DT_PATH(zephyr_user)

#define IMU_NODE DT_NODELABEL(imu_spi)

static struct k_work button_work;

static const struct i2c_dt_spec i2c_led_controller = I2C_DT_SPEC_GET(I2C21_NODE);

static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(SW1_NODE, gpios);

static struct gpio_callback button_cb_data;

int write_to_i2c(uint8_t reg, uint8_t val)
{
        uint8_t buf[2] = {reg, val};
        int ret = i2c_write_dt(&i2c_led_controller, buf, sizeof(buf));
        if (ret != 0)
        {
                LOG_ERR("I2C Fail [Reg 0x%02X = 0x%02X], Err: %d", reg, val, ret);
        }
        return ret;
}

int read_from_i2c(uint8_t reg, uint8_t *val)
{
        int ret = i2c_write_read_dt(&i2c_led_controller, &reg, sizeof(reg), val, sizeof(*val));
        if (ret != 0)
        {
                LOG_ERR("Failed to read reg 0x%02X [Addr 0x%02X], Err: %d",
                        reg, i2c_led_controller.addr, ret);
        }
        return ret;
}

void dump_lp5817_registers(void)
{
        uint8_t reg_val;
        // Check ENABLE, DEV_CONFIG, MASTER_CURRENT, PWM, and Dot Correction registers
        uint8_t regs_to_check[] = {0x00, 0x01, 0x02, 0x03, 0x04,
                                   0x0D, 0x0E, 0x0F,
                                   0x13,
                                   0x14, 0x15, 0x16,
                                   0x18, 0x19, 0x1A,
                                   0x40};

        LOG_INF("--- LP5817 Register Dump ---");
        for (size_t i = 0; i < ARRAY_SIZE(regs_to_check); i++)
        {
                if (read_from_i2c(regs_to_check[i], &reg_val) == 0)
                {
                        LOG_INF("Reg [0x%02X] = 0x%02X", regs_to_check[i], reg_val);
                }
                else
                {
                        LOG_WRN("Could not read from REG [0x%02X] = 0x%02X", regs_to_check[i], reg_val);
                }
        }
}

void set_led_purple(void)
{
        int ret;

        ret = write_to_i2c(0x00, 0x01);
        if (ret != 0)
        {
                LOG_ERR("Failed to enable LP5817");
                return;
        }
        k_msleep(2);

        ret = write_to_i2c(0x02, 0x3F);
        if (ret != 0)
        {
                LOG_ERR("Failed to set master current");
                return;
        }

        // Set Max current
        write_to_i2c(0x01, 0x01);

        // Enable OUT0, OUT1, OUT2
        write_to_i2c(0x02, 0x07);

        // Set Dot Correction (0x14 - 0x16) to max scaling (0xFF = 100%)
        write_to_i2c(0x14, 0x01); // OUT0_DC (Red)
        write_to_i2c(0x15, 0x00); // OUT1_DC (Green)
        write_to_i2c(0x16, 0x01); // OUT2_DC (Blue)

        // Set Manual PWM Brightness (0x18 - 0x1A)
        LOG_INF("Settings LED colours");
        write_to_i2c(0x18, 0xFF); // OUT0_PWM (Red) = 100%
        write_to_i2c(0x19, 0x00); // OUT1_PWM (Green) = 0%
        write_to_i2c(0x1A, 0xFF); // OUT2_PWM (Blue) = 100%

        // Push settings to output latch: UPDATE_CMD (0x0F) requires key 0x55
        write_to_i2c(0x0F, 0x55);
}

void set_led_blue()
{
        LOG_INF("Settings LED colours");
        write_to_i2c(0x18, 0x00); // OUT0_PWM (Red) = 0%%
        write_to_i2c(0x19, 0x00); // OUT1_PWM (Green) = 0%
        write_to_i2c(0x1A, 0xFF); // OUT2_PWM (Blue) = 100%

        write_to_i2c(0x0F, 0x55);
}

void button_work_handler(struct k_work *work)
{
        set_led_blue();
        k_sleep(K_MSEC(1000));
        set_led_purple();
}

int init_buttons()
{
        int ret;

        if (!device_is_ready(button.port))
        {
                LOG_ERR("Button GPIO device not ready");
                return -1;
        }

        ret = gpio_pin_configure_dt(&button, GPIO_INPUT);
        if (ret < 0)
        {
                LOG_ERR("Failed to configure button pin");
                return ret;
        }
        ret = gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_TO_ACTIVE);

        return 1;
}

void button_pressed(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
        LOG_INF("Button pressed");
        k_work_submit(&button_work);
}

/*
IMU Read/Write loop
Set Imu
        Use shift reg to set CS pin
        Set CS High
Transceive
        Over the MOSI, MISO pins
Close comms
        Set CS to low

Repeat
*/

int main(void)
{
        int ret;

        k_work_init(&button_work, button_work_handler);

        gpio_init_callback(&button_cb_data, button_pressed, BIT(button.pin));
        gpio_add_callback(button.port, &button_cb_data);

        if (!device_is_ready(i2c_led_controller.bus))
        {
                LOG_ERR("I2C bus %s is not ready!\n", i2c_led_controller.bus->name);
                return -1;

                set_led_purple();

                // dump_lp5817_registers();

                ret = init_buttons();
                while (1)
                {
                        k_sleep(K_MSEC(1000));
                }

                return 0;
        }
}