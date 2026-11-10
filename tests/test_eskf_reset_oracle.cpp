// Independent FP64 covariance oracle for right-error quaternion injection.
#include "../eskf15.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>

using namespace inertial;
constexpr int N = kDim;

static std::array<std::array<double, 3>, 3> inverse3(
    std::array<std::array<double, 3>, 3> a) {
    std::array<std::array<double, 3>, 3> inv{};
    for (int i = 0; i < 3; ++i) inv[i][i] = 1.0;
    for (int c = 0; c < 3; ++c) {
        int pivot = c;
        for (int r = c + 1; r < 3; ++r)
            if (std::fabs(a[r][c]) > std::fabs(a[pivot][c])) pivot = r;
        assert(std::fabs(a[pivot][c]) > 1e-20);
        std::swap(a[c], a[pivot]);
        std::swap(inv[c], inv[pivot]);
        const double d = a[c][c];
        for (int j = 0; j < 3; ++j) { a[c][j] /= d; inv[c][j] /= d; }
        for (int r = 0; r < 3; ++r) if (r != c) {
            const double f = a[r][c];
            for (int j = 0; j < 3; ++j) {
                a[r][j] -= f * a[c][j];
                inv[r][j] -= f * inv[c][j];
            }
        }
    }
    return inv;
}

static std::array<std::array<double, 3>, 3> right_jacobian(Vec3 d) {
    const double x = d.x, y = d.y, z = d.z;
    const double theta2 = x*x + y*y + z*z;
    const double theta = std::sqrt(theta2);
    double a, b;
    if (theta < 1e-4) {
        a = 0.5 - theta2/24.0 + theta2*theta2/720.0;
        b = 1.0/6.0 - theta2/120.0 + theta2*theta2/5040.0;
    } else {
        a = (1.0 - std::cos(theta))/theta2;
        b = (theta - std::sin(theta))/(theta2*theta);
    }
    const double s[3][3] = {{0,-z,y},{z,0,-x},{-y,x,0}};
    std::array<std::array<double, 3>, 3> g{};
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) {
        double s2 = 0.0;
        for (int k = 0; k < 3; ++k) s2 += s[i][k] * s[k][j];
        g[i][j] = (i == j ? 1.0 : 0.0) - a*s[i][j] + b*s2;
    }
    return g;
}
static void reset_covariance(const double input[N][N],
    const std::array<std::array<double, 3>, 3>& g, double output[N][N]) {
    for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j) {
        output[i][j] = input[i][j];
        if (i >= 6 && i < 9) {
            output[i][j] = 0.0;
            for (int a = 0; a < 3; ++a) output[i][j] += g[i-6][a] * input[6+a][j];
        }
    }
    double left[N][N]{};
    for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j) {
        left[i][j] = output[i][j];
        if (j >= 6 && j < 9) {
            left[i][j] = 0.0;
            for (int a = 0; a < 3; ++a) left[i][j] += output[i][6+a] * g[j-6][a];
        }
    }
    for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j) output[i][j] = left[i][j];
}

struct DVec { double x, y, z; };
struct DQuat { double w, x, y, z; };
static DQuat multiply(DQuat a, DQuat b) {
    return {a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
        a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
        a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
        a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};
}
static DQuat inverse(DQuat q) { return {q.w,-q.x,-q.y,-q.z}; }
static DQuat expd(DVec v) {
    const double n=std::sqrt(v.x*v.x+v.y*v.y+v.z*v.z);
    if(n<1e-12) return {1.0,v.x/2.0,v.y/2.0,v.z/2.0};
    const double scale=std::sin(n/2.0)/n;
    return {std::cos(n/2.0),v.x*scale,v.y*scale,v.z*scale};
}
static DVec logd(DQuat q) {
    const double n=std::sqrt(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
    q={q.w/n,q.x/n,q.y/n,q.z/n};
    if(q.w<0.0) q={-q.w,-q.x,-q.y,-q.z};
    const double v=std::sqrt(q.x*q.x+q.y*q.y+q.z*q.z);
    if(v<1e-14) return {2*q.x,2*q.y,2*q.z};
    const double scale=2.0*std::atan2(v,q.w)/v;
    return {q.x*scale,q.y*scale,q.z*scale};
}

static void test_reset_jacobian_finite_difference() {
    constexpr double eps=1e-6;
    const DVec corrections[]={{0,0,0},{1.2e-5,-2.1e-5,0.7e-5},
                              {0.59,-0.34,0.22}};
    for(const DVec d:corrections) {
        float actual[3][3];
        Eskf15::attitude_reset_jacobian({static_cast<float>(d.x),static_cast<float>(d.y),
                                         static_cast<float>(d.z)},actual);
        const DQuat center=expd(d);
        for(int j=0;j<3;j++) {
            DVec shifted=d;
            if(j==0) shifted.x+=eps;
            if(j==1) shifted.y+=eps;
            if(j==2) shifted.z+=eps;
            const DVec numeric=logd(multiply(inverse(center),expd(shifted)));
            const double value[3]={numeric.x/eps,numeric.y/eps,numeric.z/eps};
            for(int i=0;i<3;i++)
                assert(std::fabs(value[i]-actual[i][j])<3e-5);
        }
        const auto reference=right_jacobian({static_cast<float>(d.x),
            static_cast<float>(d.y),static_cast<float>(d.z)});
        for(int i=0;i<3;i++) for(int j=0;j<3;j++)
            assert(std::fabs(reference[i][j]-actual[i][j])<2e-6);
    }
}

static bool test_posterior_covariance_uses_exact_reset() {
    Settings config;
    config.expected_period_us = 5000;
    config.gravity_policy = GravityPolicy::ConfirmedOnly;
    Eskf15 filter(config);
    uint64_t timestamp = 1000000;
    for (unsigned i = 0; i < 120; ++i) {
        timestamp += 5000;
        filter.process({timestamp, {0,0,kGravity}, {0,0,0}});
    }
    assert(filter.ready());

    // Excitation creates velocity/attitude cross-covariance, so a velocity
    // measurement produces a finite multi-axis attitude injection.
    for (unsigned i = 0; i < 600; ++i) {
        timestamp += 5000;
        const float t = static_cast<float>(i) * 0.005f;
        const Vec3 accel{2.0f*std::sin(1.7f*t), 1.4f*std::cos(1.1f*t),
                         kGravity + 1.0f*std::sin(0.8f*t)};
        const Vec3 gyro{0.7f*std::sin(0.9f*t), 0.55f*std::cos(1.3f*t),
                        0.45f*std::sin(1.1f*t)};
        assert(filter.process({timestamp, accel, gyro}));
    }

    constexpr double sigma = 0.025;
    const double residual[3] = {0.7, -0.5, 0.6};
    double p[N][N]{};
    for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j)
        p[i][j] = filter.covariance(i,j);

    std::array<std::array<double,3>,3> s{};
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
        s[i][j] = p[3+i][3+j] + (i == j ? sigma*sigma : 0.0);
    const auto sinv = inverse3(s);
    double ph[15][3]{}, gain[15][3]{}, dx[15]{};
    for (int i = 0; i < N; ++i) for (int j = 0; j < 3; ++j)
        ph[i][j] = p[i][3+j];
    for (int i = 0; i < N; ++i) for (int j = 0; j < 3; ++j)
        for (int k = 0; k < 3; ++k) gain[i][j] += ph[i][k] * sinv[k][j];
    for (int i = 0; i < N; ++i) for (int j = 0; j < 3; ++j)
        dx[i] += gain[i][j] * residual[j];
    const double correction_norm = std::sqrt(dx[6]*dx[6] + dx[7]*dx[7] + dx[8]*dx[8]);
    std::fprintf(stderr, "oracle attitude correction norm=%.9f rad\n", correction_norm);
    assert(correction_norm > 0.005);

    double joseph[N][N]{};
    for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j) {
        double value = 0.0;
        for (int a = 0; a < N; ++a) for (int b = 0; b < N; ++b) {
            const double ji = (i == a ? 1.0 : 0.0)
                - (a >= 3 && a < 6 ? gain[i][a-3] : 0.0);
            const double jj = (j == b ? 1.0 : 0.0)
                - (b >= 3 && b < 6 ? gain[j][b-3] : 0.0);
            value += ji * p[a][b] * jj;
        }
        for (int k = 0; k < 3; ++k) value += gain[i][k] * gain[j][k] * sigma*sigma;
        joseph[i][j] = value;
    }
    const Vec3 dtheta{static_cast<float>(dx[6]), static_cast<float>(dx[7]),
                      static_cast<float>(dx[8])};
    const auto reset = right_jacobian(dtheta);
    double rotated[N][N]{};
    reset_covariance(joseph, reset, rotated);
    std::array<std::array<double, 3>, 3> first_order{};
    const double sx[3][3]={{0,-dtheta.z,dtheta.y},
        {dtheta.z,0,-dtheta.x},{-dtheta.y,dtheta.x,0}};
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j)
        first_order[i][j]=(i==j?1.0:0.0)-0.5*sx[i][j];
    double approximate[N][N]{};
    reset_covariance(joseph, first_order, approximate);

    const Vec3 measured_velocity = filter.state().velocity
        + Vec3{static_cast<float>(residual[0]), static_cast<float>(residual[1]),
               static_cast<float>(residual[2])};
    assert(filter.update_velocity_world_at({timestamp, 7, 0}, measured_velocity,
                                           static_cast<float>(sigma)));
    double max_error = 0.0, reset_error = 0.0, first_order_reset_error = 0.0;
    int max_i=0,max_j=0;
    for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j) {
        const double exact_error=std::fabs(filter.covariance(i,j)-rotated[i][j]);
        const double approximate_error=std::fabs(filter.covariance(i,j)-approximate[i][j]);
        if(exact_error>max_error){max_error=exact_error;max_i=i;max_j=j;}
        if((i>=6&&i<9)||(j>=6&&j<9)) {
            reset_error=std::max(reset_error,exact_error);
            first_order_reset_error=std::max(first_order_reset_error,approximate_error);
        }
    }
    std::printf("max covariance error=%.9g at (%d,%d); exact reset block=%.9g; first-order reset block=%.9g\n",
        max_error,max_i,max_j,reset_error,first_order_reset_error);
    if (max_error > 5e-4 || !(reset_error + 1e-8 < first_order_reset_error)) {
        std::puts("FAIL posterior covariance does not match the exact right-error reset oracle");
        return false;
    }
    assert(filter.covariance_positive_definite());
    return true;
}

int main() {
    test_reset_jacobian_finite_difference();
    if (!test_posterior_covariance_uses_exact_reset()) return 1;
    std::puts("PASS independent FP64 Joseph and right-error covariance-reset oracle");
}
