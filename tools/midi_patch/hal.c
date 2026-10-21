/* Our own hardware drivers (docs/clean-firmware-plan.md, stage 2). Included at the end of translate.c, which stays the one translation
 * unit (no .rodata, no relocations: build_patch.py refuses them). Each driver replaces a stock routine with the same behaviour, so the
 * stock RAM it works on (LED matrix, shadow, brightness) stays the interface until the stock code around it is gone too. A driver is
 * switched on at run time with SysEx 1C (bit per driver, RAM only, off after every power-up): the stock routine stays the default
 * until ours has been checked on the device. docs/hardware-map.md describes the hardware they talk to. */

/* The switch (SysEx 1C <mask> [<flags>]): which of our drivers replace the stock ones. */
#define HAL_LED 1u                                   /* our LED refresh instead of the stock one */
#define HAL_DISP 2u                                  /* our display sender */
#define HAL_BTN 4u                                   /* our button matrix and encoder scan */
#define HAL_STRIP 8u                                 /* our touch strip read cycle */
#define HAL_PADS 16u                                 /* our pad averaging and evaluation */
#define HAL_REPORTS 32u                              /* our report builders and dispatcher */
#define HAL_COLOUR 64u                               /* our LED colour layer (with HAL_REPORTS: from our dispatcher) */
#define HAL2_LOOP 1u                                 /* (second mask byte) our service routine and normal-mode scan */
#define HAL2_TICK 2u                                 /* (second mask byte) our SysTick handler */
#define HAL_FLAG_NEXT_BOOT 2u                        /* flags: the next boot uses our board init (once) */
#define HAL_FLAG_NEXT_BOOT_USB 8u                    /* flags: the next boot uses our board init and our USB stack (once) */
#define HAL_FLAG_REBOOT 4u                           /* flags: reboot now (after the reply) */
#define HAL_FLAG_LED_INIT 1u                         /* flags, one-shot: run our LED chip start-up now, then send the whole matrix again */

static void own_startup_end(void);
static void own_usb_init(void);
static void own_usb_tx(void);
#define USB_SUSP (*(volatile u8 *)0x200001A5)                     /* the USB library's "suspended" flag */

/* Bit-band aliases of single GPIO bits: a write sets or clears only that pin, like the stock code does. */
#define BB(reg, bit) (*(volatile u32 *)(0x42000000u + ((reg) - 0x40000000u) * 32u + (bit) * 4u))
#define GPIOB_CRL (*(volatile u32 *)0x40010C00u)

static void __attribute__((noinline)) dly(u32 n)    /* a short busy wait: n loop turns, a few cycles each */
{
    volatile u32 i;
    for (i = 0; i < n; i++) { }
}

/* ---- the LED bus: two IS31FL3731-type matrix drivers (I2C addresses 0x74 and 0x77) on a bit-banged bus, SCL = PB6, SDA = PB7 ----
 * SCL is always push-pull; SDA is push-pull while the master sends (start, stop, each byte) and an input with pull-up while it waits for
 * the acknowledge. About 0.7 us per half bit (a few hundred kHz). */
#define LED_SCL BB(0x40010C0Cu, 6)
#define LED_SDA BB(0x40010C0Cu, 7)
#define LED_SDA_IN BB(0x40010C08u, 7)
static void led_sda_out(void) { GPIOB_CRL = (GPIOB_CRL & ~0xF0000000u) | 0x30000000u; }    /* PB7 output push-pull 50 MHz */
static void led_sda_in(void) { GPIOB_CRL = (GPIOB_CRL & ~0xF0000000u) | 0x80000000u; }     /* PB7 input with pull (ODR = 1: up) */
static void led_start(void) { led_sda_out(); dly(1); LED_SDA = 1; LED_SCL = 1; dly(12); LED_SDA = 0; dly(8); LED_SCL = 0; }
static void led_stop(void) { led_sda_out(); dly(1); LED_SDA = 0; LED_SCL = 1; dly(8); LED_SDA = 1; dly(12); }
static void led_byte(u32 b)
{
    u32 k;
    led_sda_out();
    for (k = 0; k < 8; k++) { LED_SDA = (b >> 7) & 1; b <<= 1; dly(12); LED_SCL = 1; dly(8); LED_SCL = 0; }
}
static u32 led_ack(void)                             /* 0 = the chip acknowledged; 1 = nothing pulled SDA low within 250 reads */
{
    u32 n = 250, v = 1;
    LED_SDA = 1; led_sda_in(); dly(5);
    while (n--) { v = LED_SDA_IN; if (!v) break; }
    LED_SCL = 1; dly(8); LED_SCL = 0;
    return v;
}
/* One register write burst: address byte, first register, the data (the chip's register pointer moves on by itself; d = 0: n zeros).
 * 1 = every byte was acknowledged. */
static u32 led_write(u32 addr8, u32 reg, const volatile u8 *d, u32 n)
{
    u32 k, ok = 0;
    led_stop(); led_start();
    led_byte(addr8);
    if (led_ack() != 1) {
        led_byte(reg);
        if (led_ack() != 1) {
            for (k = 0; k < n; k++) { led_byte(d ? d[k] : 0); if (led_ack() == 1) break; }
            ok = k == n;
        }
    }
    led_stop();
    return ok;
}
static u32 led_write1(u32 addr8, u32 reg, u32 v) { u8 b = (u8)v; return led_write(addr8, reg, &b, 1); }

/* The stock RAM the LED layer works on: the matrix the colour code -> LED cell mapping fills (control registers of chip 0x74, of 0x77, then
 * 144 PWM values of each), the shadow of what the chips hold (same order, walked with LED_SHOFF), the brightness level index and its
 * table (percent), and the refresh step counter (set to 10 when the matrix changed). */
#define LED_MATRIX ((volatile u8 *)0x20000EE2)
#define LED_SHADOW ((volatile u8 *)0x20000CD8)
#define LED_BRI (*(volatile u8 *)0x20000150)
#define LED_SHOFF (*(volatile u16 *)0x20000152)
#define LED_LEVELS ((const volatile u8 *)0x2000017C)
#define LED_STEP (*(volatile u8 *)(0x20001028 + 0xBC))
#define LED_A 0xE8u                                  /* write address of chip 0x74 */
#define LED_B 0xEEu                                  /* ... of chip 0x77 */

/* One step of the refresh, one per main-loop pass while LED_STEP is not 0: 10 = the LED control registers of chip A (and the shadow walk
 * starts over), 9 = those of chip B, then the PWM registers in four blocks of 36, alternating A and B (8 .. 1). PWM values are scaled by
 * the brightness level; a block is sent only when something in it changed. */
static void __attribute__((noinline)) own_led_refresh(void)
{
    u32 s = LED_STEP, addr, reg, n, src, k, j, changed = 0, lvl;
    volatile u8 *sh;
    if (s == 10 || s == 9) { addr = s == 10 ? LED_A : LED_B; reg = 0; n = 18; src = s == 10 ? 0 : 18; if (s == 10) LED_SHOFF = 0; }
    else {
        j = (s >= 2 && s <= 8) ? (8 - s) >> 1 : 3;
        addr = (s >= 2 && s <= 8 && !(s & 1)) ? LED_A : LED_B;
        reg = 0x24 + 0x24 * j; n = 36; src = (addr == LED_A ? 0x24 : 0xB4) + 0x24 * j;
    }
    sh = LED_SHADOW + LED_SHOFF;
    lvl = LED_LEVELS[LED_BRI];
    for (k = 0; k < n; k++) {
        u32 v = LED_MATRIX[src + k];
        if (s <= 8) v = (u8)(v * lvl / 100);
        if (sh[k] != v) { sh[k] = (u8)v; changed = 1; }
    }
    if (changed) { if (led_write(addr, reg, sh, n)) ST->hal_ok++; else ST->hal_fail++; }
    LED_STEP = (u8)(s - 1);
    LED_SHOFF = (u16)(LED_SHOFF + n);
}

/* Bring both chips up: function page (0x0B) cleared, frame 0 cleared (LEDs off, no blinking, PWM 0), normal operation (shutdown register
 * 0x0A = 1), back on frame 0. The same sequence as the stock start-up, including its write of C2 = 10 to chip 0x74 after each chip. */
static void __attribute__((noinline)) own_led_init(void)
{
    u32 c, addr;
    for (c = 0; c < 2; c++) {
        addr = c ? LED_B : LED_A;
        led_write1(addr, 0xFD, 0x0B);
        led_write(addr, 0x00, 0, 13);
        led_write1(addr, 0xFD, 0x00);
        led_write(addr, 0x00, 0, 18);
        led_write(addr, 0x12, 0, 18);
        led_write(addr, 0x24, 0, 144);
        led_write1(addr, 0xFD, 0x0B);
        led_write1(addr, 0x0A, 0x01);
        led_write1(LED_A, 0xC2, 0x10);
        led_write1(addr, 0xFD, 0x00);
    }
}

/* ---- the display: an SSD1306-type 128 x 32 OLED on SPI2 (SCK PB13, MOSI PB15), data / command on PB14 ----
 * The picture is the stock framebuffer (512 bytes, 4 pages of 128 columns, a lit pixel is a CLEARED bit; the controller wants a set bit, so
 * every byte goes out inverted). It is sent in 8 chunks (64 columns of one page), one per call: the counter DISP_CNT counts the chunks still
 * to send (8 = page 0 left half ... 1 = page 3 right half), DISP_GAP makes the main loop wait 3 ms before the next call, and a counter that
 * was marked "changed again while sending" (bit 7, set by the code that applies a new picture) starts over at 8 after its last chunk. */
#define SPI2_CR2 (*(volatile u16 *)0x40003804u)
#define SPI2_SR (*(volatile u16 *)0x40003808u)
#define SPI2_DR (*(volatile u16 *)0x4000380Cu)
#define GPIOB_ODR (*(volatile u32 *)0x40010C0Cu)
#define DISP_FB ((const u8 *)(0x20001028 + 0xCA))
#define DISP_PTR (*(const u8 * volatile *)0x20000188)  /* where the next chunk's data starts */
#define DISP_CNT (*(volatile u8 *)(0x20001028 + 0xC8))
#define DISP_GAP (*(volatile u8 *)(0x20001028 + 0xC9))

static u32 spi_put(u32 b)                            /* one byte into SPI2 once the transmit buffer is free (at most 21 looks) */
{
    u32 n;
    for (n = 0; n <= 20; n++) if (SPI2_SR & 2) { SPI2_DR = (u16)b; return 1; }
    return 0;
}
/* A command (dc = 0) or data byte (dc = 1) with the data / command line set first; then about 20 us of waiting (100 looks at the transmit
 * interrupt, which is never enabled: the stock code waits like this, long enough for the byte to leave before D/C goes back high). */
static void disp_put(u32 dc, u32 b)
{
    u32 n;
    if (dc == 0) GPIOB_ODR &= ~0x4000u; else if (dc == 1) GPIOB_ODR |= 0x4000u;
    spi_put(b);
    for (n = 100; n; n--) if ((SPI2_SR & 2) && (SPI2_CR2 & 0x80)) break;
    GPIOB_ODR |= 0x4000u;
}
static void disp_window(u32 x0, u32 page, const u8 *p)     /* 64 columns of one page: position, then the inverted bytes */
{
    u32 x;
    disp_put(0, 0xB0 + page); disp_put(0, 0x10 | (x0 >> 4)); disp_put(0, x0 & 15);
    for (x = 0; x < 64; x++) spi_put(0xFFu - p[x]);
}
static void __attribute__((noinline)) own_disp_send(void)
{
    u32 c = DISP_CNT, r = c % 17, k = (r >= 2 && r <= 8) ? 8 - r : 7;
    const u8 *p = k ? DISP_PTR + 0x40 : DISP_FB;
    DISP_PTR = p;
    disp_window((k & 1) * 64, k >> 1, p);
    DISP_GAP = 3;
    c = (c - 1) & 0xFF;
    DISP_CNT = (u8)c;
    if (r == 1 && c > 0x7F) DISP_CNT = 8;
}

/* ---- buttons and encoder: a 5 x 8 matrix and a quadrature encoder on GPIO ----
 * Each call is one step: the encoder pins (PC6, PC7) are read and debounced every time; every second call the matrix moves on, alternating
 * "drive the next column low" and "read its 8 rows" (PC8..PC15, pull-ups: pressed = 0), so a column settles for a whole call before it is
 * read. A row byte counts as stable when it was read the same twice in a row; the stable state of every column and the debounced encoder
 * pins are kept in the stock block BTN, and the returned flags (1 encoder, 2 a column changed) are passed to the evaluation, which turns
 * them into the stock button bytes (struct + 0x8B + id, "changed" flag + 0x8A) and encoder steps (+ 0xBA: 1 or 2, by direction). */
#define BTN ((volatile u8 *)0x20000129)
#define GPIOC_IDR (*(volatile u32 *)0x40011008u)
#define HW_COLMASK ((const u16 *)HW_ADDR)
#define HW_BTN_ID ((const u8 *)(HW_ADDR + 16))
#define STK ((volatile u8 *)0x20001028)

static u32 __attribute__((noinline)) own_btn_scan(void)
{
    u32 f = 0, enc, c, rows, n;
    *(volatile u16 *)(0x20001028 + 0x88) = 1;           /* (the main loop's scan timer) */
    enc = GPIOC_IDR & 0xC0;
    if (BTN[0] == enc) {
        n = BTN[1];
        if (n < 0xF0) {
            n = (n + 1) & 0xFF; BTN[1] = (u8)n;
            if (n == 1) { BTN[7] = (enc >> 6) & 1; BTN[8] = (enc >> 7) & 1; f = 1; }
        }
    } else { BTN[1] = 0; BTN[0] = (u8)enc; }
    if (!BTN[2]) { BTN[2] = 1; return f; }
    BTN[2] = 0;
    if (!BTN[4]) {                                       /* drive the column low, the others high */
        BTN[4] = 1;
        GPIOB_ODR = (GPIOB_ODR | 0xC1Cu) & ~(u32)HW_COLMASK[BTN[3]];
        return f;
    }
    BTN[4] = 0;                                          /* read its rows */
    rows = (GPIOC_IDR >> 8) & 0xFF;
    c = BTN[3];
    if (BTN[9 + c] == rows) {
        n = BTN[14 + c];
        if (n < 0xF0) {
            n = (n + 1) & 0xFF; BTN[14 + c] = (u8)n;
            if (n == 2) { BTN[0x18 + c] = (u8)~rows; f = (f + 2) & 0xFF; }
        }
    } else { BTN[14 + c] = 0; BTN[9 + c] = (u8)rows; }
    c = (c + 1) & 0xFF;
    BTN[3] = (u8)c;
    if (c >= 5) BTN[3] = 0;
    return f;
}

static void __attribute__((noinline, used)) own_btn_eval(u32 f)
{
    if (f & 1) {                                         /* quadrature: which pin changed while the other matched decides the direction */
        if (BTN[5] != BTN[7]) { if (BTN[5] == BTN[6]) STK[0xBA] = 1; BTN[5] = BTN[7]; }
        if (BTN[6] != BTN[8]) { if (BTN[5] == BTN[6]) STK[0xBA] = 2; BTN[6] = BTN[8]; }
    }
    if (f & 2) {
        u32 c, b;
        for (c = 0; c < 5; c++) {
            u32 d = BTN[0x13 + c] ^ BTN[0x18 + c], now = BTN[0x18 + c];
            if (!d) continue;
            for (b = 0; b < 8; b++) {
                u32 m = 1u << b;
                if (!(d & m)) continue;
                BTN[0x13 + c] ^= (u8)m;
                STK[0x8A] = 1;
                STK[0x8B + HW_BTN_ID[c * 8 + b]] = (u8)(m & now);
            }
        }
    }
}

/* ---- the touch strip: a controller at I2C address 0x15 on a second bit-banged bus, SDA = PA9, SCL = PA10, both open-drain ----
 * Slower than the LED bus (the half-bit delay counts STK[0xC7] loop turns per unit), it lets the controller stretch the clock (the master
 * waits until SCL is really high: bounded here, the stock code would wait forever), and before a start it frees a stuck SDA with up to 10
 * clock pulses. A transaction is the address byte (R/W in bit 0) and its data in one buffer; the last byte of a read is not acknowledged. */
#define SB_SDA BB(0x4001080Cu, 9)
#define SB_SCL BB(0x4001080Cu, 10)
#define SB_SDA_IN BB(0x40010808u, 9)
#define SB_SCL_IN BB(0x40010808u, 10)
#define GPIOA_CRH (*(volatile u32 *)0x40010804u)
static void sb_mode(u32 shift, u32 mode) { GPIOA_CRH = (GPIOA_CRH & ~(0xFu << shift)) | (mode << shift); }
#define SDA_IN() sb_mode(4, 4)                       /* input floating */
#define SDA_OUT() sb_mode(4, 7)                      /* output open-drain 50 MHz */
#define SCL_IN() sb_mode(8, 4)
#define SCL_OUT() sb_mode(8, 7)
/* The strip bus delay: n units of STK[0xC7] loop turns, the same instructions as the stock loop (the controller's wake-up after its reset
 * is timing-sensitive: a C loop that ran 1.7 times slower made it fail on the device, 2026-10-20). */
static void __attribute__((noinline, naked)) sdly(u32 n)
{
    __asm volatile(
        "movs r2, #0\n"
        "ldr r1, =0x20001028\n"
        "ldrb r3, [r1, #0xc7]\n"
        "b 2f\n"
        "1: movs r1, #0\n"
        "b 4f\n"
        "3: adds r1, r1, #1\n"
        "uxth r1, r1\n"
        "4: cmp r3, r1\n"
        "bhi 3b\n"
        "adds r2, r2, #1\n"
        "uxth r2, r2\n"
        "2: cmp r2, r0\n"
        "blo 1b\n"
        "bx lr\n"
        ".ltorg\n");
}
static void sb_wait_scl(void) { u32 n = 7000000; while (!SB_SCL_IN && --n) { } }   /* clock stretching: the controller holds SCL for
                                                                                  * a long time after its configuration (11 ms was too short on the device); about 0.4 s, under the 1 s watchdog */
static u32 sb_free(void)                            /* 1 when SDA is high, after clocking up to 10 times if a slave holds it low */
{
    u32 k;
    SDA_IN();
    if (SB_SDA_IN) return 1;
    SDA_OUT(); SB_SDA = 1; SDA_IN(); SCL_OUT();
    for (k = 1; ; k++) {
        if (SB_SDA_IN) return 1;
        if (k > 10) return 0;
        SB_SCL = 0; sdly(1); SB_SCL = 1; sdly(1);
    }
}
static u32 sb_start(void)
{
    if (!sb_free()) return 0;
    SDA_IN(); SCL_IN();
    if (!SB_SDA_IN || !SB_SCL_IN) return 0;
    SDA_OUT(); SCL_OUT();
    SB_SDA = 0; sdly(1); SB_SCL = 0; sdly(1);
    return 1;
}
static u32 sb_stop(void)
{
    if (!sb_free()) return 0;
    SDA_OUT(); SB_SDA = 0; SB_SCL = 1; sdly(1); SB_SDA = 1; sdly(1);
    SDA_IN(); SCL_IN();
    return SB_SDA_IN && SB_SCL_IN;
}
static u32 sb_put(u32 b)                             /* 1 = acknowledged */
{
    u32 k, ack;
    for (k = 0; k < 8; k++) { SB_SCL = 0; sdly(2); SB_SDA = (b >> 7) & 1; SB_SCL = 1; sdly(2); b = (b << 1) & 0xFF; }
    SB_SCL = 0; sdly(1); SB_SDA = 1; SB_SCL = 1;
    SCL_IN(); sb_wait_scl(); SCL_OUT(); sdly(1);
    SDA_IN(); ack = !SB_SDA_IN;
    SDA_OUT(); sdly(1); SB_SCL = 0;
    return ack;
}
static u32 sb_get(u32 last)                          /* last = 1: answer the byte with a not-acknowledge */
{
    u32 k, v = 0;
    SB_SDA = 1; SDA_IN();
    for (k = 8; k; k--) {
        SB_SCL = 0; sdly(2); SB_SCL = 1;
        SCL_IN(); sb_wait_scl(); SCL_OUT(); sdly(2);
        if (SB_SDA_IN) v |= 1u << (k - 1);
    }
    SB_SCL = 0; sdly(1); SDA_OUT(); SB_SDA = last ? 1 : 0; sdly(1); SB_SCL = 1;
    SCL_IN(); sb_wait_scl(); SCL_OUT(); sdly(1); SB_SCL = 0;
    return v;
}
static u32 sb_xfer(volatile u8 *buf, u32 len)      /* 1 = done; the read bytes land behind the address byte */
{
    u32 mode;
    if (!len) return 0;
    mode = (buf[0] & 1) ? 1 : 3;                     /* 1 = address of a read, 2 = reading, 3 = writing */
    if (!sb_start()) goto fail;
    for (; len; len--) {
        if (mode == 1) { if (!sb_put(*buf++)) goto fail; mode = 2; }
        else if (mode == 2) *buf++ = (u8)sb_get(len == 1);
        else if (!sb_put(*buf++)) goto fail;
    }
    sb_stop();
    return 1;
fail:
    sb_stop();
    return 0;
}

/* The read cycle, every 5 ms (STK[0xC2]): register 0 of the controller, then the number of touches (0..2), two positions (0..199 + 1)
 * and the pressure. The stock filter that turns them into the strip values (STK[0xC4], [0xC5] positions, [0xC6] pressure, [0xC3] "changed"):
 * a different number of touches takes the new positions at once (going from one touch to two keeps the one closer to the old position
 * first); the same number moves a position only after a jump of more than 10, or after 3 reads moving the same way. */
#define STRIP ((volatile u8 *)0x2000018C)            /* [0] last touch count, [2..3] the write, [4..5] last positions, [6..7] direction, [8..9] last direction, [10..11] count, [14..18] the read */
static void __attribute__((noinline)) own_strip_read(void)
{
    volatile u8 *r = STRIP + 14;
    u32 n, prev, k, d, a, p1, p2, d1, d2;
    STK[0xC2] = 5;
    if (!sb_xfer(STRIP + 2, 2) || !sb_xfer(r, 5)) { ST->strip_fail++; return; }
    ST->strip_ok++;
    n = r[1];
    if (n >= 3) return;
    prev = STRIP[0];
    if (n == prev) {
        for (k = 0; k < prev; k++) {
            u32 old = STRIP[4 + k], now = r[2 + k];
            if (old == now) continue;
            if (old > now) { d = old - now; STRIP[6 + k] = 1; } else { d = now - old; STRIP[6 + k] = 2; }
            if (d > 10) { STK[0xC3] = 1; STK[0xC4 + k] = (u8)now; continue; }
            if (STRIP[8 + k] != STRIP[6 + k]) {
                STRIP[8 + k] = STRIP[6 + k];
                if (STRIP[6 + k]) { if (STRIP[10 + k]) STRIP[10 + k]--; }
                else STRIP[10 + k] = 1;
                continue;
            }
            if (STRIP[10 + k] < 3) STRIP[10 + k]++;
            else { STK[0xC3] = 1; STK[0xC4 + k] = (u8)now; }
        }
    } else {
        if (prev == 1 && n) {
            a = STK[0xC4]; p1 = r[2]; p2 = r[3];
            d1 = a > p1 ? a - p1 : p1 - a; d2 = a > p2 ? a - p2 : p2 - a;
            if (d1 > d2) { if (d2 > 5) { STK[0xC4] = (u8)p1; STK[0xC5] = (u8)p2; } else { STK[0xC5] = (u8)a; STK[0xC4] = (u8)p1; } }
            else { if (d1 > 5) { STK[0xC4] = (u8)p1; STK[0xC5] = (u8)p2; } else STK[0xC5] = (u8)p2; }
        } else { STK[0xC4] = r[2]; STK[0xC5] = r[3]; }
        STK[0xC3] = 1; STRIP[8] = 0; STRIP[9] = 0; STRIP[0] = (u8)n;
    }
    STRIP[4] = r[2]; STRIP[5] = r[3];
    if (STK[0xC6] != r[4]) { STK[0xC6] = r[4]; STK[0xC3] = 1; }
}

/* ---- the pads: 16 force sensors on ADC1, scanned by DMA1 channel 1 into ADC_RAW (docs/hardware-map.md) ----
 * Every finished scan is added up; every 5 scans the average of each pad goes to PAD_AVG and the pads are evaluated. The evaluation turns
 * the average into a 12-bit pressure (a 16-segment curve, then the pad's own offset and the global threshold), and runs a small state machine
 * per pad: a hit is reported at its peak (once the reading falls again, at least 6 ms after the touch began), a slow press after 60 ms; the
 * pressure is reported when it changed and at least 30 evaluations passed since the last report; a release after 7 evaluations at zero.
 * The events are written as 3-byte records (pad, type << 4 | value >> 8, value & 0xFF) into the stock report buffer, which the translator
 * reads. Event types: 0 press, 1 hit (above the higher threshold), 2 / 3 release of a press / hit, 4 pressure. */
#define PAD_ACC ((volatile u16 *)0x20000738)          /* sums of the scans so far */
#define PAD_AVG ((volatile u16 *)0x20000758)          /* the averages */
#define PAD_NSCAN (*(volatile u8 *)0x20000128)
#define PAD_TH ((volatile u16 *)0x2000014A)           /* threshold (from the sensitivity), threshold + 100, threshold + 200 */
#define PAD_CNT ((volatile u8 *)0x20000CB8)           /* evaluations since the last pressure report */
#define PAD_OFF ((volatile u8 *)0x20000CC8)           /* each pad's offset (calibration, from the settings) */
#define PAD_PEAK ((volatile u16 *)0x20000C78)
#define PAD_ZERO ((volatile u16 *)0x20000C98)         /* evaluations at zero */
#define PAD_ST(i) ((volatile u8 *)(0x20001028 + 8 + 8 * (i)))   /* [0..1] last reported pressure, [4] ms since the touch, [5] phase, [6] hit state */
#define PAD_OUT ((volatile u8 *)(0x20001028 + 0x2EA)) /* the event buffer (63 bytes), its "full" flag STK[0x2CE], "evaluate again" STK[6] */
#define ADC_CR2 (*(volatile u32 *)0x40012408u)
#define DMA1_IFCR (*(volatile u32 *)0x40020004u)

static void __attribute__((noinline)) own_adc_avg(void)       /* a scan is finished (DMA channel 1 complete) */
{
    u32 i;
    for (i = 0; i < 16; i++) PAD_ACC[i] = (u16)(PAD_ACC[i] + (ADC_RAW[i] & 0xFFF));
    if (++PAD_NSCAN >= 5) {
        PAD_NSCAN = 0;
        for (i = 0; i < 16; i++) { PAD_AVG[i] = (u16)(PAD_ACC[i] / 5); PAD_ACC[i] = 0; }
        STK[6] = 1;
    }
    DMA1_IFCR = 2;                                   /* the transfer-complete flag of channel 1 */
    ADC_CR2 |= 0x500000;                             /* the next scan: external trigger = software, start */
}

static u32 pad_curve(u32 v)                          /* the raw average (12 bit) to pressure; 0 below 300 */
{
    if (v < 300) return 0;
    if (v < 1300) return (v - 300) / 10;
    if (v < 2000) return (v - 1300) / 5 + 100;
    if (v < 2500) return (v - 2000) * 2 / 5 + 240;
    if (v < 2850) return 440 + (v - 2500) / 2;
    if (v < 3150) return v - 2235;
    if (v < 3400) return 915 + (v - 3150) * 2;
    if (v < 3600) return 1415 + (v - 3400) * 3;
    if (v < 3750) return 2015 + (v - 3600) * 4;
    if (v < 3850) return 2615 + (v - 3750) * 5;
    if (v < 3900) return 3115 + (v - 3850) * 8;
    if (v < 3925) return 3515 + (v - 3900) * 12;
    if (v < 3940) return 3815 + (v - 3925) * 14;
    if (v < 3950) return 4025 + (v - 3940) * 16;
    if (v < 3955) return 4185 + (v - 3950) * 18;
    return 4275 + (v - 3955) * 20;
}

static void __attribute__((noinline)) own_pad_eval(void)
{
    volatile u8 *q = PAD_OUT;
    u32 n = 0, i;
    STK[6] = 0;
    PAD_TH[1] = (u16)(PAD_TH[0] + 100); PAD_TH[2] = (u16)(PAD_TH[0] + 200);
    for (i = 0; i < 16; i++) {
        volatile u8 *p = PAD_ST(i);
        u32 x = pad_curve(PAD_AVG[i]) & 0xFFFF;
        x = PAD_OFF[i] > x ? 0 : x - PAD_OFF[i];
        x = x < PAD_TH[0] ? 0 : x - PAD_TH[0];
        if (x >= 0x1000) x = 0xFFF;
        if (PAD_CNT[i] < 0xFF) PAD_CNT[i]++;
        if (PAD_CNT[i] > 30 && *(volatile u16 *)p != x) {           /* pressure */
            PAD_CNT[i] = 0; *(volatile u16 *)p = (u16)x;
            q[0] = (u8)i; q[1] = (u8)(0x40 + (x >> 8)); q[2] = (u8)x; q += 3; n += 3;
        }
        if (x) {
            if (p[5] == 0) { p[5] = 1; p[6] = 0; p[4] = 0; PAD_PEAK[i] = (u16)x; }
            else if (p[5] == 1) {
                if (x > PAD_PEAK[i]) {                                /* still rising: a slow press after 60 ms */
                    PAD_PEAK[i] = (u16)x;
                    if (p[4] > 60) {
                        p[5] = 8;
                        if (PAD_PEAK[i] > PAD_TH[1]) { p[6] = 1; q[0] = (u8)i; q[1] = (u8)(PAD_PEAK[i] >> 8); q[2] = (u8)PAD_PEAK[i]; q += 3; n += 3; }
                    }
                } else if (p[4] > 5) {                                /* past the peak: a hit */
                    p[5] = 8;
                    if (PAD_PEAK[i] > PAD_TH[2]) { p[6] = 0x11; q[0] = (u8)i; q[1] = (u8)(0x10 + (PAD_PEAK[i] >> 8)); q[2] = (u8)PAD_PEAK[i]; q += 3; n += 3; }
                }
            } else {
                PAD_PEAK[i] = (u16)x;
                if (!p[6] && x > PAD_TH[1]) { p[6] = 1; q[0] = (u8)i; q[1] = (u8)(PAD_PEAK[i] >> 8); q[2] = (u8)PAD_PEAK[i]; q += 3; n += 3; }
            }
            PAD_ZERO[i] = 0;
        } else if (PAD_ZERO[i] > 6) {                                 /* released */
            p[5] = 0;
            if (p[6] == 0x11) { p[6] = 0x31; q[0] = (u8)i; q[1] = 0x30; q[2] = 0; q += 3; n += 3; }
            else if (p[6] == 1) { p[6] = 0x21; q[0] = (u8)i; q[1] = 0x20; q[2] = 0; q += 3; n += 3; }
        } else PAD_ZERO[i]++;
        if (n > 0x39) break;                                          /* the buffer is nearly full: the rest next time (from the start) */
    }
    if (n) {
        STK[0x2CE] = 1;
        if (i < 16) STK[6] = 1;
        for (; n < 0x3F; n++) *q++ = 0;
    }
}

/* ---- the reports: what the scans found, in the two report formats the translator reads ----
 * Report 1 (14 bytes: id 1, 5 bytes of button bits by id, the encoder touch, the 4-bit encoder counter, a millisecond time stamp, the two
 * strip positions) is built in STK[0x2DD..0x2E9] and flagged by STK[0x2CD]; report 2 (id 2, the 63-byte pad event buffer) by STK[0x2CE]. The
 * dispatcher hands whatever is flagged to the translator (as one buffer, report 1 first), applies a pending LED frame or display region and
 * the brightness / sensitivity requests. */
#define REP1 (STK + 0x2DD)
static void __attribute__((noinline)) own_btn_report(void)
{
    u32 id, bits = 0;
    STK[0x8A] = 0;
    for (id = 0; id < 41; id++) {
        if (STK[0x8B + id]) bits += 1u << (id & 7);
        if ((id & 7) == 7 || id == 40) { STK[0xB4 + (id >> 3)] = (u8)bits; bits = 0; }
    }
    STK[0x2CD] = 1;
    for (id = 0; id < 5; id++) REP1[id] = STK[0xB4 + id];
}
static void __attribute__((noinline)) own_enc_report(void)
{
    u32 c = REP1[6];
    STK[0x2CD] = 1;
    if (STK[0xBA] == 1) c = c < 15 ? c + 1 : 0;
    else c = c ? c - 1 : 15;
    REP1[6] = (u8)c;
    STK[0xBA] = 0;
}
static u32 strip_map(u32 v)                          /* the low end of the strip is compressed (0..2 -> 0, 3..10 -> 1, ... 39.. -> v - 34), at most 200 */
{
    u32 m = v > 38 ? v - 34 : v > 37 ? 5 : v > 34 ? 4 : v > 31 ? 3 : v > 10 ? 2 : v > 2 ? 1 : 0;
    return (m & 0xFF) > 200 ? 200 : m & 0xFF;
}
#define STRIP_LAST ((volatile u8 *)0x20000198)       /* the positions last reported */
static void __attribute__((noinline)) own_strip_report(void)
{
    u32 a = STK[0xC4], b = STK[0xC5], ma = strip_map(a), mb = strip_map(b), t;
    STK[0xC3] = 0;
    if (STRIP_LAST[0] != ma || STRIP_LAST[1] != mb) {
        u32 ms = *(volatile u16 *)(0x20001028 + 0xC0);
        STK[0x2CD] = 1;
        REP1[7] = (u8)ms; REP1[8] = (u8)(ms >> 8); REP1[9] = (u8)ma; REP1[10] = 0; REP1[11] = (u8)mb; REP1[12] = 0;
        STRIP_LAST[0] = (u8)a; STRIP_LAST[1] = (u8)b;
    }
    t = STK[0xC6] ? 1 : 0;                           /* the controller's fourth byte: the encoder's touch sensor */
    if (STRIP[1] != t) { STRIP[1] = (u8)t; STK[0x2CD] = 1; REP1[5] = (u8)t; }
}

/* ---- the LED colour layer: a colour code (colour << 2 | brightness 0..3) for LED index 0..79 to PWM values of its cells ----
 * Each LED has a kind (1 = one colour, 3 = RGB, 4 = four cells), a number of cells and its first cell; each cell is a bit of one of the
 * chips' LED-control bytes (row, bit) and so a PWM register (row * 8 + bit). The colour code goes through a colour map to a palette entry;
 * a cell that is not dark is switched on and scaled by its trim (LED_TRIM: below 0x80 = + percent, from 0x80 = - percent, read from the
 * device's settings page at start-up), a dark cell is switched off. The tables (LEDTAB) are copied from the user's stock image at build
 * time. Indices from 0x80 are NI's factory calibration of single cells, which nothing of ours uses: they still go to the stock routine. */
#define LEDTAB ((const u8 *)LEDTAB_ADDR)
#define LED_TRIM ((volatile u8 *)0x20000E1C)
#define LED_CTRL ((volatile u8 *)0x20000EE2)
#define LED_PWM ((volatile u8 *)0x20000F06)
static void __attribute__((noinline, used)) own_led_colour(u32 idx, u32 code)
{
    u32 kind, cnt, st, lvl, col, k;
    if (idx >= 0x50) return;
    kind = LEDTAB[idx]; cnt = LEDTAB[0x50 + idx]; st = LEDTAB[0xA0 + idx];
    lvl = code & 3; col = LEDTAB[0x27C + (code >> 2)];
    if (col > 0x20) return;
    for (k = 0; k < cnt; k++) {
        u32 row = LEDTAB[0xF0 + st + k], bit = LEDTAB[0x1B6 + st + k], cell = (bit + row * 8) & 0xFFFF, v, t;
        if (kind == 1) v = LEDTAB[0x29C + col * 4 + lvl];
        else if (kind == 3) v = LEDTAB[0x2E8 + col * 12 + k * 4 + lvl];
        else if (kind == 4) v = LEDTAB[0x3CC + col * 16 + k * 4 + lvl];
        else return;
        LED_PWM[cell] = (u8)v;
        if (!v) { LED_CTRL[row] &= (u8)~(1u << bit); continue; }
        LED_CTRL[row] |= (u8)(1u << bit);
        t = LED_TRIM[st + k];
        v = t > 0x7F ? v - v * (t - 0x80) / 100 : v + v * t / 100;
        LED_PWM[cell] = (u8)v;
    }
}
static void led_colour(u32 idx, u32 code, u32 a, u32 b, u32 e)
{
    if ((OURS(ST->hal & HAL_COLOUR)) && idx < 0x50) own_led_colour(idx, code);
    else ((void (*)(u32, u32, u32, u32, u32))STOCK(0x08005491))(idx, code, a, b, e);
}

#define LEDF (STK + 0x329)                           /* the LED frame: 80 colour codes (or a command, below) */
#define DISPH (STK + 0x379)                          /* the display region: x, -, page, -, width, -, height, -, then the pixel bytes */
#define LED_COLOUR(i, c, a, b, e) led_colour((i), (c), (a), (b), (e))
static void __attribute__((noinline)) own_dispatch(void)
{
    u8 buf[80];
    u32 n = 0, k;
    STK[0x2D3] = 0;
    if (STK[0x2CD]) { STK[0x2CD] = 0; buf[0] = 1; for (k = 1; k < 14; k++) buf[k] = STK[0x2DC + k]; n = 14; }
    if (STK[0x2CE]) { STK[0x2CE] = 0; buf[n] = 2; for (k = 0; k < 63; k++) buf[n + 1 + k] = STK[0x2EA + k]; n = (n + 64) & 0xFF; }
    if (STK[0x2CF]) {
        STK[0x2CF] = 0;
        if (LEDF[0] == 0xAA && LEDF[1] == 0xAB && LEDF[2] == 0xAC) {          /* a single LED cell, optionally with a colour override */
            if (LEDF[3] > 0x7F) {
                if (LEDF[8] != 0xAD) *(volatile u8 *)0x20000151 = 0;
                else { *(volatile u8 *)0x20000151 = 1; for (k = 0; k < 4; k++) ((volatile u8 *)0x20000154)[k] = LEDF[9 + k]; }
                LED_COLOUR(LEDF[3], LEDF[4], LEDF[5], LEDF[6], LEDF[7]);
            }
        } else if (LEDF[0] == 0xAA && LEDF[1] == 0xAB && LEDF[2] == 0xAD) {   /* pad offsets (calibration), or 0xF0: keep them in the settings */
            if (LEDF[3] == 0xF0) ((void (*)(u32))STOCK(0x08004705))(0x40);
            else for (k = 0; k < 16; k++) PAD_OFF[k] = LEDF[3 + k];
        } else for (k = 0; k < 80; k++) if (LEDF[k] < 0x80) LED_COLOUR(k, LEDF[k], 0, 0, 0);
        LED_STEP = 10;
    }
    if (STK[0x2D0]) {                                /* a display region into the framebuffer, then a refresh */
        u32 x0 = DISPH[0], p0 = DISPH[2], xe = (x0 + DISPH[4]) & 0xFF, pe = (p0 + DISPH[6]) & 0xFF;
        STK[0x2D0] = 0;
        if (xe < 0x81 && pe < 5) {
            const volatile u8 *d = DISPH + 8;
            u32 pg, x;
            for (pg = p0; pg < pe; pg++) for (x = x0; x < xe; x++) STK[0xCA + ((x + pg * 128) & 0xFFFF)] = *d++;
            DISP_CNT = DISP_CNT ? (u8)(DISP_CNT | 0x80) : 8;
        }
    }
    if (STK[0x2D1]) { STK[0x2D1] = 0; if (STK[0x481] < 11) { LED_BRI = STK[0x481]; LED_STEP = 10; } }      /* LED brightness level */
    if (STK[0x2D2]) {                                                          /* pad sensitivity */
        STK[0x2D2] = 0;
        if (STK[0x483] == 0x22 && STK[0x484] == 0xFF && STK[0x485] == 5 && STK[0x486] == 1 && STK[0x487] < 0x65)
            PAD_TH[0] = (u16)((100 - STK[0x487]) * 6);
    }
    if (n) translate_report(buf, n);
}

/* ---- the hooks and the switch ---- */

/* Replaces both stock calls of the LED refresh (in the normal scan and in the service routine; each is only made while LED_STEP != 0). */
static void w_disp_send(void)                            /* replaces the stock call of the display sender in the service routine */
{
    if (OURS(ST->hal & HAL_DISP)) own_disp_send();
    else ((void (*)(void))STOCK(0x080068B1))();
}

static u32 w_btn_scan(void)                              /* replaces the stock scan step in the service routine; its result goes to ... */
{
    if (OURS(ST->hal & HAL_BTN)) return own_btn_scan();
    return ((u32 (*)(void))STOCK(0x08007715))();
}
static void w_btn_eval(u32 f)                            /* ... the evaluation, called when it is not 0 */
{
    if (OURS(ST->hal & HAL_BTN)) own_btn_eval(f);
    else ((void (*)(u32))STOCK(0x080077E9))(f);
}

static void w_strip_read(void)                           /* replaces the stock strip read in the service routine (made every 5 ms) */
{
    if (OURS(ST->hal & HAL_STRIP)) own_strip_read();
    else ((void (*)(void))STOCK(0x08007FA5))();
}

static void w_adc_avg(void)                              /* replaces the stock averaging, called when a scan is finished */
{
    if (OURS(ST->hal & HAL_PADS)) own_adc_avg();
    else ((void (*)(void))STOCK(0x080033A5))();
}
static void w_pad_eval(void)                             /* replaces the stock evaluation, called when STK[6] is set */
{
    if (OURS(ST->hal & HAL_PADS)) own_pad_eval();
    else ((void (*)(void))STOCK(0x08003971))();
}

static void w_btn_report(void) { if (OURS(ST->hal & HAL_REPORTS)) own_btn_report(); else ((void (*)(void))STOCK(0x080038D1))(); }
static void w_enc_report(void) { if (OURS(ST->hal & HAL_REPORTS)) own_enc_report(); else ((void (*)(void))STOCK(0x0800392D))(); }
static void w_strip_report(void) { if (OURS(ST->hal & HAL_REPORTS)) own_strip_report(); else ((void (*)(void))STOCK(0x08003CE5))(); }
static void w_dispatch(void) { if (OURS(ST->hal & HAL_REPORTS)) own_dispatch(); else ((void (*)(void))STOCK(0x08003E25))(); }

static void w_led_refresh(void)
{
    if (OURS(ST->hal & HAL_LED)) own_led_refresh();
    else ((void (*)(void))STOCK(0x08006029))();
}

static void hal_set(struct state *s, u32 mask, u32 mask2, u32 flags)
{
    s->hal2 = (u8)(mask2 & (HAL2_LOOP | HAL2_TICK));
    s->hal = (u8)(mask & (HAL_LED | HAL_DISP | HAL_BTN | HAL_STRIP | HAL_PADS | HAL_REPORTS | HAL_COLOUR));
    if (flags & HAL_FLAG_NEXT_BOOT) BOOT_FLAG = BOOT_OWN_INIT;
    if (flags & HAL_FLAG_NEXT_BOOT_USB) BOOT_FLAG = BOOT_OWN_USB;
    if (flags & HAL_FLAG_REBOOT) s->reboot = 1;
    if (flags & HAL_FLAG_LED_INIT) {
        u32 k;
        own_led_init();
        for (k = 0; k < 0x144; k++) LED_SHADOW[k] = 0;    /* the chips hold zeros now: the next refresh sends every block that is not */
        LED_STEP = 10;
    }
}

/* ---- the SysTick handler (every 0.5 ms; every second call is the millisecond) and the main loop's work ---- */
#define TICK_HALF (*(volatile u8 *)0x200001A4)
#define U16(o) (*(volatile u16 *)(0x20001028 + (o)))
static void __attribute__((noinline)) own_systick(void)
{
    u32 i;
    if (U16(0x88)) U16(0x88)--;                                    /* the button scan timer runs at 0.5 ms */
    if (TICK_HALF) { TICK_HALF = 0; return; }
    TICK_HALF = 1;
    if (U16(2)) U16(2)--;                                          /* the start-up countdown */
    for (i = 0; i < 16; i++) if (STK[0xC + 8 * i] < 0xFF) STK[0xC + 8 * i]++;   /* each pad's ms since its touch began */
    if (STK[0xC2]) STK[0xC2]--;                                    /* strip read timer */
    U16(0xC0) = U16(0xC0) == 0xFFFF ? 0 : (u16)(U16(0xC0) + 1);     /* the millisecond counter */
    if (STK[0xC9]) STK[0xC9]--;                                    /* display chunk gap */
    if (U16(0x7EA) > 1) U16(0x7EA)--;                              /* settings save delay */
    if (U16(0xBE)) U16(0xBE)--;                                    /* (start-up animation step timer) */
}

#define DMA1_ISR (*(volatile u32 *)0x40020000u)
#define SUSP_COUNT (*(volatile u16 *)0x200001AE)
/* What the stock main loop does on every pass (after the watchdog): the start-up step while the countdown runs, then each job when it is
 * due, the USB transmit ring, and the dispatcher when something is pending. */
static void __attribute__((noinline)) own_service(void)
{
    u32 f;
    if (OURS(ST->own_init)) { if (!ST->boot_done && U16(2) <= 1) { ST->boot_done = 1; own_startup_end(); } }
    else if (U16(2)) ((void (*)(void))STOCK(0x08008C35))();               /* the stock start-up animation */
    if (DMA1_ISR & 2) w_adc_avg();
    if (!U16(0x88)) { f = w_btn_scan(); if (f) w_btn_eval(f); }
    if (!STK[0xC2]) w_strip_read();
    if (STK[0xBC]) w_led_refresh();
    if (!STK[0xC9] && STK[0xC8]) w_disp_send();
    if (OURS(ST->own_usb)) own_usb_tx();
    else if (*(volatile u16 *)0x20000146 != *(volatile u16 *)0x20000148) ((void (*)(void))STOCK(0x080089B5))();   /* the stock USB transmit */
    f = (STK[0x2CD] + STK[0x2CE] + STK[0x2CF] + STK[0x2D0] + STK[0x2D1] + STK[0x2D2]) & 0xFF;
    STK[0x2D3] = (u8)f;
    if (f) w_dispatch();
}
/* Normal mode, after the service routine: evaluate what changed, the display fade and the settings save, and after a long USB suspend the
 * suspended mode (display and LED drivers off). */
static void __attribute__((noinline)) own_normal(void)
{
    if (STK[6]) w_pad_eval();
    if (STK[0xBA]) w_enc_report();
    if (STK[0x8A]) w_btn_report();
    if (STK[0xC3]) w_strip_report();
    if (STK[0xBC]) w_led_refresh();
#ifndef NATIVE                                       /* (nothing sets these in the standalone image: they belong to NI's host protocol) */
    if (U16(0x2CA)) ((void (*)(void))STOCK(0x08006625))();                /* display contrast fade (still NI's) */
    if (U16(0x7EA) == 1) ((void (*)(void))STOCK(0x080047D5))();           /* settings save (still NI's) */
#endif
    if (USB_SUSP) {
        SUSP_COUNT = (u16)(SUSP_COUNT + 1);
        if (SUSP_COUNT > 0xFFF0) {
            STK[0] = 1;                                            /* suspended mode */
            disp_put(0, 0x8D); disp_put(0, 0x10); disp_put(0, 0xAE);   /* display: charge pump off, display off */
            BB(0x40010C0Cu, 8) = 0; BB(0x40010C0Cu, 9) = 0;         /* PB8, PB9 low: the LED drivers off */
        }
    } else SUSP_COUNT = 0;
}
static void w_systick(void) { if (OURS(ST->hal2 & HAL2_TICK)) own_systick(); else ((void (*)(void))STOCK(0x08007ED5))(); }
static void w_service(void) { if (OURS(ST->hal2 & HAL2_LOOP)) own_service(); else ((void (*)(void))STOCK(0x08004621))(); }
static void w_normal(void) { if (OURS(ST->hal2 & HAL2_LOOP)) own_normal(); else ((void (*)(void))STOCK(0x080042A1))(); }

/* ---- start-up: the settings pages (device data written by NI's tools: they stay as they are) ----
 * Page A (0x0801F000): the trim of every LED cell (0xC6 bytes) and at +0x200 the offsets of the 16 pads. Page B (0x0801F800): two 256-byte
 * blocks (block 1: +4 LED brightness level, +5 pad sensitivity), the display contrast at +0x3E6, a format mark (4, 4) at +0x3E8, the 4-byte
 * device id at +0x104 that is the USB serial number, and the firmware version (0x52) at +0x3FE, which the stock code writes back (only
 * when it changed). Only the normal case is ours: a blank or unknown page (never seen on a unit that ran NI's firmware) goes to the stock
 * routine, which carries NI's defaults. */
#define SETBUF ((volatile u8 *)0x20000318)            /* a 1 KB page buffer */
#define SERIAL_DESC ((volatile u8 *)0x20000048)       /* the USB serial number string descriptor (18 bytes: 8 UTF-16 hex digits) */
#ifdef NATIVE
static void settings_defaults(void)                  /* no usable settings pages (and nothing written): no trims, pad offsets 100, brightness 10, sensitivity 80 */
{
    u32 k;
    for (k = 0; k < 0xC6; k++) LED_TRIM[k] = 0;
    for (k = 0; k < 16; k++) PAD_OFF[k] = 100;
    STK[0x5E0] = 10; STK[0x5E1] = 80; STK[0x2CC] = 0x80;
}
#define SETTINGS_FALLBACK() settings_defaults()
#else
#define SETTINGS_FALLBACK() ((void (*)(void))0x080047F5)()
#endif
static void fl_read(u32 addr, u32 n)
{
    u32 k;
    FLASH_UNLOCK();
    for (k = 0; k < n; k++) SETBUF[k] = *(const volatile u8 *)(addr + k);
    FLASH_LOCK();
}
static u32 settings_write_b(void)                    /* page B from SETBUF, only if it differs; USB and SysTick interrupts off meanwhile */
{
    const u32 page = 0x0801F800u;
    u32 k, ok = 1;
    for (k = 0; k < 0x400 && *(const volatile u8 *)(page + k) == SETBUF[k]; k++) { }
    if (k == 0x400) return 1;
    *(volatile u32 *)0x40005C40u = 0; *(volatile u32 *)0xE000E010u &= ~2u;          /* USB_CNTR, SysTick TICKINT */
    FLASH_UNLOCK(); FLASH_CLEAR(0x35);
    if (FLASH_ERASE(page) != 4) ok = 0;
    for (k = 0; ok && k < 0x400; k += 4) {
        u32 wv = SETBUF[k] | (u32)SETBUF[k + 1] << 8 | (u32)SETBUF[k + 2] << 16 | (u32)SETBUF[k + 3] << 24;
        FLASH_PROG(page + k, wv);
        if (*(const volatile u32 *)(page + k) != wv) ok = 0;
    }
    FLASH_LOCK();
    *(volatile u32 *)0x40005C40u = 0xBF00; *(volatile u32 *)0xE000E010u |= 2u;
    return ok;
}
static void __attribute__((noinline)) own_settings_load(void)
{
    u32 k, c;
    STK[0x7E8] = 0; U16(0x7EA) = 0;
    fl_read(0x0801F000u, 0x400);
    if (SETBUF[0] == 0xFF || SETBUF[0x200] == 0xFF) { SETTINGS_FALLBACK(); return; }   /* blank: NI's defaults (ours in the standalone image) */
    for (k = 0; k < 0xC6; k++) LED_TRIM[k] = SETBUF[k];
    for (k = 0; k < 16; k++) PAD_OFF[k] = SETBUF[0x200 + k];
    fl_read(0x0801F800u, 0x400);
    if (SETBUF[0x3E8] != 4 || SETBUF[0x3E9] != 4) { SETTINGS_FALLBACK(); return; }      /* unknown format: NI's defaults (ours in the standalone image) */
    c = SETBUF[0x3E6]; STK[0x2CC] = (u8)(c > 0xE0 ? 0xE0 : c);
    SETBUF[0x3FE] = 0x52; SETBUF[0x3FF] = 0;
    for (k = 0; k < 256; k++) { STK[0x5DC + k] = SETBUF[k]; STK[0x6DE + k] = SETBUF[0x100 + k]; }
    for (k = 0; k < 8; k++) {                        /* the serial number: the device id as 8 hex digits, last nibble first */
        u32 b = STK[0x6E2 + (k >> 1)], nib = (k & 1) ? b >> 4 : b & 15;
        SERIAL_DESC[2 + 2 * (7 - k)] = (u8)(nib > 9 ? nib + 0x37 : nib + 0x30);
    }
    for (k = 2; k < 18; k++) SETBUF[0x3EC + k] = SERIAL_DESC[k];
    settings_write_b();
}

/* ---- start-up: the touch-strip controller ----
 * Reset it (PA15 low), wake it with a raw two-byte sequence (67 4A, no acknowledges), configure it (address 0x01: 02; 0x40: D2 FF 00 00 00 00;
 * 0x38: 80) and read its status from 0x40: bytes 3 and 4 are F5 F6 when its application runs; then a second reset pulse and the fast bus
 * timing for the read cycles. Anything else (the controller is in its bootloader and needs its firmware, or does not answer) restarts the
 * chip into the stock path (a boot of ours is one-shot), whose routine carries the controller's firmware and writes it, or stops with an
 * error picture: NI's code and data, needed only for a controller that lost its firmware. */
static void sb_raw(u32 b)                            /* one byte clocked out without an acknowledge */
{
    u32 k;
    for (k = 0; k < 8; k++) { SB_SDA = (b >> 7) & 1; sdly(1); SB_SCL = 1; sdly(1); b = (b << 1) & 0xFF; SB_SCL = 0; }
}
#define STRIP_DIAG ((volatile u8 *)0x20004FC0)      /* what the last strip start-up of ours saw (survives a reset): 'S', step, the status read */
static u32 __attribute__((noinline)) strip_app_running(void)
{
    u8 w[8], r[8];
    u32 k;
    STRIP_DIAG[0] = 'S'; STRIP_DIAG[1] = 1;
    SB_SDA = 0; SB_SCL = 0; BB(0x4001080Cu, 15) = 0;
    sdly(20);
    BB(0x4001080Cu, 15) = 1; SB_SDA = 1; SB_SCL = 1;
    sdly(2);
    sdly(1); SB_SDA = 0; sdly(1); SB_SCL = 0;
    sb_raw(0x67); sb_raw(0x4A);
    SB_SDA = 1; sdly(1); SB_SCL = 1;
    sdly(500);
    w[0] = 0x02; w[1] = 0x02;
    if (!sb_xfer(w, 2)) return 0;
    STRIP_DIAG[1] = 2;
    w[0] = 0x80; w[1] = 0xD2; w[2] = 0xFF; w[3] = 0; w[4] = 0; w[5] = 0; w[6] = 0;
    STRIP_DIAG[2] = (u8)sb_xfer(w, 7);
    w[0] = 0x70; w[1] = 0x80;
    STRIP_DIAG[3] = (u8)sb_xfer(w, 2);
    sdly(60000);
    r[0] = 0x81; r[1] = r[2] = r[3] = r[4] = r[5] = r[6] = 0;
    STRIP_DIAG[4] = (u8)sb_xfer(r, 7);
    for (k = 0; k < 7; k++) STRIP_DIAG[5 + k] = r[k];
    STRIP_DIAG[1] = 3;
    return r[3] == 0xF5 && r[4] == 0xF6;
}
static void __attribute__((noinline)) own_strip_start(void)
{
    sdly(300);
    u32 ok = strip_app_running();
#ifdef NATIVE
    if (!ok) return;                                 /* the standalone image carries no strip firmware: the strip stays silent */
#endif
    if (!ok) {                      /* no application in the controller (or no answer): back to the stock path, which can */
        __asm volatile("dsb"); *(volatile u32 *)0xE000ED0Cu = 0x05FA0004u; for (;;) { }   /* write its firmware (our boot flag is used up) */
    }
    sdly(100); BB(0x4001080Cu, 15) = 0; sdly(100); BB(0x4001080Cu, 15) = 1; sdly(1000);
    STK[0xC7] = 2;
}

/* ---- start-up: the board (docs/hardware-map.md) ----
 * The same set-up as the stock board init, in the same order: clocks (8 MHz crystal x 9 = 72 MHz, flash 2 wait states, APB1 / 2), the vector
 * table above the bootloader, SWD kept and JTAG off, the ADC scan of the 16 pads with its DMA channel (calibrated, the first scan started), the
 * button matrix, the LED bus, SPI2 for the display, the strip bus and its controller, and SysTick (0.5 ms). One piece is still the stock
 * code, for a case never seen on a working unit: a blank settings page or a strip controller without its firmware. */
#define RCC_CR (*(volatile u32 *)0x40021000u)
#define RCC_CFGR (*(volatile u32 *)0x40021004u)
#define RCC_CIR (*(volatile u32 *)0x40021008u)
#define RCC_AHBENR (*(volatile u32 *)0x40021014u)
#define RCC_APB2ENR (*(volatile u32 *)0x40021018u)
#define RCC_APB1ENR (*(volatile u32 *)0x4002101Cu)
#define FLASH_ACR (*(volatile u32 *)0x40022000u)
#define SCB_VTOR (*(volatile u32 *)0xE000ED08u)
#define AFIO_MAPR (*(volatile u32 *)0x40010004u)
#define REG(a) (*(volatile u32 *)(a))
#define GPIOA 0x40010800u
#define GPIOB 0x40010C00u
#define GPIOC 0x40011000u
#define ADC1 0x40012400u
#define DMA1_CH1 0x40020008u
#define SYST_CSR (*(volatile u32 *)0xE000E010u)
#define SYST_RVR (*(volatile u32 *)0xE000E014u)

/* The ST library's GPIO set-up: the mode nibble of each pin (with the speed for outputs), pull-up / pull-down through the output register. */
#define GM_AIN 0x00u
#define GM_IPU 0x48u
#define GM_OUT_PP 0x10u
#define GM_OUT_OD 0x14u
#define GM_AF_PP 0x18u
static void gpio_init(u32 base, u32 pins, u32 mode)
{
    u32 cur = (mode & 0x0F) | ((mode & 0x10) ? 3u : 0u), k, reg, half;
    for (half = 0; half < 2; half++) {
        u32 m = (pins >> (8 * half)) & 0xFF;
        if (!m) continue;
        reg = REG(base + 4 * half);
        for (k = 0; k < 8; k++) if (m & (1u << k)) {
            reg = (reg & ~(0xFu << (4 * k))) | (cur << (4 * k));
            if (mode == 0x28) REG(base + 0x14) = 1u << (k + 8 * half);
            if (mode == GM_IPU) REG(base + 0x10) = 1u << (k + 8 * half);
        }
        REG(base + 4 * half) = reg;
    }
}
static u32 own_clocks(void)                          /* 1 = running on the crystal and the PLL (72 MHz), 0 = on the internal 8 MHz */
{
    u32 n;
    RCC_CR |= 1; RCC_CFGR &= 0xF8FF0000u; RCC_CR &= 0xFEF6FFFFu; RCC_CR &= ~0x40000u; RCC_CFGR &= ~0x7F0000u; RCC_CIR = 0;   /* reset state */
    RCC_CR &= ~0x10000u; RCC_CR &= ~0x40000u; RCC_CR |= 0x10000u;                            /* crystal on */
    for (n = 0; n < 0x500 && !(RCC_CR & 0x20000u); n++) { }
    if (!(RCC_CR & 0x20000u)) return 0;
    FLASH_ACR &= ~0x10u; FLASH_ACR |= 0x10u; FLASH_ACR &= ~3u; FLASH_ACR |= 2u;              /* prefetch, 2 wait states */
    RCC_CFGR &= ~0xF0u; RCC_CFGR &= ~0x3800u; RCC_CFGR = (RCC_CFGR & ~0x700u) | 0x400u;     /* AHB / 1, APB2 / 1, APB1 / 2 */
    RCC_CFGR = (RCC_CFGR & ~0x3F0000u) | 0x1D0000u;                                          /* PLL: crystal x 9 */
    RCC_CR |= 0x1000000u;
    while (!(RCC_CR & 0x2000000u)) { }
    RCC_CFGR = (RCC_CFGR & ~3u) | 2u;
    while ((RCC_CFGR & 0xCu) != 8u) { }
    return 1;
}
static void own_adc_init(void)
{
    u32 k, ch, sq;
    RCC_CFGR = (RCC_CFGR & ~0xC000u) | 0x8000u;                                              /* ADC clock / 6 = 12 MHz */
    gpio_init(GPIOA, 0x00FF, GM_AIN); gpio_init(GPIOB, 0x0003, GM_AIN); gpio_init(GPIOC, 0x003F, GM_AIN);
    RCC_AHBENR |= 1; RCC_APB2ENR |= 0x200;
    REG(DMA1_CH1) &= ~1u; REG(DMA1_CH1) = 0; REG(DMA1_CH1 + 4) = 0; REG(DMA1_CH1 + 8) = 0; REG(DMA1_CH1 + 12) = 0; DMA1_IFCR = 0xF;
    REG(DMA1_CH1) = (REG(DMA1_CH1) & 0xFFFF800Fu) | 0x25A0u;                                /* 16 bit, memory increment, circular, high */
    REG(DMA1_CH1 + 4) = 16; REG(DMA1_CH1 + 8) = ADC1 + 0x4C; REG(DMA1_CH1 + 12) = 0x20000718;
    REG(DMA1_CH1) |= 1;
    REG(ADC1 + 4) = (REG(ADC1 + 4) & 0xFFF0FEFFu) | 0x60100u;                                /* scan */
    REG(ADC1 + 8) = (REG(ADC1 + 8) & 0xFFF1F7FDu) | 0xE0000u;                                /* started by software */
    REG(ADC1 + 0x2C) = (REG(ADC1 + 0x2C) & 0xFF0FFFFFu) | (15u << 20);                       /* 16 conversions */
    for (k = 0; k < 16; k++) {                       /* the scan order: 10 11 12 13 0 1 2 3 4 5 6 7 14 15 8 9, each 71.5 cycles */
        ch = k < 4 ? 10 + k : k < 12 ? k - 4 : k < 14 ? k + 2 : k - 6;
        if (ch > 9) REG(ADC1 + 0x0C) = (REG(ADC1 + 0x0C) & ~(7u << (3 * (ch - 10)))) | (6u << (3 * (ch - 10)));
        else REG(ADC1 + 0x10) = (REG(ADC1 + 0x10) & ~(7u << (3 * ch))) | (6u << (3 * ch));
        sq = k < 6 ? 0x34 : k < 12 ? 0x30 : 0x2C;
        REG(ADC1 + sq) = (REG(ADC1 + sq) & ~(0x1Fu << (5 * (k % 6)))) | (ch << (5 * (k % 6)));
    }
    REG(ADC1 + 8) |= 0x100;                          /* DMA */
    REG(ADC1 + 8) |= 1;                              /* on */
    REG(ADC1 + 8) |= 8; while (REG(ADC1 + 8) & 8) { }        /* reset the calibration ... */
    REG(ADC1 + 8) |= 4; while (REG(ADC1 + 8) & 4) { }        /* ... calibrate */
    REG(ADC1 + 8) |= 0x500000;                       /* the first scan */
}
static void __attribute__((noinline)) own_board_init(void)
{
    u32 xtal = own_clocks();
    SCB_VTOR = 0x08003000u;
    RCC_APB2ENR |= 1; AFIO_MAPR &= ~0x07000000u; AFIO_MAPR = (AFIO_MAPR & ~0x07000000u) | 0x02000000u;   /* SWD on, JTAG off */
    own_settings_load();
    own_adc_init();
    RCC_APB2ENR |= 0x18; gpio_init(GPIOB, 0x0C1C, GM_OUT_PP); gpio_init(GPIOC, 0xFFC0, GM_IPU);                     /* button matrix */
    RCC_APB2ENR |= 0x08; gpio_init(GPIOB, 0x00C0, GM_OUT_PP); LED_SCL = 1; LED_SDA = 1;                            /* LED bus ... */
    gpio_init(GPIOB, 0x0300, GM_OUT_PP); BB(0x40010C0Cu, 8) = 1; BB(0x40010C0Cu, 9) = 1;                           /* ... and the LED drivers on */
    RCC_APB2ENR |= 0x08; RCC_APB1ENR |= 0x4000; gpio_init(GPIOB, 0xA000, GM_AF_PP); gpio_init(GPIOB, 0x5000, GM_OUT_PP);   /* SPI2 */
    REG(0x40003800) = (REG(0x40003800) & 0x3040u) | 0xC31Fu; REG(0x4000381C) &= ~0x800u; REG(0x40003810) = 7; REG(0x40003800) |= 0x40;
    RCC_APB2ENR |= 0x04; gpio_init(GPIOA, 0x0600, GM_OUT_OD); gpio_init(GPIOA, 0x8000, GM_OUT_OD);                  /* strip bus */
    SB_SCL = 1; SB_SDA = 1; BB(0x4001080Cu, 15) = 0; STK[0xC7] = 0x12;
    own_strip_start();
    SYST_RVR = (xtal ? 72000000u : 8000000u) / 16000u;   /* SysTick from AHB / 8: 0.5 ms */
    SYST_CSR |= 2; SYST_CSR |= 1;
}

/* ---- start-up, second half: pad / button / LED state, the LED chips, the display (without NI's logo), the end of the start-up ---- */
static void own_threshold(void)                      /* the pad threshold from the sensitivity, and the pad states reset (as the stock routine) */
{
    u32 k;
    PAD_TH[0] = STK[0x5E1] > 100 ? 0 : (u16)((100 - STK[0x5E1]) * 6);
    STK[6] = 0;
    for (k = 0; k < 16; k++) { *(volatile u16 *)PAD_ST(k) = 0; PAD_ST(k)[4] = 0xFF; PAD_ST(k)[5] = 0; PAD_ST(k)[6] = 0; }
}
static void __attribute__((noinline)) dloop(u32 n) { volatile u32 x = n; while (x--) { } }
static void own_display_init(const u8 *pic)          /* reset pulse, the controller set-up, then a picture (0: blank) */
{
    u32 pg, x;
    GPIOB_ODR |= 0x1000; dloop(40000); GPIOB_ODR &= ~0x1000u; dloop(200000); GPIOB_ODR |= 0x1000; dloop(40);   /* PB12: the display's reset */
    disp_put(0, 0xAE); disp_put(0, 0x40); disp_put(0, 0xB0); disp_put(0, 0xC0); disp_put(0, 0x81); disp_put(0, STK[0x2CC]);
    disp_put(0, 0xA0); disp_put(0, 0xA6); disp_put(0, 0xA8); disp_put(0, 0x1F); disp_put(0, 0xD3); disp_put(0, 0x00);
    disp_put(0, 0xD5); disp_put(0, 0xF0); disp_put(0, 0xD9); disp_put(0, 0x22); disp_put(0, 0xDA); disp_put(0, 0x02); disp_put(0, 0xDB); disp_put(0, 0x49);
    for (pg = 0; pg < 4; pg++) {
        disp_put(0, 0xB0 + pg); disp_put(0, 0x00); disp_put(0, 0x10);
        for (x = 0; x < 128; x++) disp_put(1, pic ? pic[pg * 128 + x] : 0);
    }
    dloop(4000);
    for (x = 0; x < 512; x++) STK[0xCA + x] = (u8)(0xFF - (pic ? pic[x] : 0));   /* the framebuffer holds it inverted (lit = 0) */
}
static void __attribute__((noinline, used)) own_stage2(const u8 *pic, u32 countdown)
{
    u32 k;
    own_threshold();
    *(volatile u8 *)0x200010E2 = 0; *(volatile u8 *)0x200010E3 = 0;
    U16(0x88) = 1; STK[0x8A] = 0; for (k = 0; k < 41; k++) STK[0x8B + k] = 0; for (k = 0; k < 6; k++) STK[0xB4 + k] = 0;   /* buttons */
    for (k = 0; k < 0x144; k++) LED_MATRIX[k] = 0;                     /* the LEDs: all off, the brightness from the settings */
    LED_BRI = STK[0x5E0]; *(volatile u8 *)0x20000151 = 0; for (k = 0; k < 4; k++) ((volatile u8 *)0x20000154)[k] = 0;
    own_led_init();
    own_display_init(pic);
    for (k = 0; k < 4; k++) ((volatile u8 *)0x200010EB)[k] = 0;
    STK[0] = 0; U16(4) = 0; for (k = 0x2CD; k <= 0x2D2; k++) STK[k] = 0; U16(0x2CA) = 0; STK[0x4AF] = 0; STK[0x7E2] = 0;   /* the stock state block */
    STK[0x4A3] = 0xF8; STK[0x4A4] = 0x80; STK[0x4A5] = 0; STK[0x4A6] = 0x20; STK[0x4A7] = 0; STK[0x4A8] = 1; STK[0x4A9] = 0; STK[0x4AA] = 0; STK[0x4AB] = 0;
    STK[0x4AC] = 100; STK[0x4AD] = 0; STK[0x2DC] = 1; STK[0x7DE] = 'n'; STK[0x7DF] = 'o'; STK[0x7E0] = 'n'; STK[0x7E1] = 'e';
    U16(2) = (u16)countdown; U16(0xBE) = 150;
}
/* The end of the start-up (the stock code does this when its LED animation is over): the display on, the scan flags cleared, USB started
 * (still NI's USB set-up), the transmit ring emptied. */
static void own_startup_end(void)
{
    U16(2) = 0; *(volatile u16 *)0x200001B0 = 0;
    disp_put(0, 0x8D); disp_put(0, 0x14); disp_put(0, 0xAF);
    STK[6] = 0; STK[0xBA] = 0; STK[0x8A] = 0; STK[0xC3] = 0;
    if (OURS(ST->own_usb)) own_usb_init(); else ((void (*)(void))STOCK(0x08008665))();   /* USB set-up and connect */
    *(volatile u16 *)0x20000146 = 0; *(volatile u16 *)0x20000148 = 0; *(volatile u8 *)0x20000778 = 0;
    *(volatile u16 *)0x200001A2 = 0;
}

/* The entry points the build patches into the stock code (bl / b.w at the hook sites); hal.c itself calls the static ones (a call to a
 * global function would need a relocation, which the build does not allow). */
void mmk3_disp_send(void) { w_disp_send(); }
u32 mmk3_btn_scan(void) { return w_btn_scan(); }
void mmk3_btn_eval(u32 f) { w_btn_eval(f); }
void mmk3_strip_read(void) { w_strip_read(); }
void mmk3_adc_avg(void) { w_adc_avg(); }
void mmk3_pad_eval(void) { w_pad_eval(); }
void mmk3_btn_report(void) { w_btn_report(); }
void mmk3_enc_report(void) { w_enc_report(); }
void mmk3_strip_report(void) { w_strip_report(); }
void mmk3_dispatch(void) { w_dispatch(); }
void mmk3_led_refresh(void) { w_led_refresh(); }
void mmk3_systick(void) { w_systick(); }
void mmk3_service(void) { w_service(); }
void mmk3_normal(void) { w_normal(); }
