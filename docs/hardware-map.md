# Hardware map of the Mikro MK3 (what our own drivers talk to)

Facts about the board, established for `docs/clean-firmware-plan.md`: register values read from the running device with `tools/periph_dump.py` (2026-10-19, stock init + our patch), and bus protocols observed by running the stock routines in the emulator with a peripheral model (`tools/emu/periph.py`). No NI code is reproduced here; where our driver must behave like the stock one, the behaviour is described and `tools/midi_patch/test_hal_*.py` compare the two on the emulated hardware.

## Chip set-up (read from the device)
- **Clocks**: 8 MHz crystal (HSE) x 9 = 72 MHz SYSCLK; AHB /1, APB1 /2 (36 MHz), APB2 /1; ADC clock /6 = 12 MHz; USB clock /1.5 = 48 MHz.
- **Clocks enabled**: DMA1, SRAM, FLITF; AFIO, GPIOA, GPIOB, GPIOC, ADC1; SPI2, USB. No timers, no hardware I2C, no USART.
- **Debug port**: `AFIO_MAPR` SWJ_CFG = 2: **SWD stays enabled** (PA13 SWDIO, PA14 SWCLK), JTAG off. An ST-Link on the SWD pads can halt, read and reflash the chip while the firmware runs (no read or write protection, `docs/hardware-probe.md`).
- **Interrupts**: only USB low priority (and the SysTick exception, 0.5 ms: AHB/8, reload 4500). Everything else is polled from the main loop.
- **Watchdog**: IWDG prescaler /32, reload 1250 = 1 s.
- **Vector table**: `VTOR = 0x08003000` (the application base above the bootloader).

## Pins
| Pin | Mode | Use |
|---|---|---|
| PA0-PA7 | input (floating) | pads: ADC channels 0-7 |
| PB0, PB1 | analog | pads: ADC channels 8, 9 |
| PC0-PC5 | analog | pads: ADC channels 10-15 |
| PB2, PB3, PB4, PB10, PB11 | output push-pull | button matrix columns (5) |
| PC6-PC15 | input pull-up | button matrix rows and the encoder |
| PB6 / PB7 | output (PB7 also input with pull-up while waiting for an acknowledge) | LED bus: SCL / SDA |
| PB8, PB9 | output, high | (held high by the LED set-up) |
| PA9 / PA10 | open-drain (`CRH` 0x7) / input | touch-strip bus: SDA / SCL |
| PA8, PA15 | output (PA15 open-drain), high | (strip controller side) |
| PB12 | output | display chip select |
| PB13 / PB15 | SPI2 SCK / MOSI (alternate function) | display |
| PB14 | output | display data / command |

## Pads: ADC1 + DMA1 channel 1
- ADC1 in scan mode, 16 conversions per scan in the order 10, 11, 12, 13, 0, 1, 2, 3, 4, 5, 6, 7, 14, 15, 8, 9, each with 71.5 cycles sampling (7 us at 12 MHz: about 112 us per scan); started by software (external trigger = SWSTART), not continuous.
- DMA1 channel 1: ADC1 data register to RAM, 16-bit, circular, memory increment, priority high, 16 transfers: the raw values of the last scan in scan order.

## LED bus: two IS31FL3731-type matrix drivers
- Bit-banged I2C on SCL = PB6, SDA = PB7, about 0.7 us per half bit. Chips at 7-bit addresses **0x74** and **0x77**, each 144 LEDs with 8-bit PWM (the register map of the IS31FL3731: `0xFD` selects a page, page `0x0B` holds the function registers, frame page 0 holds LED control at `0x00-0x11`, blink control at `0x12-0x23`, PWM at `0x24-0xB3`).
- Each write is: stop, start, address byte, acknowledge, register, acknowledge, data bytes each acknowledged, stop. SDA is driven push-pull while sending and is an input with pull-up while waiting (up to 250 reads) for the acknowledge; a missing acknowledge ends the write.
- **Start-up**, per chip (0x74, then 0x77): page `0x0B`; function registers `0x00-0x0C` = 0; page 0; LED control, blink control and PWM = 0; page `0x0B`; register `0x0A` (shutdown) = 1 = normal operation; a write of `0x10` to register `0xC2` of chip 0x74; page 0.
- **Refresh**: the LED state lives in a 324-byte matrix (control of 0x74, control of 0x77, PWM of 0x74, PWM of 0x77). After a change it is sent in 10 steps, one per main-loop pass: the control registers of 0x74 and of 0x77, then the PWM registers in four blocks of 36, alternating the chips. PWM values are scaled by the brightness level (11 levels: 21, 29, 38, 46, 54, 62, 70, 78, 86, 94, 100 %); a shadow of what the chips hold means a block is sent only when it changed.
- On the device (2026-10-19) our driver's start-up and refresh were acknowledged by both chips (80 of 80 bursts).

## Display: SSD1306-type 128 x 32 OLED on SPI2
- SPI2 master, clock /16 (2.25 MHz), CPOL 1 / CPHA 1, MSB first, 8 bit, one-line transmit (bidirectional mode, output). Chip select PB12, data / command PB14.
- Start-up commands (in order): `AE` (off), `40` (start line 0), `B0` (page 0), `C0` (COM scan normal), `81 00` (contrast, then set from the settings), `A0` (segment remap), `A6` (normal, not inverted), `A8 1F` (multiplex 32), `D3 00` (offset 0), `D5 F0` (clock), `D9 22` (pre-charge), `DA 02` (COM pins), `DB 49` (VCOMH), then the picture.

## Touch strip controller
- Bit-banged I2C on SDA = PA9, SCL = PA10, both open-drain; the half-bit delay is a calibrated loop count. The controller may stretch the clock (the master waits for SCL to rise), and before each start the master clocks up to 10 times to free an SDA held low by a slave.
- **Read cycle**, every 5 ms: write register `0x00` to address **0x15**, then read 4 bytes: number of touches (0..2, more is ignored), position of touch 1, position of touch 2 (1..200), pressure. A small filter turns them into the strip values: a new number of touches takes the new positions at once (from one touch to two, the touch nearer the old position stays first); with the same number of touches a position moves after a jump of more than 10, or after 3 reads moving the same way; a pressure change is passed on at once.
- **Start-up**: the firmware writes configuration to the controller and reads back two 7-byte status blocks, expecting fixed identification bytes (`F5 F6` in the first, `00 30 00 00 00 20` in the second); if the controller does not answer as expected it retries, and the start-up stops there. (Details with the start-up driver.)
- On the device (2026-10-19) our read cycle ran 401 times in 2 s without a failure.

## Buttons and encoder
- **Matrix**: 5 columns driven low one at a time in the order PB3, PB4, PB2, PB10, PB11 (the others high); 8 rows read from PC8..PC15 (pull-ups, pressed = low). The button at column c, row r has the id `build_patch.BTN_MATRIX[c * 8 + r]` (ids as in `mmk3_config.BUTTON_NAMES`; the encoder push is id 39 at column 4, row 7).
- **Encoder**: a quadrature encoder on PC6 / PC7 (pull-ups).
- **Scan**: one step per main-loop pass: the encoder pins are read and debounced every step; every second step the matrix alternates between driving the next column and reading its rows, so a column settles for a whole step before it is read. A row byte counts when read the same twice in a row. The encoder direction comes from which pin changed while the other one matched.

## Pads
- **Averaging**: when a DMA scan is complete the 16 raw values (12 bit) are added up; every 5 scans each pad's average is taken and the pads are evaluated; the next scan is started by software.
- **Evaluation**: the average goes through a 16-segment curve to a 12-bit pressure (0 below a raw 300, steeper towards the top: the sensor's response flattens), minus the pad's own offset (calibration, from the settings page) and the global threshold (from the sensitivity setting). Per pad a state machine reports: a **hit** (type 1) at its peak, once the reading falls again at least 6 ms after the touch began, if the peak is above threshold + 200; a slow **press** (type 0) after 60 ms of rising, above threshold + 100 (or later once the pressure gets there); the **pressure** (type 4) when it changed and 30 evaluations passed since the last report; the **release** (type 3 after a hit, 2 after a press) after 7 evaluations at zero. Records are 3 bytes (pad, type << 4 | value >> 8, value & 0xFF), at most 19 per buffer.
- At rest (2026-10-19, this unit) some pads read a raw 200..1450 without being touched, below what the curve, offset and threshold let through.

## Flash and bootloader (see also docs/firmware-notes.md)
- Bootloader `0x08000000-0x08002FFF` (its initial stack pointer `0x20000C90`), application from `0x08003000`.
- Handshake page `0x0801FC00`: the application requests DFU mode by leaving `55 5A A5 AA 59 95 3A A3` there (rest erased) and resetting; after a successful flash the bootloader leaves `59 95 3A A3 55 5A A5 AA`.
- The reset flags in `RCC_CSR` survive the bootloader (it does not clear them): the application sees power-on, pin, software and watchdog resets.
