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
}
