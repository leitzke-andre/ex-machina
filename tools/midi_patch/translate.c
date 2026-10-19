/* HID-report -> USB-MIDI translator for the Maschine Mikro MK3 firmware.
 *
 * Replaces the single call  bl 0x08008a38 (ring-buffer enqueue)  at 0x08004036
 * inside the main service routine 0x08004620. That routine hands us a buffer of
 * concatenated input reports (layouts confirmed by three community drivers and a real unit):
 *   id 0x01 (14 bytes): 5 bytes button bits (bit = button id 0..39; 39 = encoder press),
 *                       byte 5 bit 0 = encoder touched (button id 40), encoder nibble (0..15, counts UP clockwise),
 *                       16-bit strip timestamp, strip position 1 (0 = untouched, 1..200),
 *                       0, strip position 2, 0. Sent only when something changes.
 *   id 0x02 (64 bytes): up to 21 pad events of 3 bytes [pad, type<<4|val>>8, val&0xff]
 *                       types: 0 press-on, 1 note-on (hit, peak), 2 press-off, 3 note-off,
 *                       4 aftertouch. A 000 triplet ends the list.
 * Pad index 0..15 is row-major from the TOP-left: index 0 is the pad printed 13, index 12 is pad 1.
 * We turn them into 4-byte USB-MIDI event packets (cable 0) and enqueue those
 * in the same ring buffer, which the existing EP1 IN sender drains unchanged.
 *
 * Build: clang --target=thumbv7m-none-eabi -Os -ffreestanding -fno-builtin -c
 * No relocations: all addresses are fixed constants.
 */
typedef unsigned char u8;
typedef signed char s8;
typedef unsigned short u16;
typedef unsigned int u32;

#ifdef NATIVE
#define STOCK(a) 0x08003141u                         /* the standalone image has no NI code: every call to it goes to a "return 0" stub (native.c) */
#else
#define STOCK(a) (a)                                 /* a routine of NI's firmware in the patched image */
#endif
static u32 ring_put(const void *src, u32 n);
static void own_threshold(void);
#ifdef NATIVE
#define OURS(x) 1                                    /* the standalone image: always our code (no switch, nothing of NI's to switch to) */
#else
#define OURS(x) (x)                                  /* the patched image: our code where the run-time switch (SysEx 1C) says so */
#endif
#ifdef NATIVE
#define THRESHOLD() own_threshold()
#else
#define THRESHOLD() ((void (*)(void))0x080046B9)()   /* the stock routine (the tests count its calls) */
#endif
static u32 enqueue(const void *src, u32 n);
#define ENQUEUE enqueue                              /* the transmit ring: ours with our USB stack (usb.c ring_put, the same as the stock enqueue: test_hal_usb.py), else the stock one */

/* What a button does (cfg.btn_act / btn_act2). ACT_CC sends the CC number in btn_cc (0xff = unassigned), ACT_NOTE the note number,
 * ACT_MMC the MMC command byte (1 stop, 2 play, 6 record strobe ...); the realtime actions ignore btn_cc. */
enum { ACT_CC, ACT_NOTE, ACT_START, ACT_CONT, ACT_STOP, ACT_MMC, ACT_NONE,
       /* the controller's own functions (no MIDI of their own, they change how the pads play); btn_cc is their parameter */
       ACT_PADMODE,         /* Group mode: the pads play the configured pad notes (drums) */
       ACT_KEYS,            /* pads play 16 chromatic notes from keys_root, pad 1 lowest, ascending left to right and bottom to top */
       ACT_FIXVEL,          /* toggle: every Note On at the fixed velocity (cfg.fixvel) */
       ACT_VEL16,           /* toggle: every pad plays the same note, pad n at velocity 8 * n (16 Velocities) */
       ACT_CURVE,           /* select the velocity curve: parameter 0 = next, 1 = previous; the choice is kept across power cycles */
       ACT_TRANSPOSE,       /* shift the pad notes: parameter 64 + semitones (76 = one octave up, 52 = one down) */
       ACT_PANIC,           /* All Sound Off + All Notes Off on all 16 channels */
       ACT_SHIFT,           /* hold: buttons use their second (shifted) action, btn_act2 / btn_cc2 */
       ACT_SCALE,           /* select the scale of Keyboard / Chords mode: parameter 0 = next, 1 = previous (switches to Keyboard mode from Group mode) */
       ACT_CHORDS,          /* Chords mode: every pad plays the chord on its scale degree */
       ACT_CHORDTYPE,       /* select the chord type (triad, seventh, sus2, sus4, power): parameter 0 = next, 1 = previous */
       ACT_STRIP,           /* touch strip mode: parameter 0 = the configured CC, 1 = pitch bend (springs back), 2 = mod wheel CC 1 that holds its value, shown as a bar */
       ACT_ENCTGT,          /* the encoder drives target 1..3 (parameter 0..2: enc_tgt_cc) instead of enc_cc; the same button again goes back */
       ACT_PROGRAM,         /* Program Change: parameter 0 = next, 1 = previous, 2 = back to program 0 */
       ACT_TAP,             /* tap tempo (the last taps set the tempo; ignored while a MIDI clock is coming in) */
       ACT_CLOCKOUT,        /* toggle: send MIDI clock (24 per beat) at the tempo, with Start when switched on and Stop when switched off */
       ACT_ARP,             /* toggle: arpeggiator / Note Repeat: the held pads' notes are played in time instead of at once */
       ACT_ARPTYPE,         /* arp pattern: parameter 0 = next, 1 = previous (repeat, up, down, up-down, played, random) */
       ACT_RATE,            /* arp / repeat rate: parameter 0 = next, 1 = previous (1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T) */
       ACT_ARPOCT,          /* arp octave range 1..4, stepping round */
       ACT_LATCH,           /* toggle: the arp keeps playing after the pads are released (until the next new chord) */
       ACT_MUTE,            /* toggle: pad hits mute / unmute that pad (muted pads are silent and dark) */
       ACT_SOLO,            /* toggle: pad hits solo / unsolo that pad (while any pad is soloed only soloed pads play) */
       ACT_CLEAR,           /* clear all mutes and solos */
       ACT_SNAP,            /* parameter 0: store the encoder targets, strip and encoder values, or (when stored) send them back; 1: store again */
       ACT_CHANNEL,         /* MIDI channel: parameter 0 = next, 1 = previous (kept across power cycles like the curve; the notes on the old channel are released) */
       ACT_SLOT,            /* the four preset slots in flash: parameter 0..3 = make slot n+1 the active config, 4..7 = store the active config in slot n-3,
                               8 = load the next slot holding a config (1, 2, 3, 4, 1, ...) */
       ACT_STEP,            /* the step sequencer's edit mode: pad n = step n of the selected track (a third pad function next to Group / Keyboard / Chords) */
       ACT_SEQRUN,          /* parameter 0: start / stop the sequencer (it follows the grid), 1: restart it from step 1 */
       ACT_SEQSEL,          /* hold: a pad hit selects that track instead of editing a step */
       ACT_SEQPAT,          /* pattern 1..4: parameter 0 = next, 1 = previous */
       ACT_SEQCLEAR,        /* parameter 0: clear the selected track of the pattern, 1: clear the whole pattern */
       ACT_SEQSAVE,         /* keep the four patterns in flash (they are loaded again at power-up) */
       ACT_PAGE,            /* pad page in Group mode: every pad plays 16 notes higher per page (0..7); parameter 0 = next, 1 = previous, 2 = back to page 1 */
       ACT_ENCPAGE,         /* the encoder targets' page (enc_pages of them): the CC of target t on page p is enc_tgt_cc[t] + enc_page_step * p; parameter 0 = next, 1 = previous, 2 = page 1 */
       ACT_LAST = ACT_ENCPAGE };
/* Local LED behaviour (cfg.led_flags): the device lights itself, without any host feedback. */
#define LF_BTN_IDLE  1      /* assigned buttons rest dimly lit */
#define LF_BTN_PRESS 2      /* ... and light up while pressed (in toggle mode: while on) */
#define LF_PAD_IDLE  4      /* pads rest in a dim colour */
#define LF_PAD_HIT   8      /* ... and flash brightly while hit */
#define LF_STRIP     16     /* the touch-strip LED under the finger lights up */

struct cfg {                /* lives in flash at CFG_ADDR, editable offline */
    u8 magic[4];            /* "MMK3" */
    u8 channel;             /* 0..15 */
    u8 pad_note[16];        /* indexed by pad index in the report (0 = pad 13 ... 12 = pad 1) */
    u8 btn_cc[48];          /* by button id: 0..38 buttons, 39 encoder press, 40 encoder touch; parameter of the action (CC number, 0xff = none) */
    u8 enc_cc;              /* encoder rotation CC; 0xff = none */
    u8 strip_cc;            /* touch strip CC (absolute 0..127); 0xff = none */
    u8 vel_shift;           /* pressure = value12 >> vel_shift (0..127); Note On velocity = vel_table[value12 >> (vel_shift - 1)] (1..127) */
    u8 led_channel;         /* MIDI channel on which note n (0..79) drives LED n directly */
    u8 pad_led[16];         /* LED index of each pad (on `channel`, note pad_note[p] lights pad_led[p]) */
    u8 enc_mode;            /* 0 = relative offset (64 + delta, NI "Relative (Offset)"), 1 = absolute 0..127, 2 = relative two's complement (+n -> n, -n -> 128-n, NI "Relative") */
    u8 flags;               /* bit 0: send strip_cc = 0 when the strip is released */
    u8 sens;                /* pad sensitivity 0..100 (stock scale, default in the ROM table: 80); 0xff = keep stored value */
    u8 enc_init;            /* absolute encoder: starting value (NI's template: 0) */
    u16 boot_ms;            /* startup countdown before scanning begins (stock 6000 ms, which the LED fade-in cuts to about 1.8 s); 0xffff = keep stock */
    u8 btn_mode;            /* ACT_CC buttons: 0 gate (127 on press, 0 on release), 1 toggle (NI's default: 127 / 0 on alternate presses),
                               2 trigger (127 on press only) */
    u8 btn_act[48];         /* ACT_* per button id */
    u8 led_flags;           /* LF_* bits */
    u8 btn_led_idle;        /* LED code of an assigned button at rest (0x7c = dim) */
    u8 btn_led_on;          /* LED code while pressed / on (0x7f = bright) */
    u8 pad_colour;          /* pad colour 1..17 (17 = white; 0 = white too): rests at colour*4+1, flashes at colour*4+3 */
    u8 strip_colour;        /* colour of the strip LED under the finger (same numbering, 0 = white), shown bright */
    u8 vel_curve;           /* 0..8: soft3 soft2 soft1 linear hard1 hard2 hard3 fixed custom (VEL_TABLES); ACT_CURVE changes it in RAM and keeps it, see "settings log" */
    u8 fixvel;              /* 1..127: velocity of every note while Fixed Vel is on */
    u8 keys_root;           /* note of pad 1 in Keyboard mode (60 = C3) */
    u8 press_mode;          /* pad pressure: 0 polyphonic aftertouch, 1 channel pressure, 2 control change press_cc, 3 none */
    u8 press_cc;
    u8 btn_act2[48];        /* the shifted layer: ACT_* per button id while a Shift button (ACT_SHIFT) is held; ACT_NONE = the button keeps its normal action */
    u8 btn_cc2[48];
    u8 scale;               /* 0..23: the scale Keyboard and Chords mode start with (SCALES; 0 = chromatic) */
    u8 chord_type;          /* 0..4: triad, seventh, sus2, sus4, power */
    u8 enc_tgt_cc[3];       /* CC of the encoder targets 1..3 (ACT_ENCTGT); 0xff = none */
    u8 arp_type;            /* 0..5 repeat, up, down, up-down, played, random */
    u8 arp_rate;            /* 0..6: 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T */
    u8 arp_oct;             /* 1..4 octaves */
    u8 tempo;               /* start tempo in BPM minus 20 (20..275 BPM) */
    u8 btn_mode_ovr[12];    /* per button (id k: byte k >> 2, bits 2 * (k & 3)): 0 = the global btn_mode, 1 gate, 2 toggle, 3 trigger */
    u8 enc_pages;           /* 1..8: pages of encoder targets */
    u8 enc_page_step;       /* 1..32: how far the CC of a target moves per page */
    u8 enc_accel;           /* 0 = off, 1..3: turning faster takes bigger steps */
} __attribute__((packed));
_Static_assert(sizeof(struct cfg) == 274, "cfg layout is mirrored in mmk3_config.py");
#define CFG_DEFAULTS ((const struct cfg *)0x0800CE00)   /* the build-time defaults, in flash; the ACTIVE config is a RAM copy, see struct state */
#define OFS(f) ((u32)__builtin_offsetof(struct cfg, f))

/* Velocity curve: 256 bytes in flash written by build_patch.py (one of NI's curves or a custom table). The index is the
 * 12-bit hit value >> (vel_shift - 1), saturated at 255, so vel_shift is the gain in front of the curve. */
#define VEL_TABLES ((const u8 *)0x0800D000)             /* 9 curves x 256 bytes */
#define CURVE_COUNT (*(const volatile u8 *)0x0800D900)  /* how many of them ACT_CURVE steps through (8, or 9 with a custom table) */
#define FONT_ADDR 0x0800D940u                            /* 5 x 7 font, ASCII 32..95, 5 column bytes each (bit 0 = top row) */
#define TXT_ADDR 0x0800DA80u                             /* the texts of the display messages: 16 bytes each, NUL padded (build_patch.py TEXTS) */
#define SCALE_N 24u
#define HW_ADDR 0x0800E700                        /* the board's wiring for hal.c (build_patch.py hw_blob: button matrix) */
#define LEDTAB_ADDR 0x0800E780                    /* the LED colour tables for hal.c (build_patch.py led_tables, from the user's stock image) */
#define SCALES ((const u16 *)0x0800E6C0)                 /* 12-bit masks of the scales, bit n = semitone n (build_patch.py SCALES) */

struct state {              /* RAM above the firmware's stack, zeroed by mmk3_init */
    u32 magic;
    u16 held;               /* bit per pad currently sounding */
    u8 btn[5];
    u8 tog[6];              /* toggle-mode state per button id (bit k) */
    u8 touch;               /* encoder touched */
    u8 enc;
    u8 encabs;              /* absolute encoder value */
    u8 pos;
    u8 pres[16];
    u8 have;                /* baseline for report 1 captured */
    u8 insx;                /* inside a SysEx message */
    u8 started;             /* the stock startup (LED fade-in) is over and the LEDs were re-applied, see mmk3_tick() */
    u8 lit;                 /* the shadow holds LEDs to show (something was flushed or the resting state was set) */
    u8 strip_led;           /* strip LED index + 1 currently lit by the finger, 0 = none */
    u16 sxn;                /* bytes collected in sx[] */
    u8 out[512];            /* outgoing USB-MIDI packets for one translate call */
    u8 sx[336];             /* incoming SysEx body */
    u8 led[80];             /* shadow of the LED codes shown (0xFF = never set); always written out COMPLETE, see led_flush() */
    u8 base[80];            /* the resting code of each LED: what it returns to when a local press / hit ends (host feedback sets it) */
    /* Run-time configuration (see the "configuration" section below): the active config is one of two RAM buffers and cfgp points at it,
     * so a new config becomes active with a single pointer store while the USB interrupt and the main loop keep reading consistently. */
    struct cfg cfgbuf[2];
    const struct cfg *cfgp;
    u8 cfgi;                /* index of the buffer cfgp points at */
    u8 saved;               /* a valid saved config is in flash */
    u8 flags_boot;          /* the config in use at boot came from the saved record */
    u8 dirty;               /* the active config differs from what is saved (or from the defaults when nothing is saved) */
    u8 req;                 /* pending request (SysEx command 0x10..0x14), handled by mmk3_tick() */
    u8 slot_req;            /* a preset slot to load (1..4) or store (5..8), or the next one to load (9), done by the main loop */
    u8 slot_cur;            /* the slot the active config came from or went to (1..4), 0 = not known: a new config clears it */
    u8 req_arg;
    u8 slname[24] __attribute__((aligned(4)));          /* the name kept with a preset slot: of the last slot loaded or stored (0xFF padded; all 0xFF = none); a new config clears it */
    u8 req_err;             /* the request was malformed when it arrived */
    u16 reply_len, reply_pos;   /* SysEx reply waiting to be sent from the main loop */
    u8 stage[288];          /* config received by SET, validated and activated by the tick */
    u8 reply[336] __attribute__((aligned(4)));      /* the reply being sent; also the scratch record the flash writers build (never while a reply is pending) */
    /* The controller's own modes (run-time only: they start fresh at power-up; the velocity curve lives in the config) */
    u8 shift;               /* number of Shift buttons (ACT_SHIFT) held */
    u8 lay[6];              /* bit per button id: the press that is held used the shifted layer, so its release does too */
    u8 padmode;             /* 0 Group (configured pad notes), 1 Keyboard (the scale from keys_root), 2 Chords (a chord on each scale degree) */
    u8 bar_on;              /* the strip LEDs show the mod wheel bar */
    u8 fixed, vel16;        /* Fixed Vel / 16 Velocities active */
    s8 transpose;           /* semitones added to every pad note */
    u8 psent;               /* the last channel pressure / CC pressure value sent is not 0 (to be zeroed when the last pad lets go) */
    u8 panic;               /* All Sound Off / All Notes Off messages still to send (of 32) */
    u8 log_req;             /* settings that changed with the buttons and are to be appended to the settings log by the main loop: bit 0 velocity curve, bit 1 MIDI channel */
    u8 cn[16][4];           /* the notes each held pad started (a chord has up to 4), for the Note Offs and the pressure (cn[pad][0]) */
    u8 cnn[16];             /* how many */
    u8 scale, ctype;        /* the scale and chord type in use (start from the config) */
    u8 strip_mode;          /* 0 the configured CC, 1 pitch bend, 2 mod wheel with a bar */
    u8 mod_val;             /* the mod wheel value the strip holds */
    u8 enc_tgt;             /* 0 = enc_cc, 1..3 = ACT_ENCTGT target */
    u8 enc_page;            /* the encoder target page in use */
    u8 page;                /* the pad page (Group mode) */
    u8 tval[8][3];          /* absolute value of each encoder target on each page */
    u8 snap_page;           /* the encoder page the snapshot was taken on */
    u8 prog;                /* the program number ACT_PROGRAM is at */
    /* time, arp, mute / solo, strum, snapshot (phase 3) */
    u8 padfn;               /* 0 play, 1 mute edit, 2 solo edit */
    u16 mute, solo;         /* bit per pad (report index) */
    u8 arp_on, arp_type, arp_rate, arp_oct, latch, clock_out;
    u16 bpm;                /* tempo */
    u16 last_ms;            /* the millisecond counter at the last clock pass */
    u32 acc_us;             /* microseconds towards the next pulse (24 per beat) */
    u32 pulse;              /* pulses since the grid started */
    u8 ext_in, ext_seen;    /* incoming MIDI clock bytes counted by the USB interrupt / handled by the tick (free-running, the difference is what is pending) */
    u8 ext_go, ext_go_seen, ext_stp, ext_stp_seen;   /* the same for Start / Continue and Stop */
    u8 ext_any;             /* a MIDI clock has been seen since power-up */
    u16 ext_ms;             /* the millisecond counter when the last clock byte came in */
    u8 ext_active;          /* an external clock is driving the grid */
    u8 an[16], av[16], ap[16], ann;     /* the arp's note list: note, velocity, the pad it came from; count */
    u8 son[16], sonn;       /* arp notes sounding now */
    u8 ixs[16];             /* scratch: the list in pitch order */
    u16 astep;              /* steps played since the list started */
    u8 arp_kick;            /* the first note came in with no grid running: start the grid with it */
    u16 parp;               /* pads whose hold goes through the arp */
    u16 rnd;
    u8 tap_n;               /* taps in the current run */
    u16 tap_last, tap_iv[3];
    u8 tap_btn;             /* the button that carries the beat LED (the one set to ACT_TAP), 0xFF none */
    u8 strum;               /* strum note sounding + 1, 0 none */
    u8 strum_off;           /* a strum note to release from the main loop (note + 1) */
    u8 snap_have, snap[5];
    /* the step sequencer: 4 patterns of 16 tracks (the 16 pad notes) of 16 steps, 2 bits per step (off, normal, accent) */
    u32 pat[4][16];
    u8 seq_on, seq_pos, seq_cur, seq_trk, seq_pat, seq_sel, seq_kick, seq_led, seq_save, seq_dirty;
    u16 seq_son;            /* tracks sounding now */
    /* The display: a message (title in 2x size, a detail line, an optional bar) shows for MSG_MS, then the picture that was there returns */
    u8 dstate;              /* D_* */
    u8 dbar;                /* bar length 0..118 pixels, 0xFF = no bar */
    u16 dt0;                /* time the message was written (stock millisecond counter) */
    char mt[12], md[24];    /* title (up to 10 characters), detail line (up to 21) */
    u8 vdirty;              /* the picture behind the messages (idle screen / sequencer grid) must be drawn again */
    u32 vsig;               /* what it was last drawn for (a change of any part of it sets vdirty) */
    u8 vgen;                /* bumped when the sequencer grid changes without anything in vsig changing */
    char vs[24];            /* the status line of the idle screen / the top line of the sequencer grid */
    char vd[24];            /* the detail line of the idle screen while notes are shown: their names; empty = the version */
    u32 vnotes[4];          /* the notes the idle screen shows (bit n = note n): those sounding, kept for NOTE_HOLD_MS after the last one stopped */
    u16 nt0;                /* when the last note stopped (the stock millisecond counter) */
    u8 nt_on;               /* nt0 is running */
    u8 gest;                /* the DFU gesture (Shift + Stop + Erase): 0 not held, 1 held since gest_t0, 2 announced (the reset follows) */
    u8 healthy;             /* the crash-loop guard was cleared after HEALTHY_MS of normal running */
    u16 gest_t0, run_t0;    /* when the gesture began; when the startup ended */
    u16 cap_mask;           /* raw pad capture: the ADC channels being recorded (0 = off), see cap_tick() */
    u8 cap_period;          /* ... one frame every cap_period ms */
    u8 cap_hang;            /* a HANG request was confirmed: the next tick stops (the watchdog test) */
    u16 cap_t;              /* ... when the last frame was taken */
    u8 hal, hal2;           /* our own drivers switched on (hal.c, SysEx 1C): mask bytes */
    u8 own_init;            /* this boot ran our board init (and runs our start-up and main loop) */
    u8 boot_done;           /* our start-up has ended (display on, USB started) */
    u8 own_usb;             /* this boot runs our USB stack (usb.c) */
    u8 u_ctl, u_zlp, u_addr, u_addr_set, u_config, u_detach, u_ever, u_ok;   /* usb.c: control transfer state, address, configuration, DFU detach, a request answered */
    u16 u_left, u_detach_t, u_t0;
    const volatile u8 *u_ptr;
    u8 u_buf[8];
    u8 reboot;              /* a reboot was asked for (SysEx 1C flag 4): done once the reply is out */
    u16 hal_ok, hal_fail;   /* LED bursts of our driver that every chip acknowledged / that one did not (for checking it on the device) */
    u16 strip_ok, strip_fail;   /* read cycles of our strip driver that worked / that the controller did not answer */
};
#define ST_ADDR 0x20004200u
#define ST ((struct state *)ST_ADDR)
#define ST_MAGIC 0x4D4D4B33u
_Static_assert(ST_ADDR + sizeof(struct state) <= 0x20005000u, "state must fit into the free RAM above the stack");

static void cfg_load(struct state *s);
static void enter_dfu(void);
static void hal_set(struct state *s, u32 mask, u32 mask2, u32 flags);
static void own_board_init(void);
static void own_stage2(const u8 *pic, u32 countdown);
static void pat_load(struct state *s);
static void mode_reset(struct state *s, const struct cfg *c);

static void state_reset(struct state *s)
{
    u8 *z = (u8 *)s; u32 n;
    for (n = 0; n < sizeof *s; n++) z[n] = 0;
    for (n = 0; n < 80; n++) s->led[n] = 0xFF;
    s->magic = ST_MAGIC;
    cfg_load(s);                                    /* the saved config if there is a valid one, else the defaults */
    pat_load(s);                                    /* the step patterns kept in flash */
    s->encabs = s->cfgp->enc_init & 127;
    mode_reset(s, s->cfgp);
}

static struct state *state(void)                    /* the state, initialised on first use */
{
    struct state *s = ST;
    if (s->magic != ST_MAGIC) state_reset(s);
    return s;
}

static u8 *emit(u8 *q, u8 status, u8 d1, u8 d2)
{
    q[0] = status >> 4; q[1] = status; q[2] = d1; q[3] = d2;
    return q + 4;
}

static u8 *emit1(u8 *q, u8 b)                 /* single-byte realtime message (Start, Continue, Stop ...) */
{
    q[0] = 0x0F; q[1] = b; q[2] = 0; q[3] = 0;
    return q + 4;
}

static u8 *emit_mmc(u8 *q, u8 cmd)            /* MIDI Machine Control: F0 7F 7F 06 <cmd> F7 as two USB-MIDI packets */
{
    q[0] = 0x04; q[1] = 0xF0; q[2] = 0x7F; q[3] = 0x7F;
    q[4] = 0x07; q[5] = 0x06; q[6] = cmd; q[7] = 0xF7;
    return q + 8;
}

static u8 clamp7(u32 v, u8 lo) { return v > 127 ? 127 : (v < lo ? lo : (u8)v); }

/* Note On velocity through the curve table `curve`; at least 1, because a Note On with velocity 0 is a Note Off. */
static u8 velocity(u32 val, u8 shift, u8 curve)
{
    u32 i = val >> (shift ? shift - 1 : 0);
    return clamp7(VEL_TABLES[(curve > 8 ? 3 : curve) * 256 + (i > 255 ? 255 : i)], 1);
}

#define SENS_BYTE (*(volatile u8 *)0x20001609)      /* struct 0x20001028 + 0x5e1, the stored sensitivity */

/* ---- LED output ---- */

#define LED_BUF ((volatile u8 *)0x20001351)    /* struct 0x20001028 + 0x329: 80 LED values */
#define LED_FLAG (*(volatile u8 *)0x200012F7)  /* struct + 0x2cf: "LED frame pending" */

/* The stock main loop applies the LED frame like this: it clears LED_FLAG FIRST and then reads the 80 entries one by one (values
 * >= 0x80 are skipped). A USB packet can therefore arrive in the middle of a pass, and a partial frame written for that packet
 * would be wiped or half-read (found on the real device: a 17-message burst lit a different random handful of LEDs each time;
 * reproduced in tools/midi_patch/test_led_race.py). So the firmware keeps a shadow of every LED it was told about and writes the
 * COMPLETE state each time, setting the flag last: whatever a pass in progress misses, the next pass (the flag is set again)
 * applies, and the last pass always sees the final state. */
static void led_flush(void)
{
    u32 k;
    for (k = 0; k < 80; k++) LED_BUF[k] = ST->led[k];
    LED_FLAG = 1;
    ST->lit = 1;
}

static u8 btn_defined(u8 act, u8 par) { return act == ACT_CC ? par != 0xff : act != ACT_NONE; }
static u8 btn_has_action(const struct cfg *c, u32 k) { return btn_defined(c->btn_act[k], c->btn_cc[k]); }
static u8 bmode(const struct cfg *c, u32 k)               /* the mode of a CC button: its own, else the global one (0 gate, 1 toggle, 2 trigger) */
{
    u8 o = (c->btn_mode_ovr[k >> 2] >> ((k & 3) * 2)) & 3;
    return o ? (u8)(o - 1) : c->btn_mode;
}
static u8 tgt_cc(const struct cfg *c, u32 t, u32 page)    /* the CC of encoder target t (0..2) on a page; 0xFF = none (also when it would pass 127) */
{
    u32 v;
    if (c->enc_tgt_cc[t] == 0xFF) return 0xFF;
    v = c->enc_tgt_cc[t] + (u32)c->enc_page_step * page;
    return v > 127 ? 0xFF : (u8)v;
}

static u8 pad_code(const struct cfg *c, u8 variant) { return (u8)(((c->pad_colour ? c->pad_colour : 17) << 2) | variant); }
static u8 strip_code(const struct cfg *c) { return (u8)(((c->strip_colour ? c->strip_colour : 17) << 2) | 3); }

#define STRIP_LED0 55           /* LEDs 55..79: the 25 touch-strip LEDs, left to right */

/* ---- the controller's own functions: pad modes, Fixed Vel, 16 Velocities, velocity curve, transpose, panic, and the display messages ---- */

/* The texts of the messages are data in flash (no string literals: the object must have no .rodata); this is their order, build_patch.py
 * holds the strings (TEXTS) and test_modes.py checks that the two agree. */
enum { T_PADMODE, T_KEYBOARD, T_FIXVEL, T_VEL16, T_VELOCITY, T_TRANSPOSE, T_PANIC, T_GROUP, T_ON, T_OFF, T_ALLOFF, T_BASE, T_ROOT,
       T_NOTE0, T_NOTE1, T_NOTE2, T_NOTE3, T_NOTE4, T_NOTE5, T_NOTE6, T_NOTE7, T_NOTE8, T_NOTE9, T_NOTE10, T_NOTE11,
       T_CURVE0, T_CURVE1, T_CURVE2, T_CURVE3, T_CURVE4, T_CURVE5, T_CURVE6, T_CURVE7, T_CURVE8,
       T_CHORDS, T_SCALE, T_CHORD, T_ENCODER, T_STRIP, T_PITCH, T_MOD, T_NORMAL, T_PROGRAM, T_PC, T_VALUE, T_CC, T_TRIAD, T_SEVENTH, T_SUS2, T_SUS4, T_POWER,
       T_SCALE0, T_SCALE1, T_SCALE2, T_SCALE3, T_SCALE4, T_SCALE5, T_SCALE6, T_SCALE7, T_SCALE8, T_SCALE9, T_SCALE10, T_SCALE11,
       T_SCALE12, T_SCALE13, T_SCALE14, T_SCALE15, T_SCALE16, T_SCALE17, T_SCALE18, T_SCALE19, T_SCALE20, T_SCALE21, T_SCALE22, T_SCALE23,
       T_PAGE, T_ENCPAGE, T_DFU, T_FLASHTOLEAVE, T_STEP, T_TRK, T_PAT, T_RUN, T_STOP, T_TRACK, T_PATTERN, T_CLEAR, T_PATTERNS, T_CHANNEL, T_SLOT, T_LOADED, T_SAVED, T_EMPTY, T_ERROR, T_EXNAME, T_VER, T_M0, T_M1, T_M2, T_CH, T_CLK, T_SEQ,
       T_ARP, T_ARPTYPE, T_RATE, T_OCT, T_LATCH, T_TEMPO, T_BPM, T_CLOCK, T_MUTE, T_SOLO, T_CLEARED, T_LOCK, T_STORED, T_RECALLED, T_EXT, T_STRUM,
       T_AT0, T_AT1, T_AT2, T_AT3, T_AT4, T_AT5, T_RATE0, T_RATE1, T_RATE2, T_RATE3, T_RATE4, T_RATE5, T_RATE6, T_COUNT };

#define MS16 (*(volatile u16 *)0x200010E8)               /* the stock SysTick handler's free-running millisecond counter (struct + 0xc0) */
#define DISP_HDR ((volatile u8 *)0x200013A1)              /* struct + 0x379: x,0,page,0,w,0,h,0 (u16 each) */
#define DISP_DATA ((volatile u8 *)0x200013A9)             /* pixel bytes, 1 byte = 8 vertical pixels of one column */
#define DISP_FLAG (*(volatile u8 *)0x200012F8)            /* struct + 0x2d0: "display region pending" */
/* The stock code sends the framebuffer to the display in 8 chunks of 64 columns, one per main-loop pass (0x080068b0); struct + 0xc8 counts the chunks left. The
 * apply routine sets it to 8, or, if it is not 0, ORs 0x80 into it, and the sender then repeats the last chunk (page 3, columns 64-127) with a pointer that runs
 * on through the framebuffer and past its end: a bar of changing pixels at the bottom right of the screen (seen on the device with every message, since the first
 * generation that wrote the screen). A region is therefore written only when this counter is 0. */
#define DISP_BUSY (*(volatile u8 *)0x200010F0)
#define MSG_MS 1500                                       /* how long a message stays */
#define NOTE_HOLD_MS 500                                  /* how long the notes stay on the screen after the last one stopped (a staccato note is readable) */
enum { D_IDLE, D_MSG0, D_MSG1, D_SHOW, D_VIEW0, D_VIEW1 };

static u32 tc(char *b, u32 p, char ch, u32 lim) { if (p < lim) b[p++] = ch; return p; }
static u32 tx(char *b, u32 p, u32 id, u32 lim)            /* append text `id` */
{
    const char *t = (const char *)(TXT_ADDR + id * 16);
    while (*t && p < lim) b[p++] = *t++;
    return p;
}
static u32 tn(char *b, u32 p, u32 v, u32 lim)             /* append a number 0..999 */
{
    if (v >= 100) p = tc(b, p, (char)('0' + v / 100), lim);
    if (v >= 10) p = tc(b, p, (char)('0' + v / 10 % 10), lim);
    return tc(b, p, (char)('0' + v % 10), lim);
}
static u32 tnote(char *b, u32 p, int n, u32 lim)          /* note name, middle C (60) = C3 like NI's apps */
{
    u32 u = n < 0 ? 0 : n > 127 ? 127 : (u32)n, o = u / 12;
    p = tx(b, p, T_NOTE0 + u % 12, lim);
    if (o < 2) { p = tc(b, p, '-', lim); return tn(b, p, 2 - o, lim); }
    return tn(b, p, o - 2, lim);
}

static const u8 *glyph(char ch)                           /* the 5 column bytes of a character (lower case shows as upper case) */
{
    u32 c = (u8)ch;
    if (c >= 'a' && c <= 'z') c -= 32;
    if (c < 32 || c > 95) c = '?';
    return (const u8 *)(FONT_ADDR + (c - 32) * 5);
}

static u8 bar_col(u32 x, u32 w)                           /* a frame from x = 4 to 123 with `w` pixels filled, 8 rows high */
{
    if (x < 4 || x > 123) return 0;
    if (x == 4 || x == 123) return 0x7E;
    return (u8)(0x42 | (x - 5 < w ? 0x3C : 0));
}

/* The screen is 128 x 32; a column is a 32-bit mask (bit r = row r lit), drawn by the functions below and cut into the two halves (pages 0-1, 2-3) the
 * stock staging buffer takes. Rows: 1-14 title (2x size), 17-23 detail line (5 x 7), 25-30 bar, 25-31 status line. */
static u32 text_col(const char *t, u32 n, u32 x, u32 x0)  /* the 7 bits of column x of a 5 x 7 text that starts at x0 (6-pixel cells) */
{
    u32 ci, w;
    if (x < x0) return 0;
    ci = (x - x0) / 6; w = (x - x0) % 6;
    if (ci >= n || w >= 5 || !t[ci]) return 0;
    return glyph(t[ci])[w];
}
static u32 title_col(const char *t, u32 x)                /* the same at twice the size: 10 x 14 pixels in a 12-pixel cell, 10 characters from x = 4 */
{
    u32 ci, w, g, v = 0, i;
    if (x < 4) return 0;
    ci = (x - 4) / 12; w = (x - 4) % 12;
    if (ci >= 10 || w >= 10 || !t[ci]) return 0;
    g = glyph(t[ci])[w >> 1];
    for (i = 0; i < 7; i++) if ((g >> i) & 1) v |= 3u << (2 * i);
    return v;
}
static const char *txt(u32 id) { return (const char *)(TXT_ADDR + id * 16); }

static u32 col_msg(const struct state *s, u32 x)          /* a message: title, detail line, optional bar */
{
    u32 m = title_col(s->mt, x) << 1 | text_col(s->md, 21, x, 4) << 17;
    if (s->dbar != 0xFF) m |= (u32)bar_col(x, s->dbar) << 24;
    return m;
}
static u32 col_idle(const struct state *s, u32 x)         /* the idle screen: the firmware's name and version, then a status line */
{
    return title_col(txt(T_EXNAME), x) << 1 | (s->vd[0] ? text_col(s->vd, 21, x, 4) : text_col(txt(T_VER), 15, x, 4)) << 17 | text_col(s->vs, 21, x, 4) << 25;
}

/* One half of the picture straight into the stock staging buffer. Bytes are inverted at the end: a lit pixel is a cleared bit. */
static u32 col_view(const struct state *s, u32 x);        /* the picture behind the messages (idle screen; the sequencer grid when it is there) */
static void render_half(struct state *s, u32 half, u32 msg)
{
    volatile u8 *d = DISP_DATA;
    u32 x;
    for (x = 0; x < 128; x++) {
        u32 m = msg ? col_msg(s, x) : col_view(s, x);
        m >>= 16 * half;
        d[x] = (u8)~m; d[128 + x] = (u8)~(m >> 8);
    }
}

/* Hands one half (pages 2h, 2h+1) to the stock display code if it is idle: 1 if done. The USB interrupt (SysEx display region) fills the same
 * buffer, so this runs with interrupts off; it is short (about 150 us). */
static u32 disp_write(struct state *s, u32 half, u32 msg)
{
    u32 ok = 0, pm;
    __asm__ volatile("mrs %0, primask\n\tcpsid i" : "=r"(pm) :: "memory");
    if (!DISP_FLAG && !DISP_BUSY) {
        render_half(s, half, msg);
        DISP_HDR[0] = 0; DISP_HDR[1] = 0; DISP_HDR[2] = (u8)(half * 2); DISP_HDR[3] = 0;
        DISP_HDR[4] = 128; DISP_HDR[5] = 0; DISP_HDR[6] = 2; DISP_HDR[7] = 0;
        DISP_FLAG = 1; ok = 1;
    }
    __asm__ volatile("msr primask, %0" :: "r"(pm) : "memory");
    return ok;
}

static void notes_tick(struct state *s);                  /* which notes the idle screen shows now */
static void view_notes(struct state *s);
static void view_build(struct state *s);                  /* the status / top line of the picture behind the messages */
static u32 view_sig(const struct state *s);               /* everything that picture shows, in one number */

/* Main loop: moves a message through its stages, then draws the picture behind it again; draws that picture when what it shows changed. */
static void disp_tick(struct state *s)
{
    u16 now = MS16;
    u32 sig = view_sig(s);
    notes_tick(s);
    if (sig != s->vsig) { s->vsig = sig; s->vdirty = 1; }
    switch (s->dstate) {
    case D_IDLE: if (s->vdirty) { s->vdirty = 0; view_build(s); s->dstate = D_VIEW0; } break;
    case D_MSG0: if (disp_write(s, 0, 1)) s->dstate = D_MSG1; break;
    case D_MSG1: if (disp_write(s, 1, 1)) { s->dstate = D_SHOW; s->dt0 = now; } break;
    case D_SHOW: if ((u16)(now - s->dt0) >= MSG_MS) { s->vdirty = 0; view_build(s); s->dstate = D_VIEW0; } break;
    case D_VIEW0: if (disp_write(s, 0, 0)) s->dstate = D_VIEW1; break;
    case D_VIEW1: if (disp_write(s, 1, 0)) s->dstate = D_IDLE; break;
    }
}

static void m_begin(struct state *s, u32 title)           /* a new message: the title, no detail yet */
{
    u32 k;
    for (k = 0; k < sizeof s->mt; k++) s->mt[k] = 0;
    for (k = 0; k < sizeof s->md; k++) s->md[k] = 0;
    s->dbar = 0xFF;
    tx(s->mt, 0, title, 10);
}
static void m_show(struct state *s)                       /* ... ready: (re)start showing it */
{
    s->dstate = D_MSG0;
}

static u32 scale_mask(const struct state *s, u32 chord)    /* the 12-bit mask of the scale in use (chords on the chromatic scale are built on the major scale) */
{
    u32 m = SCALES[s->scale >= SCALE_N ? 0 : s->scale];
    return (chord && m == 0xFFF) ? SCALES[1] : m;
}
static int scale_note(u32 mask, u32 degree)                /* semitones above the root of scale degree `degree` (the octaves continue) */
{
    u32 n = 0, i, k = 0, idx;
    for (i = 0; i < 12; i++) n += (mask >> i) & 1;
    idx = degree % n;
    for (i = 0; i < 12; i++) if ((mask >> i) & 1) { if (k++ == idx) return (int)(degree / n * 12 + i); }
    return 0;
}
__attribute__((optnone, noinline)) static u32 chord_def(u32 type)                             /* count in bits 0-3, then the scale-degree offset of each note in 4-bit steps (optnone: the optimiser would turn these cases into a lookup table in .rodata) */
{
    if (type == 1) return 0x64204;                         /* seventh: 1 3 5 7 */
    if (type == 2) return 0x4103;                          /* sus2: 1 2 5 */
    if (type == 3) return 0x4303;                          /* sus4: 1 4 5 */
    if (type == 4) return 0x402;                           /* power: 1 5 */
    return 0x4203;                                         /* triad: 1 3 5 */
}
static u8 clampnote(int n) { return (u8)(n < 0 ? 0 : n > 127 ? 127 : n); }

static int pad1_note(struct state *s, const struct cfg *c)    /* the lowest pad's note in the current mode, with the transposition */
{
    return (s->padmode ? c->keys_root : c->pad_note[12] + 16 * s->page) + s->transpose;
}

static void announce_pads(struct state *s, const struct cfg *c)
{
    char *b = s->md;
    u32 p = 0;
    int lo = pad1_note(s, c), hi = lo + scale_note(scale_mask(s, 0), 15);
    m_begin(s, s->padmode == 2 ? T_CHORDS : s->padmode ? T_KEYBOARD : T_PADMODE);
    if (s->padmode == 2) {
        p = tx(b, p, T_TRIAD + s->ctype, 21); p = tc(b, p, ' ', 21); p = tc(b, p, ' ', 21); tnote(b, p, lo, 21);
        m_show(s);
        return;
    }
    if (!s->padmode) {
        p = tx(b, p, T_GROUP, 21); p = tc(b, p, ' ', 21); p = tc(b, p, ' ', 21);
        hi = c->pad_note[3] + s->transpose + 16 * s->page;
    }
    p = tnote(b, p, lo, 21); p = tc(b, p, '-', 21); tnote(b, p, hi, 21);
    m_show(s);
}

static void announce_scale(struct state *s, const struct cfg *c)
{
    u32 p;
    m_begin(s, T_SCALE);
    p = tx(s->md, 0, T_SCALE0 + (s->scale >= SCALE_N ? 0 : s->scale), 21);
    p = tc(s->md, p, ' ', 21); p = tc(s->md, p, ' ', 21); tnote(s->md, p, pad1_note(s, c), 21);
    m_show(s);
}

static void announce_chord(struct state *s)
{
    m_begin(s, T_CHORD);
    tx(s->md, 0, T_TRIAD + s->ctype, 21);
    m_show(s);
}

static void announce_strip(struct state *s)
{
    m_begin(s, T_STRIP);
    tx(s->md, 0, s->strip_mode == 1 ? T_PITCH : s->strip_mode == 2 ? T_MOD : s->strip_mode == 3 ? T_STRUM : T_NORMAL, 21);
    m_show(s);
}

static void announce_enc(struct state *s, u32 cc, u32 val)
{
    u32 p;
    m_begin(s, T_CC);
    p = tc(s->mt, 2, ' ', 10); tn(s->mt, p, cc, 10);
    p = tx(s->md, 0, T_VALUE, 21); p = tc(s->md, p, ' ', 21); tn(s->md, p, val, 21);
    s->dbar = (u8)(val * 118 / 127);
    m_show(s);
}

static void announce_program(struct state *s)
{
    u32 p;
    m_begin(s, T_PROGRAM);
    p = tx(s->md, 0, T_PC, 21); p = tc(s->md, p, ' ', 21); tn(s->md, p, s->prog, 21);
    m_show(s);
}

static void announce_toggle(struct state *s, const struct cfg *c, u32 title, u8 on, u32 vel)
{
    u32 p;
    m_begin(s, title);
    p = tx(s->md, 0, on ? T_ON : T_OFF, 21);
    if (on) {
        p = tc(s->md, p, ' ', 21); p = tc(s->md, p, ' ', 21);
        if (vel) { p = tn(s->md, p, vel, 21); s->dbar = (u8)(vel * 118 / 127); }
        else { p = tn(s->md, p, 8, 21); p = tc(s->md, p, '-', 21); tn(s->md, p, 127, 21); }
    }
    (void)c;
    m_show(s);
}

static void announce_transpose(struct state *s, const struct cfg *c)
{
    char *b = s->md;
    u32 p;
    int t = s->transpose;
    m_begin(s, T_TRANSPOSE);
    p = tx(b, 0, s->padmode ? T_ROOT : T_BASE, 21);
    p = tc(b, p, ' ', 21); p = tnote(b, p, pad1_note(s, c), 21); p = tc(b, p, ' ', 21); p = tc(b, p, ' ', 21);
    p = tc(b, p, t < 0 ? '-' : '+', 21); tn(b, p, (u32)(t < 0 ? -t : t), 21);
    m_show(s);
}

static void announce_curve(struct state *s, const struct cfg *c)
{
    m_begin(s, T_VELOCITY);
    tx(s->md, 0, T_CURVE0 + (c->vel_curve > 8 ? 3 : c->vel_curve), 21);
    m_show(s);
}

static u8 mode_state(const struct state *s, u8 act)       /* 0 the mode is off, 1 on, 2 this action is not a mode (if-chains: no switch tables) */
{
    if (act == ACT_PADMODE) return !s->padmode;
    if (act == ACT_KEYS) return s->padmode == 1;
    if (act == ACT_CHORDS) return s->padmode == 2;
    if (act == ACT_FIXVEL) return s->fixed;
    if (act == ACT_VEL16) return s->vel16;
    if (act == ACT_ARP) return s->arp_on;
    if (act == ACT_LATCH) return s->latch;
    if (act == ACT_CLOCKOUT) return s->clock_out;
    if (act == ACT_STEP) return s->padmode == 3;
    if (act == ACT_MUTE) return s->padfn == 1;
    if (act == ACT_SOLO) return s->padfn == 2;
    return 2;
}
static u8 mode_state2(const struct state *s, u8 act, u8 par)    /* the same for the actions whose state depends on the parameter */
{
    if (act == ACT_STRIP) return s->strip_mode == par;
    if (act == ACT_ENCTGT) return s->enc_tgt == par + 1;
    if (act == ACT_SEQRUN) return par == 0 ? s->seq_on : 2;
    return mode_state(s, act);
}

/* The buttons that select a mode show it: lit while their mode is on (in either layer), else at rest. Fills the shadow only. */
static void mode_leds(struct state *s)
{
    const struct cfg *c = s->cfgp;
    u32 k;
    for (k = 0; k < 39; k++) {
        u8 a = mode_state2(s, c->btn_act[k], c->btn_cc[k]), b = mode_state2(s, c->btn_act2[k], c->btn_cc2[k]);
        if (a == 2 && b == 2) continue;
        s->base[k] = s->led[k] = (a == 1 || b == 1) ? c->btn_led_on : (c->led_flags & LF_BTN_IDLE) ? c->btn_led_idle : 0;
        s->lit = 1;
    }
}

static u8 padnum(u8 idx) { return (u8)((3 - (idx >> 2)) * 4 + (idx & 3)); }    /* the pad printed n + 1 <-> its report index (the mapping is its own inverse): 0 = pad 1 ... 15 = pad 16 */

__attribute__((optnone, noinline)) static u32 rate_pulses(u32 r)   /* MIDI clock pulses (24 per beat) in one step: 1/4 1/8 1/8T 1/16 1/16T 1/32 1/32T (optnone: no lookup table) */
{
    if (r == 0) return 24;
    if (r == 1) return 12;
    if (r == 2) return 8;
    if (r == 3) return 6;
    if (r == 4) return 4;
    if (r == 5) return 3;
    return 2;
}

static void arp_add(struct state *s, u8 note, u8 vel, u8 pad)
{
    u32 k;
    if (s->ann >= 16) return;
    for (k = 0; k < s->ann; k++) if (s->an[k] == note && s->ap[k] == pad) return;
    s->an[s->ann] = note; s->av[s->ann] = vel; s->ap[s->ann] = pad; s->ann++;
}
static void arp_drop_pad(struct state *s, u8 pad)
{
    u32 k, j = 0;
    for (k = 0; k < s->ann; k++) if (s->ap[k] != pad) { s->an[j] = s->an[k]; s->av[j] = s->av[k]; s->ap[j] = s->ap[k]; j++; }
    s->ann = (u8)j;
}

static u32 pad_audible(const struct state *s, u32 pad)     /* muted pads and (while any pad is soloed) the others are silent */
{
    return !((s->mute >> pad) & 1) && (!s->solo || ((s->solo >> pad) & 1));
}
static u8 pad_rest(const struct state *s, const struct cfg *c, u32 pad)   /* a pad's resting LED: dim colour, dark when silent, brighter when soloed */
{
    if ((s->solo >> pad) & 1) return pad_code(c, 2);
    return pad_audible(s, pad) ? pad_code(c, 1) : 0;
}
/* The step sequencer on the pad LEDs: pad n shows step n of the selected track (dim = off, colour = on, bright = accent), the playhead in white. */
static void seq_leds(struct state *s)
{
    const struct cfg *c = s->cfgp;
    u32 k, v = s->pat[s->seq_pat][s->seq_trk];
    for (k = 0; k < 16; k++) {
        u32 st = (v >> (2 * k)) & 3, li = c->pad_led[padnum((u8)k)];
        if (li >= 80) continue;
        s->base[li] = s->led[li] = pad_code(c, st == 2 ? 3 : st == 1 ? 2 : 0);
        if (s->seq_on && s->seq_cur == k) s->led[li] = (u8)((17 << 2) | 3);
    }
    s->seq_led = 1; s->lit = 1;
}
static void pad_leds(struct state *s)                      /* fills the shadow only */
{
    const struct cfg *c = s->cfgp;
    u32 k;
    if (s->padmode == 3) { seq_leds(s); return; }
    if (!(c->led_flags & LF_PAD_IDLE) && !s->seq_led) return;
    for (k = 0; k < 16; k++) if (c->pad_led[k] < 80) s->base[c->pad_led[k]] = s->led[c->pad_led[k]] = (c->led_flags & LF_PAD_IDLE) ? pad_rest(s, c, k) : 0;
    s->seq_led = 0; s->lit = 1;
}

static void announce_onoff(struct state *s, u32 title, u32 on)
{
    m_begin(s, title);
    tx(s->md, 0, on ? T_ON : T_OFF, 21);
    m_show(s);
}
static void announce_arp(struct state *s)                  /* ARP / ON  UP  1/16 */
{
    u32 p;
    m_begin(s, T_ARP);
    p = tx(s->md, 0, s->arp_on ? T_ON : T_OFF, 21);
    if (s->arp_on) {
        p = tc(s->md, p, ' ', 21); p = tc(s->md, p, ' ', 21); p = tx(s->md, p, T_AT0 + s->arp_type, 21);
        p = tc(s->md, p, ' ', 21); tx(s->md, p, T_RATE0 + s->arp_rate, 21);
    }
    m_show(s);
}
static void announce_text(struct state *s, u32 title, u32 detail)
{
    m_begin(s, title);
    tx(s->md, 0, detail, 21);
    m_show(s);
}
static void announce_tempo(struct state *s)
{
    u32 p;
    m_begin(s, s->ext_active ? T_EXT : T_TEMPO);
    if (!s->ext_active) {
        p = tn(s->md, 0, s->bpm, 21); p = tc(s->md, p, ' ', 21); tx(s->md, p, T_BPM, 21);
        s->dbar = (u8)((s->bpm - 20u) * 118 / 255);
    }
    m_show(s);
}

/* Tap tempo: the average of the last three taps (a pause of two seconds starts a new run). */
static void tap_tempo(struct state *s)
{
    u16 t = MS16;
    if (s->tap_n && (u16)(t - s->tap_last) > 2000) s->tap_n = 0;
    if (s->tap_n && !s->ext_active) {
        u32 k, sum = 0, cnt = s->tap_n < 3 ? s->tap_n : 3, bpm;
        s->tap_iv[2] = s->tap_iv[1]; s->tap_iv[1] = s->tap_iv[0]; s->tap_iv[0] = (u16)(t - s->tap_last);
        for (k = 0; k < cnt; k++) sum += s->tap_iv[k];
        bpm = 60000u * cnt / (sum ? sum : 1);
        s->bpm = (u16)(bpm < 20 ? 20 : bpm > 275 ? 275 : bpm);
    }
    s->tap_last = t;
    if (s->tap_n < 250) s->tap_n++;
    announce_tempo(s);
}

static void announce_track(struct state *s, const struct cfg *c)    /* STEP / TRK 3 C1 PAT 1 */
{
    u32 p;
    m_begin(s, T_STEP);
    p = tx(s->md, 0, T_TRK, 21); p = tc(s->md, p, ' ', 21); p = tn(s->md, p, s->seq_trk + 1u, 21); p = tc(s->md, p, ' ', 21);
    p = tnote(s->md, p, c->pad_note[padnum(s->seq_trk)], 21); p = tc(s->md, p, ' ', 21);
    p = tx(s->md, p, T_PAT, 21); p = tc(s->md, p, ' ', 21); tn(s->md, p, s->seq_pat + 1u, 21);
    m_show(s);
}
/* A pad hit in step mode: with a Select button held it picks the track, else it steps the step through off, normal, accent. */
static void seq_pad(struct state *s, const struct cfg *c, u8 pad)
{
    u32 step = padnum(pad), v;
    if (s->seq_sel) { s->seq_trk = (u8)step; announce_track(s, c); }
    else {
        v = s->pat[s->seq_pat][s->seq_trk];
        v = (v & ~(3u << (2 * step))) | (((((v >> (2 * step)) & 3) + 1) % 3) << (2 * step));
        s->pat[s->seq_pat][s->seq_trk] = v; s->seq_dirty = 1;
    }
    s->vgen++; seq_leds(s);
}

/* ---- the picture behind the messages ---- */
/* The notes sounding now, from every source: the pads held (a chord pad has up to 4), what the arp, the sequencer and the strip have sounding. Bit n of nb[n >> 5]. */
static void note_set(u32 *nb, u32 n) { nb[n >> 5] |= 1u << (n & 31); }
static void sounding(const struct state *s, const struct cfg *c, u32 *nb)
{
    u32 k, j;
    nb[0] = nb[1] = nb[2] = nb[3] = 0;
    for (k = 0; k < 16; k++) if ((s->held >> k) & 1) for (j = 0; j < s->cnn[k]; j++) note_set(nb, s->cn[k][j] & 127u);       /* (a pad held through the arp has no notes of its own) */
    for (k = 0; k < s->sonn && k < 16; k++) note_set(nb, s->son[k] & 127u);
    for (k = 0; k < 16; k++) if ((s->seq_son >> k) & 1) note_set(nb, c->pad_note[padnum((u8)k)] & 127u);
    if (s->strum) note_set(nb, (u32)(s->strum - 1) & 127u);
}
/* Keeps s->vnotes = the notes to show: the sounding ones as they change, and the last ones for NOTE_HOLD_MS after the last of them stopped. */
static void notes_tick(struct state *s)
{
    u32 nb[4], k, any = 0, same = 1;
    sounding(s, s->cfgp, nb);
    for (k = 0; k < 4; k++) { any |= nb[k]; same &= nb[k] == s->vnotes[k]; }
    if (any) {
        s->nt_on = 0;
        if (!same) { for (k = 0; k < 4; k++) s->vnotes[k] = nb[k]; s->vdirty = 1; }
    } else if (s->vnotes[0] | s->vnotes[1] | s->vnotes[2] | s->vnotes[3]) {
        if (!s->nt_on) { s->nt_on = 1; s->nt0 = MS16; }
        else if ((u16)(MS16 - s->nt0) >= NOTE_HOLD_MS) { for (k = 0; k < 4; k++) s->vnotes[k] = 0; s->nt_on = 0; s->vdirty = 1; }
    }
}
static void view_notes(struct state *s)                   /* the detail line of the idle screen: the note names, lowest first; with more than 5 the first 4 and "+n" */
{
    u32 n, p = 0, shown = 0, total = 0;
    for (n = 0; n < 128; n++) total += (s->vnotes[n >> 5] >> (n & 31)) & 1;
    for (n = 0; n < sizeof s->vd; n++) s->vd[n] = 0;
    for (n = 0; n < 128 && total; n++) {
        if (!((s->vnotes[n >> 5] >> (n & 31)) & 1)) continue;
        if (total > 5 && shown == 4) { p = tc(s->vd, p, ' ', 21); p = tc(s->vd, p, '+', 21); tn(s->vd, p, total - 4, 21); break; }
        if (shown) p = tc(s->vd, p, ' ', 21);
        p = tnote(s->vd, p, (int)n, 21); shown++;
    }
}

static u32 view_sig(const struct state *s)
{
    u32 v = (u32)s->padmode | (u32)(s->cfgp->channel & 15) << 2 | (u32)s->arp_on << 6 | (u32)s->clock_out << 7 | (u32)s->bpm << 8;
    if (s->padmode == 3 || s->seq_on) v |= (u32)s->seq_cur << 17 | (u32)s->seq_trk << 22 | (u32)s->seq_pat << 26 | (u32)s->seq_on << 28 | (u32)(s->vgen & 7) << 29;
    return v;
}
static void view_build(struct state *s)                   /* the status line of the idle screen / the top line of the sequencer grid */
{
    const struct cfg *c = s->cfgp;
    u32 p, k;
    for (k = 0; k < sizeof s->vs; k++) s->vs[k] = 0;
    if (s->padmode == 3) {
        p = tx(s->vs, 0, T_TRK, 21); p = tc(s->vs, p, ' ', 21); p = tn(s->vs, p, s->seq_trk + 1u, 21); p = tc(s->vs, p, ' ', 21);
        p = tnote(s->vs, p, c->pad_note[padnum(s->seq_trk)], 21); p = tc(s->vs, p, ' ', 21);
        p = tx(s->vs, p, T_PAT, 21); p = tc(s->vs, p, ' ', 21); p = tn(s->vs, p, s->seq_pat + 1u, 21);
        if (s->seq_on) { p = tc(s->vs, p, ' ', 21); tx(s->vs, p, T_RUN, 21); }
        return;
    }
    view_notes(s);
    p = tx(s->vs, 0, T_M0 + (s->padmode > 2 ? 0 : s->padmode), 21); p = tc(s->vs, p, ' ', 21);
    p = tx(s->vs, p, T_CH, 21); p = tn(s->vs, p, (u32)(c->channel & 15) + 1, 21); p = tc(s->vs, p, ' ', 21); p = tn(s->vs, p, s->bpm, 21);
    if (s->arp_on) { p = tc(s->vs, p, ' ', 21); p = tx(s->vs, p, T_ARP, 21); }
    if (s->clock_out) { p = tc(s->vs, p, ' ', 21); p = tx(s->vs, p, T_CLK, 21); }
    if (s->seq_on) { p = tc(s->vs, p, ' ', 21); tx(s->vs, p, T_SEQ, 21); }
}
static u32 col_seq(const struct state *s, u32 x)           /* the sequencer grid: 16 cells of 8 pixels (off: a small bar, on: tall, accent: taller), the playhead below, beat marks */
{
    u32 step = x >> 3, c = x & 7, st = (s->pat[s->seq_pat][s->seq_trk] >> (2 * step)) & 3, m = text_col(s->vs, 21, x, 4) << 1;
    if (c >= 1 && c <= 6) m |= st == 2 ? 0x3FFFu << 9 : st == 1 ? 0x3FFu << 11 : 3u << 14;
    if (s->seq_on && s->seq_cur == step) m |= 7u << 25;
    else if (!(step & 3) && (c == 3 || c == 4)) m |= 3u << 29;
    return m;
}
static u32 col_view(const struct state *s, u32 x) { return s->padmode == 3 ? col_seq(s, x) : col_idle(s, x); }

/* The mod wheel value as a bar on the 25 strip LEDs (dim); the finger LED is put back on top. Fills the shadow only. */
static void strip_bar(struct state *s)
{
    const struct cfg *c = s->cfgp;
    u32 k, n = s->strip_mode == 2 ? (s->mod_val * 25u + 126) / 127 : 0;
    u8 code = (u8)(((c->strip_colour ? c->strip_colour : 17) << 2) | 1);
    if (s->strip_mode != 2 && !s->bar_on) return;
    for (k = 0; k < 25; k++) s->base[STRIP_LED0 + k] = s->led[STRIP_LED0 + k] = k < n ? code : 0;
    s->bar_on = s->strip_mode == 2;
    if (s->strip_led) s->led[s->strip_led - 1] = strip_code(c);
    s->lit = 1;
}

/* A button with one of the controller's own actions went down. */
static void mode_action(struct state *s, const struct cfg *c, u8 act, u8 par)
{
    if (act == ACT_PADMODE || act == ACT_KEYS || act == ACT_CHORDS) {
        s->padmode = act == ACT_KEYS ? 1 : act == ACT_CHORDS ? 2 : 0; pad_leds(s); announce_pads(s, c);
    } else if (act == ACT_SCALE) {
        if (!s->padmode || s->padmode == 3) s->padmode = 1;
        pad_leds(s);
        s->scale = (u8)(par == 1 ? (s->scale ? s->scale - 1 : SCALE_N - 1) : (s->scale + 1 >= SCALE_N ? 0 : s->scale + 1));
        announce_scale(s, c);
    } else if (act == ACT_CHORDTYPE) {
        s->ctype = (u8)(par == 1 ? (s->ctype ? s->ctype - 1 : 4) : (s->ctype >= 4 ? 0 : s->ctype + 1));
        announce_chord(s);
    } else if (act == ACT_STRIP) {
        if (s->strum) { s->strum_off = s->strum; s->strum = 0; }
        s->strip_mode = par > 3 ? 0 : par; strip_bar(s); announce_strip(s);
    } else if (act == ACT_ENCTGT) {
        u32 t = par < 3 ? par + 1u : 0;
        s->enc_tgt = (u8)(s->enc_tgt == t ? 0 : t);
        m_begin(s, T_CC);
        if (s->enc_tgt && tgt_cc(c, s->enc_tgt - 1u, s->enc_page) != 0xFF) { u32 p = tc(s->mt, 2, ' ', 10); tn(s->mt, p, tgt_cc(c, s->enc_tgt - 1u, s->enc_page), 10); tx(s->md, 0, T_ENCODER, 21); }
        else { s->mt[0] = 0; tx(s->mt, 0, T_ENCODER, 10); tx(s->md, 0, s->enc_tgt ? T_OFF : T_NORMAL, 21); }
        m_show(s);
    } else if (act == ACT_STEP) {
        s->padmode = s->padmode == 3 ? 0 : 3; pad_leds(s); s->vgen++;
        if (s->padmode == 3) announce_track(s, c); else announce_pads(s, c);
    } else if (act == ACT_SEQRUN) {
        if (par == 1) { s->seq_pos = 0; }
        else {
            s->seq_on = !s->seq_on; s->seq_pos = 0; s->seq_cur = 16;
            if (s->seq_on && !s->ext_active && !s->clock_out && !(s->arp_on && s->ann)) s->seq_kick = 1;     /* no grid running: it starts with the sequencer */
            announce_text(s, T_SEQ, s->seq_on ? T_RUN : T_STOP);
        }
        pad_leds(s);
    } else if (act == ACT_SEQPAT) {
        s->seq_pat = (u8)(par == 1 ? (s->seq_pat ? s->seq_pat - 1 : 3) : (s->seq_pat >= 3 ? 0 : s->seq_pat + 1));
        m_begin(s, T_PATTERN); tn(s->md, 0, s->seq_pat + 1u, 21); m_show(s);
        s->vgen++; pad_leds(s);
    } else if (act == ACT_SEQCLEAR) {
        u32 k;
        if (par == 1) for (k = 0; k < 16; k++) s->pat[s->seq_pat][k] = 0; else s->pat[s->seq_pat][s->seq_trk] = 0;
        s->seq_dirty = 1; s->vgen++; pad_leds(s);
        announce_text(s, T_CLEAR, par == 1 ? T_PATTERN : T_TRACK);
    } else if (act == ACT_SEQSAVE) {
        s->seq_save = 1;                                  /* flash work: left to the main loop */
        return;
    } else if (act == ACT_PAGE) {
        u32 p;
        s->page = (u8)(par == 2 ? 0 : par == 1 ? (s->page ? s->page - 1 : 7) : (s->page >= 7 ? 0 : s->page + 1));
        m_begin(s, T_PAGE);
        p = tn(s->md, 0, s->page + 1u, 21); p = tc(s->md, p, '/', 21); p = tn(s->md, p, 8, 21); p = tc(s->md, p, ' ', 21); p = tc(s->md, p, ' ', 21);
        p = tnote(s->md, p, c->pad_note[12] + s->transpose + 16 * s->page, 21); p = tc(s->md, p, '-', 21); tnote(s->md, p, c->pad_note[3] + s->transpose + 16 * s->page, 21);
        m_show(s);
    } else if (act == ACT_ENCPAGE) {
        u32 n = c->enc_pages ? c->enc_pages : 1, p, t;
        s->enc_page = (u8)(par == 2 ? 0 : par == 1 ? (s->enc_page ? s->enc_page - 1 : n - 1) : (s->enc_page + 1u >= n ? 0 : s->enc_page + 1));
        m_begin(s, T_ENCPAGE);
        p = tn(s->md, 0, s->enc_page + 1u, 21); p = tc(s->md, p, '/', 21); p = tn(s->md, p, n, 21); p = tc(s->md, p, ' ', 21); p = tc(s->md, p, ' ', 21);
        p = tx(s->md, p, T_CC, 21); p = tc(s->md, p, ' ', 21);
        for (t = 0; t < 3; t++) {
            u8 cc = tgt_cc(c, t, s->enc_page);
            if (cc == 0xFF) p = tc(s->md, p, '-', 21); else p = tn(s->md, p, cc, 21);
            if (t < 2) p = tc(s->md, p, ' ', 21);
        }
        m_show(s);
    } else if (act == ACT_TAP) {
        tap_tempo(s);
    } else if (act == ACT_ARP) {
        s->arp_on = !s->arp_on; s->parp = 0;
        if (!s->arp_on) s->ann = 0;                       /* the tick releases what is sounding */
        announce_arp(s);
    } else if (act == ACT_ARPTYPE) {
        s->arp_type = (u8)(par == 1 ? (s->arp_type ? s->arp_type - 1 : 5) : (s->arp_type >= 5 ? 0 : s->arp_type + 1));
        s->astep = 0; announce_text(s, T_ARPTYPE, T_AT0 + s->arp_type);
    } else if (act == ACT_RATE) {
        s->arp_rate = (u8)(par == 1 ? (s->arp_rate ? s->arp_rate - 1 : 6) : (s->arp_rate >= 6 ? 0 : s->arp_rate + 1));
        announce_text(s, T_RATE, T_RATE0 + s->arp_rate);
    } else if (act == ACT_ARPOCT) {
        s->arp_oct = (u8)(s->arp_oct >= 4 ? 1 : s->arp_oct + 1);
        m_begin(s, T_OCT); tn(s->md, 0, s->arp_oct, 21); m_show(s);
    } else if (act == ACT_LATCH) {
        u32 k;
        s->latch = !s->latch;
        if (!s->latch) for (k = 0; k < 16; k++) if (!((s->held >> k) & 1)) arp_drop_pad(s, (u8)k);
        announce_onoff(s, T_LATCH, s->latch);
    } else if (act == ACT_MUTE || act == ACT_SOLO) {
        u8 m = act == ACT_MUTE ? 1 : 2;
        s->padfn = s->padfn == m ? 0 : m;
        announce_onoff(s, act == ACT_MUTE ? T_MUTE : T_SOLO, s->padfn == m);
    } else if (act == ACT_CLEAR) {
        s->mute = s->solo = 0; pad_leds(s);
        announce_text(s, T_MUTE, T_CLEARED);
    } else if (act == ACT_FIXVEL) {
        s->fixed = !s->fixed; if (s->fixed) s->vel16 = 0;
        announce_toggle(s, c, T_FIXVEL, s->fixed, c->fixvel);
    } else if (act == ACT_VEL16) {
        s->vel16 = !s->vel16; if (s->vel16) s->fixed = 0;
        announce_toggle(s, c, T_VEL16, s->vel16, 0);
    } else if (act == ACT_CURVE) {
        u32 n = CURVE_COUNT, cur = c->vel_curve;
        if (n < 2 || n > 9) n = 8;
        cur = par == 1 ? (cur ? cur - 1 : n - 1) : (cur + 1 >= n ? 0 : cur + 1);
        ((struct cfg *)c)->vel_curve = (u8)cur;         /* the active config is a RAM copy */
        s->log_req |= 1;
        announce_curve(s, c);
    } else if (act == ACT_SLOT) {
        s->slot_req = par <= 8 ? (u8)(par + 1) : 0;        /* flash work: left to the main loop */
        return;
    } else if (act == ACT_CHANNEL) {
        u32 k, ch = c->channel & 15;
        ch = par == 1 ? (ch ? ch - 1 : 15) : (ch >= 15 ? 0 : ch + 1);
        ((struct cfg *)c)->channel = (u8)ch;
        s->panic = 32; s->held = 0; s->psent = 0; s->ann = 0; s->sonn = 0; s->parp = 0; s->strum = 0;      /* what sounds on the old channel is released */
        for (k = 0; k < sizeof s->pres; k++) s->pres[k] = 0;
        s->log_req |= 2;
        m_begin(s, T_CHANNEL); tn(s->md, 0, ch + 1, 21); m_show(s);
    } else if (act == ACT_TRANSPOSE) {
        int t = s->transpose + (par == 0xFF ? 0 : (int)par - 64);
        s->transpose = (s8)(t < -64 ? -64 : t > 63 ? 63 : t);
        announce_transpose(s, c);
    } else if (act == ACT_PANIC) {
        u32 k;
        s->panic = 32; s->held = 0; s->psent = 0; s->ann = 0; s->sonn = 0; s->parp = 0; s->strum = 0;
        for (k = 0; k < sizeof s->pres; k++) s->pres[k] = 0;
        m_begin(s, T_PANIC); tx(s->md, 0, T_ALLOFF, 21); m_show(s);
    }
    mode_leds(s);
    led_flush();
}


/* The notes a pad plays now, into out[] (up to 4): its configured note (Group), root + scale degree (Keyboard), the chord on that degree (Chords), or one
 * note for all pads (16 Velocities); transposed. Returns how many. */
static u32 pad_notes_now(struct state *s, const struct cfg *c, u8 pad, u8 *out)
{
    u32 k, n = 1, deg = padnum(pad);
    int root = c->keys_root + s->transpose;
    if (s->vel16) out[0] = clampnote(s->padmode ? root : c->pad_note[12] + s->transpose + 16 * s->page);
    else if (s->padmode == 2) {
        u32 v = chord_def(s->ctype), m = scale_mask(s, 1);
        n = v & 15;
        for (k = 0; k < n; k++) out[k] = clampnote(root + scale_note(m, deg + ((v >> (4 + 4 * k)) & 15)));
    }
    else if (s->padmode) out[0] = clampnote(root + scale_note(scale_mask(s, 0), deg));
    else out[0] = clampnote(c->pad_note[pad] + s->transpose + 16 * s->page);
    return n;
}

static u8 hit_velocity(struct state *s, const struct cfg *c, u8 pad, u32 val)
{
    if (s->vel16) return clamp7((padnum(pad) + 1u) * 8, 1);
    if (s->fixed) return clamp7(c->fixvel, 1);
    return velocity(val, c->vel_shift, c->vel_curve);
}

/* The notes the strip strums, ascending: those of the pads held now, else the first note of every pad (the current mode's). At most 16. */
static u32 strum_notes(struct state *s, const struct cfg *c, u8 *out)
{
    u32 n = 0, p, j, k;
    u8 tmp[4];
    for (p = 0; p < 16 && n < 16; p++) {
        if ((s->held >> p) & 1) { for (j = 0; j < s->cnn[p] && n < 16; j++) out[n++] = s->cn[p][j]; if (!s->cnn[p] && n < 16) out[n++] = s->cn[p][0]; }
    }
    if (!n) for (p = 0; p < 16; p++) { pad_notes_now(s, c, (u8)p, tmp); out[n++] = tmp[0]; }
    for (j = 1; j < n; j++) { u8 v = out[j]; for (k = j; k > 0 && out[k - 1] > v; k--) out[k] = out[k - 1]; out[k] = v; }
    return n;
}

/* A button with a non-CC action changed (press: now = 1). Returns the new write pointer. */
static u8 *button_event(struct state *s, const struct cfg *c, u8 *q, u8 act, u8 par, u8 now)
{
    u8 ch = c->channel & 15;
    if (act == ACT_NOTE) return emit(q, (now ? 0x90 : 0x80) | ch, par, now ? 127 : 0);
    if (act == ACT_SEQSEL) { if (now) { if (s->seq_sel < 255) s->seq_sel++; } else if (s->seq_sel) s->seq_sel--; return q; }
    if (act == ACT_SHIFT) { if (now) { if (s->shift < 255) s->shift++; } else if (s->shift) s->shift--; return q; }
    if (!now) return q;                              /* everything else acts on press only */
    if (act == ACT_CLOCKOUT) {
        s->clock_out = !s->clock_out;
        s->pulse = 0; s->acc_us = 0; s->last_ms = MS16;
        q = emit1(q, s->clock_out ? 0xFA : 0xFC);
        m_begin(s, T_CLOCK);
        if (s->clock_out) { u32 p = tx(s->md, 0, T_ON, 21); p = tc(s->md, p, ' ', 21); p = tc(s->md, p, ' ', 21); p = tn(s->md, p, s->bpm, 21); p = tc(s->md, p, ' ', 21); tx(s->md, p, T_BPM, 21); }
        else tx(s->md, 0, T_OFF, 21);
        m_show(s); mode_leds(s); led_flush();
        return q;
    }
    if (act == ACT_SNAP) {
        u32 k;
        if (par == 1 || !s->snap_have) {
            for (k = 0; k < 3; k++) s->snap[k] = s->tval[s->enc_page][k];
            s->snap_page = s->enc_page; s->snap[3] = s->mod_val; s->snap[4] = s->encabs; s->snap_have = 1;
            announce_text(s, T_LOCK, T_STORED);
        } else {
            for (k = 0; k < 3; k++) { u8 cc = tgt_cc(c, k, s->snap_page); s->tval[s->snap_page][k] = s->snap[k]; if (cc != 0xFF) q = emit(q, 0xB0 | ch, cc, s->snap[k]); }
            s->mod_val = s->snap[3]; q = emit(q, 0xB0 | ch, 1, s->mod_val);
            s->encabs = s->snap[4]; if (c->enc_cc != 0xFF && c->enc_mode == 1) q = emit(q, 0xB0 | ch, c->enc_cc, s->encabs);
            strip_bar(s); led_flush();
            announce_text(s, T_LOCK, T_RECALLED);
        }
        return q;
    }
    if (act == ACT_PROGRAM) {
        s->prog = (u8)(par == 2 ? 0 : par == 1 ? (s->prog ? s->prog - 1 : 127) : (s->prog >= 127 ? 0 : s->prog + 1));
        announce_program(s);
        return emit(q, 0xC0 | ch, s->prog, 0);
    }
    if (act >= ACT_PADMODE) { mode_action(s, c, act, par); return q; }
    return act == ACT_MMC ? emit_mmc(q, par) : emit1(q, act == ACT_START ? 0xFA : act == ACT_CONT ? 0xFB : 0xFC);
}

/* The output buffer is handed to the stock ring whenever less than the worst case of the next item is left (a chord pad event is 8 packets);
 * the stock enqueue copies at once, and its return value is not used by the caller. */
#define ROOM(n) do { if ((u32)(q - s->out) + (n) > sizeof s->out) { ENQUEUE(s->out, (u32)(q - s->out)); q = s->out; } } while (0)

static u32 translate_report(const u8 *buf, u32 len);
u32 mmk3_translate(const u8 *buf, u32 len) { return translate_report(buf, len); }   /* (a global symbol: hal.c calls the static one, no relocation) */
static u32 translate_report(const u8 *buf, u32 len)
{
    struct state *s = state();
    const struct cfg *c = s->cfgp;
    u8 *q = s->out;
    u8 ch = c->channel & 15;
    u8 dirty = 0;                                    /* local LED changes to write out */
    u32 i = 0;

    while (i < len) {
        u8 id = buf[i];
        if (id == 1 && i + 14 <= len) {
            const u8 *r = buf + i + 1;
            u32 k, n;
            u8 touch = r[5] & 1;
            /* Report 1 is sent only when something changes, so the very first one can already be a button press (seen on the real
             * device: the first report after a quiet period was "Project pressed"). Buttons, encoder touch and the strip therefore
             * start from "nothing pressed"; only the encoder counter, whose start value is unknown, takes its baseline from the
             * first report. */
            for (n = 0; n < 82; n++) {                       /* two passes: the Shift buttons first, so a Shift pressed in the same report as another button applies to it */
                u8 now, old;
                k = n % 41;
                if ((c->btn_act[k] == ACT_SHIFT) != (n < 41)) continue;
                ROOM(48);
                now = k < 40 ? (r[k >> 3] >> (k & 7)) & 1 : touch;
                old = k < 40 ? (s->btn[k >> 3] >> (k & 7)) & 1 : s->touch;
                if (now != old) {
                    u8 bit = (u8)(1u << (k & 7)), lay, act, par;
                    if (now) {                       /* a press picks its layer, the release uses the same one */
                        lay = s->shift && btn_defined(c->btn_act2[k], c->btn_cc2[k]);
                        if (lay) s->lay[k >> 3] |= bit; else s->lay[k >> 3] &= (u8)~bit;
                    } else lay = (s->lay[k >> 3] & bit) != 0;
                    act = lay ? c->btn_act2[k] : c->btn_act[k];
                    par = lay ? c->btn_cc2[k] : c->btn_cc[k];
                    if (btn_defined(act, par)) {
                        if (act == ACT_CC) {
                            u8 bm = bmode(c, k);
                            if (bm == 1) {                     /* toggle: alternate 127 / 0 on each press, nothing on release */
                                if (now) {
                                    s->tog[k >> 3] ^= bit;
                                    q = emit(q, 0xB0 | ch, par, (s->tog[k >> 3] & bit) ? 127 : 0);
                                }
                            } else if (bm == 2) {              /* trigger: 127 on press only */
                                if (now) q = emit(q, 0xB0 | ch, par, 127);
                            } else {                           /* gate */
                                q = emit(q, 0xB0 | ch, par, now ? 127 : 0);
                            }
                        } else {
                            q = button_event(s, c, q, act, par, now);
                        }
                        if (k < 39 && (c->led_flags & LF_BTN_PRESS)) {
                            if (act == ACT_CC && bmode(c, k) == 1) {    /* toggle: the LED shows the state */
                                if (now) {
                                    s->base[k] = s->led[k] = (s->tog[k >> 3] & bit) ? c->btn_led_on : c->btn_led_idle;
                                    dirty = 1;
                                }
                            } else {                                    /* momentary: bright while pressed, then back to rest */
                                s->led[k] = now ? c->btn_led_on : s->base[k];
                                dirty = 1;
                            }
                        }
                    }
                }
            }
            if (s->have) {
                /* The 4-bit counter counts UP when the knob is turned clockwise (measured on the real device with a clockwise-only
                 * recording), so the step is (new - old) and clockwise is positive, like NI's engine. */
                u8 d = (r[6] - s->enc) & 15;
                u8 cc = s->enc_tgt ? tgt_cc(c, s->enc_tgt - 1u, s->enc_page) : c->enc_cc;
                ROOM(48);
                if (d && cc != 0xff) {
                    int sd = d < 8 ? (int)d : (int)d - 16;
                    if (c->enc_accel) {                        /* faster turns take bigger steps: |step| * (1 + accel * (|step| - 1)), at most 40 */
                        int a = sd < 0 ? -sd : sd, m = a * (1 + (int)c->enc_accel * (a - 1));
                        sd = sd < 0 ? -(m > 40 ? 40 : m) : (m > 40 ? 40 : m);
                    }
                    if (s->enc_tgt || c->enc_mode == 1) {      /* absolute: the encoder's own value, or that of the target */
                        u8 *pv = s->enc_tgt ? &s->tval[s->enc_page][s->enc_tgt - 1] : &s->encabs;
                        int v = (int)*pv + sd;
                        u8 nv = (u8)(v < 0 ? 0 : v > 127 ? 127 : v);
                        if (nv != *pv) {                       /* like NI's engine: nothing is sent when the limit is hit */
                            *pv = nv;
                            q = emit(q, 0xB0 | ch, cc, nv);
                            if (s->enc_tgt) announce_enc(s, cc, nv);
                        }
                    } else if (c->enc_mode == 2) {
                        q = emit(q, 0xB0 | ch, cc, (u8)(sd > 0 ? sd : 128 + sd));
                    } else {
                        q = emit(q, 0xB0 | ch, cc, (u8)(64 + sd));
                    }
                }
            }
            ROOM(48);
            if (s->strip_mode == 1) {                        /* pitch bend over the whole strip, back to the centre when the finger leaves */
                if (r[9] && r[9] != s->pos) { u32 v = (u32)(r[9] - 1) * 16383 / 199; q = emit(q, 0xE0 | ch, (u8)(v & 127), (u8)(v >> 7)); }
                else if (!r[9] && s->pos) q = emit(q, 0xE0 | ch, 0, 64);
            } else if (s->strip_mode == 2) {                 /* mod wheel: CC 1, keeps its value when the finger leaves, shown as a bar */
                if (r[9] && r[9] != s->pos) {
                    u8 v = clamp7((u32)(r[9] - 1) * 127 / 199, 0);
                    if (v != s->mod_val) { s->mod_val = v; q = emit(q, 0xB0 | ch, 1, v); strip_bar(s); dirty = 1; }
                }
            } else if (s->strip_mode == 3) {                 /* strum: the strip is divided among the notes of the held pads (else of all 16 pads) */
                if (r[9] != s->pos) {
                    u8 nt[16]; u32 n = strum_notes(s, c, nt), zone = r[9] ? (u32)(r[9] - 1) * n / 200 : 0xFF;
                    if (s->strum && (!r[9] || nt[zone] + 1 != s->strum)) { q = emit(q, 0x80 | ch, (u8)(s->strum - 1), 0); s->strum = 0; }
                    if (r[9] && !s->strum) { q = emit(q, 0x90 | ch, nt[zone], 100); s->strum = (u8)(nt[zone] + 1); }
                }
            } else if (c->strip_cc != 0xff) {
                if (r[9] && r[9] != s->pos)
                    q = emit(q, 0xB0 | ch, c->strip_cc, clamp7((u32)(r[9] - 1) * 127 / 199, 0));
                else if (!r[9] && s->pos && (c->flags & 1))
                    q = emit(q, 0xB0 | ch, c->strip_cc, 0);
            }
            if (c->led_flags & LF_STRIP) {                   /* the LED under the finger: positions 1..200 -> 25 LEDs */
                u8 want = r[9] ? (u8)(STRIP_LED0 + (u32)(r[9] - 1) * 25 / 200 + 1) : 0;
                if (want != s->strip_led) {
                    if (s->strip_led) s->led[s->strip_led - 1] = s->base[s->strip_led - 1];
                    if (want) s->led[want - 1] = strip_code(c);
                    s->strip_led = want; dirty = 1;
                }
            }
            for (k = 0; k < 5; k++) s->btn[k] = r[k];
            s->touch = touch;
            s->enc = r[6];
            s->pos = r[9];
            s->have = 1;
            i += 14;
        } else if (id == 2 && i + 64 <= len) {
            const u8 *r = buf + i + 1;
            u32 k;
            for (k = 0; k < 21; k++, r += 3) {
                u8 pad = r[0], type = r[1] >> 4;
                u32 val = ((u32)(r[1] & 15) << 8) | r[2];
                u8 pl, pm = c->press_mode;
                u16 bit;
                if (!pad && !r[1] && !r[2]) break;
                if (pad > 15) continue;
                ROOM(48);
                pl = c->pad_led[pad];
                bit = (u16)(1u << pad);
                switch (type) {
                case 0: case 1: {
                    u8 nb[4], vel = hit_velocity(s, c, pad, val);
                    u32 cnt, j;
                    if (s->padmode == 3) { seq_pad(s, c, pad); dirty = 1; break; }       /* step mode: the pad is a step (or, with Select held, a track) */
                    if (s->padfn) {                              /* mute / solo edit: the hit toggles the pad */
                        u16 *w = s->padfn == 1 ? &s->mute : &s->solo;
                        *w ^= bit; pad_leds(s); dirty = 1;
                        break;
                    }
                    if (!pad_audible(s, pad)) break;
                    cnt = pad_notes_now(s, c, pad, nb);
                    if (s->arp_on) {                             /* the notes go to the arp's list; it plays them in time */
                        if (s->latch && !(s->held & ~bit)) s->ann = 0;       /* a new chord replaces the latched one */
                        if (!s->ann) { s->astep = 0; if (!s->ext_active && !s->clock_out) s->arp_kick = 1; }
                        for (j = 0; j < cnt; j++) arp_add(s, nb[j], vel, pad);
                        s->parp |= bit;
                        s->cn[pad][0] = nb[0]; s->cnn[pad] = 0; s->held |= bit; s->pres[pad] = 0;
                        if ((c->led_flags & LF_PAD_HIT) && pl < 80) { s->led[pl] = pad_code(c, 3); dirty = 1; }
                        break;
                    }
                    if (s->held & bit) for (j = 0; j < s->cnn[pad]; j++) q = emit(q, 0x80 | ch, s->cn[pad][j], 0);
                    for (j = 0; j < cnt; j++) { q = emit(q, 0x90 | ch, nb[j], vel); s->cn[pad][j] = nb[j]; }
                    s->cnn[pad] = (u8)cnt; s->held |= bit; s->pres[pad] = 0;
                    if ((c->led_flags & LF_PAD_HIT) && pl < 80) { s->led[pl] = pad_code(c, 3); dirty = 1; }
                    break;
                }
                case 2: case 3:
                    if (s->held & bit) { u32 j; for (j = 0; j < s->cnn[pad]; j++) q = emit(q, 0x80 | ch, s->cn[pad][j], 0); }
                    if (s->parp & bit) { s->parp &= ~bit; if (!s->latch) arp_drop_pad(s, pad); }
                    s->cnn[pad] = 0;
                    s->held &= ~bit;
                    if (!s->held && s->psent) {                 /* the last pad let go: pressure back to 0 */
                        q = pm == 1 ? emit(q, 0xD0 | ch, 0, 0) : emit(q, 0xB0 | ch, c->press_cc, 0);
                        s->psent = 0;
                    }
                    if ((c->led_flags & LF_PAD_HIT) && pl < 80) { s->led[pl] = s->base[pl]; dirty = 1; }
                    break;
                case 4:
                    if (s->held & bit) {
                        u8 p = clamp7(val >> c->vel_shift, 0);
                        if (p != s->pres[pad] && pm < 3) {
                            s->pres[pad] = p;
                            if (pm == 0) q = emit(q, 0xA0 | ch, s->cn[pad][0], p);
                            else { q = pm == 1 ? emit(q, 0xD0 | ch, p, 0) : emit(q, 0xB0 | ch, c->press_cc, p); s->psent = p != 0; }
                        }
                    }
                    break;
                }
            }
            i += 64;
        } else {
            break;   /* unknown/short report: drop the remainder */
        }
    }
    if (dirty) led_flush();
    if (q != s->out) return ENQUEUE(s->out, (u32)(q - s->out));
    return 0;
}

/* ---- boot hook: replaces `bl 0x08007ea2` at the top of main (0x08008cf8) ---------------- */

/* USB descriptor blobs live in flash at DESC_*_ADDR (see build_patch.py). The firmware keeps
 * {pointer, length} pairs in a RAM table, copied from compressed .data at startup, so we
 * repoint the device and configuration entries here, before USB is enabled. */
#define DESC_TABLE ((volatile u32 *)0x20000080)
#define DESC_DEV_ADDR 0x0800CF20u
#define DESC_CFG_ADDR 0x0800CF40u
#define DESC_CFG_LEN 119u

/* ---- safety: the crash-loop guard (docs/clean-firmware-plan.md, stage 0) ----
 * RAM keeps its content through a reset (not through a power cycle), so the guard counts consecutive watchdog resets there. Three in a row
 * and the device goes into DFU mode instead of starting again; any other reset cause starts the count over, and HEALTHY_MS of normal
 * running clear it. The watchdog is started here, at the patch's first instruction, so that a hang before the stock init starts it (with
 * its own 1 s) also ends in a reset: about 26 s (40 kHz / 256, reload 4095). */
#define RCC_CSR (*(volatile u32 *)0x40021024u)
#define IWDG_KR (*(volatile u32 *)0x40003000u)
#define IWDG_PR (*(volatile u32 *)0x40003004u)
#define IWDG_RLR (*(volatile u32 *)0x40003008u)
#define GUARD ((volatile u32 *)0x20004FF0u)          /* magic, count, ~count, RCC_CSR of this boot (above the state, below the end of RAM) */
#define GUARD_MAGIC 0x47524431u
#define GUARD_LIMIT 3u
#define HEALTHY_MS 10000u
#define ADC_RAW ((const volatile u16 *)0x20000718)
#define CAP_BASE 0x20001C20u                         /* header: magic, frames, frame size, mask; frames from CAP_BASE + 16 */
#define CAP_END 0x200041F0u
#define CAP ((volatile u32 *)CAP_BASE)
#define CAP_MAGIC 0x50414352u
#define BOOT_FLAG (*(volatile u32 *)0x20004FECu)  /* one-shot: the next boot uses our board init (hal.c own_board_init) */
#define BOOT_OWN_INIT 0x4F574E31u
#define BOOT_OWN_USB 0x4F574E32u                  /* ... and our USB stack */
_Static_assert(ST_ADDR + sizeof(struct state) <= 0x20004FC0u, "the state must leave the diagnostics, the boot flag and the guard words alone");

static void guard_boot(void)
{
    u32 csr = RCC_CSR, n;
    RCC_CSR = csr | (1u << 24);                      /* RMVF: the next boot sees only its own cause */
    IWDG_KR = 0x5555u; IWDG_PR = 6; IWDG_RLR = 0xFFFu; IWDG_KR = 0xAAAAu; IWDG_KR = 0xCCCCu;
    n = (GUARD[0] == GUARD_MAGIC && GUARD[2] == ~GUARD[1]) ? GUARD[1] : 0;
    n = (csr & (1u << 29)) ? n + 1 : 0;              /* IWDGRSTF: one more watchdog reset in a row */
    GUARD[0] = GUARD_MAGIC; GUARD[1] = n; GUARD[2] = ~n; GUARD[3] = csr;
    if (n >= GUARD_LIMIT) { GUARD[1] = 0; GUARD[2] = ~0u; enter_dfu(); }
}

/* Replaces main()'s call of the stock watchdog set-up: prescaler / 32, reload 1250 = 1 s, then started (the same values). */
static void iwdg_start(void)
{
    IWDG_KR = 0x5555u; IWDG_PR = 3; IWDG_RLR = 1250; IWDG_KR = 0xAAAAu; IWDG_KR = 0xCCCCu;
}

void mmk3_iwdg_start(void) { iwdg_start(); }
static void init_body(void);
void mmk3_init(void) { init_body(); }
static void init_body(void)
{
    u32 own = BOOT_FLAG == BOOT_OWN_INIT || BOOT_FLAG == BOOT_OWN_USB, own_usb = BOOT_FLAG == BOOT_OWN_USB;
    BOOT_FLAG = 0;                                   /* one-shot: if our init fails, the watchdog reset comes back to the stock one */
    guard_boot();
    state_reset(ST);
    DESC_TABLE[0] = DESC_DEV_ADDR;  DESC_TABLE[1] = 18;
    DESC_TABLE[2] = DESC_CFG_ADDR;  DESC_TABLE[3] = DESC_CFG_LEN;
    if (own) { ST->own_init = 1; ST->own_usb = (u8)own_usb; ST->hal = 0x7F; ST->hal2 = 3; own_board_init(); }     /* a boot of ours: every driver of ours from the start */
    else ((void (*)(void))STOCK(0x08007EA3))(); /* original board/USB init */
}

/* ---- late boot hook: replaces `bl 0x08008bac` in main (stage-2 init: pad sensitivity, LED chips, ...) ---- */
#define BOOT_COUNT (*(volatile u16 *)0x2000102A)    /* struct + 2: startup countdown in ms, set by stage 2 */

/* The resting state: assigned buttons dimly lit, pads in their colour. Only the shadow is filled here: the stock startup (an LED fade-in
 * that ends by clearing every LED) would wipe a frame written now, so mmk3_tick() applies it when the startup is over. */
static void local_led_init(struct state *s, u8 clear)
{
    const struct cfg *c = s->cfgp;
    u32 k;
    if (clear)                                       /* a new config: every LED is commanded off first (0xFF would leave it lit) */
        for (k = 0; k < 80; k++) s->led[k] = s->base[k] = 0;
    s->strip_led = 0;
    if (c->led_flags & LF_BTN_IDLE)
        for (k = 0; k < 39; k++)
            if (btn_has_action(c, k)) s->base[k] = s->led[k] = c->btn_led_idle;
    if (c->led_flags & LF_PAD_IDLE)
        for (k = 0; k < 16; k++)
            if (c->pad_led[k] < 80) s->base[c->pad_led[k]] = s->led[c->pad_led[k]] = pad_rest(s, c, k);
    mode_leds(s);                                    /* the buttons that select a mode show the current one */
    if (clear || (c->led_flags & (LF_BTN_IDLE | LF_PAD_IDLE))) s->lit = 1;
}

static void boot2_body(void);
void mmk3_boot2(void) { boot2_body(); }
static void boot2_body(void)
{
    struct state *s = state();
    const struct cfg *c = s->cfgp;
    if (s->own_init) own_stage2(0, c->boot_ms != 0xFFFF ? c->boot_ms : 300);   /* ours: no logo, no LED animation, 0.3 s */
    else ((void (*)(void))STOCK(0x08008BAD))();            /* stock stage-2 init */
    if (c->sens <= 100) {
        SENS_BYTE = c->sens;
        THRESHOLD();                                 /* threshold = (100 - sens) * 6, the pad states reset */
    }
    if (c->boot_ms != 0xFFFF) BOOT_COUNT = c->boot_ms;
    local_led_init(s, 0);
}

/* ---- run-time configuration ------------------------------------------------------------------------------------------------------
 *
 * The active config is a RAM copy of struct cfg. At boot it is the saved record in flash if there is a valid one, else the build-time
 * defaults. A host edits it with SysEx (F0 7D 4D 4B <cmd> ... F7, see docs/remap-protocol.md):
 *   10 INFO   -> 50 <protocol> <cfg size lo,hi> <flags: 1 saved, 2 unsaved changes, 4 loaded from flash at boot>
 *   11 GET    -> 51 <the active config, 7-bit packed>
 *   12 SET    <config, 7-bit packed>  -> 52 <status> [offset lo, hi]    validated, then active at once (not saved)
 *   13 SAVE   -> 53 <status>          writes the active config to the flash page SAVE_PAGE
 *   14 RESET  [1] -> 54 <status>      back to the defaults; with the argument 1 the saved config is erased as well
 *   1E PEEK   <address, 5 x 7 bits, MSB first> <length 1..64> -> 5E <status> <address> <the bytes, 7-bit packed>
 *             read-only diagnostic: flash, RAM, the chip's ID / flash-size / option-byte registers (see peek_ok); status 0 ok, 1 range
 *             not allowed, 2 bad length
 * status: 0 ok, 1 wrong length, 2 value out of range (followed by the offset of the first bad byte), 3 flash error
 * The USB interrupt only stores a request; everything else (validating, flash, the reply) runs in mmk3_tick() in the main loop, so the
 * flash stalls and the ring buffer see the same context as the rest of the firmware. A new request is ignored while one is pending.
 */
#define PROTO_VERSION 2
#define FW_VERSION 0x00                                 /* Ex-Machina v0 (build_patch.py FW_VERSION; shown on the idle screen, reported by INFO) */

/* Range check of a config block: 0 if it is usable, else 1 + the offset of the first bad byte (the block is never trusted). */
static u32 cfg_check(const struct cfg *c)
{
    u32 i;
    if (c->magic[0] != 'M' || c->magic[1] != 'M' || c->magic[2] != 'K' || c->magic[3] != '3') return 1;
    if (c->channel > 15) return OFS(channel) + 1;
    for (i = 0; i < 16; i++) if (c->pad_note[i] > 127) return OFS(pad_note) + i + 1;
    for (i = 0; i < 48; i++) {
        if (c->btn_cc[i] > 127 && c->btn_cc[i] != 0xFF) return OFS(btn_cc) + i + 1;
        if (c->btn_act[i] > ACT_LAST) return OFS(btn_act) + i + 1;
    }
    if (c->enc_cc > 127 && c->enc_cc != 0xFF) return OFS(enc_cc) + 1;
    if (c->strip_cc > 127 && c->strip_cc != 0xFF) return OFS(strip_cc) + 1;
    if (c->vel_shift < 1 || c->vel_shift > 8) return OFS(vel_shift) + 1;
    if (c->led_channel > 15) return OFS(led_channel) + 1;
    for (i = 0; i < 16; i++) if (c->pad_led[i] >= 80 && c->pad_led[i] != 0xFF) return OFS(pad_led) + i + 1;
    if (c->enc_mode > 2) return OFS(enc_mode) + 1;
    if (c->flags > 1) return OFS(flags) + 1;
    if (c->sens > 100 && c->sens != 0xFF) return OFS(sens) + 1;
    if (c->enc_init > 127) return OFS(enc_init) + 1;
    if (c->btn_mode > 2) return OFS(btn_mode) + 1;
    if (c->led_flags > 31) return OFS(led_flags) + 1;
    if (c->btn_led_idle > 127) return OFS(btn_led_idle) + 1;
    if (c->btn_led_on > 127) return OFS(btn_led_on) + 1;
    if (c->pad_colour > 17) return OFS(pad_colour) + 1;
    if (c->strip_colour > 17) return OFS(strip_colour) + 1;
    if (c->vel_curve > 8) return OFS(vel_curve) + 1;
    if (c->fixvel < 1 || c->fixvel > 127) return OFS(fixvel) + 1;
    if (c->keys_root > 127) return OFS(keys_root) + 1;
    if (c->press_mode > 3) return OFS(press_mode) + 1;
    if (c->press_cc > 127) return OFS(press_cc) + 1;
    for (i = 0; i < 48; i++) {
        if (c->btn_cc2[i] > 127 && c->btn_cc2[i] != 0xFF) return OFS(btn_cc2) + i + 1;
        if (c->btn_act2[i] > ACT_LAST) return OFS(btn_act2) + i + 1;
    }
    if (c->scale >= SCALE_N) return OFS(scale) + 1;
    if (c->chord_type > 4) return OFS(chord_type) + 1;
    for (i = 0; i < 3; i++) if (c->enc_tgt_cc[i] > 127 && c->enc_tgt_cc[i] != 0xFF) return OFS(enc_tgt_cc) + i + 1;
    if (c->arp_type > 5) return OFS(arp_type) + 1;
    if (c->arp_rate > 6) return OFS(arp_rate) + 1;
    if (c->arp_oct < 1 || c->arp_oct > 4) return OFS(arp_oct) + 1;
    if (c->enc_pages < 1 || c->enc_pages > 8) return OFS(enc_pages) + 1;
    if (c->enc_page_step < 1 || c->enc_page_step > 32) return OFS(enc_page_step) + 1;
    if (c->enc_accel > 3) return OFS(enc_accel) + 1;
    return 0;
}

static void copy8(void *dst, const void *src, u32 n)
{
    u8 *d = dst; const u8 *p = src;
    while (n--) *d++ = *p++;
}

static u32 same8(const void *a, const void *b, u32 n)
{
    const u8 *p = a, *q = b;
    while (n--) if (*p++ != *q++) return 0;
    return 1;
}

static u16 crc16(const u8 *p, u32 n)                /* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF */
{
    u16 crc = 0xFFFF;
    u32 k;
    while (n--) {
        crc ^= (u16)(*p++ << 8);
        for (k = 0; k < 8; k++) crc = (crc & 0x8000) ? (u16)((crc << 1) ^ 0x1021) : (u16)(crc << 1);
    }
    return crc;
}

/* ---- the saved record: one page, rewritten completely on every save ----
 * The page is the last 1 KB page of the application area, below the stock settings pages (0x0801F000 and up), which are never
 * touched. A save erases the page and programs the data first and the magic LAST, so a save that is cut short leaves no valid
 * record and the next boot uses the defaults. */
#define SAVE_PAGE 0x0801EC00u
#define SLOT_BASE 0x0801D800u                       /* the four preset slots: one record per page (SLOT_PAGE(n)); the step patterns have a page too */
#define SLOT_PAGE(n) (SLOT_BASE + 0x400u * (n))
#define PAT_PAGE 0x0801E800u
#define REC_MAGIC 0x46434B4Du                       /* "MKCF" little endian: bytes 4D 4B 43 46 */
#define REC_VERSION 1
struct rec {
    u32 magic;
    u16 version, len;
    u16 crc, reserved;
    u8 data[276];                                   /* the config, zero padded to a whole number of words */
};
_Static_assert(sizeof(struct rec) == 288 && sizeof(struct cfg) <= 276, "record layout is mirrored in mmk3_config.py");
#define SAVED ((const struct rec *)SAVE_PAGE)

static void log_apply(struct cfg *c);

/* The run-time modes start fresh: Group, no transpose, no Fixed Vel / 16 Velocities, the scale and chord type of the config, the strip and encoder on their
 * configured CCs, program 0. */
static void mode_reset(struct state *s, const struct cfg *c)
{
    u32 k;
    s->padmode = s->fixed = s->vel16 = 0; s->transpose = 0;
    s->scale = c->scale; s->ctype = c->chord_type;
    s->strip_mode = 0; s->mod_val = 0; s->bar_on = 0; s->enc_tgt = 0; s->prog = 0;
    for (k = 0; k < 24; k++) s->tval[k / 3][k % 3] = 64;
    s->enc_page = 0; s->page = 0;
    s->padfn = 0; s->mute = s->solo = 0;
    s->arp_on = 0; s->ann = 0; s->parp = 0; s->latch = 0; s->clock_out = 0;     /* (what the arp has sounding is released by the tick) */
    s->arp_type = c->arp_type; s->arp_rate = c->arp_rate; s->arp_oct = c->arp_oct; s->bpm = (u16)(c->tempo + 20);
    s->acc_us = 0; s->pulse = 0; s->last_ms = MS16; s->astep = 0; s->arp_kick = 0; s->tap_n = 0;
    if (s->strum) s->strum_off = s->strum;
    s->strum = 0; s->snap_have = 0;
    s->seq_on = 0; s->seq_cur = 16; s->seq_sel = 0; s->seq_kick = 0; s->seq_led = 0;       /* (the patterns stay; what the sequencer has sounding is released by the tick) */
    s->tap_btn = 0xFF;
    for (k = 0; k < 39; k++) if (c->btn_act[k] == ACT_TAP || c->btn_act2[k] == ACT_TAP) { s->tap_btn = (u8)k; break; }
}

/* A record in a flash page (the saved config or a preset slot): rec_ok = it is intact; rec_load = it is, and `out` now holds its config laid over the
 * defaults and range-checked. */
/* Project (button 0, top left) always loads the next preset slot, with and without Shift: whatever a config says, it is set here on every config
 * that enters RAM (the defaults, the saved one, a slot, one from the host), so the way through the slots can never be mapped away. */
#define BTN_PROJECT 0
static void cfg_fixed(struct cfg *c)
{
    c->btn_act[BTN_PROJECT] = ACT_SLOT; c->btn_cc[BTN_PROJECT] = 8;
    c->btn_act2[BTN_PROJECT] = ACT_NONE; c->btn_cc2[BTN_PROJECT] = 0xFF;   /* with Shift: the same */
}

static u32 rec_ok(u32 page)
{
    const struct rec *r = (const struct rec *)page;
    return r->magic == REC_MAGIC && r->version == REC_VERSION && r->len >= 4 && r->len <= sizeof(struct cfg) && crc16(r->data, r->len) == r->crc;
}
static u32 rec_load(u32 page, struct cfg *out)
{
    const struct rec *r = (const struct rec *)page;
    if (!rec_ok(page)) return 0;
    copy8(out, CFG_DEFAULTS, sizeof *out);
    copy8(out, r->data, r->len);                    /* a shorter record (older layout) only overlays the fields it has */
    if (cfg_check(out)) return 0;
    cfg_fixed(out);
    return 1;
}

static void cfg_load(struct state *s)
{
    struct cfg *c = &s->cfgbuf[0];
    copy8(c, CFG_DEFAULTS, sizeof *c);
    cfg_fixed(c);
    u32 k;
    s->cfgp = c; s->cfgi = 0;
    for (k = 0; k < 24; k++) s->slname[k] = 0xFF;
    if (rec_load(SAVE_PAGE, &s->cfgbuf[1])) { copy8(c, &s->cfgbuf[1], sizeof *c); s->saved = 1; s->flags_boot = 1; }
    log_apply(c);
}

/* ST's flash primitives (the standard peripheral library routines of the stock firmware). */
/* The flash controller (our own, the same logic as ST's library the stock firmware uses): status 1 busy, 2 programming error, 3 write
 * protected, 4 complete, 5 timeout. */
#define FL_KEYR (*(volatile u32 *)0x40022004u)
#define FL_SR (*(volatile u32 *)0x4002200Cu)
#define FL_CR (*(volatile u32 *)0x40022010u)
#define FL_AR (*(volatile u32 *)0x40022014u)
static void FLASH_UNLOCK(void) { FL_KEYR = 0x45670123u; FL_KEYR = 0xCDEF89ABu; }
static void FLASH_LOCK(void) { FL_CR |= 0x80u; }
static void FLASH_CLEAR(u32 flags) { FL_SR = flags; }
static u32 fl_status(void) { u32 sr = FL_SR; return (sr & 1u) ? 1u : (sr & 4u) ? 2u : (sr & 0x10u) ? 3u : 4u; }
static u32 fl_wait(u32 timeout)
{
    u32 st = fl_status();
    while (st == 1u && timeout) { volatile u32 d = 0xFF; while (d) d--; st = fl_status(); timeout--; }
    return timeout ? st : 5u;
}
static u32 __attribute__((noinline)) FLASH_ERASE(u32 page)          /* page erase, returns 4 = complete */
{
    u32 st = fl_wait(0xFFFFFu);
    if (st != 4u) return st;
    FL_CR |= 2u; FL_AR = page; FL_CR |= 0x40u;
    st = fl_wait(0xFFFFFu);
    if (st != 1u) FL_CR &= 0x1FFDu;
    return st;
}
static u32 __attribute__((noinline)) FLASH_PROG(u32 addr, u32 word) /* programs one 32-bit word (two halfwords) into erased flash */
{
    u32 st = fl_wait(0xFFFFu);
    if (st != 4u) return st;
    FL_CR |= 1u;
    *(volatile u16 *)addr = (u16)word;
    st = fl_wait(0xFFFFu);
    if (st == 4u) { *(volatile u16 *)(addr + 2) = (u16)(word >> 16); st = fl_wait(0xFFFFu); }
    if (st != 1u) FL_CR &= 0x1FFEu;
    return st;
}

static u32 page_blank(u32 page)
{
    const u32 *p = (const u32 *)page;
    u32 k;
    for (k = 0; k < 256; k++) if (p[k] != 0xFFFFFFFFu) return 0;
    return 1;
}
static u32 page_erase(u32 page)                      /* 1 on success (a blank page is left alone) */
{
    u32 ok = 1;
    if (page_blank(page)) return 1;
    FLASH_UNLOCK(); FLASH_CLEAR(0x35);
    if (FLASH_ERASE(page) != 4) ok = 0;
    FLASH_LOCK();
    return ok && page_blank(page);
}

/* ---- safety: the way into NI's bootloader (docs/clean-firmware-plan.md, stage 0) ----
 * The bootloader starts in DFU mode when the handshake page holds the request below (it leaves the two words swapped after a successful
 * flash, and then starts the app). The app asks for it like the stock DFU_DETACH does: the page holds the request and nothing else, then
 * a system reset. The device stays in DFU mode, even across a power cycle, until an image is flashed. */
#define HANDSHAKE 0x0801FC00u
#define AIRCR (*(volatile u32 *)0xE000ED0Cu)
static void enter_dfu(void)
{
    __asm volatile("cpsid i");
    if (page_erase(HANDSHAKE)) {
        FLASH_UNLOCK(); FLASH_CLEAR(0x35);
        FLASH_PROG(HANDSHAKE, 0xAAA55A55u);          /* 55 5A A5 AA */
        FLASH_PROG(HANDSHAKE + 4, 0xA33A9559u);      /* 59 95 3A A3 */
        FLASH_LOCK();
    }
    __asm volatile("dsb");
    AIRCR = 0x05FA0004u;                             /* SYSRESETREQ */
    for (;;) { }
}

/* ---- the settings log: changes made with the controller's own buttons that are kept without saving the whole config ----
 * The second half of the save page (offset 0x200 ..) is a list of 32-bit words, each programmed once into erased flash: 0x5A, kind, value,
 * and a check byte. Today there is one kind (1 = velocity curve); the LAST valid word wins at boot and overrides the curve of the saved
 * config (or of the defaults). Appending is one word program, no erase, so a curve change costs a few microseconds of flash time; a word
 * cut short by a power loss fails its check and is skipped. A full SAVE (which erases the page) bakes the current curve into the record. */
#define LOG_BASE (SAVE_PAGE + 0x200u)
#define LOG_WORDS 128u
#define LOG_KIND_CURVE 1u
#define LOG_KIND_CHANNEL 2u
static u32 log_word(u32 kind, u32 value) { return 0x5Au | (kind << 8) | (value << 16) | ((0x5Au ^ kind ^ value ^ 0xFFu) << 24); }
static u32 log_valid(u32 w) { return (w & 0xFF) == 0x5A && (w >> 24) == ((0x5Au ^ ((w >> 8) & 0xFF) ^ ((w >> 16) & 0xFF) ^ 0xFFu) & 0xFF); }

static u32 log_blank(void)
{
    const u32 *p = (const u32 *)LOG_BASE;
    u32 k;
    for (k = 0; k < LOG_WORDS; k++) if (p[k] != 0xFFFFFFFFu) return 0;
    return 1;
}

static void log_apply(struct cfg *c)                /* boot: the last curve in the log */
{
    const u32 *p = (const u32 *)LOG_BASE;
    u32 k;
    for (k = 0; k < LOG_WORDS; k++)
        if (log_valid(p[k])) {
            u32 kind = (p[k] >> 8) & 0xFF, v = (p[k] >> 16) & 0xFF;
            if (kind == LOG_KIND_CURVE && v <= 8) c->vel_curve = (u8)v;
            if (kind == LOG_KIND_CHANNEL && v <= 15) c->channel = (u8)v;
        }
}

static u32 save_erase(void) { return page_erase(SAVE_PAGE); }   /* the saved config (and the settings log) is gone: 1 on success */

/* Writes a config as a record into a page: 1 on success (verified by reading it back). The magic goes last, so a cut leaves no valid record. The record
 * is built in s->reply (a stack buffer of that size would cost a quarter of the stack): callers make sure no reply is waiting there. */
#define SLOT_NAME 0x120u                            /* a slot's name: 24 bytes behind its record (a blank byte = none) */
#define NAME_MAX 20u                                /* characters of a name: what the detail line shows whole (6 pixels each from x = 4) */
static u32 rec_write(struct state *s, u32 page, const struct cfg *c, u32 named)
{
    struct rec *r = (struct rec *)s->reply;
    u32 *w = (u32 *)s->reply;
    u32 k, n = sizeof(struct rec) / 4;
    for (k = 0; k < n; k++) w[k] = 0;
    copy8(r->data, c, sizeof *c);
    r->magic = REC_MAGIC; r->version = REC_VERSION; r->len = sizeof *c; r->crc = crc16(r->data, sizeof *c); r->reserved = 0xFFFF;
    if (same8((const void *)page, r, sizeof *r) && (page != SAVE_PAGE || log_blank()) && (!named || same8((const void *)(page + SLOT_NAME), s->slname, 24))) return 1;     /* already there (and no curve log to clear): no erase, no wear */
    if (!page_erase(page)) return 0;
    FLASH_UNLOCK(); FLASH_CLEAR(0x35);
    for (k = 3; k < n; k++) FLASH_PROG(page + 4 * k, w[k]);   /* the data first ... */
    FLASH_PROG(page + 4, w[1]); FLASH_PROG(page + 8, w[2]);
    FLASH_PROG(page, w[0]);                                    /* ... the magic last */
    if (named) for (k = 0; k < 6; k++) if (((const u32 *)s->slname)[k] != 0xFFFFFFFFu) FLASH_PROG(page + SLOT_NAME + 4 * k, ((const u32 *)s->slname)[k]);
    FLASH_LOCK();
    return same8((const void *)page, r, sizeof *r);
}
static u32 save_write(struct state *s, const struct cfg *c) { return rec_write(s, SAVE_PAGE, c, 0); }
static void slname_load(struct state *s, u32 page)       /* the slot's name into slname: printable characters up to the first other byte */
{
    const u8 *p = (const u8 *)(page + SLOT_NAME);
    u32 k, ok = 1;
    for (k = 0; k < 24; k++) { u8 ch = p[k]; if (k >= NAME_MAX || ch < 32 || ch > 95) ok = 0; s->slname[k] = ok ? ch : 0xFF; }
}

/* Appends a word to the settings log. A full log is cleared by a full save of the active config (which erases the page), or, when nothing
 * is saved, by an erase. */
static void log_append(struct state *s, u32 kind, u32 value)
{
    const u32 *p = (const u32 *)LOG_BASE;
    u32 k;
    for (k = 0; k < LOG_WORDS && p[k] != 0xFFFFFFFFu; k++) { }
    if (k == LOG_WORDS) {
        if (s->saved) { if (save_write(s, s->cfgp)) s->dirty = 0; return; }
        if (!save_erase()) return;
        k = 0;
    }
    FLASH_UNLOCK(); FLASH_CLEAR(0x35);
    FLASH_PROG(LOG_BASE + 4 * k, log_word(kind, value));
    FLASH_LOCK();
}

/* The four step patterns (256 bytes) in their own flash page: magic, version, length, CRC, then the data; the magic is programmed last. */
struct patrec { u32 magic; u16 version, len, crc, reserved; u32 data[64]; };
#define PAT_MAGIC 0x54415053u
static void pat_load(struct state *s)
{
    const struct patrec *r = (const struct patrec *)PAT_PAGE;
    if (r->magic == PAT_MAGIC && r->version == 1 && r->len == sizeof r->data && crc16((const u8 *)r->data, sizeof r->data) == r->crc) copy8(s->pat, r->data, sizeof s->pat);
}
static u32 pat_write(struct state *s)                   /* 1 on success; builds the record in s->reply like rec_write */
{
    struct patrec *r = (struct patrec *)s->reply;
    u32 *w = (u32 *)s->reply;
    u32 k, n = sizeof(struct patrec) / 4;
    for (k = 0; k < n; k++) w[k] = 0;
    copy8(r->data, s->pat, sizeof r->data);
    r->magic = PAT_MAGIC; r->version = 1; r->len = sizeof r->data; r->crc = crc16((const u8 *)r->data, sizeof r->data); r->reserved = 0xFFFF;
    if (same8((const void *)PAT_PAGE, r, sizeof *r)) return 1;
    if (!page_erase(PAT_PAGE)) return 0;
    FLASH_UNLOCK(); FLASH_CLEAR(0x35);
    for (k = 3; k < n; k++) FLASH_PROG(PAT_PAGE + 4 * k, w[k]);
    FLASH_PROG(PAT_PAGE + 4, w[1]); FLASH_PROG(PAT_PAGE + 8, w[2]);
    FLASH_PROG(PAT_PAGE, w[0]);
    FLASH_LOCK();
    return same8((const void *)PAT_PAGE, r, sizeof *r);
}

/* ---- activating a config ---- */

/* The active config has changed: forget state that depended on the old one, rebuild the LEDs, apply the pad sensitivity. */
static void cfg_activate(struct state *s, const struct cfg *c)
{
    u32 k;
    for (k = 0; k < sizeof s->tog; k++) s->tog[k] = 0;
    s->encabs = c->enc_init & 127;
    mode_reset(s, c);                               /* the modes start over with a new config (the velocity curve is part of it) */
    s->cfgp = c;                                    /* one store: from here on every reader sees the new config */
    local_led_init(s, 1);
    led_flush();
    if (c->sens <= 100 && SENS_BYTE != c->sens) {   /* like the stage-2 init: the stock threshold routine recomputes from the stored value */
        SENS_BYTE = c->sens;
        THRESHOLD();
    }
}

static void cfg_commit(struct state *s, const struct cfg *n)
{
    u8 i = s->cfgi ^ 1;                             /* fill the buffer that is not in use, then switch */
    copy8(&s->cfgbuf[i], n, sizeof *n);
    cfg_fixed(&s->cfgbuf[i]);
    u32 k;
    s->cfgi = i;
    s->dirty = 1;
    for (k = 0; k < 24; k++) s->slname[k] = 0xFF;        /* a new config has no slot name and no slot (a slot load sets them after) */
    s->slot_cur = 0;
    cfg_activate(s, &s->cfgbuf[i]);
}

/* The slot after the current one that holds a config (1..4), 0 = none. Without a current slot (power-up, a config from the host), the one whose
 * config is the active one counts as current; if none is, the search starts at slot 1. */
static u32 slot_next(struct state *s)
{
    u32 cur = s->slot_cur, k, n;
    if (!cur)
        for (k = 0; k < 4 && !cur; k++) {
            struct cfg *t = &s->cfgbuf[s->cfgi ^ 1];
            if (rec_load(SLOT_PAGE(k), t) && same8(t, s->cfgp, sizeof *t)) cur = k + 1;
        }
    for (k = 1; k <= 4; k++) {
        n = (cur + k - 1) & 3;                           /* (cur 0: slot 1 first) */
        if (rec_ok(SLOT_PAGE(n))) return n + 1;
    }
    return 0;
}

/* A preset slot, asked for with a button: op 1..4 make slot op the active config, 5..8 store the active config in slot op - 4, 9 load the next
 * slot that holds a config. */
static void slot_do(struct state *s, u32 op)
{
    u32 n, p;
    if (op == 9) {
        op = slot_next(s);
        if (!op) { m_begin(s, T_SLOT); tx(s->md, 0, T_EMPTY, 21); m_show(s); return; }   /* no slot holds a config */
    }
    n = (op - 1) & 3;
    m_begin(s, T_SLOT);
    p = tc(s->mt, 4, ' ', 10); tn(s->mt, p, n + 1, 10);
    if (op <= 4) {
        struct cfg *t = &s->cfgbuf[s->cfgi ^ 1];               /* the buffer that is not in use */
        if (rec_load(SLOT_PAGE(n), t)) {
            cfg_commit(s, t); slname_load(s, SLOT_PAGE(n)); s->slot_cur = (u8)(n + 1);
            if (s->slname[0] != 0xFF) { u32 k = 0; while (k < NAME_MAX && s->slname[k] != 0xFF) { tc(s->md, k, (char)s->slname[k], 21); k++; } }
            else tx(s->md, 0, T_LOADED, 21);
        } else tx(s->md, 0, T_EMPTY, 21);
    } else if (rec_write(s, SLOT_PAGE(n), s->cfgp, 1)) { s->slot_cur = (u8)(n + 1); tx(s->md, 0, T_SAVED, 21); }
    else tx(s->md, 0, T_ERROR, 21);
    m_show(s);
}

/* ---- requests ---- */

static u32 pack7(u8 *dst, const u8 *src, u32 n)      /* 7-bit packing: a byte with the high bits of the next 7 bytes, then those 7 bytes */
{
    u32 i, j, o = 0;
    for (i = 0; i < n; i += 7) {
        u8 hi = 0;
        for (j = 0; j < 7 && i + j < n; j++) hi |= (u8)((src[i + j] >> 7) << j);
        dst[o++] = hi;
        for (j = 0; j < 7 && i + j < n; j++) dst[o++] = src[i + j] & 0x7F;
    }
    return o;
}

static u32 unpack7(u8 *dst, u32 cap, const u8 *src, u32 n)   /* returns the number of bytes recovered (stops at cap) */
{
    u32 i, j, o = 0;
    for (i = 0; i < n; i += 8)
        for (j = 1; j < 8 && i + j < n && o < cap; j++)
            dst[o++] = (u8)((src[i + j] & 0x7F) | (((src[i] >> (j - 1)) & 1) << 7));
    return o;
}

static void rep_start(struct state *s, u8 cmd)
{
    s->reply[0] = 0xF0; s->reply[1] = 0x7D; s->reply[2] = 0x4D; s->reply[3] = 0x4B; s->reply[4] = cmd;
    s->reply_len = 5; s->reply_pos = 0;
}
static void rep_byte(struct state *s, u8 b) { s->reply[s->reply_len++] = b & 0x7F; }
static void rep_end(struct state *s) { s->reply[s->reply_len++] = 0xF7; }

/* PEEK may read only places that exist on this chip and cannot fault: a bus fault would hang the device until the watchdog resets it. */
static u32 peek_ok(u32 a, u32 n)
{
    u32 e = a + n - 1;                               /* last byte; the ranges below are inclusive */
#define IN(lo, hi) (a >= (lo) && e <= (hi))
    if (e < a) return 0;
    if (a >= 0x40000000u && ((a | n) & 3)) return 0;  /* registers are read as whole words (a byte read of the FLASH registers bus-faults the chip) */
    return IN(0x08000000u, 0x0801FFFFu)              /* flash (128 KB part) */
        || IN(0x20000000u, 0x20004FFFu)              /* RAM (20 KB) */
        || IN(0x1FFFF7E0u, 0x1FFFF7FFu)              /* flash size (16 bit) and the 96-bit unique ID */
        || IN(0x1FFFF800u, 0x1FFFF80Fu)              /* option bytes (read protection, write protection) */
        || IN(0x40022000u, 0x4002202Fu)              /* flash interface: ACR, SR, CR, OBR, WRPR */
        || IN(0xE0042000u, 0xE0042003u)              /* DBGMCU_IDCODE */
        || IN(0xE000ED00u, 0xE000ED3Fu)              /* SCB: CPUID, ICSR, VTOR, AIRCR, SCR, CCR, SHPR, SHCSR, fault status */
        || IN(0xE000E010u, 0xE000E01Fu)              /* SysTick */
        || IN(0xE000E100u, 0xE000E11Fu) || IN(0xE000E400u, 0xE000E43Fu)    /* NVIC: enabled interrupts, priorities */
        /* the configuration registers of the peripherals (stage-1 recon, docs/clean-firmware-plan.md); registers whose read has a side
         * effect (ADC / SPI / USART data, I2C status, the timers' DMA burst register) are left out */
        || IN(0x40021000u, 0x40021027u)              /* RCC, including CSR (the reset cause) */
        || IN(0x40010000u, 0x4001001Fu)              /* AFIO */
        || IN(0x40010400u, 0x40010417u)              /* EXTI */
        || (a >= 0x40010800u && e <= 0x40011BFFu && ((a & 0x3FFu) + n) <= 0x1Cu)   /* GPIOA..E: CRL, CRH, IDR, ODR, BSRR, BRR, LCKR */
        || IN(0x40012400u, 0x4001244Bu)              /* ADC1 without DR */
        || IN(0x40012800u, 0x4001284Bu)              /* ADC2 without DR */
        || IN(0x40020000u, 0x4002008Fu)              /* DMA1 */
        || IN(0x40012C00u, 0x40012C4Bu) || IN(0x40000000u, 0x4000004Bu) || IN(0x40000400u, 0x4000044Bu) || IN(0x40000800u, 0x4000084Bu)   /* TIM1..4 without DMAR */
        || IN(0x40013000u, 0x4001300Bu) || IN(0x40003800u, 0x4000380Bu)    /* SPI1, SPI2: CR1, CR2, SR */
        || IN(0x40005400u, 0x4000540Fu) || IN(0x40005800u, 0x4000580Fu)    /* I2C1, I2C2: CR1, CR2, OAR1, OAR2 */
        || IN(0x40003000u, 0x4000300Fu)              /* IWDG */
        || IN(0x40007000u, 0x40007007u)              /* PWR */
        || IN(0x40006C00u, 0x40006C2Bu)              /* BKP */
        || IN(0x40005C00u, 0x40005C53u)              /* USB registers */
        || IN(0x40006000u, 0x400063FFu);             /* USB packet memory */
#undef IN
}

/* Called from the USB interrupt with the SysEx body after the manufacturer/product bytes (b[0..n-1] = cmd, data ...). */
static void req_start(struct state *s, const u8 *b, u32 n)
{
    if (s->req) return;                              /* busy: the host asks again */
    s->req_err = 0; s->req_arg = n > 1 ? b[1] : 0;
    if (b[0] == 0x1E) { copy8(s->stage, b + 1, n > 7 ? 6 : n - 1); if (n != 7) s->req_err = 1; }
    if (b[0] == 0x1C) { if (n < 2 || n > 4) s->req_err = 1; s->stage[0] = n > 2 ? b[2] : 0; s->stage[1] = n > 3 ? b[3] : 0; }
    if (b[0] == 0x1D) { copy8(s->stage, b + 1, n > 5 ? 4 : n - 1); if (n != 5) s->req_err = 1; }
    if (b[0] == 0x1F && !(n == 5 && b[1] == 'H' && b[2] == 'A' && b[3] == 'N' && b[4] == 'G')) s->req_err = 1;
    if (b[0] == 0x12 && unpack7(s->stage, sizeof s->stage, b + 1, n - 1) != sizeof(struct cfg)) s->req_err = 1;
    if ((b[0] == 0x15 && (n < 2 || n > 2 + NAME_MAX)) || (b[0] == 0x16 && n != 2)) s->req_err = 1;       /* the slot number is required, a store may add a name (up to 20 characters) */
    if (b[0] == 0x15 && !s->req_err) {
        u32 k;
        for (k = 0; k < 24; k++) {
            u8 ch = k < NAME_MAX && k + 2 < n ? b[k + 2] : 0xFF;
            if (ch != 0xFF) { if (ch >= 97 && ch <= 122) ch -= 32; if (ch < 32 || ch > 95) ch = '?'; }
            s->slname[k] = ch;
        }
    }
    s->req = b[0];
}

static void request(struct state *s)                 /* main loop: one pending request, its reply goes to reply[] */
{
    u8 cmd = s->req, status = 0;
    s->u_ok = 1;                                     /* (usb.c: a host talks to us) */
    u32 bad = 0;
    if (cmd == 0x15 || cmd == 0x16) {                /* store the active config in slot / make a slot the active config: status 2 bad slot, 3 flash error, 4 empty slot */
        u32 n = s->req_arg;
        if (s->req_err) status = 1;
        else if (n > 3) status = 2;
        else if (cmd == 0x15) { if (rec_write(s, SLOT_PAGE(n), s->cfgp, 1)) s->slot_cur = (u8)(n + 1); else status = 3; }
        else { struct cfg *t = &s->cfgbuf[s->cfgi ^ 1]; if (rec_load(SLOT_PAGE(n), t)) { cfg_commit(s, t); slname_load(s, SLOT_PAGE(n)); s->slot_cur = (u8)(n + 1); } else status = 4; }
        rep_start(s, 0x40 + cmd); rep_byte(s, status); rep_end(s);
    } else if (cmd == 0x17) {                        /* which slots hold a config: a bit mask */
        u32 i, mask = 0;
        for (i = 0; i < 4; i++) if (rec_ok(SLOT_PAGE(i))) mask |= 1u << i;
        rep_start(s, 0x57); rep_byte(s, 0); rep_byte(s, (u8)mask);
        for (i = 0; i < 4; i++) {                    /* then the names: 20 characters each, 0 = none / padding */
            const u8 *nm = (const u8 *)(SLOT_PAGE(i) + SLOT_NAME);
            u32 k, ok = (mask >> i) & 1;
            for (k = 0; k < NAME_MAX; k++) { if (nm[k] < 32 || nm[k] > 95) ok = 0; rep_byte(s, ok ? nm[k] : 0); }
        }
        rep_end(s);
    } else if (cmd == 0x10) {
        rep_start(s, 0x50);
        rep_byte(s, PROTO_VERSION); rep_byte(s, sizeof(struct cfg) & 0x7F); rep_byte(s, sizeof(struct cfg) >> 7);
        rep_byte(s, (s->saved ? 1 : 0) | (s->dirty ? 2 : 0) | (s->flags_boot ? 4 : 0));
        rep_byte(s, FW_VERSION);
        rep_end(s);
    } else if (cmd == 0x11) {
        rep_start(s, 0x51);
        s->reply_len += pack7(s->reply + s->reply_len, (const u8 *)s->cfgp, sizeof(struct cfg));
        rep_end(s);
    } else if (cmd == 0x12) {
        if (s->req_err) status = 1;
        else if ((bad = cfg_check((const struct cfg *)s->stage)) != 0) status = 2;
        else cfg_commit(s, (const struct cfg *)s->stage);
        rep_start(s, 0x52); rep_byte(s, status);
        if (status == 2) { rep_byte(s, (bad - 1) & 0x7F); rep_byte(s, (bad - 1) >> 7); }
        rep_end(s);
    } else if (cmd == 0x13) {
        if (same8(s->cfgp, CFG_DEFAULTS, sizeof(struct cfg))) {          /* the defaults need no record: back to a blank page */
            if (!save_erase()) status = 3;
            else { s->saved = 0; s->dirty = 0; }
        } else if (!save_write(s, s->cfgp)) status = 3;
        else { s->saved = 1; s->dirty = 0; }
        rep_start(s, 0x53); rep_byte(s, status); rep_end(s);
    } else if (cmd == 0x1D) {                        /* raw pad capture: mask (3 x 7 bits, LSB first), period in ms (1..127); a zero mask stops it */
        u32 mask = s->stage[0] | (u32)s->stage[1] << 7 | (u32)(s->stage[2] & 3) << 14, per = s->stage[3];
        if (s->req_err || per < 1) status = 1;
        else {
            s->cap_mask = 0;
            CAP[0] = CAP_MAGIC; CAP[1] = 0; CAP[3] = mask; CAP[2] = 2;
            { u32 k; for (k = 0; k < 16; k++) if (mask >> k & 1) CAP[2] += 2; }
            s->cap_period = (u8)per; s->cap_t = (u16)(MS16 - per); s->cap_mask = (u16)mask;
        }
        rep_start(s, 0x5D); rep_byte(s, status); rep_end(s);
    } else if (cmd == 0x1C) {                        /* HAL: which of our own drivers replace the stock ones (hal.c); RAM only */
        rep_start(s, 0x5C); rep_byte(s, s->req_err ? 1 : 0); if (!s->req_err) hal_set(s, s->req_arg, s->stage[1], s->stage[0]); rep_byte(s, s->hal);
        rep_byte(s, s->hal_ok & 0x7F); rep_byte(s, (s->hal_ok >> 7) & 0x7F); rep_byte(s, s->hal_ok >> 14);       /* the LED bursts so far: acknowledged ... */
        rep_byte(s, s->hal_fail & 0x7F); rep_byte(s, (s->hal_fail >> 7) & 0x7F); rep_byte(s, s->hal_fail >> 14);  /* ... and not */
        rep_byte(s, s->strip_ok & 0x7F); rep_byte(s, (s->strip_ok >> 7) & 0x7F); rep_byte(s, s->strip_ok >> 14);   /* the strip read cycles */
        rep_byte(s, s->strip_fail & 0x7F); rep_byte(s, (s->strip_fail >> 7) & 0x7F); rep_byte(s, s->strip_fail >> 14);
        rep_byte(s, s->hal2); rep_byte(s, s->own_init); rep_byte(s, s->own_usb);
        rep_end(s);
    } else if (cmd == 0x1F) {                        /* HANG (the watchdog test): confirmed, then the next tick stops */
        rep_start(s, 0x5F); rep_byte(s, s->req_err ? 1 : 0); rep_end(s);
        if (!s->req_err) s->cap_hang = 1;
    } else if (cmd == 0x1E) {
        u32 addr = 0, len = s->stage[5], i;
        const volatile u8 *p;
        u8 tmp[64];
        for (i = 0; i < 5; i++) addr = (addr << 7) | (s->stage[i] & 0x7F);
        status = (s->req_err || len < 1 || len > 64) ? 2 : peek_ok(addr, len) ? 0 : 1;
        rep_start(s, 0x5E); rep_byte(s, status);
        for (i = 0; i < 5; i++) rep_byte(s, (u8)(addr >> (28 - 7 * i)));
        if (!status) {
            p = (const volatile u8 *)addr;
            if (addr >= 0x40000000u) for (i = 0; i < len; i += 4) { u32 w = *(const volatile u32 *)(addr + i); tmp[i] = (u8)w; tmp[i + 1] = (u8)(w >> 8); tmp[i + 2] = (u8)(w >> 16); tmp[i + 3] = (u8)(w >> 24); }
            else for (i = 0; i < len; i++) tmp[i] = p[i];
            s->reply_len += pack7(s->reply + s->reply_len, tmp, len);
        }
        rep_end(s);
    } else if (cmd == 0x14) {
        cfg_commit(s, CFG_DEFAULTS);
        s->dirty = s->saved;                         /* different from what is saved, unless nothing is saved */
        if (s->req_arg == 1) {
            if (!save_erase()) status = 3;
            else { s->saved = 0; s->dirty = 0; }
        }
        rep_start(s, 0x54); rep_byte(s, status); rep_end(s);
    }
    s->req = 0;                                      /* only now may the interrupt take the next one (it would overwrite stage[] before) */
}

#define RING_W (*(volatile u16 *)0x20000146)         /* the stock TX ring (0x500 bytes): write and read index */
#define RING_R (*(volatile u16 *)0x20000148)

/* Moves the reply into the stock TX ring as USB-MIDI SysEx packets, as far as the ring has room (the stock enqueue would otherwise
 * split a packet when the ring fills up); the rest follows on the next tick. */
static void reply_pump(struct state *s)
{
    u8 buf[64];
    u32 n = 0, room = (RING_R + 0x500u - RING_W - 1u) % 0x500u;
    while (s->reply_pos < s->reply_len && n + 4 <= sizeof buf && n + 4 <= room) {
        u32 left = s->reply_len - s->reply_pos, take = left > 3 ? 3 : left, k;
        buf[n] = (u8)(left > 3 ? 4 : 4 + left);      /* 4: SysEx continues, 5/6/7: SysEx ends with 1/2/3 bytes */
        for (k = 0; k < 3; k++) buf[n + 1 + k] = k < take ? s->reply[s->reply_pos + k] : 0;
        s->reply_pos += take;
        n += 4;
    }
    if (n) ENQUEUE(buf, n);
    if (s->reply_pos >= s->reply_len) s->reply_len = s->reply_pos = 0;
}

/* All Sound Off (CC 120) and All Notes Off (CC 123) on every channel, as far as the ring has room; the rest follows on the next tick. */
static void panic_pump(struct state *s)
{
    u8 buf[64];
    u32 n = 0, room = (RING_R + 0x500u - RING_W - 1u) % 0x500u;
    while (s->panic && n + 4 <= sizeof buf && n + 4 <= room) {
        u32 i = 32u - s->panic;
        emit(buf + n, 0xB0 | (i >> 1), (i & 1) ? 123 : 120, 0);
        n += 4; s->panic--;
    }
    if (n) ENQUEUE(buf, n);
}

/* ---- the grid: 24 pulses per beat from the internal tempo or an incoming MIDI clock; drives the arp, the clock output and the beat LED ---- */

static u8 *arp_off(struct state *s, const struct cfg *c, u8 *q)    /* releases what the arp has sounding */
{
    u32 k;
    for (k = 0; k < s->sonn; k++) q = emit(q, 0x80 | (c->channel & 15), s->son[k], 0);
    s->sonn = 0;
    return q;
}

/* One step: the previous notes off, then the next note (or, for Repeat, all of them) on. */
static u8 *arp_step(struct state *s, const struct cfg *c, u8 *q)
{
    u32 n = s->ann, m, j, k, o = s->arp_oct ? s->arp_oct : 1, ch = c->channel & 15;
    u8 ty = s->arp_type, note;
    q = arp_off(s, c, q);
    if (!n) return q;
    if (ty == 0) {                                   /* repeat: every held note again */
        for (k = 0; k < n; k++) { q = emit(q, 0x90 | ch, s->an[k], s->av[k]); s->son[k] = s->an[k]; }
        s->sonn = (u8)n; s->astep++;
        return q;
    }
    for (k = 0; k < n; k++) s->ixs[k] = (u8)k;
    if (ty != 4) for (j = 1; j < n; j++) { u8 v = s->ixs[j]; for (k = j; k > 0 && s->an[s->ixs[k - 1]] > s->an[v]; k--) s->ixs[k] = s->ixs[k - 1]; s->ixs[k] = v; }
    m = n * o;
    if (ty == 2) j = m - 1 - s->astep % m;
    else if (ty == 3) { if (m < 2) j = 0; else { k = s->astep % (2 * m - 2); j = k < m ? k : 2 * m - 2 - k; } }
    else if (ty == 5) { s->rnd = (u16)(s->rnd * 25173u + 13849u); j = (u32)(s->rnd >> 4) % m; }
    else j = s->astep % m;
    k = s->ixs[j % n];
    note = (u8)(s->an[k] + 12 * (j / n));
    if (s->an[k] + 12 * (j / n) <= 127) { q = emit(q, 0x90 | ch, note, s->av[k]); s->son[0] = note; s->sonn = 1; }
    s->astep++;
    return q;
}

static u8 *seq_off(struct state *s, const struct cfg *c, u8 *q)     /* releases what the sequencer has sounding */
{
    u32 t;
    for (t = 0; t < 16; t++) if ((s->seq_son >> t) & 1) q = emit(q, 0x80 | (c->channel & 15), c->pad_note[padnum((u8)t)], 0);
    s->seq_son = 0;
    return q;
}

/* One step of the sequencer: the previous notes off, then every track that has this step on (normal 100, accent 127; muted pads stay silent). */
static u8 *seq_step(struct state *s, const struct cfg *c, u8 *q)
{
    u32 t, pos = s->seq_pos;
    q = seq_off(s, c, q);
    for (t = 0; t < 16; t++) {
        u32 st = (s->pat[s->seq_pat][t] >> (2 * pos)) & 3;
        if (st && pad_audible(s, padnum((u8)t))) {
            q = emit(q, 0x90 | (c->channel & 15), c->pad_note[padnum((u8)t)], st == 2 ? 127 : 100);
            s->seq_son |= (u16)(1u << t);
        }
    }
    s->seq_cur = (u8)pos; s->seq_pos = (u8)((pos + 1) & 15);
    if (s->padmode == 3) { seq_leds(s); led_flush(); }                 /* the playhead moves on the pads */
    return q;
}

static void clock_tick(struct state *s)
{
    const struct cfg *c = s->cfgp;
    u16 now = MS16, dt = (u16)(now - s->last_ms);
    u8 buf[160], *q = buf, n, k;
    u32 room = (RING_R + 0x500u - RING_W - 1u) % 0x500u, np = 0, running;
    if (room < 200) return;                          /* the ring is backed up: try again next time (nothing is lost, the time keeps counting) */
    s->last_ms = now;
    s->ext_active = s->ext_any && (u16)(now - s->ext_ms) < 400;
    n = (u8)(s->ext_go - s->ext_go_seen);
    if (n) { s->ext_go_seen = s->ext_go; s->pulse = 0; s->acc_us = 0; }              /* the host (re)started: the grid starts with it */
    n = (u8)(s->ext_stp - s->ext_stp_seen);
    if (n) { s->ext_stp_seen = s->ext_stp; q = arp_off(s, c, q); }
    if (s->strum_off) { q = emit(q, 0x80 | (c->channel & 15), (u8)(s->strum_off - 1), 0); s->strum_off = 0; }
    if (!s->arp_on && s->sonn) q = arp_off(s, c, q);
    if (!s->seq_on && s->seq_son) q = seq_off(s, c, q);
    n = (u8)(s->ext_in - s->ext_seen); s->ext_seen = s->ext_in;
    running = s->clock_out || s->seq_on || (s->arp_on && (s->ann || s->sonn));
    if (s->arp_kick || s->seq_kick) {                 /* a note or the sequencer starts with no grid running: the grid starts with it, the first step sounds at once */
        u8 ak = s->arp_kick, sk = s->seq_kick;
        s->arp_kick = s->seq_kick = 0;
        if (ak && s->arp_on) q = arp_step(s, c, q);
        if (sk && s->seq_on) { if (q != buf) { ENQUEUE(buf, (u32)(q - buf)); q = buf; } q = seq_step(s, c, q); }
        s->pulse = 1; s->acc_us = 0;
    }
    else if (s->ext_active) np = n > 8 ? 8 : n;
    else if (running) {
        u32 period = 2500000u / s->bpm;
        s->acc_us += (u32)dt * 1000u;
        while (s->acc_us >= period && np < 8) { s->acc_us -= period; np++; }
        if (np == 8 && s->acc_us >= period) s->acc_us = 0;
    } else s->acc_us = 0;
    if (!running && !s->ext_active && s->tap_btn != 0xFF && s->led[s->tap_btn] != s->base[s->tap_btn]) { s->led[s->tap_btn] = s->base[s->tap_btn]; led_flush(); }   /* the clock stopped mid-blink */
    for (k = 0; k < np; k++) {
        u32 p = s->pulse;
        if (q != buf) { ENQUEUE(buf, (u32)(q - buf)); q = buf; }
        if (s->clock_out && !s->ext_active) q = emit1(q, 0xF8);
        if (s->arp_on) {
            u32 rate = rate_pulses(s->arp_rate), ph = p % rate;
            if (ph == 0 && q != buf) { ENQUEUE(buf, (u32)(q - buf)); q = buf; }
            if (ph == 0) q = arp_step(s, c, q); else if (ph == (rate >> 1 ? rate >> 1 : 1)) q = arp_off(s, c, q);
        }
        if (s->seq_on) {
            u32 ph = p % 6;                              /* 1/16 notes */
            if (ph == 0) { if (q != buf) { ENQUEUE(buf, (u32)(q - buf)); q = buf; } q = seq_step(s, c, q); }
            else if (ph == 3) q = seq_off(s, c, q);
        }
        if (s->tap_btn != 0xFF) {                    /* the beat: the Tap button blinks */
            u32 ph = p % 24;
            if (ph == 0) { s->led[s->tap_btn] = c->btn_led_on; led_flush(); }
            else if (ph == 6) { s->led[s->tap_btn] = (c->led_flags & LF_BTN_IDLE) ? c->btn_led_idle : 0; led_flush(); }     /* (the button may be lit as a mode indicator: the blink needs a dark phase) */
        }
        s->pulse = p + 1;
    }
    if (q != buf) ENQUEUE(buf, (u32)(q - buf));
}

/* ---- main-loop hook: replaces `bl 0x08005414` (kick the watchdog) at the top of every main-loop iteration (0x08008d06) ---------------- */
#define COUNTDOWN (*(volatile u16 *)0x2000102A)     /* struct + 2: startup period, 6000 ms from the stage-2 init down to 0 */

/* The stock startup plays an LED fade-in and ends (countdown 0) by clearing every LED without looking at the LED buffer again, so
 * whatever was shown before that, the resting state included, is gone. Once the countdown is 0 the shadow is written out once more.
 * This is also the place for work that must not run in an interrupt. */
/* The DFU gesture, the guard's "healthy" mark and the watchdog test. */
#define BTN_DOWN(s, k) (((s)->btn[(k) >> 3] >> ((k) & 7)) & 1)
static void safety_tick(struct state *s)
{
    u16 now = MS16;
    if (s->cap_hang) { __asm volatile("cpsid i"); for (;;) { } }          /* HANG: stop until the watchdog resets the chip */
    if (!s->healthy) {
        if (!s->run_t0) s->run_t0 = now ? now : 1;
        else if ((u16)(now - s->run_t0) >= HEALTHY_MS) { GUARD[1] = 0; GUARD[2] = ~0u; s->healthy = 1; }
    }
    if (s->gest == 2) { if ((u16)(now - s->gest_t0) >= 300) enter_dfu(); return; }    /* the message is on the screen: go */
    if (!(BTN_DOWN(s, 25) && BTN_DOWN(s, 24) && BTN_DOWN(s, 19))) { s->gest = 0; return; }   /* Shift + Stop + Erase */
    if (!s->gest) { s->gest = 1; s->gest_t0 = now; }
    else if ((u16)(now - s->gest_t0) >= 2000) { s->gest = 2; s->gest_t0 = now; announce_text(s, T_DFU, T_FLASHTOLEAVE); }
}

/* Raw pad capture (stage-1 recon): every cap_period ms, a frame of the millisecond counter and the raw 12-bit ADC values of the channels in
 * cap_mask (the stock DMA buffer, in its scan order) goes into the free RAM at CAP_BASE, until it is full; the host reads it with PEEK. */
static void cap_tick(struct state *s)
{
    u16 now = MS16;
    u32 size = 2, k, frames = CAP[1];
    volatile u16 *f;
    if ((u16)(now - s->cap_t) < s->cap_period) return;
    s->cap_t = now;
    for (k = 0; k < 16; k++) if (s->cap_mask >> k & 1) size += 2;
    if (CAP_BASE + 16 + (frames + 1) * size > CAP_END) { s->cap_mask = 0; return; }
    f = (volatile u16 *)(CAP_BASE + 16 + frames * size);
    *f++ = now;
    for (k = 0; k < 16; k++) if (s->cap_mask >> k & 1) *f++ = ADC_RAW[k];
    CAP[1] = frames + 1;
}

static void tick_body(void);
void mmk3_tick(void) { tick_body(); }
static void tick_body(void)
{
    struct state *s = ST;
    IWDG_KR = 0xAAAAu;                               /* the watchdog kick (the stock call this hook replaces did only this) */
    if (!COUNTDOWN && !s->started) {
        s->started = 1; s->vdirty = 1;
        if (s->lit) led_flush();
    }
    if (s->req && !s->reply_len) request(s);
    if (s->seq_save && !s->reply_len) { u32 ok = pat_write(s); s->seq_save = 0; if (ok) s->seq_dirty = 0; announce_text(s, T_PATTERNS, ok ? T_SAVED : T_ERROR); }
    if (s->slot_req && !s->req && !s->reply_len) { u8 r = s->slot_req; s->slot_req = 0; slot_do(s, r); }
    if (s->reply_len) reply_pump(s);
    else if (s->reboot && ++s->reboot > 50) { __asm volatile("dsb"); AIRCR = 0x05FA0004u; for (;;) { } }   /* (a few passes after the reply went out) */
    if (s->panic) panic_pump(s);
    if (s->log_req && !s->reply_len) {
        u8 r = s->log_req;
        s->log_req = 0;
        if (r & 1) log_append(s, LOG_KIND_CURVE, s->cfgp->vel_curve);
        if (r & 2) log_append(s, LOG_KIND_CHANNEL, s->cfgp->channel & 15);
    }
    if (s->started) { clock_tick(s); disp_tick(s); safety_tick(s); }
    if (s->cap_mask) cap_tick(s);
}

/* ---- host -> device hook: replaces `bl 0x08008798` in the EP1 OUT callback (0x08004a4c) --- */

#define RX_LEN (*(volatile u8 *)0x20000074)
#define RX_BUF ((const volatile u8 *)0x200001D8)

/* A LED the host sets keeps that colour as its resting state (a local press / hit returns to it). */
static void led_host_set(u32 idx, u8 code) { ST->led[idx] = code; ST->base[idx] = code; }

/* SysEx (manufacturer 0x7D, "MK"):   F0 7D 4D 4B <cmd> ... F7
 *   cmd 01  display region: x page w-1 h-1 <7-bit packed pixel bytes, w*h of them>
 *           x 0..127, page 0..3 (8 px rows), w 1..128, h 1..4, w*h <= 256
 *   cmd 02  LED frame: 80 bytes (LED colour codes 0..127), one per LED index
 * 7-bit packing: groups of 8 MIDI bytes; the first holds bit 7 of the next 7 data bytes
 * (bit k -> data byte k). Regions are handed to the stock code through the same RAM buffers a
 * native 0xe0 display report / 0x80 LED report would fill, so the firmware does the rest. */
static void sysex_done(void)
{
    struct state *s = ST;
    const u8 *b = s->sx;
    u32 n = s->sxn, i;
    if (n < 4 || b[0] != 0x7D || b[1] != 0x4D || b[2] != 0x4B) return;
    if (b[3] == 1 && n >= 8) {
        u32 x = b[4], page = b[5], w = b[6] + 1u, h = b[7] + 1u, cnt = w * h, k = 0;
        if (x + w > 128 || page + h > 4 || cnt > 256 || DISP_FLAG || DISP_BUSY) return;     /* (a host paces its regions: one that arrives while the last is still being sent is dropped) */
        for (i = 8; i < n && k < cnt; i += 8) {
            u32 j;
            for (j = 1; j < 8 && i + j < n && k < cnt; j++, k++)
                DISP_DATA[k] = (u8)((b[i + j] & 0x7F) | (((b[i] >> (j - 1)) & 1) << 7));
        }
        if (k < cnt) return;                 /* truncated message */
        DISP_HDR[0] = (u8)x; DISP_HDR[1] = 0; DISP_HDR[2] = (u8)page; DISP_HDR[3] = 0;
        DISP_HDR[4] = (u8)w; DISP_HDR[5] = 0; DISP_HDR[6] = (u8)h; DISP_HDR[7] = 0;
        DISP_FLAG = 1;
    } else if (b[3] == 2 && n >= 4 + 80) {
        for (i = 0; i < 80; i++) led_host_set(i, b[4 + i]);
        led_flush();
    } else if ((b[3] >= 0x10 && b[3] <= 0x17) || (b[3] >= 0x1C && b[3] <= 0x1F)) {
        req_start(s, b + 3, n - 3);
    }
}

static void sysex_feed(u8 c)
{
    struct state *s = ST;
    if (c == 0xF0) { s->insx = 1; s->sxn = 0; }
    else if (c == 0xF7) { if (s->insx) sysex_done(); s->insx = 0; }
    else if (c & 0x80) s->insx = 0;          /* any other status byte aborts */
    else if (s->insx && s->sxn < sizeof s->sx) s->sx[s->sxn++] = c;
}

/* USB-MIDI packets start with a byte < 0x10 (cable 0); NI's own OUT reports start with
 * 0x80 / 0xe0 / 0xf3 / 0xf4 and still go to the original parser.
 * Note On/Off: on cfg.led_channel note n (< 80) drives LED n; on cfg.channel the pad note
 * pad_note[p] drives LED pad_led[p]. The velocity is the firmware's LED colour code
 * (colour = vel >> 2, brightness variant = vel & 3); velocity 0 or Note Off turns the LED off.
 * CC on cfg.channel: the CC number a button sends lights that button's LED.
 * Every LED message updates the shadow in ST->led[] and the whole shadow is written out (see led_flush()). */
static void rx_handle(void);
void mmk3_rx(void) { rx_handle(); }                 /* (the stock OUT callback's call; usb.c calls the static one) */
static void rx_handle(void)
{
    const struct cfg *c = state()->cfgp;
    u32 n = RX_LEN, i, any = 0;
    if (!n || RX_BUF[0] >= 0x10) {
        ((void (*)(void))STOCK(0x08008799))();
        return;
    }
    for (i = 0; i + 4 <= n; i += 4) {
        u8 cin = RX_BUF[i] & 15, st = RX_BUF[i + 1], note = RX_BUF[i + 2], vel = RX_BUF[i + 3];
        if (cin == 0xF) {                    /* single-byte real-time messages: counted here, acted on by the main loop (clock_tick) */
            struct state *s = state();
            if (st == 0xF8) { s->ext_in++; s->ext_any = 1; s->ext_ms = MS16; }
            else if (st == 0xFA || st == 0xFB) s->ext_go++;
            else if (st == 0xFC) s->ext_stp++;
        } else if (cin >= 4 && cin <= 7) {          /* SysEx start/continue (3 bytes) or end (1..3 bytes) */
            u32 cnt = cin == 4 ? 3 : cin - 4, k;
            for (k = 0; k < cnt; k++) sysex_feed(RX_BUF[i + 1 + k]);
        } else if (cin == 0xB && (st & 15) == (c->channel & 15)) {
            /* CC feedback: the CC a button sends lights that button's LED (0 off, else dim/normal/bright) */
            u32 b;
            for (b = 0; b < 39; b++) {
                if (c->btn_act[b] == ACT_CC && c->btn_cc[b] == note) {
                    led_host_set(b, vel == 0 ? 0 : vel < 43 ? 0x7C : vel < 86 ? 0x7E : 0x7F);
                    any = 1;
                    break;
                }
            }
        } else if (cin == 8 || cin == 9) {
            u8 ch = st & 15, led = 0xFF, v = (cin == 9 && vel < 0x80) ? vel : 0;
            if (ch == (c->led_channel & 15)) {
                if (note < 80) led = note;
            } else if (ch == (c->channel & 15)) {
                u32 p;
                for (p = 0; p < 16; p++) if (c->pad_note[p] == note) { led = c->pad_led[p]; break; }
            }
            if (led < 80) { led_host_set(led, v); any = 1; }
        }
    }
    if (any) led_flush();
}

#include "hal.c"
#include "usb.c"
#ifdef NATIVE
#include "native.c"
#endif
