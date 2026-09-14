#include <zephyr/logging/log.h>
#include <zephyr/types.h>
#include <zephyr/drivers/spi.h>

#include "sensor.h"

LOG_MODULE_REGISTER(sensor_scan, LOG_LEVEL_DBG);

#define SPI_OP SPI_OP_MODE_MASTER | SPI_TRANSFER_MSB | SPI_WORD_SET(8) | SPI_MODE_CPOL | SPI_MODE_CPHA

#define ZEPHYR_USER_NODE DT_PATH(zephyr_user)

#define IMU_NODE DT_NODELABEL(imu_spi)

static const struct spi_dt_spec imu_spec = SPI_DT_SPEC_GET(IMU_NODE, SPI_OP, 0);

static const struct gpio_dt_spec reg0_dsb = GPIO_DT_SPEC_GET(ZEPHYR_USER_NODE, reg0_dsb_gpios);
static const struct gpio_dt_spec reg0_cp = GPIO_DT_SPEC_GET(ZEPHYR_USER_NODE, reg0_cp_gpios);

static const struct gpio_dt_spec reg1_dsb = GPIO_DT_SPEC_GET(ZEPHYR_USER_NODE, reg1_dsb_gpios);
static const struct gpio_dt_spec reg1_cp = GPIO_DT_SPEC_GET(ZEPHYR_USER_NODE, reg1_cp_gpios);

static struct k_thread sensor_thread_id;
static K_THREAD_STACK_DEFINE(sensor_thread_id_stack, 1024);

K_THREAD_DEFINE(sensor_init_thread_id, 512, sensor_scan, NULL, NULL, NULL, 1, 0, 0);

int init_shift_reg(void)
{
    if (!gpio_is_ready_dt(&reg0_dsb) || !gpio_is_ready_dt(&reg0_cp) ||
        !gpio_is_ready_dt(&reg1_dsb) || !gpio_is_ready_dt(&reg1_cp))
    {
        LOG_ERR("Shift register GPIO pins not ready");
        return -1;
    }

    gpio_pin_configure_dt(&reg0_dsb, GPIO_OUTPUT_ACTIVE);
    gpio_pin_configure_dt(&reg0_cp, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&reg1_dsb, GPIO_OUTPUT_ACTIVE);
    gpio_pin_configure_dt(&reg1_cp, GPIO_OUTPUT_INACTIVE);

    shift_pattern(&reg0_dsb, &reg0_cp, 0xFF);
    shift_pattern(&reg1_dsb, &reg1_cp, 0xFF);

    k_busy_wait(75);
    return 0;
}

void shift_pattern(const struct gpio_dt_spec *dsb, const struct gpio_dt_spec *cp, uint8_t pattern)
{
    for (int i = 7; i >= 0; i--)
    {
        uint8_t bit = (pattern >> i) & 0x01;

        gpio_pin_set_dt(dsb, bit);
        k_busy_wait(75);

        gpio_pin_set_dt(cp, 1);
        k_busy_wait(75);
        gpio_pin_set_dt(cp, 0);
        k_busy_wait(75);
    }
    gpio_pin_set_dt(dsb, 0);
    k_busy_wait(75);
}

int sensor_scan(void)
{
    int err;

    err = spi_is_ready_dt(&imu_spec);
    if (!err)
    {
        LOG_ERR("ERR: SPI device not ready, err %d", err);
        return 0;
    }

    init_shift_reg();

    while (1)
    {

        uint8_t buf[3] = {0};
        uint8_t tx_data[3] = {0};
        struct spi_buf tx_buf = {.buf = tx_data, .len = 3};
        const struct spi_buf_set tx = {.buffers = &tx_buf, .count = 1};
        struct spi_buf rx_buf = {.buf = buf, .len = 3};
        const struct spi_buf_set rx = {.buffers = &rx_buf, .count = 1};

        uint8_t id;
        tx_data[0] = 0x72 | 0x80;
        shift_pattern(&reg0_dsb, &reg0_cp, 0xF7);
        err = spi_transceive_dt(&imu_spec, &tx, &rx);
        shift_pattern(&reg0_dsb, &reg0_cp, 0xFF);
        id = buf[1] ? buf[1] : buf[2];
        LOG_DBG("Read value: 0x%02X, 0x%02X, 0x%02X (0x%02X)", buf[0], buf[1], buf[2], id);
        k_sleep(K_MSEC(1000));
    }

    return 0;
}