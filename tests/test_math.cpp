// Independent double-precision finite-difference checks of the firmware's
// continuous dynamics, gravity and yaw measurement Jacobians.
#include "../eskf15.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <random>
using inertial::Eskf15;
using inertial::Vec3;
using inertial::Quat;
using inertial::kDim;
struct V {
    double x=0,y=0,z=0;
    V operator+(V b)const{return {x+b.x,y+b.y,z+b.z};}
    V operator-(V b)const{return {x-b.x,y-b.y,z-b.z};}
    V operator*(double s)const{return {x*s,y*s,z*s};}
    double norm()const{return std::sqrt(x*x+y*y+z*z);}
};
static V cross(V a,V b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
struct Q {
    double w=1,x=0,y=0,z=0;
    Q operator*(Q b)const{return {w*b.w-x*b.x-y*b.y-z*b.z,w*b.x+x*b.w+y*b.z-z*b.y,w*b.y-x*b.z+y*b.w+z*b.x,w*b.z+x*b.y-y*b.x+z*b.w};}
    Q inv()const{return {w,-x,-y,-z};}
    void norm(){double n=std::sqrt(w*w+x*x+y*y+z*z);w/=n;x/=n;y/=n;z/=n;}
    static Q exp(V a){double n=a.norm();if(n<1e-12)return {1,a.x/2,a.y/2,a.z/2};double s=std::sin(n/2)/n;return {std::cos(n/2),a.x*s,a.y*s,a.z*s};}
    V rotate(V b)const{V t=cross({x,y,z},b)*2;return b+t*w+cross({x,y,z},t);}
};
static Quat fq(Q q){return {(float)q.w,(float)q.x,(float)q.y,(float)q.z};}
static Vec3 vf(V v){return {(float)v.x,(float)v.y,(float)v.z};}
static V logq(Q q){q.norm();if(q.w<0){q.w=-q.w;q.x=-q.x;q.y=-q.y;q.z=-q.z;}double n=std::sqrt(q.x*q.x+q.y*q.y+q.z*q.z); if(n<1e-10)return {2*q.x,2*q.y,2*q.z};double t=2*std::atan2(n,q.w)/n;return {q.x*t,q.y*t,q.z*t};}
struct S {V p,v,ba,bg;Q q;};
static S propagate(S s,V acc,V gyro,double dt){V f=acc-s.ba,w=gyro-s.bg;Q mid=s.q*Q::exp(w*(dt/2));mid.norm();V a=mid.rotate(f)+V{0,0,-9.80665};s.p=s.p+s.v*dt+a*(dt*dt/2);s.v=s.v+a*dt;s.q=s.q*Q::exp(w*dt);s.q.norm();return s;}
static S perturb(S s,int i,double eps){V *v=nullptr;int j=i%3;if(i<3)v=&s.p;else if(i<6)v=&s.v;else if(i<9){V d{};if(j==0)d.x=eps;else if(j==1)d.y=eps;else d.z=eps;s.q=s.q*Q::exp(d);s.q.norm();return s;}else if(i<12)v=&s.ba;else v=&s.bg;if(j==0)v->x+=eps;else if(j==1)v->y+=eps;else v->z+=eps;return s;}
static std::array<double,15> error(S reference,S perturbed){V p=perturbed.p-reference.p,v=perturbed.v-reference.v,t=logq(reference.q.inv()*perturbed.q),ba=perturbed.ba-reference.ba,bg=perturbed.bg-reference.bg;return {p.x,p.y,p.z,v.x,v.y,v.z,t.x,t.y,t.z,ba.x,ba.y,ba.z,bg.x,bg.y,bg.z};}
static bool close(double a,double b,double tolerance){return std::abs(a-b)<=tolerance;}
static void test_quaternion_sign_and_gravity_tangent() {
    const Q qd=Q::exp({0.61,-0.28,0.83});
    const Quat q=fq(qd),neg{-q.w,-q.x,-q.y,-q.z};
    const Vec3 bias{0.021f,-0.014f,0.009f};
    const Vec3 measured=q.unrotate({0.15f*inertial::kGravity,0.0f,
        std::sqrt(1.0f-0.15f*0.15f)*inertial::kGravity})+bias;
    float r[3],rn[3],H[3][kDim],Hn[3][kDim];
    assert(Eskf15::gravity_measurement_model(q,measured,bias,r,H));
    assert(Eskf15::gravity_measurement_model(neg,measured,bias,rn,Hn));
    for(int i=0;i<3;i++) {
        assert(std::fabs(r[i]-rn[i])<1e-7f);
        for(int j=0;j<kDim;j++) assert(std::fabs(H[i][j]-Hn[i][j])<1e-7f);
    }
    assert(std::fabs(r[0])+std::fabs(r[1])+std::fabs(r[2])>0.1f);
    const Quat world_yaw=Quat::exp({0,0,0.9f});
    Quat yaw_rotated=world_yaw*q; yaw_rotated.normalize();
    float ry[3],Hy[3][kDim];
    assert(Eskf15::gravity_measurement_model(yaw_rotated,measured,bias,ry,Hy));
    for(int i=0;i<3;i++) {
        assert(std::fabs(r[i]-ry[i])<2e-6f);
        for(int j=0;j<kDim;j++) assert(std::fabs(H[i][j]-Hy[i][j])<2e-6f);
    }
    float heading_r[3],heading_rn[3],heading_H[3][kDim],heading_Hn[3][kDim];
    assert(Eskf15::heading_measurement_model(q,0.31f,heading_r,heading_H));
    assert(Eskf15::heading_measurement_model(neg,0.31f,heading_rn,heading_Hn));
    for(int i=0;i<3;i++) {
        assert(std::fabs(heading_r[i]-heading_rn[i])<1e-7f);
        for(int j=0;j<kDim;j++)
            assert(std::fabs(heading_H[i][j]-heading_Hn[i][j])<1e-7f);
    }
    float heading_r_yawed[3],heading_H_yawed[3][kDim];
    assert(Eskf15::heading_measurement_model(yaw_rotated,
        inertial::wrap_pi(0.31f+0.9f),heading_r_yawed,heading_H_yawed));
    assert(std::fabs(heading_r[0]-heading_r_yawed[0])<2e-6f);
    for(int i=0;i<3;i++) for(int j=0;j<kDim;j++)
        assert(std::fabs(heading_H[i][j]-heading_H_yawed[i][j])<2e-6f);
    constexpr double eps=1e-4;
    for(int j=0;j<3;j++) {
        V dtheta{};
        if(j==0)dtheta.x=eps;
        if(j==1)dtheta.y=eps;
        if(j==2)dtheta.z=eps;
        Q plus=qd*Q::exp(dtheta),minus=qd*Q::exp(dtheta*(-1));
        plus.norm();minus.norm();
        float rp[3],rm[3],hp[3][kDim],hm[3][kDim];
        assert(Eskf15::heading_measurement_model(fq(plus),0.31f,rp,hp));
        assert(Eskf15::heading_measurement_model(fq(minus),0.31f,rm,hm));
        assert(close(-(static_cast<double>(rp[0])-rm[0])/(2*eps),heading_H[0][6+j],3e-4));
    }

    const Vec3 h=q.unrotate({0,0,1});
    const float hv[3]={h.x,h.y,h.z};
    double residual_radial=0,residual_norm2=0;
    for(int i=0;i<3;i++) {
        residual_radial+=hv[i]*r[i];
        residual_norm2+=static_cast<double>(r[i])*r[i];
    }
    // Two unit gravity vectors have no first-order radial innovation; the
    // radial residual is only the sphere's second-order curvature term.
    assert(std::fabs(residual_radial+0.5*residual_norm2)<2e-6);
    double frobenius2=0;
    for(int j=0;j<3;j++) {
        double left=0,right=0;
        for(int i=0;i<3;i++) {
            left+=hv[i]*H[i][6+j];
            right+=H[i][6+j]*hv[i];
            frobenius2+=static_cast<double>(H[i][6+j])*H[i][6+j];
        }
        assert(std::fabs(left)<2e-6 && std::fabs(right)<2e-6);
    }
    // [h]x has singular values 1, 1, 0 for unit h: two observable tangent
    // directions and one unobservable rotation about gravity.
    assert(std::fabs(frobenius2-2.0)<2e-5);

    const Quat near_vertical=Quat::exp({0,inertial::kPi/2.0f,0});
    const Quat neg_vertical{-near_vertical.w,-near_vertical.x,-near_vertical.y,-near_vertical.z};
    assert(!Eskf15::heading_measurement_model(near_vertical,0.0f,heading_r,heading_H));
    assert(!Eskf15::heading_measurement_model(neg_vertical,0.0f,heading_rn,heading_Hn));
    std::puts("PASS quaternion sign invariance and rank-two gravity tangent model");
}

static void test_gravity_bias_jacobian_at_finite_innovation() {
    const Quat q{};
    const Vec3 bias{0.021f,-0.014f,0.009f};
    const Vec3 measured_direction{0.15f,0.0f,std::sqrt(1.0f-0.15f*0.15f)};
    const Vec3 accel=measured_direction*inertial::kGravity+bias;
    float residual[3],H[3][kDim];
    assert(Eskf15::gravity_measurement_model(q,accel,bias,residual,H));
    assert(std::fabs(residual[0])>0.1f); // Exercise the nonlinear, nonzero-innovation case.
    constexpr double eps=1e-3;
    double max_bias_error=0.0;
    for(int j=0;j<3;j++) {
        Vec3 plus=bias,minus=bias;
        if(j==0){plus.x+=eps;minus.x-=eps;}
        if(j==1){plus.y+=eps;minus.y-=eps;}
        if(j==2){plus.z+=eps;minus.z-=eps;}
        float rp[3],rm[3],hp[3][kDim],hm[3][kDim];
        assert(Eskf15::gravity_measurement_model(q,accel,plus,rp,hp));
        assert(Eskf15::gravity_measurement_model(q,accel,minus,rm,hm));
        for(int i=0;i<3;i++) {
            const double numerical=-(static_cast<double>(rp[i])-rm[i])/(2.0*eps);
            max_bias_error=std::max(max_bias_error,std::abs(numerical-H[i][9+j]));
            assert(close(numerical,H[i][9+j],2e-4));
        }
    }
    std::printf("PASS nonzero-innovation gravity bias Jacobian; max error=%.8f\n",max_bias_error);
}
int main(){
    std::mt19937 rng(0xC0FFEE);
    std::uniform_real_distribution<double> d(-1,1);
    constexpr double eps=1e-4,dt=2e-4;
    double max_motion_error=0,max_gravity_error=0,max_heading_error=0;
    int checks=0;
    for(int n=0;n<32;n++) {
        S s;V angles{d(rng),d(rng),d(rng)};s.q=Q::exp(angles);s.ba={d(rng)*.1,d(rng)*.1,d(rng)*.1};s.bg={d(rng)*.01,d(rng)*.01,d(rng)*.01};
        V f{d(rng)*4,d(rng)*4,9.80665+d(rng)*2},w{d(rng)*2,d(rng)*2,d(rng)*2};
        float A[kDim][kDim];Eskf15::continuous_error_jacobian(fq(s.q),vf(f),vf(w),A);
        S base_next=propagate(s,f+s.ba,w+s.bg,dt);
        for(int j=0;j<kDim;j++){
            S shifted=perturb(s,j,eps);
            auto after=error(base_next,propagate(shifted,f+s.ba,w+s.bg,dt));
            auto before=error(s,shifted);
            for(int i=0;i<kDim;i++){
                double numerical=(after[i]-before[i])/(eps*dt);
                max_motion_error=std::max(max_motion_error,std::abs(numerical-A[i][j]));
                if(!close(numerical,A[i][j],0.004)) {printf("FAILED n=%d i=%d j=%d numeric=%g analytic=%g diff=%g q=(%g,%g,%g,%g) baseq=(%g,%g,%g,%g) nextq=(%g,%g,%g,%g)\n",n,i,j,numerical,A[i][j],numerical-A[i][j],s.q.w,s.q.x,s.q.y,s.q.z,base_next.q.w,base_next.q.x,base_next.q.y,base_next.q.z,propagate(shifted,f+s.ba,w+s.bg,dt).q.w,propagate(shifted,f+s.ba,w+s.bg,dt).q.x,propagate(shifted,f+s.ba,w+s.bg,dt).q.y,propagate(shifted,f+s.ba,w+s.bg,dt).q.z); return 2;}
                checks++;
            }
        }
        // For r=z(accel,ba)-h(q), the EKF uses H=-dr/dx.
        float H[3][kDim],r[3];
        V rawacc=s.q.inv().rotate({0,0,9.80665})+s.ba;
        assert(Eskf15::gravity_measurement_model(fq(s.q),vf(rawacc),vf(s.ba),r,H));
        for(int j=0;j<kDim;j++){
            S hi=perturb(s,j,eps),lo=perturb(s,j,-eps);
            float Hp[3][kDim],Hm[3][kDim],rp[3],rm[3];
            Eskf15::gravity_measurement_model(fq(hi.q),vf(rawacc),vf(hi.ba),rp,Hp);
            Eskf15::gravity_measurement_model(fq(lo.q),vf(rawacc),vf(lo.ba),rm,Hm);
            for(int i=0;i<3;i++){
                double numerical=-(rp[i]-rm[i])/(2*eps);
                max_gravity_error=std::max(max_gravity_error,std::abs(numerical-H[i][j]));
                assert(close(numerical,H[i][j],0.002));
            }
        }
        float Hy[3][kDim],ry[3];
        if(Eskf15::heading_measurement_model(fq(s.q),0.3f,ry,Hy)){
            for(int j=6;j<9;j++){
                S hi=perturb(s,j,eps),lo=perturb(s,j,-eps);
                float hp[3][kDim],hm[3][kDim],rp[3],rm[3];
                assert(Eskf15::heading_measurement_model(fq(hi.q),0.3f,rp,hp));
                assert(Eskf15::heading_measurement_model(fq(lo.q),0.3f,rm,hm));
                double numerical=-(rp[0]-rm[0])/(2*eps);
                max_heading_error=std::max(max_heading_error,std::abs(numerical-Hy[0][j]));
                assert(close(numerical,Hy[0][j],0.002));
            }
        }
    }
    printf("PASS independent finite differences: %d dynamics entries, max |A error|=%.6f, |Hgravity|=%.6f, |Hyaw|=%.6f\n",checks,max_motion_error,max_gravity_error,max_heading_error);
    test_quaternion_sign_and_gravity_tangent();
    test_gravity_bias_jacobian_at_finite_innovation();
}
