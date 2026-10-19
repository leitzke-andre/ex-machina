/* The standalone image (docs/clean-firmware-plan.md, the last step): no NI code at all. build_patch.py --native writes the vector table at
 * 0x08003000 (initial stack 0x20001C18, as NI's), a "return 0" stub at 0x08003140 for the calls the patched image makes into NI's code
 * (STOCK() points there: none of them is reached in this image, the switches are all on our side), our string descriptors at NAT_STR,
 * and then the same data and code as the patched image, compiled with -DNATIVE. NI's bootloader below 0x08003000 starts it like NI's
 * firmware: its reset handler is ours. Included at the end of translate.c. */

#define NAT_STR 0x08003200u                          /* string descriptors: 0 (languages, 4 bytes), 1 manufacturer, 2 product (build_patch.py) */
#define NAT_STR1_LEN 38u
#define NAT_STR2_LEN 38u
#define RAM32(a) (*(volatile u32 *)(a))
#define RAM8(a) (*(volatile u8 *)(a))

/* The start values our code expects in RAM (the patched image gets them from NI's start-up data): the serial-number descriptor (its digits
 * are filled in from the settings page), the descriptor table, the LED brightness levels in percent, the strip controller's address bytes. */
static void ram_start_values(void)
{
    u32 k;
    SERIAL_DESC[0] = 0x12; SERIAL_DESC[1] = 3;
    for (k = 0; k < 8; k++) { SERIAL_DESC[2 + 2 * k] = '0'; SERIAL_DESC[3 + 2 * k] = 0; }
    DESC_TABLE[8] = NAT_STR; DESC_TABLE[9] = 4;                                          /* string 0 */
    DESC_TABLE[10] = NAT_STR + 4; DESC_TABLE[11] = NAT_STR1_LEN;                         /* 1: manufacturer */
    DESC_TABLE[12] = NAT_STR + 4 + NAT_STR1_LEN; DESC_TABLE[13] = NAT_STR2_LEN;          /* 2: product */
    DESC_TABLE[14] = 0x20000048u; DESC_TABLE[15] = 18;                                    /* 3: serial number */
    DESC_TABLE[16] = NAT_STR; DESC_TABLE[17] = 4; DESC_TABLE[18] = NAT_STR; DESC_TABLE[19] = 4;
    RAM8(0x2000017C) = 21; RAM8(0x2000017D) = 29; RAM8(0x2000017E) = 38; RAM8(0x2000017F) = 46; RAM8(0x20000180) = 54;   /* brightness levels (%) */
    RAM8(0x20000181) = 62; RAM8(0x20000182) = 70; RAM8(0x20000183) = 78; RAM8(0x20000184) = 86; RAM8(0x20000185) = 94; RAM8(0x20000186) = 100;
    RAM8(0x2000018E) = 0x2A; RAM8(0x2000018F) = 0x00; RAM8(0x2000019A) = 0x2B;          /* the strip read: write register 0 to 0x15, read from 0x15 */
}

void native_reset(void)
{
    u32 a;
    for (a = 0x20000000u; a < 0x20001818u; a += 4) RAM32(a) = 0;                         /* RAM: zero, apart from the stack (in use), our state */
    for (a = 0x20001C18u; a < 0x20004200u; a += 4) RAM32(a) = 0;                         /* (set up by its own code) and the words that survive a reset */
    ram_start_values();
    BOOT_FLAG = BOOT_OWN_USB;                        /* every part of the start-up and the USB stack: ours */
    init_body();
    boot2_body();
    iwdg_start();
    for (;;) {
        tick_body();                                 /* the watchdog, requests, clock, display */
        w_service();                                 /* the jobs that are due, the USB transmit ring, the dispatcher */
        if (U16(2)) continue;                        /* the start-up is still running */
        if (STK[0] == 0) w_normal();
        else if (STK[0] == 1) {                      /* suspended by the host: back when it resumes */
            if (!USB_SUSP) {
                STK[0] = 0;
                disp_put(0, 0x8D); disp_put(0, 0x14); disp_put(0, 0xAF);
                BB(0x40010C0Cu, 8) = 1; BB(0x40010C0Cu, 9) = 1;
            }
        } else STK[0] = 0;
    }
}

void native_nmi(void) { }
void native_fault(void) { for (;;) { } }             /* the watchdog resets the chip; three in a row and the guard goes into DFU mode */
