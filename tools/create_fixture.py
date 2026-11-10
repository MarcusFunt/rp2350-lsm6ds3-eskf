#!/usr/bin/env python3
"""Synthetic repeatable IMU-only fixture; not measured hardware evidence."""
from pathlib import Path
import math
f=Path(__file__).resolve().parent.parent/'fixtures'/'stationary_then_yaw.csv'
f.parent.mkdir(parents=True, exist_ok=True)
with f.open('w') as h:
    h.write('# dataset=synthetic; no hardware ground truth; timebase=sim_200hz\n')
    h.write('# calibration_id=0; frame=body_xyz; units=m/s2,rad/s\n')
    h.write('timestamp_us,ax_mps2,ay_mps2,az_mps2,gx_rps,gy_rps,gz_rps\n')
    for i in range(1,1201):
        gz=0.0 if i<=200 else math.pi/8
        h.write(f'{i*5000},0,0,9.80665,0,0,{gz:.12g}\n')
print(f)
