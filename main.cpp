// RP2350 + original LSM6DS3, Pico SDK 2.x, RP2350 Cortex-M33 target.
// Core 0: PIO event timing + SPI0 RX/TX DMA + sample queue + USB diagnostics.
// Core 1: 15-state floating-point error-state Kalman filter (ESKF).
// Data are acquired from the OUTX_L_G..OUTZ_H_XL registers on gyro DRDY.
// This baseline intentionally DOES NOT enable the sensor's internal FIFO.

#include <cmath>
#include <cstdint>
#include <cstdio>

#include "pico/stdlib.h"
#include "pico/multicore.h"
#include "pico/util/queue.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/pio.h"
#include "hardware/spi.h"
#include "hardware/sync.h"
#include "drdy_period.pio.h"
#include "eskf15.hpp"

namespace {

// Default Raspberry Pi Pico 2 / RP2350 pin mapping. Change for your PCB.
constexpr uint PIN_SPI_RX = 16;      // IMU SDO / MISO
constexpr uint PIN_SPI_CS = 17;      // IMU CS
constexpr uint PIN_SPI_SCK = 18;     // IMU SPC / SCK
constexpr uint PIN_SPI_TX = 19;      // IMU SDI / MOSI
constexpr uint PIN_IMU_INT1 = 20;    // IMU INT1: gyroscope data ready
constexpr uint32_t SPI_BAUD = 8'000'000;    // LSM6DS3 max SPI = 10 MHz
constexpr uint32_t PIO_INSTR_HZ = 4'000'000; // 2 PIO cycles per ~0.5 us tick
constexpr float PI_F = 3.14159265358979323846f;
constexpr float G0 = 9.80665f;

constexpr uint8_t REG_WHO_AM_I = 0x0F;
constexpr uint8_t REG_INT1_CTRL = 0x0D;
constexpr uint8_t REG_CTRL1_XL = 0x10;
constexpr uint8_t REG_CTRL2_G = 0x11;
constexpr uint8_t REG_CTRL3_C = 0x12;
constexpr uint8_t REG_STATUS = 0x1E;
constexpr uint8_t REG_OUTX_L_G = 0x22;
constexpr uint8_t WHO_AM_I_ORIGINAL_LSM6DS3 = 0x69;
// Epoch/timebase are transport metadata, not evidence of global synchronization.
constexpr uint32_t SAMPLE_SOURCE_ID = 0x4c364433; // local label for original LSM6DS3
constexpr uint32_t TIMEBASE_ID = 1; // PIO-relative periods, software-anchored to time_us_64()
constexpr uint32_t CALIBRATION_VERSION = 0; // zero = not calibrated; set after real calibration


constexpr uint DMA_FRAME_BYTES = 13; // command + 12 gyro/accel data bytes
constexpr uint EVENT_QUEUE_CAPACITY = 64; // must be power of 2

struct EdgeEvent {
    uint64_t t_quarter_us; // PIO-relative time in 0.25us units + software epoch
    uint64_t irq_us;     // diagnostic software IRQ time, NOT true edge time
    uint32_t sequence;
};

struct ImuSample {
    uint64_t timestamp_us;
    float ax, ay, az;    // m/s^2
    float gx, gy, gz;    // rad/s
    uint32_t sequence;
};

struct FusionEstimate {
    uint64_t timestamp_us;
    uint32_t sequence;
    float qw, qx, qy, qz;
    float roll_deg, pitch_deg, yaw_deg;
    float a_norm_g;
    float px, py, pz, vx, vy, vz;
    float bgx, bgy, bgz;
    float theta_sigma_x_deg, theta_sigma_y_deg, theta_sigma_z_deg;
    uint32_t rejected_updates;
    uint32_t accepted_updates;
    uint32_t gap_count;
    uint32_t saturation_count;
    uint32_t stale_aiding_updates;
    uint32_t fusion_max_us;
    uint8_t health;
    bool valid_for_control;
    bool reset_required;
    float last_nis;
    bool imu_stationary_candidate;
    uint64_t published_us;
    uint32_t sensor_source_id;
    uint32_t timebase_id;
    uint32_t calibration_version;
};

static PIO g_pio = pio0;
static uint g_sm;
static EdgeEvent g_edge_ring[EVENT_QUEUE_CAPACITY];
static volatile uint32_t g_edge_write = 0;
static volatile uint32_t g_edge_read = 0;
static volatile uint32_t g_event_dropped = 0;
static volatile uint32_t g_edge_sequence = 0;
static uint64_t g_edge_time_quarter_us = 0;
static bool g_have_anchor = false;

static queue_t g_sample_queue;
static queue_t g_estimate_queue;
// ESKF/Joseph covariance operations use several 15x15 matrices on stack.
// A dedicated 16 KiB stack avoids relying on the default core-1 stack size.
alignas(8) static uint32_t g_core1_stack[4096];
static volatile uint32_t g_sample_dropped = 0;
static volatile uint32_t g_read_count = 0;
static volatile uint32_t g_unexpected_periods = 0;

static int g_dma_rx = -1;
static int g_dma_tx = -1;
static uint8_t g_tx[DMA_FRAME_BYTES] = {static_cast<uint8_t>(REG_OUTX_L_G | 0x80)};
static uint8_t g_rx[DMA_FRAME_BYTES] = {};

void spi_cs(bool select) {
    gpio_put(PIN_SPI_CS, !select);
}

void spi_write_reg(uint8_t reg, uint8_t value) {
    uint8_t tx[2] = {static_cast<uint8_t>(reg & 0x7f), value};
    spi_cs(true);
    spi_write_blocking(spi0, tx, sizeof(tx));
    spi_cs(false);
}

uint8_t spi_read_reg(uint8_t reg) {
    uint8_t tx[2] = {static_cast<uint8_t>(reg | 0x80), 0};
    uint8_t rx[2] = {};
    spi_cs(true);
    spi_write_read_blocking(spi0, tx, rx, sizeof(tx));
    spi_cs(false);
    return rx[1];
}

void spi_init_bus() {
    spi_init(spi0, SPI_BAUD);
    spi_set_format(spi0, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(PIN_SPI_RX, GPIO_FUNC_SPI);
    gpio_set_function(PIN_SPI_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_SPI_TX, GPIO_FUNC_SPI);
    gpio_init(PIN_SPI_CS);
    gpio_put(PIN_SPI_CS, 1);
    gpio_set_dir(PIN_SPI_CS, GPIO_OUT);
}

void imu_init() {
    uint8_t id = spi_read_reg(REG_WHO_AM_I);
    if (id != WHO_AM_I_ORIGINAL_LSM6DS3) {
        panic("LSM6DS3 WHO_AM_I=0x%02x, expected 0x69. Check wiring/variant", id);
    }

    // Disable DRDY routing and both sensors while configuring.
    spi_write_reg(REG_INT1_CTRL, 0x00);
    spi_write_reg(REG_CTRL1_XL, 0x00);
    spi_write_reg(REG_CTRL2_G, 0x00);
    spi_write_reg(REG_CTRL3_C, 0x44); // BDU=1, IF_INC=1, four-wire SPI
    // Both sensors at 208 Hz; accel +/-4g, gyro +/-245 deg/s.
    // Accelerometer 4 g sensitivity: 0.122 mg/LSB.
    // Gyro 245 dps sensitivity: 8.75 mdps/LSB.
    spi_write_reg(REG_CTRL1_XL, 0x58);
    spi_write_reg(REG_CTRL2_G, 0x50);
    spi_write_reg(REG_INT1_CTRL, 0x02); // INT1_DRDY_G (gyro is ready after XL)
    sleep_ms(70);

    if (spi_read_reg(REG_CTRL1_XL) != 0x58 ||
        spi_read_reg(REG_CTRL2_G) != 0x50 ||
        spi_read_reg(REG_INT1_CTRL) != 0x02) {
        panic("LSM6DS3 configuration readback mismatch");
    }
    // Read sample once to clear any previously latched data-ready indication.
    uint8_t tx[DMA_FRAME_BYTES] = {static_cast<uint8_t>(REG_OUTX_L_G | 0x80)};
    uint8_t rx[DMA_FRAME_BYTES] = {};
    spi_cs(true);
    spi_write_read_blocking(spi0, tx, rx, DMA_FRAME_BYTES);
    spi_cs(false);
}

void dma_init_spi() {
    g_dma_rx = dma_claim_unused_channel(true);
    g_dma_tx = dma_claim_unused_channel(true);

    dma_channel_config rc = dma_channel_get_default_config(g_dma_rx);
    channel_config_set_transfer_data_size(&rc, DMA_SIZE_8);
    channel_config_set_read_increment(&rc, false);
    channel_config_set_write_increment(&rc, true);
    channel_config_set_dreq(&rc, spi_get_dreq(spi0, false)); // SPI RX DREQ
    dma_channel_configure(g_dma_rx, &rc, g_rx, &spi_get_hw(spi0)->dr,
                          DMA_FRAME_BYTES, false);

    dma_channel_config tc = dma_channel_get_default_config(g_dma_tx);
    channel_config_set_transfer_data_size(&tc, DMA_SIZE_8);
    channel_config_set_read_increment(&tc, true);
    channel_config_set_write_increment(&tc, false);
    channel_config_set_dreq(&tc, spi_get_dreq(spi0, true));  // SPI TX DREQ
    dma_channel_configure(g_dma_tx, &tc, &spi_get_hw(spi0)->dr, g_tx,
                          DMA_FRAME_BYTES, false);
}

// At 208 Hz, this blocking wait is about 13 bytes / 8 MHz plus overhead.
// Interrupts remain enabled; SPI bytes are transferred by DMA, not software.
void spi_read_sample_dma() {
    dma_channel_set_write_addr(g_dma_rx, g_rx, false);
    dma_channel_set_read_addr(g_dma_tx, g_tx, false);
    dma_channel_set_trans_count(g_dma_rx, DMA_FRAME_BYTES, false);
    dma_channel_set_trans_count(g_dma_tx, DMA_FRAME_BYTES, false);
    spi_cs(true);
    dma_start_channel_mask((1u << g_dma_rx) | (1u << g_dma_tx));
    dma_channel_wait_for_finish_blocking(g_dma_rx);
    dma_channel_wait_for_finish_blocking(g_dma_tx);
    while (spi_is_busy(spi0)) { tight_loop_contents(); }
    spi_cs(false);
}

int16_t le_i16(const uint8_t *p) {
    return static_cast<int16_t>(static_cast<uint16_t>(p[0]) |
                                (static_cast<uint16_t>(p[1]) << 8));
}

ImuSample decode_sample(const EdgeEvent &e) {
    // g_rx[0] is received during the register address command; ignore it.
    const uint8_t *b = g_rx + 1;
    constexpr float ACCEL_TO_MSS = 0.000122f * G0;
    constexpr float GYRO_TO_RADS = 0.00875f * (PI_F / 180.0f);
    ImuSample s{};
    s.timestamp_us = (e.t_quarter_us + 2u) / 4u;
    s.sequence = e.sequence;
    s.gx = le_i16(b + 0) * GYRO_TO_RADS;
    s.gy = le_i16(b + 2) * GYRO_TO_RADS;
    s.gz = le_i16(b + 4) * GYRO_TO_RADS;
    s.ax = le_i16(b + 6) * ACCEL_TO_MSS;
    s.ay = le_i16(b + 8) * ACCEL_TO_MSS;
    s.az = le_i16(b + 10) * ACCEL_TO_MSS;
    return s;
}

// The PIO interrupt only handles captured period counters, not SPI or fusion.
void __not_in_flash_func(pio_rx_irq_handler)() {
    while (!pio_sm_is_rx_fifo_empty(g_pio, g_sm)) {
        const uint32_t x = pio_sm_get(g_pio, g_sm);
        const uint64_t now_us = time_us_64();
        if (!g_have_anchor) {
            // First edge defines software time epoch; first PIO count is invalid.
            g_edge_time_quarter_us = now_us * 4;
            g_have_anchor = true;
        } else {
            // Two PIO instructions per decrement at 4 MHz; plus ~3
            // fixed instruction cycles between detection and counter reset.
            // This theoretical correction still needs logic-analyzer validation.
            g_edge_time_quarter_us += 2ull * static_cast<uint32_t>(~x) + 3ull;
        }
        const uint32_t sequence = ++g_edge_sequence;
        const uint32_t h = g_edge_write;
        if (h - g_edge_read >= EVENT_QUEUE_CAPACITY) {
            ++g_event_dropped;
            continue;
        }
        g_edge_ring[h & (EVENT_QUEUE_CAPACITY - 1)] = {
            g_edge_time_quarter_us, now_us, sequence
        };
        __dmb();
        g_edge_write = h + 1;
    }
}

void pio_init_drdy() {
    g_sm = pio_claim_unused_sm(g_pio, true);
    const uint offset = pio_add_program(g_pio, &drdy_period_program);
    pio_gpio_init(g_pio, PIN_IMU_INT1);
    gpio_pull_down(PIN_IMU_INT1);

    pio_sm_config c = drdy_period_program_get_default_config(offset);
    sm_config_set_in_pins(&c, PIN_IMU_INT1);
    sm_config_set_jmp_pin(&c, PIN_IMU_INT1);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX); // 8 event capture words
    sm_config_set_clkdiv(&c, static_cast<float>(clock_get_hz(clk_sys)) /
                                static_cast<float>(PIO_INSTR_HZ));
    pio_sm_init(g_pio, g_sm, offset, &c);
    pio_sm_clear_fifos(g_pio, g_sm);

    const uint irq_num = pio_get_irq_num(g_pio, 0);
    irq_set_exclusive_handler(irq_num, pio_rx_irq_handler);
    pio_set_irqn_source_enabled(g_pio, 0,
        pio_get_rx_fifo_not_empty_interrupt_source(g_sm), true);
    irq_set_enabled(irq_num, true);
    pio_sm_set_enabled(g_pio, g_sm, true);
}

bool pop_edge(EdgeEvent &out) {
    if (g_edge_read == g_edge_write) return false;
    __dmb();
    out = g_edge_ring[g_edge_read & (EVENT_QUEUE_CAPACITY - 1)];
    __dmb();
    ++g_edge_read;
    return true;
}

float clamp_f(float x, float lo, float hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}

void core1_fusion() {
    // Static storage keeps the 15x15 covariance off the small default core stack.
    static inertial::Eskf15 filter;
    uint32_t successful_updates = 0;
    uint32_t max_process_us = 0;
    while (true) {
        ImuSample sample{};
        if (!queue_try_remove(&g_sample_queue, &sample)) {
            tight_loop_contents();
            continue;
        }
        inertial::Imu input{};
        input.timestamp_us = sample.timestamp_us;
        input.accel_mps2 = {sample.ax, sample.ay, sample.az};
        input.gyro_rps = {sample.gx, sample.gy, sample.gz};
        const uint64_t exec_start_us=time_us_64();
        const bool predicted=filter.process(input);
        const uint32_t exec_us=static_cast<uint32_t>(time_us_64()-exec_start_us);
        if(exec_us>max_process_us) max_process_us=exec_us;
        if (predicted) ++successful_updates;
        // Publish invalid/fault state transitions too; otherwise a continuously
        // arriving faulty IMU could leave an old healthy packet on the display.
        if ((predicted && successful_updates % 21 == 0) ||
            (!predicted && filter.health()==inertial::Health::Fault)) {
            const inertial::State &s = filter.state();
            const inertial::Quat &q = s.orientation;
            FusionEstimate estimate{};
            estimate.timestamp_us = filter.state_timestamp_us();
            estimate.sequence = sample.sequence;
            estimate.qw=q.w; estimate.qx=q.x; estimate.qy=q.y; estimate.qz=q.z;
            constexpr float RAD_TO_DEG = 180.0f / PI_F;
            estimate.roll_deg = atan2f(2.0f*(q.w*q.x+q.y*q.z),
                1.0f-2.0f*(q.x*q.x+q.y*q.y))*RAD_TO_DEG;
            estimate.pitch_deg = asinf(clamp_f(2.0f*(q.w*q.y-q.z*q.x),-1,1))*RAD_TO_DEG;
            estimate.yaw_deg = q.yaw()*RAD_TO_DEG;
            estimate.a_norm_g = input.accel_mps2.norm()/G0;
            estimate.px=s.position.x; estimate.py=s.position.y; estimate.pz=s.position.z;
            estimate.vx=s.velocity.x; estimate.vy=s.velocity.y; estimate.vz=s.velocity.z;
            estimate.bgx=s.gyro_bias.x; estimate.bgy=s.gyro_bias.y; estimate.bgz=s.gyro_bias.z;
            estimate.theta_sigma_x_deg=sqrtf(filter.variance(6))*RAD_TO_DEG;
            estimate.theta_sigma_y_deg=sqrtf(filter.variance(7))*RAD_TO_DEG;
            estimate.theta_sigma_z_deg=sqrtf(filter.variance(8))*RAD_TO_DEG;
            estimate.rejected_updates=filter.rejected_updates();
            estimate.accepted_updates=filter.accepted_updates();
            estimate.gap_count=filter.gap_count();
            estimate.saturation_count=filter.saturation_count();
            estimate.stale_aiding_updates=filter.stale_aiding_updates();
            estimate.fusion_max_us=max_process_us;
            estimate.health=static_cast<uint8_t>(filter.health());
            estimate.valid_for_control=filter.control_state_valid();
            estimate.reset_required=filter.reset_required();
            estimate.last_nis=filter.last_nis();
            estimate.imu_stationary_candidate=filter.imu_stationary_candidate();
            estimate.published_us=time_us_64();
            estimate.sensor_source_id=SAMPLE_SOURCE_ID;
            estimate.timebase_id=TIMEBASE_ID;
            estimate.calibration_version=CALIBRATION_VERSION;
            // Best effort only; never block fusion on USB.
            queue_try_add(&g_estimate_queue,&estimate);
        }
    }
}

} // namespace

int main() {
    stdio_init_all();
    sleep_ms(1200); // USB CDC enumeration; does not require a serial host.
    printf("RP2350 LSM6DS3 | PIO edge periods + SPI DMA + dual-core 15-state ESKF\n");

#ifdef PICO_DEFAULT_LED_PIN
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
#endif

    queue_init(&g_sample_queue, sizeof(ImuSample), 64);
    queue_init(&g_estimate_queue, sizeof(FusionEstimate), 8);
    spi_init_bus();
    imu_init();
    dma_init_spi();
    pio_init_drdy();
    multicore_launch_core1_with_stack(core1_fusion, g_core1_stack, sizeof(g_core1_stack));
    printf("WHO_AM_I=0x69; 208Hz gyro+accel; SPI 8MHz; data-ready=GP20; timebase=PIO+SW epoch; cal=0 (UNVERIFIED)\n");
#ifdef RP2350_STREAM_RAW_CSV
    printf("# CAUTION: 208Hz USB CSV output can cause missed frames; debug only\n");
    printf("# timebase=PIO_relative_software_epoch; calibration_id=0; frame=body_xyz; units=m/s2,rad/s\n");
    printf("timestamp_us,ax_mps2,ay_mps2,az_mps2,gx_rps,gy_rps,gz_rps\n");
#endif

    uint64_t last_print_us = time_us_64();
    uint64_t last_edge_us = time_us_64();
    uint64_t previous_ts_us = 0;
    uint32_t last_sequence = 0;
    FusionEstimate latest{};
    bool have_estimate = false;

    while (true) {
        EdgeEvent edge{};
        if (pop_edge(edge)) {
            last_edge_us = time_us_64();
            // Direct sensor registers contain only the latest sample.
            // If we are ever >1 ODR behind, discard stale edge events
            // rather than labeling one register snapshot multiple times.
            if (g_edge_read != g_edge_write) {
                ++g_event_dropped;
                continue;
            }
            const ImuSample sample = [&]() {
                spi_read_sample_dma();
                return decode_sample(edge);
            }();
            ++g_read_count;
#ifdef RP2350_STREAM_RAW_CSV
            // Intentionally OFF by default: USB printing may stall the acquisition loop.
            printf("%llu,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n",
                   static_cast<unsigned long long>(sample.timestamp_us),
                   sample.ax,sample.ay,sample.az,sample.gx,sample.gy,sample.gz);
#endif
            if (previous_ts_us) {
                const uint64_t interval = sample.timestamp_us - previous_ts_us;
                if (interval < 3500 || interval > 6500) ++g_unexpected_periods;
            }
            previous_ts_us = sample.timestamp_us;
            if (last_sequence && sample.sequence != last_sequence + 1) {
                // Gap tracking is implicit in the sequence shown in diagnostics.
            }
            last_sequence = sample.sequence;
            if (!queue_try_add(&g_sample_queue, &sample)) ++g_sample_dropped;
        }

        FusionEstimate new_estimate{};
        while (queue_try_remove(&g_estimate_queue, &new_estimate)) {
            latest = new_estimate;
            have_estimate = true;
        }

        const uint64_t now = time_us_64();
        if (now - last_print_us >= 500'000) {
            last_print_us = now;
#ifdef PICO_DEFAULT_LED_PIN
            gpio_put(PICO_DEFAULT_LED_PIN, (now / 500'000) & 1);
#endif
            if (have_estimate) {
                // Publication health must incorporate stream freshness: a filter
                // cannot self-report a missing sensor when no new IMU arrives.
                const bool stale_input=(now-last_edge_us)>100000u;
                const unsigned effective_health=(stale_input || !latest.valid_for_control) ?
                    static_cast<unsigned>(inertial::Health::Fault) :
                    static_cast<unsigned>(latest.health);
                printf("seq=%lu RPY=(%7.2f,%7.2f,%7.2f) deg "
                       "|a|=%4.2fg bg=(%+.3f,%+.3f,%+.3f) "
                       "sigma_dtheta_body=(%.1f,%.1f,%.1f)deg static=%d "
                       "health=%u valid=%u reset_required=%u age_ms=%.1f max_fusion_us=%lu NIS=%.2f "
                       "updates=%lu/%lu gaps=%lu sat=%lu stale_aid=%lu "
                       "read=%lu edge_drop=%lu sample_drop=%lu period_warn=%lu\n",
                       static_cast<unsigned long>(latest.sequence),
                       latest.roll_deg, latest.pitch_deg, latest.yaw_deg,
                       latest.a_norm_g,
                       latest.bgx, latest.bgy, latest.bgz,
                       latest.theta_sigma_x_deg, latest.theta_sigma_y_deg,
                       latest.theta_sigma_z_deg,
                       static_cast<int>(latest.imu_stationary_candidate),
                       effective_health,
                       static_cast<unsigned>(latest.valid_for_control && !stale_input),
                       static_cast<unsigned>(latest.reset_required),
                       static_cast<double>((now>=latest.timestamp_us)?now-latest.timestamp_us:0u)/1000.0,
                       static_cast<unsigned long>(latest.fusion_max_us),
                       latest.last_nis,
                       static_cast<unsigned long>(latest.accepted_updates),
                       static_cast<unsigned long>(latest.rejected_updates),
                       static_cast<unsigned long>(latest.gap_count),
                       static_cast<unsigned long>(latest.saturation_count),
                       static_cast<unsigned long>(latest.stale_aiding_updates),
                       static_cast<unsigned long>(g_read_count),
                       static_cast<unsigned long>(g_event_dropped),
                       static_cast<unsigned long>(g_sample_dropped),
                       static_cast<unsigned long>(g_unexpected_periods));
            } else {
                printf("Waiting for fusion data; reads=%lu, DRDY GPIO=%d\n",
                       static_cast<unsigned long>(g_read_count),
                       gpio_get(PIN_IMU_INT1));
            }
            if (now - last_edge_us > 1'000'000) {
                printf("WARNING: no gyroscope DRDY events for >1 s\n");
            }
        }
        tight_loop_contents();
    }
}
