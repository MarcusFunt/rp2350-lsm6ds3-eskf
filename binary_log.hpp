#pragma once
// Portable fixed-size, little-endian IMU event log. No pointer serialization,
// heap allocation, native packing, or host endianness assumptions.
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#include "eskf15.hpp"

namespace imu_log {
constexpr uint16_t kLegacyVersion=1;
constexpr uint16_t kVersion=2;
constexpr std::size_t kHeaderSize=32,kRecordSize=64;
struct Header {
    uint32_t source_id=0;
    uint32_t timebase_id=0;
    uint32_t calibration_id=0;
    uint16_t sample_rate_hz=208;
    uint16_t version=kVersion;
};
struct Record {
    uint64_t capture_us=0;
    uint64_t publication_us=0;
    uint32_t sequence=0;
    uint32_t flags=0; // bit0 FIFO, bit1 timestamp backfilled, bit2 invalid
    uint16_t version=kVersion;
    uint32_t dropped_records_before=0;
    inertial::Vec3 accel_mps2{},gyro_rps{};
    float temperature_c=NAN; // NaN=temperature not sampled or unavailable
};
inline void u16(uint8_t *p,uint16_t v){p[0]=uint8_t(v);p[1]=uint8_t(v>>8);}
inline void u32(uint8_t *p,uint32_t v){for(int i=0;i<4;i++)p[i]=uint8_t(v>>(8*i));}
inline void u64(uint8_t *p,uint64_t v){for(int i=0;i<8;i++)p[i]=uint8_t(v>>(8*i));}
inline uint16_t r16(const uint8_t *p){return uint16_t(p[0])|(uint16_t(p[1])<<8);}
inline uint32_t r32(const uint8_t *p){uint32_t x=0;for(int i=0;i<4;i++) x|=uint32_t(p[i])<<(8*i);return x;}
inline uint64_t r64(const uint8_t *p){uint64_t x=0;for(int i=0;i<8;i++) x|=uint64_t(p[i])<<(8*i);return x;}
inline void f32(uint8_t *p,float v){uint32_t x;static_assert(sizeof(float)==4,"IEEE754 FP32 required");std::memcpy(&x,&v,4);u32(p,x);}
inline float rf32(const uint8_t *p){uint32_t x=r32(p);float v;std::memcpy(&v,&x,4);return v;}
inline uint32_t crc32(const uint8_t *data,std::size_t n){
    uint32_t c=0xffffffffu;
    for(std::size_t i=0;i<n;i++){
        c^=data[i];
        for(int j=0;j<8;j++) c=(c>>1)^((c&1u)?0xedb88320u:0u);
    }
    return ~c;
}
inline void encode_header(const Header &h,uint8_t out[kHeaderSize]){
    std::memset(out,0,kHeaderSize);
    const char magic[8]={'I','M','U','L','O','G','0','1'};
    std::memcpy(out,magic,8);
    u16(out+8,h.version);u16(out+10,uint16_t(kRecordSize));
    u32(out+12,h.source_id);u32(out+16,h.timebase_id);
    u32(out+20,h.calibration_id);
    u16(out+24,h.sample_rate_hz);u16(out+26,0);u32(out+28,crc32(out,28));
}
inline bool decode_header(const uint8_t *p,std::size_t n,Header &h){
    const uint16_t version=(n==kHeaderSize)?r16(p+8):0;
    if(n!=kHeaderSize || std::memcmp(p,"IMULOG01",8)!=0 ||
       (version!=kLegacyVersion && version!=kVersion) || r16(p+10)!=kRecordSize || crc32(p,28)!=r32(p+28))
        return false;
    h.source_id=r32(p+12);h.timebase_id=r32(p+16);h.calibration_id=r32(p+20);h.sample_rate_hz=r16(p+24);
    h.version=version;
    return h.source_id!=0 && h.timebase_id!=0 && h.sample_rate_hz!=0;
}
inline void encode_record(const Record &r,uint8_t out[kRecordSize]){
    std::memset(out,0,kRecordSize);
    u32(out,0x324d5549u); // 'IUM2' bytes, fixed record marker
    u16(out+4,kVersion);u16(out+6,static_cast<uint16_t>(r.flags));
    u64(out+8,r.capture_us);u64(out+16,r.publication_us);
    u32(out+24,r.sequence);u32(out+28,r.dropped_records_before);
    f32(out+32,r.accel_mps2.x);f32(out+36,r.accel_mps2.y);f32(out+40,r.accel_mps2.z);
    f32(out+44,r.gyro_rps.x);f32(out+48,r.gyro_rps.y);f32(out+52,r.gyro_rps.z);
    f32(out+56,r.temperature_c);
    u32(out+60,crc32(out,60));
}
inline bool decode_record(const uint8_t *p,std::size_t n,Record &r){
    if(n!=kRecordSize || crc32(p,60)!=r32(p+60)) return false;
    const uint32_t marker=r32(p);
    const uint16_t version=r16(p+4);
    if(!((marker==0x314d5549u && version==kLegacyVersion) ||
         (marker==0x324d5549u && version==kVersion))) return false;
    r.version=version;
    r.capture_us=r64(p+8);r.publication_us=r64(p+16);
    r.sequence=r32(p+24);
    if(version==kLegacyVersion){r.flags=r32(p+28);r.dropped_records_before=0;}
    else {r.flags=r16(p+6);r.dropped_records_before=r32(p+28);}
    r.accel_mps2={rf32(p+32),rf32(p+36),rf32(p+40)};
    r.gyro_rps={rf32(p+44),rf32(p+48),rf32(p+52)};
    r.temperature_c=rf32(p+56);
    return r.capture_us>0 && r.publication_us>=r.capture_us &&
        std::isfinite(r.accel_mps2.x)&&std::isfinite(r.accel_mps2.y)&&std::isfinite(r.accel_mps2.z)&&
        std::isfinite(r.gyro_rps.x)&&std::isfinite(r.gyro_rps.y)&&std::isfinite(r.gyro_rps.z);
}
}
