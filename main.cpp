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
#include "calibration.hpp"
#include "aiding.hpp"
#include "runtime_health.hpp"
#include "runtime_metrics.hpp"
#include "lsm6ds3_fifo.hpp"
#include "binary_log.hpp"
#ifdef RP2350_STREAM_BINARY_LOG
#include "pico/stdio_usb.h"
#endif

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
constexpr uint32_t CALIBRATION_VERSION = 0; // 0: identity, not a measured calibration
constexpr uint32_t NOMINAL_SAMPLE_PERIOD_US = 4808; // diagnostic service interval only
// Calibration must be version-controlled and checked against real data before
// deployment. Identity is a placeholder, NOT a claim of calibrated accuracy.
static const inertial::SensorCalibration g_calibration{};


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
    uint32_t fusion_p50_us;
    uint32_t fusion_p95_us;
    uint32_t fusion_p99_us;
    uint32_t fusion_max_us;
    uint32_t sample_publication_p50_us;
    uint32_t sample_publication_p95_us;
    uint32_t sample_publication_p99_us;
    uint32_t sample_publication_max_us;
    uint32_t core1_stack_highwater_bytes;
    uint32_t last_aid_source_id;
    uint64_t last_aid_timestamp_us;
    uint8_t accepted_aid_mask;
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
static volatile uint32_t g_edge_queue_highwater = 0;
static volatile uint32_t g_edge_sequence = 0;
static uint64_t g_edge_time_quarter_us = 0;
static bool g_have_anchor = false;

static queue_t g_sample_queue;
static queue_t g_estimate_queue;
// ESKF/Joseph covariance operations use several 15x15 matrices on stack.
// A dedicated 16 KiB stack avoids relying on the default core-1 stack size.
alignas(8) static uint32_t g_core1_stack[4096];
static volatile uint32_t g_sample_dropped = 0;
static volatile uint32_t g_sample_period_service_overruns = 0;
static volatile uint32_t g_sample_queue_highwater = 0;
static volatile uint32_t g_estimate_queue_highwater = 0;
static volatile uint32_t g_read_count = 0;
static volatile uint32_t g_unexpected_periods = 0;
static volatile uint32_t g_calibration_failed = 0;
static volatile uint32_t g_fifo_resets = 0;
static volatile uint32_t g_fifo_bus_errors = 0;
static volatile uint32_t g_fifo_backfilled = 0;
static volatile uint32_t g_fifo_discarded_frames = 0;
static volatile uint32_t g_fifo_timestamp_errors = 0;
static inertial::metrics::LatencyHistogram g_fusion_latency;
static inertial::metrics::LatencyHistogram g_sample_publication_latency;
static inertial::metrics::LatencyHistogram g_spi_transfer_latency;
static inertial::metrics::LatencyHistogram g_acquisition_service_latency;
static inertial::metrics::LatencyHistogram g_edge_dispatch_latency;
static uint32_t g_fifo_sequence = 0;
#ifdef RP2350_USE_FIFO
static bool g_fifo_needs_resync = false;
void account_fifo_discard(uint32_t frames) {
    g_fifo_discarded_frames += frames;
    g_fifo_sequence += frames;
}
#endif

static int g_dma_rx = -1;
static int g_dma_tx = -1;
static uint8_t g_tx[DMA_FRAME_BYTES] = {static_cast<uint8_t>(REG_OUTX_L_G | 0x80)};
static uint8_t g_rx[DMA_FRAME_BYTES] = {};

uint32_t elapsed_us_saturated(uint64_t start_us,uint64_t end_us) {
    if(end_us<start_us) return 0;
    const uint64_t elapsed=end_us-start_us;
    return elapsed>UINT32_MAX?UINT32_MAX:static_cast<uint32_t>(elapsed);
}

void update_queue_highwater(volatile uint32_t &highwater,queue_t *queue) {
    // Occupancy is sampled immediately after a successful insert; a concurrent
    // consumer can reduce the level before this snapshot is taken.
    const uint32_t level=queue_get_level(queue);
    if(level>highwater) highwater=level;
}

uint32_t core1_stack_highwater_bytes() {
    constexpr uint32_t sentinel=0xa55aa55au;
    const volatile uint32_t *stack=g_core1_stack;
    uint32_t first_used=4096;
    for(uint32_t i=0;i<4096;i++){
        if(stack[i]!=sentinel){first_used=i;break;}
    }
    return (4096u-first_used)*sizeof(uint32_t);
}

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

// The mockable FIFO driver has no Pico SDK dependency.
// This adapter uses blocking SPI transfers at a bounded 32-frame maximum;
// it is only built when FIFO mode is selected.
#ifdef RP2350_USE_FIFO
class PicoSpiRegisterBus final : public lsm6ds3::Bus {
public:
    bool write_reg(uint8_t reg,uint8_t value) override {
        spi_write_reg(reg,value);
        return true;
    }
    bool read_burst(uint8_t reg,uint8_t *data,std::size_t count) override {
        if (!data || count==0 || count>384) return false;
        uint8_t tx[385]{};
        uint8_t rx[385]{};
        tx[0]=static_cast<uint8_t>(reg|0x80);
        const uint64_t start_us=time_us_64();
        spi_cs(true);
        const int n=spi_write_read_blocking(spi0,tx,rx,count+1);
        spi_cs(false);
        g_spi_transfer_latency.observe(elapsed_us_saturated(start_us,time_us_64()));
        if (n!=static_cast<int>(count+1)) return false;
        for(std::size_t i=0;i<count;i++) data[i]=rx[i+1];
        return true;
    }
};
static PicoSpiRegisterBus g_fifo_bus;
static lsm6ds3::Fifo g_fifo(g_fifo_bus);
#endif

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
    const uint64_t start_us=time_us_64();
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
    g_spi_transfer_latency.observe(elapsed_us_saturated(start_us,time_us_64()));
}

int16_t le_i16(const uint8_t *p) {
    return static_cast<int16_t>(static_cast<uint16_t>(p[0]) |
                                (static_cast<uint16_t>(p[1]) << 8));
}

bool calibrate_sample(ImuSample &s) {
    inertial::Imu raw{s.timestamp_us,{s.ax,s.ay,s.az},{s.gx,s.gy,s.gz}};
    inertial::Imu calibrated{};
    // Temperature cannot be assumed. It is not read by this firmware yet;
    // calibration with temperature_compensation=true therefore rejects input.
    if (!g_calibration.apply(raw,NAN,calibrated)) {
        ++g_calibration_failed;
        return false;
    }
    s.ax=calibrated.accel_mps2.x;s.ay=calibrated.accel_mps2.y;s.az=calibrated.accel_mps2.z;
    s.gx=calibrated.gyro_rps.x;s.gy=calibrated.gyro_rps.y;s.gz=calibrated.gyro_rps.z;
    return true;
}
#ifdef RP2350_USE_FIFO
ImuSample decode_fifo_frame(const lsm6ds3::Frame &f,uint64_t timestamp_us,uint32_t sequence) {
    constexpr float ACCEL_TO_MSS=0.000122f*G0;
    constexpr float GYRO_TO_RADS=0.00875f*(PI_F/180.0f);
    ImuSample s{};
    s.timestamp_us=timestamp_us;s.sequence=sequence;
    s.gx=f.gyro[0]*GYRO_TO_RADS;s.gy=f.gyro[1]*GYRO_TO_RADS;s.gz=f.gyro[2]*GYRO_TO_RADS;
    s.ax=f.accel[0]*ACCEL_TO_MSS;s.ay=f.accel[1]*ACCEL_TO_MSS;s.az=f.accel[2]*ACCEL_TO_MSS;
    return s;
}
#endif

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
        const uint32_t queued=h+1u-g_edge_read;
        if(queued>g_edge_queue_highwater) g_edge_queue_highwater=queued;
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

#ifdef RP2350_STREAM_BINARY_LOG
static uint32_t g_binary_pending_drops=0;
static bool g_binary_header_sent=false;

void count_binary_drop() {
    if(g_binary_pending_drops!=UINT32_MAX) ++g_binary_pending_drops;
}

bool emit_binary_bytes(const uint8_t *data,std::size_t count) {
    // DEBUG transport. Pico stdio USB may block and can time out without
    // reporting a partial write. This boolean only detects disconnected state.
    // Keep all output on stdio's supported path; do not bypass the USB lock.
    if(!stdio_usb_connected()) return false;
    for(std::size_t i=0;i<count;i++) putchar_raw(data[i]);
    return stdio_usb_connected();
}

bool ensure_binary_header() {
    if(g_binary_header_sent) return true;
    if(!stdio_usb_connected()) return false;
    uint8_t bytes[imu_log::kHeaderSize]{};
    imu_log::encode_header({SAMPLE_SOURCE_ID,TIMEBASE_ID,CALIBRATION_VERSION,208},bytes);
    g_binary_header_sent=emit_binary_bytes(bytes,sizeof(bytes));
    return g_binary_header_sent;
}

void emit_binary_sample(const ImuSample &s,bool timestamp_backfilled=false) {
    if(!stdio_usb_connected()){
        g_binary_header_sent=false;
        count_binary_drop();
        return;
    }
    if(!ensure_binary_header()){
        count_binary_drop();
        return;
    }
    uint8_t bytes[imu_log::kRecordSize]{};
    imu_log::Record record{};
    record.capture_us=s.timestamp_us;
    record.publication_us=time_us_64();
    record.sequence=s.sequence;
    record.flags=
#ifdef RP2350_USE_FIFO
        1u |
#endif
        (timestamp_backfilled?2u:0u);
    record.dropped_records_before=g_binary_pending_drops;
    record.accel_mps2={s.ax,s.ay,s.az};record.gyro_rps={s.gx,s.gy,s.gz};
    imu_log::encode_record(record,bytes);
    if(emit_binary_bytes(bytes,sizeof(bytes))) g_binary_pending_drops=0;
    else {count_binary_drop();g_binary_header_sent=false;}
}
#endif

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
        g_fusion_latency.observe(exec_us);
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
            estimate.fusion_p50_us=g_fusion_latency.percentile_upper_bound(5000);
            estimate.fusion_p95_us=g_fusion_latency.percentile_upper_bound(9500);
            estimate.fusion_p99_us=g_fusion_latency.percentile_upper_bound(9900);
            estimate.fusion_max_us=max_process_us;
            estimate.core1_stack_highwater_bytes=core1_stack_highwater_bytes();
            estimate.last_aid_source_id=filter.last_accepted_aid_source();
            estimate.last_aid_timestamp_us=filter.last_accepted_aid_timestamp_us();
            estimate.accepted_aid_mask=filter.accepted_aid_mask();
            estimate.health=static_cast<uint8_t>(filter.health());
            estimate.valid_for_control=filter.control_state_valid();
            estimate.reset_required=filter.reset_required();
            estimate.last_nis=filter.last_nis();
            estimate.imu_stationary_candidate=filter.imu_stationary_candidate();
            estimate.published_us=time_us_64();
            g_sample_publication_latency.observe(elapsed_us_saturated(estimate.timestamp_us,estimate.published_us));
            estimate.sample_publication_p50_us=g_sample_publication_latency.percentile_upper_bound(5000);
            estimate.sample_publication_p95_us=g_sample_publication_latency.percentile_upper_bound(9500);
            estimate.sample_publication_p99_us=g_sample_publication_latency.percentile_upper_bound(9900);
            estimate.sample_publication_max_us=g_sample_publication_latency.max_us();
            estimate.sensor_source_id=SAMPLE_SOURCE_ID;
            estimate.timebase_id=TIMEBASE_ID;
            estimate.calibration_version=CALIBRATION_VERSION;
            // Best effort only; never block fusion on USB.
            if(queue_try_add(&g_estimate_queue,&estimate))
                update_queue_highwater(g_estimate_queue_highwater,&g_estimate_queue);
        }
    }
}

} // namespace

int main() {
    stdio_init_all();
    sleep_ms(1200); // USB CDC enumeration; does not require a serial host.
#ifndef RP2350_STREAM_BINARY_LOG
    printf("RP2350 LSM6DS3 | PIO edge periods + SPI DMA + dual-core 15-state ESKF\n");
#endif

#ifdef PICO_DEFAULT_LED_PIN
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
#endif

    queue_init(&g_sample_queue, sizeof(ImuSample), 64);
    queue_init(&g_estimate_queue, sizeof(FusionEstimate), 8);
    spi_init_bus();
    if (!g_calibration.valid() || g_calibration.calibration_id!=CALIBRATION_VERSION)
        panic("Invalid calibration version, axes or matrix");
    imu_init();
#ifdef RP2350_USE_FIFO
    if (!g_fifo.configure()) panic("FIFO configuration failed");
#else
    dma_init_spi();
#endif
    pio_init_drdy();
    volatile uint32_t *stack_words=g_core1_stack;
    for(uint32_t i=0;i<4096u;i++) stack_words[i]=0xa55aa55au;
    multicore_launch_core1_with_stack(core1_fusion, g_core1_stack, sizeof(g_core1_stack));
#ifdef RP2350_STREAM_BINARY_LOG
    // Header is sent lazily when a host connects; each reconnect starts a new log.
#else
    printf("WHO_AM_I=0x69; 208Hz gyro+accel; SPI 8MHz; data-ready=GP20; timebase=PIO+SW epoch; cal=0 (UNVERIFIED)\n");
#endif
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
        // Centralized dispatch for both legacy register DMA and FIFO acquisition.
        // Avoid USB output in the critical path except when debug logging is selected.
        auto dispatch_sample=[&](ImuSample &sample,bool backfilled) {
            if(!calibrate_sample(sample)) return;
            ++g_read_count;
#ifdef RP2350_STREAM_RAW_CSV
            printf("%llu,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n",
                   static_cast<unsigned long long>(sample.timestamp_us),
                   sample.ax,sample.ay,sample.az,sample.gx,sample.gy,sample.gz);
#endif
#ifdef RP2350_STREAM_BINARY_LOG
            emit_binary_sample(sample,backfilled);
#else
            (void)backfilled;
#endif
            if(previous_ts_us){
                if(sample.timestamp_us<=previous_ts_us){ ++g_unexpected_periods; return; }
                const uint64_t interval=sample.timestamp_us-previous_ts_us;
                if(interval<3500 || interval>6500) ++g_unexpected_periods;
            }
            previous_ts_us=sample.timestamp_us;
            last_sequence=sample.sequence;
            if(!queue_try_add(&g_sample_queue,&sample)) ++g_sample_dropped;
            else update_queue_highwater(g_sample_queue_highwater,&g_sample_queue);
        };
        EdgeEvent edge{};
        if (pop_edge(edge)) {
            last_edge_us=time_us_64();
            g_edge_dispatch_latency.observe(elapsed_us_saturated(edge.irq_us,last_edge_us));
            const uint64_t acquisition_start_us=time_us_64();
            // With direct registers only the newest measurement is available.
            // FIFO mode instead preserves unconsumed samples until overrun.
            if (g_edge_read!=g_edge_write) {
                ++g_event_dropped;
                const uint32_t service_us=elapsed_us_saturated(acquisition_start_us,time_us_64());
                g_acquisition_service_latency.observe(service_us);
                if(service_us>NOMINAL_SAMPLE_PERIOD_US) ++g_sample_period_service_overruns;
                continue;
            }
#ifdef RP2350_USE_FIFO
            // Each status snapshot reports queued 16-bit words. Backfilled
            // times use exact rational nominal 208 Hz spacing, anchored to
            // this PIO DRDY edge. They are reconstructed, not sensor timestamps.
            const uint64_t anchor_us=(edge.t_quarter_us+2u)/4u;
            if(g_fifo_needs_resync) {
                if(g_fifo.flush()) {g_fifo_needs_resync=false;++g_fifo_resets;}
                else ++g_fifo_bus_errors;
            } else {
                lsm6ds3::Frame frames[32]{};
                auto batch=g_fifo.read(frames,32);
                if(batch.result==lsm6ds3::Result::NoCompleteFrame) {
                    // A partial word group can complete on the next DRDY.
                } else if(batch.result!=lsm6ds3::Result::Ok) {
                    const uint32_t observed=batch.fifo_words/6u;
                    if(batch.result==lsm6ds3::Result::BusError) {
                        ++g_fifo_bus_errors;
                        account_fifo_discard(observed);
                        if(g_fifo.flush()) ++g_fifo_resets;
                        else g_fifo_needs_resync=true;
                    } else {
                        ++g_fifo_resets;
                        account_fifo_discard(observed);
                    }
                } else {
                    const uint16_t snapshot_frames=static_cast<uint16_t>(batch.fifo_words/6u);
                    uint16_t processed=0;
                    const uint16_t max_bursts=static_cast<uint16_t>((snapshot_frames+31u)/32u);
                    bool acquisition_failed=false;
                    for(uint16_t burst=0;burst<max_bursts && processed<snapshot_frames;burst++) {
                        if(batch.result!=lsm6ds3::Result::Ok || batch.frames==0) {
                            const uint32_t fallback=static_cast<uint32_t>(snapshot_frames-processed);
                            const uint32_t observed=batch.fifo_words/6u;
                            account_fifo_discard(observed?observed:fallback);
                            if(batch.result==lsm6ds3::Result::BusError) ++g_fifo_bus_errors;
                            if(batch.result==lsm6ds3::Result::BusError || batch.result==lsm6ds3::Result::NoCompleteFrame) {
                                if(g_fifo.flush()) ++g_fifo_resets;
                                else g_fifo_needs_resync=true;
                            } else ++g_fifo_resets; // driver already flushed abnormal pattern/count/overrun
                            acquisition_failed=true;
                            break;
                        }
                        uint64_t sample_times[32]{};
                        if(!lsm6ds3::reconstruct_timestamps(anchor_us,snapshot_frames,processed,
                                                            batch.frames,208,sample_times)) {
                            ++g_fifo_timestamp_errors;
                            account_fifo_discard(static_cast<uint32_t>(snapshot_frames-processed));
                            if(g_fifo.flush()) ++g_fifo_resets;
                            else g_fifo_needs_resync=true;
                            acquisition_failed=true;
                            break;
                        }
                        for(unsigned i=0;i<batch.frames;i++) {
                            const uint64_t time_us=sample_times[i];
                            const bool reconstructed=(processed+i+1u)!=snapshot_frames;
                            if(reconstructed) ++g_fifo_backfilled;
                            auto sample=decode_fifo_frame(frames[i],time_us,++g_fifo_sequence);
                            dispatch_sample(sample,reconstructed);
                        }
                        processed=static_cast<uint16_t>(processed+batch.frames);
                        if(processed>=snapshot_frames) break;
                        const uint8_t capacity=lsm6ds3::snapshot_capacity(snapshot_frames,processed);
                        if(!capacity) break;
                        batch=g_fifo.read(frames,capacity);
                    }
                    if(processed<snapshot_frames && !acquisition_failed) {
                        account_fifo_discard(static_cast<uint32_t>(snapshot_frames-processed));
                        if(g_fifo.flush()) ++g_fifo_resets;
                        else g_fifo_needs_resync=true;
                    }
                }
            }
#else
            spi_read_sample_dma();
            auto sample=decode_sample(edge);
            dispatch_sample(sample,false);
#endif
            const uint32_t service_us=elapsed_us_saturated(acquisition_start_us,time_us_64());
            g_acquisition_service_latency.observe(service_us);
            if(service_us>NOMINAL_SAMPLE_PERIOD_US) ++g_sample_period_service_overruns;
        }

        FusionEstimate new_estimate{};
        while (queue_try_remove(&g_estimate_queue, &new_estimate)) {
            latest = new_estimate;
            have_estimate = true;
        }

        const uint64_t now = time_us_64();
#ifndef RP2350_STREAM_BINARY_LOG
        if (now - last_print_us >= 500'000) {
            last_print_us = now;
#ifdef PICO_DEFAULT_LED_PIN
            gpio_put(PICO_DEFAULT_LED_PIN, (now / 500'000) & 1);
#endif
            if (have_estimate) {
                // Freshness and estimator health are separate from physical
                // accuracy and per-axis observability.
                inertial::RuntimeHealthInput health_input{};
                health_input.now_us=now;
                health_input.last_sensor_edge_us=last_edge_us;
                health_input.estimate_timestamp_us=latest.timestamp_us;
                health_input.estimate_publication_us=latest.published_us;
                health_input.max_age_us=100000u; // diagnostic threshold, not a controller deadline
                health_input.calibration_id=latest.calibration_version;
                health_input.accepted_aid_mask=latest.accepted_aid_mask;
                health_input.estimator_health=static_cast<inertial::Health>(latest.health);
                health_input.estimator_valid=latest.valid_for_control;
                health_input.reset_required=latest.reset_required;
                const inertial::RuntimeHealth runtime=inertial::assess_runtime_health(health_input);
                printf("seq=%lu RPY=(%7.2f,%7.2f,%7.2f) deg "
                       "|a|=%4.2fg bg=(%+.3f,%+.3f,%+.3f) "
                       "sigma_dtheta_body=(%.1f,%.1f,%.1f)deg static=%d "
                       "health=%u output_available=%u runtime_flags=0x%08lx reset_required=%u "
                       "state_age_ms=%.1f publish_age_ms=%.1f sensor_src=%lu timebase=%lu cal_id=%lu "
                       "aid_src=%lu aid_age_ms=%.1f aid_mask=0x%02x yaw_obs=%u pos_obs=%u "
                       "fusion_us_p50/p95/p99/max=%lu/%lu/%lu/%lu "
                       "sample_pub_age_us_p50/p95/p99/max=%lu/%lu/%lu/%lu core1_stack_highwater=%lu "
                       "spi_us_p50/p95/p99/max=%lu/%lu/%lu/%lu "
                       "acq_service_us_p50/p95/p99/max=%lu/%lu/%lu/%lu "
                       "irq_to_dispatch_us_p50/p95/p99/max=%lu/%lu/%lu/%lu "
                       "queue_highwater=edge:%lu/sample:%lu/estimate:%lu "
                       "sample_period_service_overruns=%lu(period=%luus provisional) NIS=%.2f "
                       "updates=%lu/%lu gaps=%lu sat=%lu stale_aid=%lu "
                       "read=%lu edge_drop=%lu sample_drop=%lu period_warn=%lu fifo_reset=%lu fifo_bus=%lu backfilled=%lu fifo_discard=%lu fifo_ts_err=%lu cal_fail=%lu\n",
                       static_cast<unsigned long>(latest.sequence),
                       latest.roll_deg, latest.pitch_deg, latest.yaw_deg,
                       latest.a_norm_g,
                       latest.bgx, latest.bgy, latest.bgz,
                       latest.theta_sigma_x_deg, latest.theta_sigma_y_deg,
                       latest.theta_sigma_z_deg,
                       static_cast<int>(latest.imu_stationary_candidate),
                       static_cast<unsigned>(latest.health),
                       static_cast<unsigned>(runtime.output_available()),
                       static_cast<unsigned long>(runtime.flags),
                       static_cast<unsigned>(latest.reset_required),
                       static_cast<double>((now>=latest.timestamp_us)?now-latest.timestamp_us:0u)/1000.0,
                       static_cast<double>((now>=latest.published_us)?now-latest.published_us:0u)/1000.0,
                       static_cast<unsigned long>(latest.sensor_source_id),
                       static_cast<unsigned long>(latest.timebase_id),
                       static_cast<unsigned long>(latest.calibration_version),
                       static_cast<unsigned long>(latest.last_aid_source_id),
                       static_cast<double>((latest.last_aid_timestamp_us && now>=latest.last_aid_timestamp_us)?now-latest.last_aid_timestamp_us:0u)/1000.0,
                       static_cast<unsigned>(latest.accepted_aid_mask),
                       static_cast<unsigned>(runtime.yaw_observable),
                       static_cast<unsigned>(runtime.position_observable),
                       static_cast<unsigned long>(latest.fusion_p50_us),
                       static_cast<unsigned long>(latest.fusion_p95_us),
                       static_cast<unsigned long>(latest.fusion_p99_us),
                       static_cast<unsigned long>(latest.fusion_max_us),
                       static_cast<unsigned long>(latest.sample_publication_p50_us),
                       static_cast<unsigned long>(latest.sample_publication_p95_us),
                       static_cast<unsigned long>(latest.sample_publication_p99_us),
                       static_cast<unsigned long>(latest.sample_publication_max_us),
                       static_cast<unsigned long>(latest.core1_stack_highwater_bytes),
                       static_cast<unsigned long>(g_spi_transfer_latency.percentile_upper_bound(5000)),
                       static_cast<unsigned long>(g_spi_transfer_latency.percentile_upper_bound(9500)),
                       static_cast<unsigned long>(g_spi_transfer_latency.percentile_upper_bound(9900)),
                       static_cast<unsigned long>(g_spi_transfer_latency.max_us()),
                       static_cast<unsigned long>(g_acquisition_service_latency.percentile_upper_bound(5000)),
                       static_cast<unsigned long>(g_acquisition_service_latency.percentile_upper_bound(9500)),
                       static_cast<unsigned long>(g_acquisition_service_latency.percentile_upper_bound(9900)),
                       static_cast<unsigned long>(g_acquisition_service_latency.max_us()),
                       static_cast<unsigned long>(g_edge_dispatch_latency.percentile_upper_bound(5000)),
                       static_cast<unsigned long>(g_edge_dispatch_latency.percentile_upper_bound(9500)),
                       static_cast<unsigned long>(g_edge_dispatch_latency.percentile_upper_bound(9900)),
                       static_cast<unsigned long>(g_edge_dispatch_latency.max_us()),
                       static_cast<unsigned long>(g_edge_queue_highwater),
                       static_cast<unsigned long>(g_sample_queue_highwater),
                       static_cast<unsigned long>(g_estimate_queue_highwater),
                       static_cast<unsigned long>(g_sample_period_service_overruns),
                       static_cast<unsigned long>(NOMINAL_SAMPLE_PERIOD_US),
                       latest.last_nis,
                       static_cast<unsigned long>(latest.accepted_updates),
                       static_cast<unsigned long>(latest.rejected_updates),
                       static_cast<unsigned long>(latest.gap_count),
                       static_cast<unsigned long>(latest.saturation_count),
                       static_cast<unsigned long>(latest.stale_aiding_updates),
                       static_cast<unsigned long>(g_read_count),
                       static_cast<unsigned long>(g_event_dropped),
                       static_cast<unsigned long>(g_sample_dropped),
                       static_cast<unsigned long>(g_unexpected_periods),
                       static_cast<unsigned long>(g_fifo_resets),
                       static_cast<unsigned long>(g_fifo_bus_errors),
                       static_cast<unsigned long>(g_fifo_backfilled),
                       static_cast<unsigned long>(g_fifo_discarded_frames),
                       static_cast<unsigned long>(g_fifo_timestamp_errors),
                       static_cast<unsigned long>(g_calibration_failed));
            } else {
                printf("Waiting for fusion data; reads=%lu, DRDY GPIO=%d\n",
                       static_cast<unsigned long>(g_read_count),
                       gpio_get(PIN_IMU_INT1));
            }
            if (now - last_edge_us > 1'000'000) {
                printf("WARNING: no gyroscope DRDY events for >1 s\n");
            }
        }
#endif
        tight_loop_contents();
    }
}
