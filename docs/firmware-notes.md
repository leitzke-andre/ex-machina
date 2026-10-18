# Firmware notes (Stage 1: updater triage)

Source: `proprietary/MM3_FWUpdater_120_Mac.zip` (x86_64 Mach-O) and `..._Win.zip` (PE32). Both contain the same image. Reproduce with `tools/carve_fw.py` (carved file is NI's property: keep it out of the repo) and `tools/scan_updater.py`.

## Result: Gate A passes
- The firmware is embedded **in plaintext** (no encryption; only the small `.data` section is RLE-compressed by the compiler's startup code) in the updater binary's `__TEXT,__const`. It starts at file offset `0x22d570` and is **40,392 bytes (`0x9dc8`) long**, ending at flash address `0x0800cdc8`. The Windows exe has the same vector table at offset `1774208`.
- **Correction:** my first carve ran to the end of `__const` (207,504 bytes), but everything after image offset `0x9dc8` is unrelated updater data (C++ type info, fonts). `tools/carve_fw.py` now carves exactly `0x9dc8` bytes.
- It is ARM Thumb-2 (Cortex-M) code linked for flash at `0x08000000`: SP `0x20001c18`, reset `0x080031c1`. Flash addresses like `0x0800xxxx` match an STM32-style part; see "Flash map and MCU" below for the identification (STM32F103RB class).
- Not yet checked: whether the DFU protocol validates a signature or CRC on upload. The image has no obvious header or trailer; the DFU exchange must be observed (Stage 2).
- The image length (0x9dc8) equals the size the updater passes to its DFU writer (`flashFirmwares`), and the load address `0x08003000` is consistent with the descriptor pointers, the boot-flag table and the settings-page code, so this is the complete application image. The bootloader below it is not part of any file we have.

## USB descriptors (from image offset `0x5d5c`)
| Item | Value |
|---|---|
| Device | USB 2.0, class `EF/02/01` (IAD composite), EP0 64 B, VID `0x17cc`, PID `0x1700`, bcdDevice `0x0052` |
| Config | 59 bytes, 2 interfaces, bus powered, **MaxPower 480 mA** (`0xF0`) |
| Interface 0 | HID (class 3), no boot protocol; EP `0x81` IN interrupt 64 B and EP `0x01` OUT interrupt 64 B, interval 10 |
| Interface 1 | DFU runtime (class `FE`/1/1), bitmask `0x09`, detach timeout 255 ms, transfer size 64 |
| Strings | "Native Instruments", "Maschine Mikro MK3", "Maschine Mikro MK3 HID", "Maschine Mikro MK3 DFU" |

**There is no MIDI or Audio-class interface in the stock firmware**, which confirms why every community driver reads HID and synthesizes MIDI on the host. The device is full-speed (64-byte endpoints) and carries display/LED data over the same HID endpoints.

## HID report descriptor (495 bytes at image offset `0x5e4d`, flash `0x08008e4d`; vendor page `0xFF01`)
Report IDs seen: `0x01` (buttons 48 bits, encoder 4 bits, 16-bit touch-strip value), `0x02` (63-byte pad data), `0x80` output (80-byte LED data), `0xd0`/`0xd1` and `0xd8`/`0xd9` feature reports, `0xe0`/`0xe1`/`0xf0`/`0xf3`/`0xf4`/`0xf8` further output/feature reports. A proper decode against the community drivers is still to do.

## Implications for the goal
- Class-compliant MIDI means **replacing the USB stack**: swap interface 0 (HID) for a USB MIDI Streaming interface, and re-map what the scan code produces. Only 2 interfaces and ~60 bytes of descriptors, so a descriptor patch is small.
- Keep interface 1 (DFU) so the stock updater and NI software can still restore the device.
- Power: 480 mA requested. iOS adapters typically supply much less, so lower the request and limit LEDs (to be tested).

## Ghidra import (Stage 3 start)
- Ghidra 12.1.4 is already installed via Homebrew. Import the carved image as raw binary, language `ARM:LE:32:Cortex`, **base address `0x08003000`**.
- Evidence for the base: the reset handler `0x080031c1` lands at image offset `0x1c0`, right after a ~0x1c0-byte vector table, and the config-descriptor pointer `0x08008d66` (image offset `0x5d66` + base) appears as a literal at image offset `0x55c4`. So the application starts at `0x08003000` and the bootloader likely occupies `0x08000000-0x08002fff` (12 KB). The bootloader is not in this image.
- Auto-analysis finds few functions on its own (183); `tools/ghidra/Dis.java` force-disassembles `push {..,lr}` prologues. Both scripts are Java because headless Ghidra here has no PyGhidra. Run with `analyzeHeadless <projdir> mm3 -process cand_fw.bin -noanalysis -scriptPath tools/ghidra -postScript Dis.java`.
- Early helper: `FUN_0800859c` (Device_Property.Init) copies byte 7 of the config descriptor (`bmAttributes`) into the device-state struct. The whole USB stack is mapped in the next sections.

## MCU identification (from peripheral base addresses in literal pools)
USB full-speed device registers (`0x40005c00`, packet memory `0x40006000`), RCC `0x40021000`, flash interface `0x40022000`, GPIOA/B/C at `0x40010800/0x40010c00/0x40011000`, ADC1 `0x40012400`, DMA1 `0x40020000`, SPI2 `0x40003800`, IWDG `0x40003000`. That is the **STM32F1 register map** (a USB-device part such as F102/F103, or a pin-compatible clone), 72 MHz Cortex-M3. This is an inference from the firmware only; confirm by reading the chip marking in Stage 2.
Consequences: the USB peripheral has only 8 endpoints and 512 B of packet memory, which is enough for one MIDI streaming interface next to the DFU interface. STM32F1 also has a mature TinyUSB/libopencm3 USB-MIDI path for a clean rewrite.

## USB stack map (Stage 3, addresses in the `0x08003000`-based Ghidra listing)
Decompiled code is NI's and stays out of the repo; regenerate it with `tools/ghidra/DecAll.java`.

The firmware uses ST's standard **STM32 USB-FS-Device library** (the `usb_int.c` / `usb_core.c` code), not a custom stack. That is good news: its structure is well known, and TinyUSB or libopencm3 can replace it.

| Address | Role (inferred from the decompile) |
|---|---|
| `0x08008794` | `USB_LP_CAN1_RX0` interrupt entry (vector 36). `USB_HP` (vector 35) is `0x0800863c`. |
| `0x080086ec` | Library interrupt dispatcher: handles RESET, SUSP, WKUP, SOF, ESOF, then CTR (endpoint transfer complete). Endpoint 0 goes to the control handlers; other endpoints jump through two callback tables (IN callbacks at table+0x10, OUT at table+0x2c), as in the ST library. |
| `0x08007a7c` | Setup-packet handler for EP0 (`Setup0_Process`): reads the 8-byte setup packet from the packet memory (PMA). |
| `0x08005448`, `0x080069bc` | EP0 IN and OUT stage handlers |
| `0x08007e0c`, `0x080074e8`, `0x0800756c` | Reset / suspend / resume helpers |
| `0x0800859c` | Reads `bmAttributes` from the config descriptor into the device-state struct |
| `0x08007890` | Builds the USB serial-number string from the chip's unique ID (hex to UTF-16) |
| `0x08008b80` | Copy into PMA (`UserToPMABufferCopy`) |
| `0x080085d4` | Queue a buffer on EP1 IN and set the endpoint to TX-valid |
| `0x080089b4` | If configured and EP1 TX idle: dequeue up to 64 bytes from the report ring buffer and send via `0x080085d4` |
| `0x08008a38` | Enqueue into the **0x500-byte TX ring buffer** (the dequeue is `0x080089f0`) |
| `0x08004620` | **Main service routine** (1) processes received OUT data and (2) builds the input reports and enqueues them |

### How reports flow
- **Input to host:** `0x08004620` checks per-report "dirty" flags. Report `0x01` is 13 bytes (buttons, encoder, touch strip, copied from a state array at struct offset `+0x2dd`). Report `0x02` is 63 bytes of pad state (from `+0x2ea`). Each is enqueued into the ring buffer with `0x08008a38`, then drained 64 bytes at a time by `0x080089b4`.
- **Output from host (LEDs/display):** received data sits at struct offset `+0x329`. Packets starting `AA AB AC` / `AA AB AD` are command frames (one form carries 5 parameters into `0x08005490`, another sets a 16-byte table, another passes a pad/LED page of up to 0x50 entries). Other dirty flags handle a 0x80-wide by up to 4-row bitmap region (copied to `+0xca` + `0x80*row`, which is almost certainly display data), a brightness value (range 0-10), and a backlight-style value.
- So one HID endpoint pair carries everything: input events in, LED/display frames out.

## Startup data and USB property tables (decoded)
The toolchain is Keil/ARM (`__scatterload`). The scatter table at flash `0x0800cd00` has two regions: a **compressed** 0x1c0-byte `.data` image at `0x0800cd20` (handler `0x08003234` is a simple RLE decompressor) copied to RAM `0x20000000`, and a 0x1a58-byte zero-init region at `0x200001c0`. I reimplemented the decompressor in Python (see `tools/decompress_data.py`) and got the initialized tables, which match ST's library structures exactly:

| RAM | Content |
|---|---|
| `0x20000010` | EP1..7 **IN** callbacks: all `0x08006471` (no-op). IN data is sent by polling in the main loop, not from the callback. |
| `0x2000002c` | EP1..7 **OUT** callbacks: EP1 = `0x08004a4d`, i.e. `FUN_08004a4c` (double-buffered OUT receive, then hands data to the service routine) |
| `0x20000080` | Descriptor table: device `0x08008d54`/18 B; config `0x08008d66`/59 B; HID report `0x08008e4d`/495 B; HID descriptor `0x08008d78`/9 B; string 0 `0x08008da1`/4 B; manufacturer `...da5`/38 B; product `...dcb`/38 B; serial (RAM `0x20000048`)/18 B; HID string `...df1`/46 B; DFU string `...e1f`/46 B |
| `0x200000d4` | `DEVICE_PROP`: Init `0x0800859d`, Reset `0x080084d1`, status in/out `0x08008599`/`0x0800859b`, **Class_Data_Setup `0x08008139`**, **Class_NoData_Setup `0x0800846d`**, Get_Interface_Setting `0x08008459`, GetDeviceDescriptor `0x08008411`, GetConfigDescriptor `0x08008405`, GetStringDescriptor `0x08008439`, max packet `0x40` |

### Endpoint setup (`Reset`, `0x080084d0`)
- EP0 is control (`0x200`), 64 bytes.
- EP1 is type `0x600` (**interrupt**), TX buffer at PMA `0xc0`, RX at `0x100`, 64 bytes each way, then both directions set to NAK/valid as needed.
- **Bulk conversion is a one-constant change:** the `SetEPType(1, 0x600)` argument becomes `0x000` (`EP_BULK`). No other endpoint-type code is involved.

### Class request handling (what has to go or stay)
- `Class_Data_Setup` serves `GET_DESCRIPTOR` for the HID report (0x22) and HID (0x21) descriptors, and HID `GET_REPORT`/`SET_REPORT` feature reports with IDs `0xd0-0xd7`, `0xd8`, `0xdd`, etc. NI's software uses these feature reports, so they can stay as a separate control-transfer channel, which means **vendor control over EP0 is an option for device configuration** even after the HID interface is replaced.
- `Class_NoData_Setup` handles HID `SET_IDLE`/`SET_PROTOCOL` (`0x21`, requests 0x0b and 0) and the **DFU class request `0x40`/`0x10`** with `wIndex` 0 or 1, which calls `FUN_08004704(1 or 2)`. This is the "enter bootloader/DFU" path used by the updater; it must be left intact.

## Scan-code evaluation (Stage 3)
Addresses are in the `0x08003000`-based listing; decompiled code is NI's and stays out of the repo. "Confirmed" means read directly from the decompile; "inferred" means deduced from behavior and not yet checked on hardware.

### Main loop (`0x08008cf8`)
Init, then forever: kick the watchdog (`0x08005414` writes `0xAAAA` to the IWDG reload key), run the service routine `0x08004620` (USB out/in), then dispatch on a mode byte: **0** = normal scan (`0x080042a0`), 1 = `0x08007af4`, 2 = LED test pattern (`0x080061c8`, steps colors through LED indices), 3 = `0x0800405c` (countdown then a shutdown/transition path). Nothing runs from timer interrupts except the USB ISR and SysTick-style housekeeping, so scan timing is set by the main-loop period.

`0x080042a0` (normal mode) calls, each only when its "dirty" flag is set: pad processing `0x08003970`, encoder `0x0800392c`, buttons `0x080038d0`, touch strip `0x08003ce4`, LED refresh `0x08006028`.

### Inputs and how they are read
| Input | Hardware (confirmed from register use) | Firmware handling |
|---|---|---|
| **16 pads** | ADC1, 16 regular channels scanned by DMA1 into `0x20000718` (16 x u16, 12-bit). Channel order in the sequence: 10, 11, 12, 13, 0, 1, 2, 3, 4, 5, 6, 7, 14, 15, 8, 9. | `0x080033a4` sums 5 consecutive scans and stores the average (x/5) at `0x20000758`. `0x08003970` then processes the 16 values (below). |
| **Buttons** | Matrix: 5 columns driven by GPIOB/GPIOC, 8 rows read from GPIOB input bits 8-15 | `0x08007714` steps one column per call, debounces each row byte (stable ~2 scans, cap `0xf0`), stores the inverted state. `0x080077e8` XORs against the last state and sets per-button bytes at struct `+0x8b+ID` via a 40-entry table at flash `0x0800904e`, mapping matrix position to button ID `0x00-0x28`. |
| **Encoder** | Two GPIOB inputs, bits 6-7 (mask `0xc0`), debounced | Same routine; direction events go to `+0xba` (1 or 2) |
| **Touch strip** | External controller on a **bit-banged I2C** bus (start `0x08005300`, write `0x080051dc`, read `0x080050e8`, stop `0x08005374`, transaction `0x08005290`). `0x08007fa4` reads 2 bytes then 5 bytes. | Up to 2 touch positions and a pressure byte are filtered (jitter below 11 counts is treated as noise, 3 consecutive confirmations) and stored at `+0xc4`, `+0xc5`, `+0xc6`, then sent in report `0x01`. |

### Pad algorithm (`0x08003970`) - the core of a MIDI patch
All of the hard work for pads is already done in firmware, before the HID report is built:
1. **Linearization:** a 16-segment piecewise-linear curve turns the raw ADC value (threshold about 300) into a value that grows up to `0x10b3+`, then subtracts a per-pad offset (bytes at `0x20000xxx+0x10`, apparently calibration) and a global threshold, and clamps at **`0xfff` (12-bit)**.
2. **Event state machine per pad** (state in an 8-byte-per-pad table starting at struct `+8`): it tracks a rising peak and emits events of three bytes `[pad index, (type<<4)|value>>8, value&0xff]` into the report-2 buffer at struct `+0x2ea`, then sets `+0x2ce`:
   - type `0x0`: pad hit, value = peak pressure (used as velocity) - emitted when the peak exceeds threshold 1 (`base+100`)
   - type `0x1`: hit above the higher threshold 2 (`base+200`) - probably the "hard hit" variant
   - type `0x4`: continuous pressure update (value changed, at most every 30 scans per pad) - a natural source for **polyphonic aftertouch**
   - type `0x3` / `0x2`: release, sent after the pad reads 0 for 8 scans; `0x3` follows a type-`0x1` hit and `0x2` a type-`0x0` hit
   The type meanings were first inferred from the state transitions and are now **confirmed**: three community drivers name them NoteOn `0x10`, NoteOff `0x30`, Aftertouch `0x40`, PressOff `0x20`, PressOn `0x00`, and all use velocity = value >> 5.
3. Up to 19 events per report (57 bytes of 63), remaining bytes zero-filled.

### What this means for the MIDI patch
- **Best hook:** translate the events right where the firmware writes them: in `0x08003970` the store `*puVar8 = pad; puVar8[1] = ...` happens in 6 places, or (simpler and less invasive) in `0x08004620` where the report-2 buffer is copied to the ring buffer (`+0x2ea`, 0x3f bytes, flag `+0x2ce`). A small routine can loop over the 3-byte events and emit USB-MIDI packets: type 0/1 -> Note On (velocity from 12-bit peak >> 5, clamped to 1-127), type 2/3 -> Note Off, type 4 -> Polyphonic Key Pressure.
- **Buttons/encoder/strip:** the button bytes at `+0x8b+ID` and the 13-byte report-1 buffer at `+0x2dd` can be diffed and sent as Note or CC messages. The strip (two touches plus pressure) maps naturally to CC / pitch bend. The 4-bit encoder value (a relative counter in report 1) can be sent as relative CC.
- **Velocity quality:** 12-bit peak values leave plenty of headroom for a 7-bit velocity, and a user-tunable velocity curve can live in a small table in flash or RAM.
- **Timing:** the loop has no fixed period. Pad latency is dominated by the peak-detect wait (about 6 to 60 scans, depending on how fast the pad rises); the existing behaviour would carry over unchanged, so latency should match the stock HID path.
- **Not touched:** ADC/DMA setup, linearization tables, debouncing and the strip's I2C protocol all stay as they are. That is the main argument for patching the stock image instead of a clean-room rewrite: the analog front end and calibration tables are the hardest part to get right.

### Emulated result (Unicorn)
`tools/emu/emu_pad.py` runs the stock pad routine with synthetic ADC input and confirms the event semantics: type `0x1` = percussive hit reported at its peak, `0x0` = slow press reported at its current value, `0x3`/`0x2` = releases (matching the hit type), `0x4` = pressure change (only sent while value changes, at most every ~30 scans). Per-pad timing counters are incremented by the SysTick handler (`0x08007ed4`), so any test harness must simulate them.

### Firmware settings page
`FUN_08004704` and `FUN_080049a0` read and write a **1 KB settings page at flash `0x0801F000`** (erase, then program 4 bytes at a time with read-back verify); output/feature reports with IDs 0xd0-0xdd, 0x40 and 0x80 fill RAM copies that are flushed there (16 pad-offset bytes at page offset `0x200`, 0xc6 bytes at `0x0`). This shows the flash is at least 128 KB, the page size is 1 KB (STM32F1 medium density), and the app uses about 40 KB out of roughly 100 KB free. It is also the natural place to store a user mapping table.

### Risks and open questions
- Per-pad calibration offsets (bytes at `0x20000010+`) appear to be set at runtime (possibly measured at startup). A patch must not skip that code.
- Not yet read: `0x0800392c` (encoder), `0x080038d0` (buttons to report 1), `0x08003ce4` (strip to report 1), `0x08006028` (LED refresh), `0x08005490` (command dispatcher for host frames `AA AB ...`), and modes 1 and 3. The LED and display side is needed if you want to keep LED feedback.
- Free flash: the image ends at `0x0800cdc8`. I don't know the flash size yet (an STM32F103 has 64 KB or 128 KB), so patch space is unconfirmed until the chip is identified.

## Patch feasibility (what this changes in the plan)
1. **Hook point for MIDI generation:** the state arrays at `+0x2dd` (buttons/encoder/strip) and `+0x2ea` (pads) that feed reports `0x01`/`0x02`. A patch can compare them to the previous state and emit MIDI events instead of (or as well as) HID reports.
2. **Descriptors:** the config descriptor must grow from 59 to about 100+ bytes (AudioControl + MIDIStreaming + two bulk endpoints). The existing descriptor block at image `0x5d5c-0x5e4b` has no room, so the patch needs to relocate descriptors to free flash and update the pointers in the library's property table. `bNumInterfaces`, `wTotalLength` and the string table also change.
3. **Endpoint type:** EP1 is an **interrupt** endpoint now and USB-MIDI wants **bulk**. The change is one constant in `Reset` at `0x080084d0` (see above).
4. **Sending MIDI:** reuse the existing EP1 IN path (`0x080089b4`). MIDI event packets are 4 bytes, so they fit the same ring buffer with a different framing.
5. **Reception:** EP1 OUT callback would need to accept MIDI from the host (optional) instead of LED/display frames. LED and display control would be lost unless the patch keeps a second channel, e.g. vendor SysEx into the same parsing code (`0x08004620`).

Open items: the LED/display command path (`0x08005490`) and the button/encoder/strip report packing that fills the state arrays (probably ADC and DMA based, given the DMA1/ADC1 use and the touch strip).

## LED and display command path (Stage 3, done)
Host OUT reports are demultiplexed by `FUN_08008798` on their first byte: `0x80` (LED frame, 80 colour codes), `0xe0` (display region, 8-byte header + up to 256 pixel bytes), `0xf3`/`0xf4` (brightness/settings), anything else ignored. The LED frame sets `+0x2cf`, the display region `+0x2d0`, and the main-loop service routine `0x08004620` applies them (`FUN_08005490` per LED; a copy loop into the 128 x 4-page framebuffer at `struct+0xca`). LED and display details, the index map and palette are in `docs/midi-patch.md` ("Display and LEDs").

## How the stock code sends the framebuffer to the display (found 2026-10-20: a flickering bar on the real screen)
The display apply routine (`0x08003f34`) copies the staging buffer into the framebuffer (struct + 0xca, 512 bytes) and then sets the sender's counter, `struct + 0xc8` (`0x200010F0`): **8 if it was 0, else it ORs in 0x80**. The sender (`0x080068b0`, one call per main-loop pass) sends **one 64-column chunk per call** over SPI2 and decrements the counter; `counter mod 17` picks the chunk (2..8 = the first seven chunks, anything else = the last one, page 3 columns 64-127), and the data pointer (`[0x20000188]`) is simply advanced by 64 on every call except for the first chunk, which resets it to the framebuffer. A clean refresh (counter 8 down to 1) is therefore 8 chunks in order. If a second region is applied while the counter is still running, bit 7 is set and the counter then counts down from 0x88 or so: **about 9 passes of the last chunk with a pointer that moves through the whole framebuffer and on past its end (RAM that is not picture), then more cycles that repeat the last chunk ten times in seventeen** - on the screen a block 64 pixels wide and 8 high at the bottom right that flickers for a moment (the user saw it with every message since the first generation that wrote the screen; host regions paced at 10 ms or more never showed it). `translate.c` writes a region only when the counter is 0 (`DISP_BUSY`) and drops a host region that arrives while it is not; `test_display_race.py` models the sender (one chunk per pass) and fails on the old behaviour (11 regions applied while it was busy).

## How the stock main loop applies LED and display commands (read for the LED race, 2026-10-17)
- LED frame (`0x08003e88`, called from the service routine at `0x0800468a`): `if (flag +0x2cf) { flag = 0; ... }`, **then** the 80 entries at `+0x329` are read one by one. If entries 0..2 are `AA AB AC` the buffer is a raw command instead; otherwise each entry `< 0x80` is applied with `FUN_08005490(index, code, 0, 0)` (RAM only: it fills the LED matrix at `0x20000f06` and sets dirty bits) and entries `>= 0x80` (0xFF) are skipped. At the end it sets a countdown of 10 at `+0xbc` (the chips are refreshed later). So the flag is not an interlock for the buffer: anything written while a pass is running can be half-read.
- Display region (`0x08003f34`): the same shape, `if (flag +0x2d0) { flag = 0; read header at +0x379, then the pixel bytes at +0x381 ... }`.
- Startup (found 2026-10-17 when the resting LEDs of the patch vanished on the real device; traced in the emulator with the real code, `tools/midi_patch/test_startup.py`): while the countdown at struct+2 is not 0, every service pass calls `0x08008c34`. Once per millisecond it either waits (`struct+0xbe`, a small timer) or calls `0x0800615c`, which plays the next of 27 animation steps: it takes 5-byte entries from the table at `0x0800bd68` and sets raw LED matrix cells through `FUN_08005490(index | 0x80, ...)`, then arms the chip refresh (`+0xbc` = 10) and a 60 ms timer. When the 27th step is done (about 150 ms + 27 x 60 ms, 1.7 s in the emulator) it **sets the countdown to 0 itself** (the 6000 ms is only the timeout), runs `0x080066ae` (SSD1306-style display commands `0x8d`, `0x14`, `0xaf`: charge pump and display on), clears a few state bytes and ends with `0x08008664`, `0x08008a84`, `0x080089a8`. The animation's last steps leave every LED matrix cell at 0, and nothing re-applies the LED buffer afterwards (its flag is 0), so LEDs lit before the end of the startup are dark after it until the next LED frame. Pads, buttons and the encoder are ignored until the countdown is 0 (mode dispatch only then).

## DFU and image facts (from the updater, Stage 1b)
`MM3UpdaterUpgradeLogic::flashFirmwares` calls `DFUDevice::writeImage(image, 0x9dc8, status)`: the firmware is exactly 40,392 bytes, sent raw with standard DFU DNLOAD blocks (block size taken from the DFU descriptor, 64 B), a zero-length DNLOAD to finish, then GETSTATUS polling and a return to application mode. No header, suffix or CRC is added by the host. What the bootloader itself verifies is not known yet.

## Flash map and MCU (new facts from the firmware itself)
| Flash | Content |
|---|---|
| `0x08000000-0x08002FFF` | bootloader (12 KB, not in any file we have) |
| `0x08003000-0x0800CDC7` | application (40,392 bytes), `.data` at `0x0800CD20` (compressed) |
| `0x0801F000` page A | settings: 0xc6 bytes of per-LED brightness trim at +0x000, 16 pad offsets at +0x200 (default 100 when blank) |
| `0x0801F800` page B | feature-report blocks (256 + 256 bytes), serial/ID bytes at +0x3ec, firmware version `0x0052` at +0x3fe; blank pages are filled from ROM defaults at `0x08009992` / `0x08009a92` |
| `0x0801FC00` | **bootloader handshake page**: to enter DFU the app writes the 8 bytes `55 5a a5 aa 59 95 3a a3` (ROM `0x0800903c`) here and issues `NVIC_SystemReset` (`FUN_0800360c`, called from the mode-3 path armed by DFU_DETACH) |
| `0x0801F400` | not referenced by any code seen |

The MCU is an STM32F1 with USB device, 1 KB flash pages (page size in the programming code), and the flash reaches `0x08020000` (the handshake page), so **128 KB = STM32F103xB class (RAM 20 KB)**. ADC1 scans channels 0-15 including 10-15 (PC0-PC5), which exist only on 64-pin packages, so most likely STM32F103RB (LQFP64) or a pin-compatible clone. This replaces the earlier assumption and makes the free flash (`0x0800CDC8-0x0801EFFF`, about 77 KB) and RAM (`0x20001C18-0x20004FFF` free) assumptions of the patch concrete. Stack: `0x20001818-0x20001C18` (1 KB; the stock struct at `0x20001028` ends exactly at `0x20001818`).

ROM default settings (used when page B is blank): block 1 begins `01 00 00 17 0a 50`, i.e. brightness 10 and **sensitivity 0x50 = 80**, which `FUN_080046b8` turns into the pad threshold `(100 - 80) * 6 = 120` (`0x2000014a`). NI's software changes these via feature reports `0xd0-0xdd`.

## Boot sequence and timing
Main (`0x08008cf8`): board init (`0x08007ea2`), stage-2 init (`0x08008bac`: sensitivity, LED chips, ...), watchdog setup, then a loop of `{kick watchdog, service routine}` that only reaches the mode dispatch once the countdown at struct+2 (set to **6000 ms** by stage 2, decremented in SysTick) reaches zero. So the stock device does not scan pads, buttons or the encoder until that countdown is 0, which the LED fade-in ends early (about 1.7 s in the emulator, 6 s at the latest; see the LED section above). SysTick reload is HCLK/16000 (4500 for 72 MHz) on HCLK/8, i.e. 0.5 ms; its body runs every second tick, so the per-pad timers (`+0xc`) count milliseconds. The hit detector therefore waits at least 6 ms after touch before reporting a hit, and releases need the pad to read 0 for about 8 passes.

## Updater logic (`MM3Updater`, from decompiling the Mac binary)
- Detection: it looks for the device by VID/PID `17cc:1700`, and for DFU mode PID+2 (`1702`).
- Version: **update is offered only when the device's bcdDevice < `0x0052`** (`MM3UpdaterUpgradeLogic::getDeviceInfo`); the stock firmware reports exactly `0x0052`, shown as "0.5.2".
- DFU interface: found by scanning the configuration descriptor for class `0xFE`, subclass 1, protocol 1 (runtime) or 2 (DFU mode) followed by a DFU functional descriptor; the interface number is taken from the descriptor, so moving it (interface 1 -> 2) is fine. With bmAttributes bit 3 (WillDetach) set it sends standard `DFU_DETACH` (`bmRequestType 0x21`, `bRequest 0`, wValue = timeout, wIndex = interface); otherwise an XMOS-style vendor request (not used here).
- Download: standard DFU 1.1 DNLOAD in wTransferSize (64) blocks, zero-length DNLOAD to finish, GETSTATUS polling (states 4 DNBUSY, 5 DNLOAD-IDLE, 6/7/8 manifest), return to application mode with DETACH. No upload, no host-side CRC or header.

## Research cross-check
Community drivers (r00tman, essaim-dev, flokapi/pymikro) and NI's manual independently confirm the HID report layouts, pad numbering, event types, LED index map and palette, strip semantics (0 = untouched), display polarity and NI's MIDI-mode defaults; the sources and what each established are in `docs/research-sources.md`. Where they disagreed with earlier notes (the "touch present" bit is really encoder touch, velocity shift 5 not 3, inverted display pixels), the notes and code were corrected.

## Current state
A complete, emulator-tested MIDI patch exists; see `docs/midi-patch.md` for design, build and test commands and open risks, and `docs/hardware-plan.md` for the staged flashing plan.

## Next (software-only candidates)
Config tool and persistence; display text (needs a font); a lower-latency hit-detector variant; extending the USB model to a full macOS/Linux host-side parser if one can be had without hardware.
