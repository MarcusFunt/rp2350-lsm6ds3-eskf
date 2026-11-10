#pragma once
// Original LSM6DS3 FIFO (NOT a DSOX tagged FIFO). ST AN4650 section 8.
// Fixed 208 Hz gyro+accel, decimation=1 => repeating 6-word pattern:
// Gyro X/Y/Z followed by Accel X/Y/Z. Bus must implement FIFO rounding.
// The driver never invents sensor timestamps: caller associates hardware
// DRDY/Pio edge and documents reconstructed backfilled timestamps.
#include <cstddef>
#include <cstdint>

namespace lsm6ds3 {
constexpr uint8_t kWho=0x0f,kFifoCtrl1=0x06,kFifoCtrl2=0x07,kFifoCtrl3=0x08,
    kFifoCtrl4=0x09,kFifoCtrl5=0x0a,kFifoStatus=0x3a,kFifoData=0x3e;
struct Bus {
    virtual ~Bus()=default;
    virtual bool write_reg(uint8_t reg,uint8_t value)=0;
    virtual bool read_burst(uint8_t first_reg,uint8_t *data,std::size_t size)=0;
};
struct Frame {
    int16_t gyro[3]{},accel[3]{};
};
enum class Result: uint8_t { Ok, NoCompleteFrame, BusError, OverrunFlushed, PatternFlushed, InvalidCountFlushed };
struct ReadResult {
    Result result=Result::NoCompleteFrame;
    uint8_t frames=0;
    uint16_t fifo_words=0;
    uint16_t fifo_pattern=0;
    bool truncated=false; // remaining complete records must be read on next call
};
// Reconstruct the nominal timestamps for one ordered chunk from a single
// FIFO status snapshot. The newest snapshotted frame is anchored at anchor_us;
// any frames acquired after that snapshot must be left for the next edge.
inline bool reconstruct_timestamps(uint64_t anchor_us,uint16_t snapshot_frames,
                                   uint16_t first_frame_index,uint8_t count,
                                   uint16_t rate_hz,uint64_t *out) {
    if(!out || !anchor_us || !snapshot_frames || !count || count>32 || !rate_hz) return false;
    const uint32_t end=uint32_t(first_frame_index)+uint32_t(count);
    if(first_frame_index>=snapshot_frames || end>snapshot_frames) return false;
    const uint64_t oldest_frames_back=uint64_t(snapshot_frames-1u-first_frame_index);
    const uint64_t oldest_offset_us=(oldest_frames_back*1000000ull)/rate_hz;
    if(oldest_offset_us>=anchor_us) return false;
    for(uint8_t i=0;i<count;i++) {
        const uint64_t frame_index=uint64_t(first_frame_index)+i;
        const uint64_t frames_back=uint64_t(snapshot_frames)-1u-frame_index;
        const uint64_t offset_us=(frames_back*1000000ull)/rate_hz;
        const uint64_t timestamp_us=anchor_us-offset_us;
        if(i && timestamp_us<=out[i-1]) return false;
        out[i]=timestamp_us;
    }
    return true;
}
class Fifo {
public:
    explicit Fifo(Bus &bus):bus_(bus){}
    bool configure(uint16_t watermark_words=12) {
        if(watermark_words<6 || watermark_words>2047) return false;
        // Bypass flush first; clear unrelated sensor-hub/4th datasets.
        return bus_.write_reg(kFifoCtrl5,0x00) &&
            bus_.write_reg(kFifoCtrl1,uint8_t(watermark_words & 0xff)) &&
            bus_.write_reg(kFifoCtrl2,uint8_t((watermark_words>>8)&0x07)) &&
            bus_.write_reg(kFifoCtrl3,0x09) && // G=001, XL=001
            bus_.write_reg(kFifoCtrl4,0x00) &&
            bus_.write_reg(kFifoCtrl5,0x2e);   // ODR 208 Hz, continuous
    }
    bool flush() {
        return bus_.write_reg(kFifoCtrl5,0x28) && // ODR=208, bypass
               bus_.write_reg(kFifoCtrl5,0x2e);
    }
    // Drain up to 32 complete frame pairs, without heap allocation.
    ReadResult read(Frame *out,std::size_t capacity) {
        ReadResult result{};
        if(!out || capacity==0 || capacity>32) { result.result=Result::BusError;return result; }
        uint8_t status[4]{};
        if(!bus_.read_burst(kFifoStatus,status,4)) {result.result=Result::BusError;return result;}
        result.fifo_words=uint16_t(status[0])|uint16_t(status[1]&0x0f)<<8;
        result.fifo_pattern=uint16_t(status[2])|uint16_t(status[3]&0x03)<<8;
        if(status[1]&0x60) { // FIFO overrun or full: lose alignment, require fresh start
            result.result=flush() ? Result::OverrunFlushed : Result::BusError;
            return result;
        }
        if(result.fifo_pattern!=0) {
            result.result=flush() ? Result::PatternFlushed : Result::BusError;
            return result;
        }
        if(result.fifo_words>4095) {
            result.result=flush() ? Result::InvalidCountFlushed : Result::BusError;
            return result;
        }
        const std::size_t available=result.fifo_words/6;
        if (!available) { result.result=Result::NoCompleteFrame;return result; }
        const std::size_t n=available<capacity?available:capacity;
        uint8_t bytes[32*12]{};
        if(!bus_.read_burst(kFifoData,bytes,n*12)) {result.result=Result::BusError;return result;}
        for (std::size_t i=0;i<n;i++) {
            const uint8_t *p=bytes+i*12;
            for (int axis=0;axis<3;axis++) {
                out[i].gyro[axis]=signed16(p+axis*2);
                out[i].accel[axis]=signed16(p+6+axis*2);
            }
        }
        result.result=Result::Ok;
        result.frames=static_cast<uint8_t>(n);
        result.truncated=available>n;
        return result;
    }
private:
    static int16_t signed16(const uint8_t *p){return static_cast<int16_t>(uint16_t(p[0])|(uint16_t(p[1])<<8));}
    Bus &bus_;
};
} // namespace lsm6ds3
