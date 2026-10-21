/* Our USB device stack (docs/clean-firmware-plan.md, stage 3): the STM32 full-speed USB peripheral, driven directly. Included at the end of
 * translate.c (one translation unit). It presents what the patched firmware has always presented: the device and configuration descriptors
 * of build_patch.py (USB-MIDI with two bulk endpoints, and a DFU runtime interface), the strings of the descriptor table, and DFU_DETACH,
 * which goes into NI's bootloader through our own enter_dfu(). Endpoint 1 carries USB-MIDI both ways: what arrives goes to the same handler
 * the stock OUT callback fed (mmk3_rx), what the translator queues in the transmit ring goes out 64 bytes at a time from the main loop.
 *
 * In the patched image it only runs on a boot of ours that asked for it (SysEx 1C flag 8, one-shot, like the board init), and that boot reboots
 * into the stock path if no host has configured the device 5 s after the start-up, or if no configuration request (SysEx) has been answered
 * after 15 s: a broken stack can not leave the device unreachable. The standalone image always runs it, without those restarts. */

#define USB_EPR(n) (*(volatile u32 *)(0x40005C00u + 4u * (n)))
#define USB_CNTR (*(volatile u32 *)0x40005C40u)
#define USB_ISTR (*(volatile u32 *)0x40005C44u)
#define USB_DADDR (*(volatile u32 *)0x40005C4Cu)
#define USB_BTABLE (*(volatile u32 *)0x40005C50u)
#define PMA16(off) (*(volatile u32 *)(0x40006000u + 2u * (off)))      /* a 16-bit word of packet memory (byte offset off, even) */

#define EP_CTR_RX 0x8000u
#define EP_DTOG_RX 0x4000u
#define EP_STAT_RX 0x3000u
#define EP_SETUP 0x0800u
#define EP_TYPE 0x0600u
#define EP_KIND 0x0100u
#define EP_CTR_TX 0x0080u
#define EP_DTOG_TX 0x0040u
#define EP_STAT_TX 0x0030u
#define EP_EA 0x000Fu
#define EP_KEEP (EP_CTR_RX | EP_SETUP | EP_TYPE | EP_KIND | EP_CTR_TX | EP_EA)   /* the bits a write leaves alone (CTR: written as 1) */
#define ST_DIS 0u
#define ST_STALL 1u
#define ST_NAK 2u
#define ST_VALID 3u
#define ISTR_CTR 0x8000u
#define ISTR_PMAOVR 0x4000u
#define ISTR_ERR 0x2000u
#define ISTR_WKUP 0x1000u
#define ISTR_SUSP 0x0800u
#define ISTR_RESET 0x0400u
#define ISTR_SOF 0x0200u
#define ISTR_ESOF 0x0100u
#define CNTR_FSUSP 0x0008u
#define CNTR_LPMODE 0x0004u
/* packet memory: the buffer table at 0, EP0 IN 0x40 / OUT 0x80, EP1 IN 0xC0 / OUT 0x100, 64 bytes each (the stock layout) */
#define PMA_EP0_TX 0x40u
#define PMA_EP0_RX 0x80u
#define PMA_EP1_TX 0xC0u
#define PMA_EP1_RX 0x100u
#define RX_COUNT_64 0x8400u                          /* COUNT_RX: 32-byte blocks, 2 of them = 64 bytes */

#define RING ((volatile u8 *)0x20000778)             /* the transmit ring (0x500 bytes) and its write / read indices */
#define RING_WI (*(volatile u16 *)0x20000146)
#define RING_RI (*(volatile u16 *)0x20000148)
#define RXLEN (*(volatile u8 *)0x20000074)           /* where the stock OUT callback left a received packet for mmk3_rx */
#define RXBUF ((volatile u8 *)0x200001D8)

static void rx_handle(void);

/* Bytes into the transmit ring: everything is USB-MIDI packets of 4 bytes, so only whole packets go in. When the host stops reading (not
 * configured yet, suspended, no app listening) the ring fills up and what does not fit is dropped whole: a packet cut in two would shift every
 * later one by its stub, and the host would read nothing but garbage from then on (the ring holds 0x4FF bytes, not a multiple of 4). */
static u32 ring_room(void) { return (RING_RI + 0x500u - RING_WI - 1u) % 0x500u; }
static u32 __attribute__((noinline, used)) ring_put(const void *src, u32 n)
{
    const u8 *b = (const u8 *)src;
    u32 k, w = RING_WI, room = ring_room() & ~3u;
    if (n > room) n = room;
    n &= ~3u;
    for (k = 0; k < n; k++) { RING[w] = b[k]; w = (w + 1u) % 0x500u; }
    RING_WI = (u16)w;                                /* one store, after the bytes: the interrupt only ever sees the index on a packet boundary */
    return k;
}
static u32 enqueue(const void *src, u32 n)
{
    u32 room;
    if (OURS(ST->own_usb)) return ring_put(src, n);
    room = ring_room() & ~3u;                        /* the stock enqueue copies bytes as long as they fit: hand it whole packets only */
    if (n > room) n = room;
    n &= ~3u;
    return n ? ((u32 (*)(const void *, u32))STOCK(0x08008A39))(src, n) : 0;
}
static u32 ring_get(u8 *dst, u32 max)
{
    u32 k;
    for (k = 0; k < max && RING_RI != RING_WI; k++) { dst[k] = RING[RING_RI]; RING_RI = (u16)((RING_RI + 1u) % 0x500u); }
    return k;
}

static void ep_stat(u32 n, u32 rx, u32 tx)           /* rx / tx: ST_* or 0xFF = leave */
{
    u32 v = USB_EPR(n), w = (v & EP_KEEP) | EP_CTR_RX | EP_CTR_TX;
    if (rx != 0xFF) w |= (v & EP_STAT_RX) ^ (rx << 12);
    if (tx != 0xFF) w |= (v & EP_STAT_TX) ^ (tx << 4);
    USB_EPR(n) = w;
}
static void ep_clear_ctr(u32 n, u32 which)           /* which: EP_CTR_RX or EP_CTR_TX */
{
    USB_EPR(n) = ((USB_EPR(n) & EP_KEEP) | EP_CTR_RX | EP_CTR_TX) & ~which;
}
static void ep_setup(u32 n, u32 type, u32 rx, u32 tx) /* type, address n, data toggles back to 0, the two states */
{
    u32 v = USB_EPR(n);
    USB_EPR(n) = type | n | EP_CTR_RX | EP_CTR_TX | (v & (EP_DTOG_RX | EP_DTOG_TX)) | ((v & EP_STAT_RX) ^ (rx << 12)) | ((v & EP_STAT_TX) ^ (tx << 4));
}
static void pma_write(u32 off, const volatile u8 *src, u32 n)
{
    u32 k;
    for (k = 0; k < n; k += 2) PMA16(off + k) = src[k] | (k + 1 < n ? (u32)src[k + 1] << 8 : 0);
}
static void pma_read(volatile u8 *dst, u32 off, u32 n)
{
    u32 k, w;
    for (k = 0; k < n; k += 2) { w = PMA16(off + k); dst[k] = (u8)w; if (k + 1 < n) dst[k + 1] = (u8)(w >> 8); }
}
#define BT_ADDR_TX(n) PMA16(8u * (n))
#define BT_COUNT_TX(n) PMA16(8u * (n) + 2u)
#define BT_ADDR_RX(n) PMA16(8u * (n) + 4u)
#define BT_COUNT_RX(n) PMA16(8u * (n) + 6u)

/* ---- control transfers on EP0 ---- */
#define CTL_IDLE 0
#define CTL_IN 1                                     /* sending the data stage */
#define CTL_STATUS_OUT 2                             /* data sent, waiting for the host's empty OUT */
#define CTL_STATUS_IN 3                              /* request done, our empty IN queued */

static void ep0_send(struct state *s)                /* the next packet of the data stage (possibly empty, to end on a full packet) */
{
    u32 n = s->u_left > 64 ? 64 : s->u_left;
    pma_write(PMA_EP0_TX, s->u_ptr, n);
    BT_COUNT_TX(0) = n;
    s->u_ptr += n; s->u_left = (u16)(s->u_left - n);
    if (!s->u_left && (n < 64 || !s->u_zlp)) s->u_ctl = CTL_STATUS_OUT;      /* the last packet: then the status stage */
    else if (!s->u_left) s->u_zlp = 0;                                       /* a full last packet: one empty packet follows */
    ep_stat(0, ST_VALID, ST_VALID);
}
static void ep0_reply(struct state *s, const volatile u8 *p, u32 n, u32 wlen)
{
    s->u_ptr = p; s->u_left = (u16)(n < wlen ? n : wlen);
    s->u_zlp = (n < wlen && (s->u_left % 64) == 0) ? 1 : 0;                  /* shorter than asked and a multiple of 64: end with an empty packet */
    s->u_ctl = CTL_IN;
    ep0_send(s);
}
static void ep0_ack(struct state *s) { BT_COUNT_TX(0) = 0; s->u_ctl = CTL_STATUS_IN; ep_stat(0, ST_VALID, ST_VALID); }
static void ep0_stall(struct state *s) { s->u_ctl = CTL_IDLE; ep_stat(0, ST_STALL, ST_STALL); }

static void ep0_setup_packet(struct state *s)
{
    u8 rq[8];
    u32 bm, req, val, idx, len;
    pma_read(rq, PMA_EP0_RX, 8);
    bm = rq[0]; req = rq[1]; val = rq[2] | (u32)rq[3] << 8; idx = rq[4] | (u32)rq[5] << 8; len = rq[6] | (u32)rq[7] << 8;
    s->u_ctl = CTL_IDLE;
    if ((bm & 0x60) == 0) {                          /* standard */
        if (req == 6 && bm == 0x80) {                /* GET_DESCRIPTOR */
            u32 type = val >> 8, i = val & 0xFF;
            if (type == 1) { ep0_reply(s, (const u8 *)DESC_TABLE[0], DESC_TABLE[1], len); return; }
            if (type == 2) { ep0_reply(s, (const u8 *)DESC_TABLE[2], DESC_TABLE[3], len); return; }
            if (type == 3 && i <= 5) { ep0_reply(s, (const u8 *)DESC_TABLE[8 + 2 * i], DESC_TABLE[9 + 2 * i], len); return; }
        } else if (req == 5 && bm == 0x00) {         /* SET_ADDRESS: after the status stage */
            s->u_addr = (u8)(val & 0x7F); s->u_addr_set = 1; ep0_ack(s); return;
        } else if (req == 9 && bm == 0x00 && val <= 1) {          /* SET_CONFIGURATION */
            s->u_config = (u8)val; s->u_flush_to = RING_WI; s->u_flush = 1;
            if (val) { ep_setup(1, 0, ST_VALID, ST_NAK); s->u_ever = 1; }
            else ep_setup(1, 0, ST_DIS, ST_DIS);
            ep0_ack(s); return;
        } else if (req == 8 && bm == 0x80) { s->u_buf[0] = s->u_config; ep0_reply(s, s->u_buf, 1, len); return; }      /* GET_CONFIGURATION */
        else if (req == 0 && (bm & 0x80)) {          /* GET_STATUS: no remote wake-up, bus powered; an endpoint: halted or not */
            s->u_buf[0] = 0; s->u_buf[1] = 0;
            if ((bm & 0x1F) == 2 && (idx & 0x7F) == 1)
                s->u_buf[0] = (idx & 0x80) ? ((USB_EPR(1) & EP_STAT_TX) == (ST_STALL << 4)) : ((USB_EPR(1) & EP_STAT_RX) == (ST_STALL << 12));
            ep0_reply(s, s->u_buf, 2, len); return;
        } else if ((req == 1 || req == 3) && !(bm & 0x80)) {      /* CLEAR / SET_FEATURE */
            if ((bm & 0x1F) == 2 && val == 0 && (idx & 0x7F) == 1) {                                   /* endpoint halt */
                if (req == 3) { if (idx & 0x80) ep_stat(1, 0xFF, ST_STALL); else ep_stat(1, ST_STALL, 0xFF); }
                else { u32 v = USB_EPR(1); USB_EPR(1) = (v & EP_KEEP) | EP_CTR_RX | EP_CTR_TX | ((idx & 0x80) ? ((v & EP_DTOG_TX) | ((v & EP_STAT_TX) ^ (ST_NAK << 4))) : ((v & EP_DTOG_RX) | ((v & EP_STAT_RX) ^ (ST_VALID << 12)))); }
                ep0_ack(s); return;
            }
            if ((bm & 0x1F) == 0) { ep0_ack(s); return; }                                              /* device: remote wake-up, ignored */
            if ((bm & 0x1F) == 2 && val == 0 && (idx & 0x7F) == 0) { ep0_ack(s); return; }            /* endpoint 0 halt: nothing to do */
        } else if (req == 10 && bm == 0x81) { s->u_buf[0] = 0; ep0_reply(s, s->u_buf, 1, len); return; }      /* GET_INTERFACE */
        else if (req == 11 && bm == 0x01 && val == 0) {                                                       /* SET_INTERFACE, alternate 0 */
            if ((idx & 0xFF) == 1 && s->u_config) { ep_setup(1, 0x0000, ST_VALID, ST_NAK); s->u_flush_to = RING_WI; s->u_flush = 1; }  /* the MIDI endpoints start over at DATA0 */
            ep0_ack(s); return;
        }
    } else if ((bm & 0x7F) == 0x21 && (idx & 0xFF) == 2) {        /* DFU runtime, interface 2 */
        if (req == 0 && !(bm & 0x80)) { s->u_detach = 1; ep0_ack(s); return; }                       /* DFU_DETACH */
        if (req == 3 && (bm & 0x80)) { u32 k; for (k = 0; k < 6; k++) s->u_buf[k] = 0; s->u_buf[4] = s->u_detach ? 1 : 0; ep0_reply(s, s->u_buf, 6, len); return; }   /* GETSTATUS: OK, appIDLE (appDETACH after a DETACH) */
        if (req == 5 && (bm & 0x80)) { s->u_buf[0] = s->u_detach ? 1 : 0; ep0_reply(s, s->u_buf, 1, len); return; }      /* GETSTATE */
    }
    ep0_stall(s);
}

static void usb_reset(struct state *s)
{
    USB_BTABLE = 0;
    BT_ADDR_TX(0) = PMA_EP0_TX; BT_COUNT_TX(0) = 0; BT_ADDR_RX(0) = PMA_EP0_RX; BT_COUNT_RX(0) = RX_COUNT_64;
    BT_ADDR_TX(1) = PMA_EP1_TX; BT_COUNT_TX(1) = 0; BT_ADDR_RX(1) = PMA_EP1_RX; BT_COUNT_RX(1) = RX_COUNT_64;
    ep_setup(0, 0x0200, ST_VALID, ST_NAK);           /* control */
    ep_setup(1, 0x0000, ST_DIS, ST_DIS);             /* bulk: enabled by SET_CONFIGURATION */
    USB_DADDR = 0x80;
    s->u_config = 0; s->u_addr_set = 0; s->u_ctl = CTL_IDLE; s->u_flush_to = RING_WI; s->u_flush = 1;
    if (s->u_detach) { s->u_detach = 2; s->u_detach_t = MS16; }       /* a reset after DETACH: into DFU mode, as DFU 1.1 asks */
}

static void __attribute__((noinline)) own_usb_isr(void)
{
    struct state *s = ST;
    u32 istr = USB_ISTR, v;
    if (istr & ISTR_RESET) { USB_ISTR = (u16)~ISTR_RESET; usb_reset(s); }
    if (istr & ISTR_SUSP) { USB_ISTR = (u16)~ISTR_SUSP; USB_CNTR |= CNTR_FSUSP; USB_SUSP = 1; }
    if (istr & ISTR_WKUP) { USB_ISTR = (u16)~ISTR_WKUP; USB_CNTR &= ~(CNTR_FSUSP | CNTR_LPMODE); USB_SUSP = 0; }
    if (istr & (ISTR_SOF | ISTR_ESOF | ISTR_ERR | ISTR_PMAOVR)) USB_ISTR = (u16)~(istr & (ISTR_SOF | ISTR_ESOF | ISTR_ERR | ISTR_PMAOVR));
    while ((istr = USB_ISTR) & ISTR_CTR) {
        u32 n = istr & 0xF;
        v = USB_EPR(n);
        if (n == 0) {
            if (v & EP_CTR_TX) {
                ep_clear_ctr(0, EP_CTR_TX);
                if (s->u_ctl == CTL_IN) ep0_send(s);
                else if (s->u_ctl == CTL_STATUS_IN) {
                    s->u_ctl = CTL_IDLE;
                    if (s->u_addr_set) { USB_DADDR = 0x80u | s->u_addr; s->u_addr_set = 0; }
                    if (s->u_detach == 1) { s->u_detach = 2; s->u_detach_t = MS16; }      /* the main loop goes into DFU mode shortly */
                }
            }
            if (v & EP_CTR_RX) {
                if (v & EP_SETUP) { ep_clear_ctr(0, EP_CTR_RX); ep0_setup_packet(s); }
                else { ep_clear_ctr(0, EP_CTR_RX); if (s->u_ctl == CTL_STATUS_OUT) s->u_ctl = CTL_IDLE; ep_stat(0, ST_VALID, 0xFF); }
            }
        } else if (n == 1) {
            if (v & EP_CTR_RX) {
                u32 cnt = BT_COUNT_RX(1) & 0x3FF;
                if (cnt > 64) cnt = 64;
                pma_read(RXBUF, PMA_EP1_RX, cnt);
                RXLEN = (u8)cnt;
                ep_clear_ctr(1, EP_CTR_RX);
                if (cnt) rx_handle();
                RXLEN = 0;
                ep_stat(1, ST_VALID, 0xFF);
            }
            if (v & EP_CTR_TX) ep_clear_ctr(1, EP_CTR_TX);
        } else USB_EPR(n) = 0;                       /* (no other endpoint is set up) */
    }
}

/* The main loop's share: the next 64 bytes of the ring when endpoint 1 is free, DFU mode after a DETACH, and the safety reboot. */
static void __attribute__((noinline)) own_usb_tx(void)
{
    struct state *s = ST;
    u8 buf[64];
    u32 n;
    if (s->u_detach == 2 && (u16)(MS16 - s->u_detach_t) >= 20) enter_dfu();
#ifndef NATIVE                                       /* (the standalone image has no stock path to go back to: a charger or an app that never */
    if ((!s->u_ever && (u16)(MS16 - s->u_t0) > 5000) || (!s->u_ok && (u16)(MS16 - s->u_t0) > 15000)) {      /* sends our SysEx is normal) */
        __asm volatile("dsb"); AIRCR = 0x05FA0004u; for (;;) { }   /* no host took it, or none could talk to us: back to the stock path */
    }
#endif
    if (s->u_flush) {                                /* bus reset / new configuration: what was queued before it is stale (what came after stays) */
        u32 to;
        s->u_flush = 0; to = s->u_flush_to;
        if ((to + 0x500u - RING_RI) % 0x500u <= (RING_WI + 0x500u - RING_RI) % 0x500u) RING_RI = (u16)to;
    }
    if (!s->u_config || (USB_EPR(1) & EP_STAT_TX) != (ST_NAK << 4) || RING_WI == RING_RI) return;   /* (VALID: busy; STALL: halted by the host) */
    n = ring_get(buf, 64);
    pma_write(PMA_EP1_TX, buf, n);
    BT_COUNT_TX(1) = n;
    {
        u32 pm;
        __asm__ volatile("mrs %0, primask\n\tcpsid i" : "=r"(pm) :: "memory");
        if (s->u_config && (USB_EPR(1) & EP_STAT_TX) == (ST_NAK << 4)) ep_stat(1, 0xFF, ST_VALID);   /* (the interrupt may have deconfigured it meanwhile) */
        __asm__ volatile("msr primask, %0" :: "r"(pm) : "memory");
    }
}

static void __attribute__((noinline)) own_usb_init(void)
{
    RCC_CFGR &= ~0x400000u;                          /* USB clock = PLL / 1.5 = 48 MHz */
    RCC_APB1ENR |= 1u << 23;
    *(volatile u32 *)0xE000ED0Cu = 0x05FA0000u | 0x700u;                     /* priority grouping (as the stock code sets it) */
    *(volatile u8 *)(0xE000E400u + 20) = 0;          /* USB low-priority interrupt: priority 0, enabled */
    *(volatile u32 *)0xE000E100u = 1u << 20;
    RCC_APB2ENR |= 4; gpio_init(GPIOA, 0x0100, GM_OUT_PP);                  /* PA8: the D+ pull-up switch */
    USB_CNTR = 1;                                    /* force reset ... */
    USB_ISTR = 0;
    USB_CNTR = 0xBF00;                               /* ... released, the interrupts on */
    BB(0x4001080Cu, 8) = 1;                          /* connect */
    ST->u_t0 = MS16;
}

void mmk3_usb_isr(void)                              /* the USB low-priority interrupt vector */
{
    if (OURS(ST->own_usb)) own_usb_isr();
    else ((void (*)(void))STOCK(0x08008795))();
}
