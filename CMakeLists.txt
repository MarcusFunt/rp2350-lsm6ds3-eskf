cmake_minimum_required(VERSION 3.13)

# An RP2350 Pico 2 board is assumed; change for your RP2350 variant.
set(PICO_BOARD pico2 CACHE STRING "RP2350 target board")
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(rp2350_lsm6ds3_fusion C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
pico_sdk_init()

add_executable(rp2350_lsm6ds3_fusion main.cpp eskf15.hpp)
pico_generate_pio_header(rp2350_lsm6ds3_fusion
    ${CMAKE_CURRENT_LIST_DIR}/drdy_period.pio)

target_link_libraries(rp2350_lsm6ds3_fusion PRIVATE
    pico_stdlib
    pico_multicore
    pico_util
    hardware_spi
    hardware_dma
    hardware_pio
    hardware_clocks
    hardware_irq
    m
)

pico_enable_stdio_usb(rp2350_lsm6ds3_fusion 1)
pico_enable_stdio_uart(rp2350_lsm6ds3_fusion 0)
pico_add_extra_outputs(rp2350_lsm6ds3_fusion)

# Debug-only raw CSV stream: USB output can perturb acquisition timing.
option(RP2350_STREAM_RAW_CSV "Emit every raw IMU sample over USB CDC (debug only)" OFF)
if(RP2350_STREAM_RAW_CSV)
    target_compile_definitions(rp2350_lsm6ds3_fusion PRIVATE RP2350_STREAM_RAW_CSV=1)
endif()
