#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <type_traits>
#include <utility>
#include <vector>
#include "../eskf15.hpp"
#include "../calibration.hpp"
#include "../aiding.hpp"
#if __has_include("../runtime_health.hpp")
#include "../runtime_health.hpp"
#define TEST_HAS_RUNTIME_HEALTH 1
#else
#define TEST_HAS_RUNTIME_HEALTH 0
#endif
#include "../lsm6ds3_fifo.hpp"
#include "../binary_log.hpp"
using namespace inertial;
static bool near(float a,float b,float eps=1e-4f){return std::fabs(a-b)<eps;}
template<class T,class=void> struct HasCalibrationWireFormat:std::false_type{};
template<class T> struct HasCalibrationWireFormat<T,std::void_t<
    decltype(T::kEncodedSize),
    decltype(std::declval<const T&>().encode(static_cast<uint8_t*>(nullptr),std::size_t{})),
    decltype(T::decode(static_cast<const uint8_t*>(nullptr),std::size_t{},std::declval<T&>()))
>>:std::true_type{};
template<class T> static void test_calibration_wire_format_impl(){
    if constexpr(HasCalibrationWireFormat<T>::value){
        T input{};input.calibration_id=0x12345678;input.source_id=0x4c364433;
        input.temperature_compensation=true;input.reference_temp_c=31.5f;
        input.body_from_sensor.v[0][0]=0;input.body_from_sensor.v[0][1]=-1;
        input.body_from_sensor.v[1][0]=1;input.body_from_sensor.v[1][1]=0;
        input.accel_correction.v[0][0]=1.1f;input.gyro_correction.v[1][1]=0.9f;
        input.accel_offset={0.1f,-0.2f,0.3f};input.gyro_offset={0.01f,-0.02f,0.03f};
        input.accel_temp_coeff={0.001f,0.002f,0.003f};input.gyro_temp_coeff={0.004f,0.005f,0.006f};
        uint8_t bytes[T::kEncodedSize]{};
        assert(input.encode(bytes,sizeof(bytes)));
        T decoded{};assert(T::decode(bytes,sizeof(bytes),decoded));
        assert(decoded.version==input.version && decoded.calibration_id==input.calibration_id);
        assert(decoded.source_id==input.source_id && decoded.temperature_compensation);
        assert(near(decoded.body_from_sensor.v[0][1],-1.0f));
        assert(near(decoded.accel_correction.v[0][0],1.1f));
        assert(near(decoded.gyro_correction.v[1][1],0.9f));
        assert(near(decoded.accel_offset.y,-0.2f) && near(decoded.gyro_offset.z,0.03f));
        assert(near(decoded.accel_temp_coeff.z,0.003f) && near(decoded.gyro_temp_coeff.x,0.004f));
        assert(near(decoded.reference_temp_c,31.5f));
        bytes[30]^=0x40;assert(!T::decode(bytes,sizeof(bytes),decoded));
        assert(!T::decode(bytes,sizeof(bytes)-1,decoded));
        assert(input.encode(bytes,sizeof(bytes)));
        calibration_wire::put16(bytes+4,2);
        calibration_wire::put32(bytes+T::kEncodedSize-4,calibration_wire::crc32(bytes,T::kEncodedSize-4));
        assert(!T::decode(bytes,sizeof(bytes),decoded));
        input.accel_correction.v[0][0]=0;
        assert(!input.encode(bytes,sizeof(bytes)));
    }else{
        assert(HasCalibrationWireFormat<T>::value && "versioned calibration serialization API is missing");
    }
}
static void test_calibration(){
    SensorCalibration c{};c.calibration_id=1234;c.temperature_compensation=true;
    c.body_from_sensor.v[0][0]=0;c.body_from_sensor.v[0][1]=-1;
    c.body_from_sensor.v[1][0]=1;c.body_from_sensor.v[1][1]=0;
    c.accel_correction.v[0][0]=2;
    c.accel_offset={1,0,0};c.accel_temp_coeff={0.1f,0,0};
    assert(c.valid());
    Imu raw{10000,{2.5f,3,4},{0,1,0}},out{};
    assert(c.apply(raw,30.0f,out));
    assert(near(out.accel_mps2.x,-3)&&near(out.accel_mps2.y,2)&&near(out.accel_mps2.z,4));
    assert(near(out.gyro_rps.x,-1)&&near(out.gyro_rps.y,0));
    assert(out.timestamp_us==raw.timestamp_us); // offline fixed calibration does not own ESKF bias state
    assert(!c.apply(raw,NAN,out));
    c.accel_correction.v[0][0]=1e-10f;
    assert(!c.valid()); // reject positive-determinant but numerically singular scale/cross-axis transforms
    c.accel_correction.v[0][0]=2;
    c.body_from_sensor.v[0][0]=1;c.body_from_sensor.v[0][1]=0;
    assert(!c.valid());
    SensorCalibration reflection{};reflection.body_from_sensor.v[0][0]=-1;
    assert(!reflection.valid());
    SensorCalibration no_temperature{};
    assert(no_temperature.apply(raw,NAN,out));
    std::cout<<"PASS calibrated sensor frame, matrix, temp and invalid transform\n";
    test_calibration_wire_format_impl<SensorCalibration>();
    std::cout<<"PASS versioned calibration serialization, roundtrip and CRC rejection\n";
}
struct MockBus: lsm6ds3::Bus {
    uint8_t regs[256]{};
    std::vector<uint8_t> fifo{};
    std::size_t pos=0;
    bool fail=false;
    bool fail_write=false;
    int flushes=0;
    bool write_reg(uint8_t r,uint8_t v) override {
        if(fail||fail_write) return false;
        regs[r]=v;
        if(r==lsm6ds3::kFifoCtrl5 && v==0x28){flushes++;pos=fifo.size();}
        return true;
    }
    bool read_burst(uint8_t r,uint8_t *p,std::size_t n) override {
        if(fail)return false;
        if(r==lsm6ds3::kFifoStatus && n==4){
            std::memcpy(p,regs+r,4);
            return true;
        }
        if(r==lsm6ds3::kFifoData && pos+n<=fifo.size()){
            std::memcpy(p,fifo.data()+pos,n);pos+=n;return true;
        }
        return false;
    }
    void status(uint16_t words,uint16_t pattern=0,uint8_t flags=0){
        regs[0x3a]=uint8_t(words);
        regs[0x3b]=uint8_t(words>>8)|flags;
        regs[0x3c]=uint8_t(pattern);
        regs[0x3d]=uint8_t(pattern>>8);
    }
    void add_frame(int16_t g,int16_t a){
        for(int i=0;i<6;i++){
            const uint16_t x=uint16_t(i<3?g+i:a+i-3);
            fifo.push_back(uint8_t(x));fifo.push_back(uint8_t(x>>8));
        }
    }
};
static void test_fifo(){
    MockBus b{};lsm6ds3::Fifo fifo(b);
    assert(fifo.configure(12));assert(b.regs[0x08]==0x09 && b.regs[0x0a]==0x2e);
    b.add_frame(-12,100);b.add_frame(-10,200);b.status(12);
    lsm6ds3::Frame f[2]{};
    const auto out=fifo.read(f,2);
    assert(out.result==lsm6ds3::Result::Ok && out.frames==2);
    assert(f[0].gyro[0]==-12 && f[0].accel[2]==102 && f[1].gyro[0]==-10 && f[1].accel[0]==200);
    b.status(3);assert(fifo.read(f,2).result==lsm6ds3::Result::NoCompleteFrame);
    b.status(6,1);assert(fifo.read(f,2).result==lsm6ds3::Result::PatternFlushed);
    b.status(0,0,0x40);assert(fifo.read(f,2).result==lsm6ds3::Result::OverrunFlushed);
    b.status(0,0,0x20);assert(fifo.read(f,2).result==lsm6ds3::Result::OverrunFlushed);
    assert(b.flushes==3);
    b.status(6,1);b.fail_write=true;assert(fifo.read(f,2).result==lsm6ds3::Result::BusError);
    b.fail_write=false;
    b.fail=true;assert(fifo.read(f,2).result==lsm6ds3::Result::BusError);
    std::cout<<"PASS FIFO pattern, overrun, signed decoding and bus failure\n";
}
static void test_fifo_capacity_truncation(){
    MockBus b{};lsm6ds3::Fifo fifo(b);
    for(int i=0;i<4;i++)b.add_frame(static_cast<int16_t>(10+i),static_cast<int16_t>(100+i));
    b.status(24);
    lsm6ds3::Frame frames[2]{};
    const auto result=fifo.read(frames,2);
    assert(result.result==lsm6ds3::Result::Ok && result.frames==2);
    assert(result.fifo_words==24 && result.truncated);
    assert(frames[0].gyro[0]==10 && frames[1].gyro[0]==11);
    std::cout<<"PASS bounded FIFO read reports unconsumed snapshot frames\n";
}
static void test_fifo_snapshot_capacity(){
    assert(lsm6ds3::snapshot_capacity(50,0)==32);
    assert(lsm6ds3::snapshot_capacity(50,32)==18);
    assert(lsm6ds3::snapshot_capacity(50,49)==1);
    assert(lsm6ds3::snapshot_capacity(50,50)==0);
    assert(lsm6ds3::snapshot_capacity(0,0)==0);
    std::cout<<"PASS FIFO drain capacity is limited to original status snapshot\n";
}
static void test_fifo_snapshot_leaves_new_arrivals_for_next_edge(){
    MockBus b{};lsm6ds3::Fifo fifo(b);
    for(int i=0;i<55;i++)b.add_frame(static_cast<int16_t>(i),static_cast<int16_t>(100+i));
    b.status(50u*6u);
    lsm6ds3::Frame frames[32]{};
    auto batch=fifo.read(frames,32);
    assert(batch.result==lsm6ds3::Result::Ok && batch.frames==32 && batch.truncated);
    const uint16_t snapshot=static_cast<uint16_t>(batch.fifo_words/6u);
    assert(snapshot==50);
    b.status(55u*6u); // five samples arrived after the original status snapshot
    batch=fifo.read(frames,lsm6ds3::snapshot_capacity(snapshot,32));
    assert(batch.result==lsm6ds3::Result::Ok && batch.frames==18 && batch.truncated);
    assert(b.pos==50u*12u && b.fifo.size()-b.pos==5u*12u);
    uint64_t first_times[32]{},tail_times[32]{};
    assert(lsm6ds3::reconstruct_timestamps(2000000,snapshot,0,32,208,first_times));
    assert(lsm6ds3::reconstruct_timestamps(2000000,snapshot,32,18,208,tail_times));
    assert(first_times[31]<tail_times[0] && tail_times[17]==2000000);
    std::cout<<"PASS FIFO burst drain preserves edge snapshot and defers newer samples\n";
}
static void test_fifo_timestamp_reconstruction(){
    uint64_t times[32]{};
    constexpr uint64_t anchor=2000000;
    assert(lsm6ds3::reconstruct_timestamps(anchor,50,0,32,208,times));
    for(unsigned i=0;i<32;i++){
        const uint64_t frames_back=49u-i;
        assert(times[i]==anchor-(frames_back*1000000u)/208u);
        if(i)assert(times[i]>times[i-1]);
    }
    assert(times[0]==1764424 && times[31]==1913462);
    uint64_t tail[18]{};
    assert(lsm6ds3::reconstruct_timestamps(anchor,50,32,18,208,tail));
    assert(tail[0]==1918270);
    assert(tail[17]==anchor);
    assert(!lsm6ds3::reconstruct_timestamps(anchor,50,0,1,208,nullptr));
    assert(!lsm6ds3::reconstruct_timestamps(anchor,0,0,1,208,times));
    assert(!lsm6ds3::reconstruct_timestamps(anchor,50,0,0,208,times));
    assert(!lsm6ds3::reconstruct_timestamps(anchor,50,0,33,208,times));
    assert(!lsm6ds3::reconstruct_timestamps(anchor,50,50,1,208,times));
    assert(!lsm6ds3::reconstruct_timestamps(anchor,50,0,1,0,times));
    assert(!lsm6ds3::reconstruct_timestamps(4800,2,0,2,208,times));
    std::cout<<"PASS exact rational 208 Hz FIFO timestamp reconstruction and range checks\n";
}
static void test_log(){
    imu_log::Header h{45,1,1234,208},hout{};
    uint8_t bytes[imu_log::kRecordSize]{};
    imu_log::encode_header(h,bytes);
    assert(imu_log::decode_header(bytes,imu_log::kHeaderSize,hout));
    assert(hout.calibration_id==1234 && hout.sample_rate_hz==208);
    bytes[17]^=1;assert(!imu_log::decode_header(bytes,imu_log::kHeaderSize,hout));
    imu_log::Record r{};r.capture_us=100;r.publication_us=140;r.sequence=5;
    r.accel_mps2={1,2,3};r.gyro_rps={4,5,6};
    imu_log::encode_record(r,bytes);
    imu_log::Record y{};assert(imu_log::decode_record(bytes,imu_log::kRecordSize,y));
    assert(y.sequence==5 && near(y.accel_mps2.y,2));
    bytes[44]^=4;assert(!imu_log::decode_record(bytes,imu_log::kRecordSize,y));
    assert(!imu_log::decode_record(bytes,18,y));
    std::cout<<"PASS binary log roundtrip, CRC and short-record rejection\n";
}
static void test_aiding(){
    Settings settings{};settings.calibration_id=1234;
    Eskf15 eskf(settings);
    for(int i=0;i<130;i++)eskf.process({uint64_t(10'000+i*4808),{0,0,kGravity},{0,0,0}});
    assert(eskf.ready());
    AidingRouter router(1,1234);
    AidingMeasurement m{};
    m.valid=true;m.source_id=77;m.calibration_id=1234;m.timebase_id=1;
    m.provenance=AidingProvenance::IndependentPhysical;
    m.type=AidingType::PositionWorld;m.frame=AidingFrame::WorldENU;
    m.sigma=0.5f;m.capture_us=eskf.state_timestamp_us();
    m.publication_us=m.capture_us+120;
    m.interval_start_us=m.capture_us;m.interval_end_us=m.capture_us;
    m.value={0,0,0};
    assert(router.apply(eskf,m)==AidingResult::Accepted);
    assert(eskf.last_accepted_aid_source()==77 && eskf.last_accepted_aid_timestamp_us()==m.capture_us);
    assert(eskf.accepted_aid_mask()==kAidPosition);
    assert(router.apply(eskf,m)==AidingResult::DuplicateOrReordered);
    m.source_id=78;m.provenance=AidingProvenance::CorrelatedOrFused;
    assert(router.apply(eskf,m)==AidingResult::CorrelatedEvidence);
    m.provenance=AidingProvenance::IndependentPhysical;
    m.timebase_id=2;assert(router.apply(eskf,m)==AidingResult::WrongTimebase);
    m.timebase_id=1;m.calibration_id=2;assert(router.apply(eskf,m)==AidingResult::BadCalibration);
    m.calibration_id=1234;m.frame=AidingFrame::BodyFLU;
    assert(router.apply(eskf,m)==AidingResult::WrongFrame);
    m.frame=AidingFrame::WorldENU;m.capture_us-=2000;m.interval_start_us=m.capture_us;m.interval_end_us=m.capture_us;
    assert(router.apply(eskf,m)==AidingResult::StaleOrFuture);
    m.capture_us=eskf.state_timestamp_us();m.interval_start_us=m.capture_us;m.interval_end_us=m.capture_us;
    m.capture_us+=50;m.publication_us=m.capture_us+50;
    m.interval_start_us=m.capture_us;m.interval_end_us=m.capture_us;
    assert(router.apply(eskf,m)==AidingResult::StaleOrFuture);
    m.capture_us=eskf.state_timestamp_us();m.interval_start_us=m.capture_us;m.interval_end_us=m.capture_us;
    m.publication_us=m.capture_us-1;assert(router.apply(eskf,m)==AidingResult::Invalid);
    m.publication_us=m.capture_us+10;m.interval_start_us=m.capture_us+1;
    assert(router.apply(eskf,m)==AidingResult::Invalid);
    m.interval_start_us=m.capture_us;m.interval_end_us=m.publication_us+1;
    assert(router.apply(eskf,m)==AidingResult::Invalid);
    std::cout<<"PASS aiding provenance, timestamp, frame and version gates\n";
}
static void test_aiding_configured_age(){
    Settings settings{};settings.calibration_id=1234;settings.max_aiding_age_us=4000;
    Eskf15 filter(settings);
    for(int i=0;i<130;i++)filter.process({uint64_t(10'000+i*4808),{0,0,kGravity},{0,0,0}});
    AidingRouter router(1,1234);AidingMeasurement m{};
    m.valid=true;m.source_id=33;m.calibration_id=1234;m.timebase_id=1;
    m.provenance=AidingProvenance::IndependentPhysical;m.type=AidingType::PositionWorld;
    m.frame=AidingFrame::WorldENU;m.sigma=0.5f;
    m.capture_us=filter.state_timestamp_us()-2000;m.publication_us=filter.state_timestamp_us()+50;
    m.interval_start_us=m.capture_us;m.interval_end_us=m.capture_us;
    assert(router.apply(filter,m)==AidingResult::Accepted);
    std::cout<<"PASS aiding router follows configured estimator freshness window\n";
}
static void test_runtime_health(){
#if TEST_HAS_RUNTIME_HEALTH
    RuntimeHealthInput in{};in.now_us=100000;in.last_sensor_edge_us=95000;
    in.estimate_timestamp_us=94000;in.estimate_publication_us=96000;
    in.max_age_us=10000;in.calibration_id=1234;in.estimator_valid=true;
    in.estimator_health=Health::Nominal;
    const RuntimeHealth fresh=assess_runtime_health(in);
    assert(fresh.output_available() && fresh.sensor_fresh && fresh.estimate_fresh);
    assert(!fresh.yaw_observable && !fresh.position_observable);
    in.last_sensor_edge_us=0;
    const RuntimeHealth missing_sensor=assess_runtime_health(in);
    assert(!missing_sensor.output_available() && !missing_sensor.sensor_fresh);
    in.last_sensor_edge_us=95000;in.estimate_publication_us=0;
    const RuntimeHealth stale_core=assess_runtime_health(in);
    assert(!stale_core.output_available() && !stale_core.estimate_fresh);
    in.estimate_publication_us=96000;in.accepted_aid_mask=kAidHeading|kAidPosition;
    const RuntimeHealth aided=assess_runtime_health(in);
    assert(aided.output_available() && aided.yaw_observable && aided.position_observable);
    in.calibration_id=0;
    const RuntimeHealth unverified=assess_runtime_health(in);
    assert(!unverified.output_available() && (unverified.flags&kCalibrationUnverified));
    in.calibration_id=1234;
    in.reset_required=true;
    assert(!assess_runtime_health(in).output_available());
    in.reset_required=false;
    in.estimator_health=Health::Degraded;
    assert(!assess_runtime_health(in).output_available());
    std::cout<<"PASS freshness, calibration, reset, health and observability status\n";
#else
    assert(TEST_HAS_RUNTIME_HEALTH && "runtime health assessment API is missing");
#endif
}
int main(){test_calibration();test_fifo();test_fifo_capacity_truncation();test_fifo_snapshot_capacity();test_fifo_snapshot_leaves_new_arrivals_for_next_edge();test_fifo_timestamp_reconstruction();test_log();test_aiding();test_aiding_configured_age();test_runtime_health();std::cout<<"Bundle C host tests passed\n";}
