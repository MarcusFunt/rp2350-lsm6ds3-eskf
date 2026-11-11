#pragma once
// Deterministic offline calibration in SI units. Raw data must first be
// converted from device LSB to m/s^2 and rad/s. All matrices are row-major.
// C_BS maps corrected vectors from sensor axes to body axes.
#include <cstddef>
#include <cmath>
#include <cstdint>
#include <cstring>
#include "eskf15.hpp"

namespace inertial {
namespace calibration_wire {
inline void put16(uint8_t *p,uint16_t v){p[0]=uint8_t(v);p[1]=uint8_t(v>>8);}
inline void put32(uint8_t *p,uint32_t v){for(int i=0;i<4;i++)p[i]=uint8_t(v>>(8*i));}
inline uint16_t get16(const uint8_t *p){return uint16_t(p[0])|(uint16_t(p[1])<<8);}
inline uint32_t get32(const uint8_t *p){uint32_t v=0;for(int i=0;i<4;i++)v|=uint32_t(p[i])<<(8*i);return v;}
inline void put_float(uint8_t *p,float v){uint32_t bits;static_assert(sizeof(float)==4,"IEEE754 FP32 required");std::memcpy(&bits,&v,4);put32(p,bits);}
inline float get_float(const uint8_t *p){const uint32_t bits=get32(p);float v;std::memcpy(&v,&bits,4);return v;}
inline uint32_t crc32(const uint8_t *p,std::size_t n){
    uint32_t crc=0xffffffffu;
    for(std::size_t i=0;i<n;i++){
        crc^=p[i];
        for(int bit=0;bit<8;bit++)crc=(crc>>1)^((crc&1u)?0xedb88320u:0u);
    }
    return ~crc;
}
} // namespace calibration_wire

struct Matrix3 {
    float v[3][3] = {{1,0,0},{0,1,0},{0,0,1}};
    Vec3 apply(Vec3 a) const {
        return {v[0][0]*a.x+v[0][1]*a.y+v[0][2]*a.z,
                v[1][0]*a.x+v[1][1]*a.y+v[1][2]*a.z,
                v[2][0]*a.x+v[2][1]*a.y+v[2][2]*a.z};
    }
    bool finite() const {
        for (const auto &row : v) for (float x : row) if (!std::isfinite(x)) return false;
        return true;
    }
    float det() const {
        return v[0][0]*(v[1][1]*v[2][2]-v[1][2]*v[2][1])
            -v[0][1]*(v[1][0]*v[2][2]-v[1][2]*v[2][0])
            +v[0][2]*(v[1][0]*v[2][1]-v[1][1]*v[2][0]);
    }
    bool positive_well_conditioned() const {
        float scale=0;
        for(const auto &row:v) for(float x:row) scale=std::fmax(scale,std::fabs(x));
        if(!(scale>0) || !std::isfinite(scale)) return false;
        float a[3][3];
        for(int i=0;i<3;i++) for(int j=0;j<3;j++) a[i][j]=v[i][j]/scale;
        const float normalized_det=a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])
            -a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
            +a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]);
        return std::isfinite(normalized_det) && normalized_det>1e-6f;
    }
};
struct SensorCalibration {
    static constexpr std::size_t kEncodedSize=184;
    static constexpr uint16_t kFormatVersion=1;
    // ID=0 expressly means uncalibrated, not a verified zero-error device.
    uint32_t version=1;
    uint32_t calibration_id=0;
    uint32_t source_id=0x4c364433; // LSM6DS3 original
    Matrix3 body_from_sensor{};
    Matrix3 accel_correction{}; // contains scale, cross-axis/misalignment effects
    Matrix3 gyro_correction{};
    Vec3 accel_offset{};         // SI constant factory/offline offset
    Vec3 gyro_offset{};
    Vec3 accel_temp_coeff{};     // SI units per C
    Vec3 gyro_temp_coeff{};
    float reference_temp_c=25.0f;
    bool temperature_compensation=false;
    // ESKF bias states estimate RESIDUAL bias after this fixed calibration.
    bool valid() const {
        if (version!=1 || source_id==0 || !body_from_sensor.finite() || !accel_correction.finite() ||
            !gyro_correction.finite() || !std::isfinite(reference_temp_c)) return false;
        if (!finite_vec(accel_offset) || !finite_vec(gyro_offset) ||
            !finite_vec(accel_temp_coeff) || !finite_vec(gyro_temp_coeff)) return false;
        // Require an approximately proper rigid rotation. Do not silently
        // accept a reflection or a scale as the sensor-to-body rotation.
        if (std::fabs(body_from_sensor.det()-1.0f)>0.01f) return false;
        const float *p=&body_from_sensor.v[0][0];
        for(int i=0;i<3;i++)for(int j=0;j<3;j++){
            float d=0;
            for(int k=0;k<3;k++) d+=p[i*3+k]*p[j*3+k];
            if (std::fabs(d-(i==j ? 1.0f:0.0f))>0.01f) return false;
        }
        if (!accel_correction.positive_well_conditioned() ||
            !gyro_correction.positive_well_conditioned()) return false;
        return true;
    }
    static bool finite_vec(Vec3 x) {
        return std::isfinite(x.x)&&std::isfinite(x.y)&&std::isfinite(x.z);
    }
    bool apply(const Imu &raw, float temp_c, Imu &corrected) const {
        if (!valid() || !finite_vec(raw.accel_mps2) || !finite_vec(raw.gyro_rps)) return false;
        if (temperature_compensation && !std::isfinite(temp_c)) return false;
        const float dt=temperature_compensation ? temp_c-reference_temp_c : 0;
        const Vec3 a=raw.accel_mps2-accel_offset-accel_temp_coeff*dt;
        const Vec3 g=raw.gyro_rps-gyro_offset-gyro_temp_coeff*dt;
        corrected=raw;
        corrected.accel_mps2=body_from_sensor.apply(accel_correction.apply(a));
        corrected.gyro_rps=body_from_sensor.apply(gyro_correction.apply(g));
        return finite_vec(corrected.accel_mps2)&&finite_vec(corrected.gyro_rps);
    }
    // Fixed little-endian format: SCAL magic, format version, flags, source
    // and calibration IDs, 40 IEEE754 values, then CRC-32 over prior bytes.
    bool encode(uint8_t *out,std::size_t size) const {
        if(!out || size!=kEncodedSize || !valid()) return false;
        std::memset(out,0,kEncodedSize);
        std::memcpy(out,"SCAL",4);
        calibration_wire::put16(out+4,kFormatVersion);
        calibration_wire::put16(out+6,temperature_compensation?1u:0u);
        calibration_wire::put32(out+8,version);
        calibration_wire::put32(out+12,calibration_id);
        calibration_wire::put32(out+16,source_id);
        std::size_t offset=20;
        auto write_matrix=[&](const Matrix3 &m){
            for(const auto &row:m.v) for(float x:row){calibration_wire::put_float(out+offset,x);offset+=4;}
        };
        auto write_vec=[&](Vec3 v){
            calibration_wire::put_float(out+offset,v.x);offset+=4;
            calibration_wire::put_float(out+offset,v.y);offset+=4;
            calibration_wire::put_float(out+offset,v.z);offset+=4;
        };
        write_matrix(body_from_sensor);write_matrix(accel_correction);write_matrix(gyro_correction);
        write_vec(accel_offset);write_vec(gyro_offset);write_vec(accel_temp_coeff);write_vec(gyro_temp_coeff);
        calibration_wire::put_float(out+offset,reference_temp_c);offset+=4;
        if(offset!=kEncodedSize-4) return false;
        calibration_wire::put32(out+offset,calibration_wire::crc32(out,offset));
        return true;
    }
    static bool decode(const uint8_t *bytes,std::size_t size,SensorCalibration &out) {
        if(!bytes || size!=kEncodedSize || std::memcmp(bytes,"SCAL",4)!=0 ||
           calibration_wire::get16(bytes+4)!=kFormatVersion ||
           (calibration_wire::get16(bytes+6)&~uint16_t(1u))!=0 ||
           calibration_wire::get32(bytes+kEncodedSize-4)!=calibration_wire::crc32(bytes,kEncodedSize-4))
            return false;
        SensorCalibration decoded{};
        decoded.temperature_compensation=(calibration_wire::get16(bytes+6)&1u)!=0;
        decoded.version=calibration_wire::get32(bytes+8);
        decoded.calibration_id=calibration_wire::get32(bytes+12);
        decoded.source_id=calibration_wire::get32(bytes+16);
        std::size_t offset=20;
        auto read_matrix=[&](Matrix3 &m){
            for(auto &row:m.v) for(float &x:row){x=calibration_wire::get_float(bytes+offset);offset+=4;}
        };
        auto read_vec=[&](){
            const Vec3 v{calibration_wire::get_float(bytes+offset),
                         calibration_wire::get_float(bytes+offset+4),
                         calibration_wire::get_float(bytes+offset+8)};
            offset+=12;return v;
        };
        read_matrix(decoded.body_from_sensor);read_matrix(decoded.accel_correction);read_matrix(decoded.gyro_correction);
        decoded.accel_offset=read_vec();decoded.gyro_offset=read_vec();
        decoded.accel_temp_coeff=read_vec();decoded.gyro_temp_coeff=read_vec();
        decoded.reference_temp_c=calibration_wire::get_float(bytes+offset);offset+=4;
        if(offset!=kEncodedSize-4 || !decoded.valid()) return false;
        out=decoded;
        return true;
    }
};
} // namespace inertial
