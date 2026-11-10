// Compare FP32 discrete process noise with independently integrated
// double-precision continuous-time covariance (64-point midpoint quadrature).
#include "../eskf15.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
using namespace inertial;
using M = std::array<std::array<double,15>,15>;
static M matmul(const M& a,const M& b){M o{};for(int i=0;i<15;i++)for(int j=0;j<15;j++)for(int k=0;k<15;k++)o[i][j]+=a[i][k]*b[k][j];return o;}
static M ident(){M a{};for(int i=0;i<15;i++)a[i][i]=1;return a;}
static M expm(const M& A,double t){ // high-order Taylor at small t
    M term=ident(),out=term;
    for(int k=1;k<=12;k++){
        term=matmul(term,A);
        for(int i=0;i<15;i++)for(int j=0;j<15;j++){
            term[i][j]*=t/k;out[i][j]+=term[i][j];
        }
    }
    return out;
}
static void seed(Eskf15& f){for(unsigned i=1;i<=80;i++)f.process({5000ull*i,{0,0,kGravity},{0,0,0}});assert(f.ready());}
int main(){
    Settings c0,c1;
    c0.accel_noise=c0.gyro_noise=c0.accel_bias_walk=c0.gyro_bias_walk=0;
    c1.accel_noise=2.0f;c1.gyro_noise=1.0f;c1.accel_bias_walk=3.0f;c1.gyro_bias_walk=2.0f;
    c0.heuristic_zero_rate=c1.heuristic_zero_rate=false;
    Eskf15 a(c0),b(c1);seed(a);seed(b);
    const float dt=0.005f;
    const Vec3 acc{0.6f,-1.2f,kGravity},gyro{0.3f,-0.5f,0.8f};
    assert(a.process({405000,acc,gyro}));assert(b.process({405000,acc,gyro}));
    float Af[15][15];
    Quat qmid=Quat::exp(gyro*(dt/2));
    Eskf15::continuous_error_jacobian(qmid,acc,gyro,Af);
    M A{};for(int i=0;i<15;i++)for(int j=0;j<15;j++)A[i][j]=Af[i][j];
    // Noise injection matrix. Same *physical* model, independently integrated.
    double B[15][12]={};
    Vec3 ex=qmid.rotate({1,0,0}),ey=qmid.rotate({0,1,0}),ez=qmid.rotate({0,0,1});
    double R[3][3]={{ex.x,ey.x,ez.x},{ex.y,ey.y,ez.y},{ex.z,ey.z,ez.z}};
    for(int i=0;i<3;i++)for(int j=0;j<3;j++)B[i+3][j]=-R[i][j];
    for(int i=0;i<3;i++){B[6+i][3+i]=-1;B[9+i][6+i]=1;B[12+i][9+i]=1;}
    const double qvar[4]={4,1,9,4};
    M qref{};
    for(int n=0;n<64;n++){
        double t=dt*(n+.5)/64.0;
        M phi=expm(A,t);
        double V[15][12]={};
        for(int i=0;i<15;i++)for(int j=0;j<12;j++)for(int k=0;k<15;k++)V[i][j]+=phi[i][k]*B[k][j];
        for(int i=0;i<15;i++)for(int j=0;j<15;j++)for(int k=0;k<12;k++)qref[i][j]+=(dt/64.0)*V[i][k]*qvar[k/3]*V[j][k];
    }
    double maxerr=0;int checked=0;
    for(int i=0;i<15;i++)for(int j=0;j<15;j++){
        double observed=b.covariance(i,j)-a.covariance(i,j);
        double ref=qref[i][j];
        if(std::abs(ref)>3e-6){
            double error=std::abs(observed-ref);
            maxerr=std::max(maxerr,error);
            if(error>std::max(0.00005,0.015*std::abs(ref))){
                printf("FAIL Q[%d,%d]: observed %.8g expected %.8g err %.5g\n",i,j,observed,ref,error);return 1;
            }
            checked++;
        }
    }
    assert(checked>20);
    assert(b.covariance_positive_definite());
    printf("PASS process Qd vs independent FP64 quadrature: %d entries, max abs error %.6g\n",checked,maxerr);
}
