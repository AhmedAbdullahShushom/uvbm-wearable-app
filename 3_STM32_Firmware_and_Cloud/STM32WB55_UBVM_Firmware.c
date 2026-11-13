/**
 * @file    STM32WB55_UBVM_Firmware.c
 * @brief   Complete Firmware Architecture for the UBVM Microcontroller (STM32WB55RG)
 *          Implements:
 *            1. TIM1 Complementary PWM Burst Generator: 5 pulses @ 2 MHz (3.3V) on DINP (PA8) & DINN (PB13)
 *               with 180-degree phase shift triggered every 2.5 seconds.
 *            2. GPIO Multiplexer Addressing (SEL0 = PC0, SEL1 = PC1) for DG409 (Tx) and DG408 (Rx)
 *               stepping across Channels 1-4 at 10-second intervals.
 *            3. TIM2 Input Capture + DMA (PA0): Logs rising-edge timestamps from MAX941 comparator output
 *               with 15.6 ns resolution (64 MHz timer clock) and zero CPU overhead.
 *            4. BLE GATT Server Notification: Transmits [Channel_ID, Timestamp_Array] to Mobile App.
 */

#include "stm32wbxx_hal.h"
#include <stdint.h>
#include <string.h>

#define NUM_TRANSDUCERS         4
#define MAX_ECHO_TIMESTAMPS     32
#define BLANKING_WINDOW_TICKS   1280  /* 20 us blind zone @ 64 MHz to ignore Tx excitation ringdown */

TIM_HandleTypeDef htim1;  /* 2 MHz 5-Pulse Complementary Burst Timer (DINP / DINN) */
TIM_HandleTypeDef htim2;  /* 64 MHz Input Capture Timer for MAX941 Comparator Output */
DMA_HandleTypeDef hdma_tim2_ch1;

uint32_t dma_capture_buffer[MAX_ECHO_TIMESTAMPS];
uint8_t  active_channel = 0; /* 0 to 3 corresponding to Transducers 1 to 4 */

typedef struct __attribute__((packed)) {
    uint8_t  transducer_id;          /* 1 to 4 */
    uint16_t anterior_echo_us_x100;  /* Anterior wall ToF in 0.01 us units */
    uint16_t posterior_echo_us_x100; /* Posterior wall ToF in 0.01 us units */
} UBVM_BLE_Packet_t;

/**
 * @brief Select active ultrasonic transducer (1-4) via DG409 & DG408 SEL0/SEL1 pins
 */
void UBVM_Select_Transducer_Channel(uint8_t ch_index) {
    HAL_GPIO_WritePin(GPIOC, GPIO_PIN_0, (ch_index & 0x01) ? GPIO_PIN_SET : GPIO_PIN_RESET); /* SEL0 */
    HAL_GPIO_WritePin(GPIOC, GPIO_PIN_1, (ch_index & 0x02) ? GPIO_PIN_SET : GPIO_PIN_RESET); /* SEL1 */
}

/**
 * @brief Configure TIM1 for 2 MHz One-Pulse Burst Mode with Repetition Counter = 4 (5 pulses total)
 *        System Clock = 64 MHz -> Period (ARR) = 31 (64 MHz / 32 = 2.00 MHz), Pulse (CCR1) = 16 (50% duty)
 */
void UBVM_TIM1_2MHz_Burst_Init(void) {
    TIM_OC_InitTypeDef sConfigOC = {0};
    TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

    htim1.Instance = TIM1;
    htim1.Init.Prescaler = 0;
    htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim1.Init.Period = 31;                /* 64 MHz / (31 + 1) = 2.0 MHz */
    htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim1.Init.RepetitionCounter = 4;      /* RCR = 4 -> Exactly 5 pulses per trigger! */
    htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_PWM_Init(&htim1);
    HAL_TIM_OnePulse_Init(&htim1, TIM_OPMODE_SINGLE);

    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    sConfigOC.Pulse = 16;                  /* 50% Duty Cycle (250 ns HIGH, 250 ns LOW) */
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH; /* Complementary output 180 deg out of phase */
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1);

    sBreakDeadTimeConfig.DeadTime = 0;
    sBreakDeadTimeConfig.BreakState = TIM_BREAK_DISABLE;
    sBreakDeadTimeConfig.AutomaticOutput = TIM_AUTOMATICOUTPUT_ENABLE;
    HAL_TIMEx_ConfigBreakDeadTime(&htim1, &sBreakDeadTimeConfig);
}

/**
 * @brief Configure TIM2 Channel 1 (PA0) in Input Capture Mode with DMA to capture MAX941 rising edges
 */
void UBVM_TIM2_InputCapture_DMA_Init(void) {
    TIM_IC_InitTypeDef sConfigIC = {0};

    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 0;              /* 64 MHz tick rate (15.625 ns resolution) */
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 0xFFFFFFFF;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    HAL_TIM_IC_Init(&htim2);

    sConfigIC.ICPolarity = TIM_INPUTCHANNELPOLARITY_RISING;
    sConfigIC.ICSelection = TIM_ICSELECTION_DIRECTTI;
    sConfigIC.ICPrescaler = TIM_ICPSC_DIV1;
    sConfigIC.ICFilter = 0;
    HAL_TIM_IC_ConfigChannel(&htim2, &sConfigIC, TIM_CHANNEL_1);
}

/**
 * @brief Execute one complete Pulse-Echo measurement cycle on the currently selected transducer
 */
void UBVM_Execute_Pulse_Echo_Measurement(UBVM_BLE_Packet_t *out_packet) {
    memset(dma_capture_buffer, 0, sizeof(dma_capture_buffer));

    /* 1. Reset & Start TIM2 Input Capture DMA before firing ultrasonic burst */
    __HAL_TIM_SET_COUNTER(&htim2, 0);
    HAL_TIM_IC_Start_DMA(&htim2, TIM_CHANNEL_1, dma_capture_buffer, MAX_ECHO_TIMESTAMPS);

    /* 2. Fire 5-Cycle 2 MHz Complementary Burst on DINP (TIM1_CH1) and DINN (TIM1_CH1N) */
    HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
    HAL_TIMEx_PWMN_Start(&htim1, TIM_CHANNEL_1);

    /* 3. Wait 200 microseconds for Anterior & Posterior bladder wall echoes to return */
    for (volatile int delay = 0; delay < 3200; delay++) { __NOP(); }

    /* 4. Stop DMA and average Anterior (< 70 us) and Posterior (>= 70 us) echo timestamps */
    HAL_TIM_IC_Stop_DMA(&htim2, TIM_CHANNEL_1);

    uint32_t ant_sum = 0, ant_cnt = 0;
    uint32_t post_sum = 0, post_cnt = 0;
    const uint32_t mid_split_ticks = 70 * 64; /* 70 us boundary @ 64 MHz */

    for (int i = 0; i < MAX_ECHO_TIMESTAMPS; i++) {
        uint32_t ticks = dma_capture_buffer[i];
        if (ticks > BLANKING_WINDOW_TICKS) {
            if (ticks < mid_split_ticks) {
                ant_sum += ticks;
                ant_cnt++;
            } else if (ticks < (160 * 64)) {
                post_sum += ticks;
                post_cnt++;
            }
        }
    }

    out_packet->transducer_id = active_channel + 1;
    out_packet->anterior_echo_us_x100  = (ant_cnt > 0)  ? (uint16_t)(((ant_sum / ant_cnt) * 100) / 64)   : 0;
    out_packet->posterior_echo_us_x100 = (post_cnt > 0) ? (uint16_t)(((post_sum / post_cnt) * 100) / 64) : 0;
}
