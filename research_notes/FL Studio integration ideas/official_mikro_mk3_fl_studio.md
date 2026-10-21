# Official FL Studio integration of the Maschine Mikro MK3 (and MK3 / Maschine+)

Researched 2026-10-21. Web sources plus a local, read-only inspection of the factory templates in NI's Controller Editor 2.8.2 installer (`proprietary/Controller_Editor_2.8.2_Mac.dmg`, opened with 7-Zip / xar / cpio into the session scratchpad; nothing installed or run). The Controller Editor files are cited as "Controller Editor 2.8.2 factory content", available from [NI's drivers & other files page](https://support.native-instruments.com/support/solutions/articles/69000882238-native-instruments-drivers-other-files).

**Bottom line:** As of 2026 there is no official, vendor-made FL Studio integration for the Maschine Mikro MK3, the Maschine MK3 or the Maschine+. That means no Image-Line device script, no NI script and no NI "FL Studio" Controller Editor template for these devices. The only official path is NI's support article. It uses the generic **Mackie Control** Controller Editor template plus FL's **Mackie Control Universal** controller type, for transport only. Everything else is community work: an Image-Line forum Controller Editor template, a debug Python script, and a paid Gumroad product. The older Maschine MK1, Mikro MK1 and Maschine Jam did get official "FL Studio" templates.

## 1. Does FL Studio ship a native script for the Mikro MK3 / Maschine MK3, and who provides what?

### Takeaway
No. FL Studio has no built-in device script for any MK3-generation Maschine. Image-Line's controller list names "Maschine Micro MK3" only as a link to a community forum thread, and it says that user scripts are untested by Image-Line. Image-Line's "MASCHINE (& MIKRO)" support from FL 10.5 covers the original Mikro through an `FL Studio.ncm` Controller Editor mapping.

### Cited Findings
- Image-Line's MIDI controllers page lists four Native Instruments entries under "WORKING SCRIPTS": Komplete Kontrol M32 & A Series, **"Maschine Micro MK3"** (linking to forum post p=1438864), a Komplete Kontrol Abstraction Layer (Tool), and Komplete Kontrol A/M/S-Series. The page says that "Scripts provided by fellow FL Studio users are untested by Image-Line" and that Image-Line scripts are posted by staff (red forum name). None of the NI entries is marked as staff-made — [Image-Line: MIDI Controllers](https://www.image-line.com/fl-studio/midi-controllers)
- The linked "Maschine Micro MK3" entry is the thread "MASCHINE MIKRO MK3 (WIP) [SCRIPT]". It was posted by community user **_Ram** on 2019-11-25, last edited 2024-08-18, and its replies run to 2026-03-06. The first post ends hoping "we get official support on this". On 2020-08-21 the author says the file "is not a script": it is a Controller Editor template, and a 2024-06-08 reply (HDSQ) also notes that it is not a MIDI script — [Image-Line forum t=213312](https://forum.image-line.com/viewtopic.php?p=1438864)
- Image-Line's manual page "Preconfigured Controllers" lists "Native Instruments MASCHINE (& MIKRO)" among drum and clip-launch controllers with no model generation, and it does not mention the MK3 or the Mikro MK3. It says that unlisted devices "will likely work" as "(generic controller)" and points to the MIDI Controller Reference forum for the latest list — [FL manual: Preconfigured Controllers](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/automation_devices.htm)
- Image-Line's "Manufacturer: Native Instruments" reference post (Scott, site admin, 2012-01-17) covers only the original **MASCHINE MIKRO**. It says to open `(FL Studio)\System\Hardware specific\Native Instruments MASCHINE MIKRO\FL Studio.ncm` in NI's Controller Editor and that support was added in **FL Studio 10.5 beta**. A 2014-07-26 reply links a user-made Mikro **MK2** mapping — [Image-Line forum p=932083](https://forum.image-line.com/viewtopic.php?p=932083); [same thread, p=635714](https://forum.image-line.com/viewtopic.php?p=635714)
- MIDI scripting (Python device scripts) has existed since FL Studio 20.7, which is what makes community support possible — [FL manual: MIDI Scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm) (via search summary of an Image-Line forum post, [p=1448892](https://forum.image-line.com/viewtopic.php?p=1448892))
- **NI side, Controller Editor 2.8.2 factory content** (local inspection): `FL Studio` templates exist only for `.ncm` (Maschine MK1, `type="Maschine"`), `.ncmm` (Mikro MK1), `.ncmj` (Maschine Jam) and `.nckf1` (Traktor Kontrol F1). The **only** Mikro MK3 template (`.ncmm3`) is `Mackie Control.ncmm3` (`type="MaschineMikroMK3"`). Maschine MK3 (`.ncm3`, `type="MaschineMK3"`) has `Ableton Live 9`, `MCU Transport`, `Mackie Control`, `Mackie Control Light` and `OFF`. Maschine+ (`.ncmp`, `type="MaschinePlus"`) has `MCU Transport`, `Mackie Control`, `Mackie Control Light` and `OFF`. None of the three has an FL Studio template — Controller Editor 2.8.2 installer, `Controller Editor Factory Content Update.pkg` ([NI drivers page](https://support.native-instruments.com/support/solutions/articles/69000882238-native-instruments-drivers-other-files))
- NI's official Maschine Jam article requires FL Studio 12.4+ and Controller Editor 2.0.2: choose "FL Studio" from Factory Templates, and the Jam then "appears automatically as Input and Output device" in FL. Only the Jam is covered — [NI: How to install the Maschine Jam template for FL Studio](https://support.native-instruments.com/support/solutions/articles/69000879818-native-instruments-how-to-install-the-maschine-jam-template-for-fl-studio)
- NI's Maschine 3 update notes (community thread, around 2024) mention FL Studio only as a plug-in host, for HiDPI issues, and say nothing about controller support (search summary) — [NI community: Official update status – Maschine 3](https://community.native-instruments.com/discussion/40)

### Inferences
- "Official FL Studio support" for the Mikro MK3 in practice means: (a) the Maschine 2/3 software as a VST/AU plug-in inside FL, controlled in Maschine mode, and (b) NI's Mackie Control transport recipe in MIDI mode. Image-Line's listing only points to a community Controller Editor template.
- The gap is generational. NI made FL Studio templates for the MK1, Mikro MK1 and Jam, Image-Line did the MK1/Mikro FL 10.5 support, and nothing was made for the MK3 family (2017+). This is consistent with the Controller Editor manual having no Mikro MK3 entry (see `docs/research-sources.md`).

### Gaps
- I found no FL Studio 2024/2025/2026 release note that adds any NI Maschine script. Searches returned nothing, but I did not read every FL changelog, so this is "not found", not "proven absent".
- The image-line.com manual URLs `midi_controllers.htm` and `basics_externalcontrollers.htm` returned 404, so the current MIDI-settings controller-type dropdown was not checked for an NI entry.

## 2. What does each control do in the official integration (NI's Mackie Control route)?

### Takeaway
NI's official recipe gives transport only. In MIDI mode, the Mikro MK3's Mackie Control template sends MCU messages from five buttons: Play, Stop, Restart, Erase and Tap (inferred MCU meanings: Play, Stop, Cycle, Rewind, Fast Forward). FL interprets them as a Mackie Control Universal. Rec, the encoder turn, Shift, the arrows and all mode buttons are disabled. Pads send no notes on the default page A. There is no channel rack, mixer, step-sequencer, browser, plug-in or FPC integration, no screen text and no FL-driven pad colours.

### Cited Findings
- NI's article "Setting up your Maschine controller for Host Transport Control in FL Studio" gives these steps:
  1. In Controller Editor, load the **Mackie Control** factory template and enable **Host Transport Control**.
  2. In FL, insert Maschine as an instrument plug-in.
  3. In Options > MIDI settings, select the Maschine controller as Output and Input (the screenshot uses a Maschine Mikro MK3), set Controller type to **Mackie Control Universal** and click Enable.
  4. MK1, Mikro MK1 and Jam users instead select **FL Studio** under Factory Templates and choose their controller as the Controller type.
  5. The controller drives the Maschine plug-in in Maschine mode. Switching to **MIDI mode** gives Host Transport Control.

  The article lists no limitations and no per-button functions. — [NI support article 69000879800](https://support.native-instruments.com/support/solutions/articles/69000879800-setting-up-your-maschine-controller-for-host-transport-control-in-fl-studio) (older URL: [210305785](https://support.native-instruments.com/hc/en-us/articles/210305785-Setting-up-Your-Maschine-Controller-for-Host-Transport-Control-in-FL-Studio))
- **Mikro MK3 `Mackie Control.ncmm3` contents** (local inspection of the XML):
  - **Enabled buttons:** `Play` = mcu-button 94, `Stop` = 93, `Restart` = 86, `Erase` = 91, `Tap` = 92 (all gate, on press); `Group` = CC 34 (toggle); `Navigation Push` (encoder press) = CC 15 (toggle).
  - **Touch strip:** CC 1, with LED feedback `TouchstripIDX` on CC 1.
  - **Disabled:** every other button, including `Rec` (CC 58), Mute, Solo, Pattern, Scene and the mode buttons; the `Navigation` wheel (encoder turn, default CC 7) and `Navigation Touch`.
  - **Pads, Pad Page A (the default):** the 16 note triggers (notes 12-27) are **disabled**, but per-pad Poly Aftertouch on notes 12-27 is enabled.
  - **Pad Pages B-H:** note triggers 24-39 … 96-111, plus poly AT, are enabled.
  - **Map flags:** `velocitycurve` 3 (Linear) and `handleTransport` 0 in the file. Turning on "Host Transport Control" in the editor presumably changes this flag (unverified).

  — Controller Editor 2.8.2 factory content ([NI drivers page](https://support.native-instruments.com/support/solutions/articles/69000882238-native-instruments-drivers-other-files))
- For comparison, the **Maschine MK3** `Mackie Control.ncm3` additionally maps:
  - the 4-D encoder turn as an `mcu-wheel`, with encoder left/right and the Left/Right buttons as mcu-button 46/47 and encoder push and Follow as 101;
  - Mute = 74 and Solo = 81;
  - Pedal = CC 11 and Group A-H LEDs = CC 100-107.

  The MK3 and Maschine+ `MCU Transport` templates map only Play 94 / Stop 93 / Restart 86 / Erase 91 / Tap 92, encoder-direction LEDs CC 30-33, Group LEDs CC 100-107, pedal CC 11 and strip CC 1 — Controller Editor 2.8.2 factory content (same source)
- NI's MIDI-mode map has **no assignment for the Mikro MK3's arrow buttons or Shift**, and in MIDI mode Shift + encoder adjusts pad sensitivity, display contrast and backlight instead of sending MIDI (this project's Ghidra reading of the Controller Editor; see `docs/research-sources.md`). This matches the community report that "Shift button and the arrow < > buttons are not sending a midi message" — [Image-Line forum p=1942132](https://forum.image-line.com/viewtopic.php?p=1942132)
- MIDI mode is entered with SHIFT + Project, and the device's display shows MIDI event messages (a MIDI monitor), not host information — [NI: Switching your controller to MIDI mode](https://support.native-instruments.com/support/solutions/articles/69000880031-native-instruments-switching-your-controller-to-midi-mode)
- The community author of the Mikro MK3 transport script summarises NI's recommendation as either **Mackie mode**, which loses the drum pads' note use, or a **general controller** template, which has no transport (search and fetch summary of the 2022-08-01 post) — [Image-Line forum p=1942132](https://forum.image-line.com/viewtopic.php?p=1942132). A 2012 thread reports the same trade-off for older Maschines ("the pads will not control any MIDI notes" with Mackie Control Universal); its workaround was two templates switched on the device — [Image-Line forum p=802778](https://forum.image-line.com/viewtopic.php?p=802778) (search summary)
- Templates can be switched on the device in MIDI mode with Shift + Templates (NI community answer, MK3) — [NI community comment 37084](https://community.native-instruments.com/discussion/comment/37084) (search summary)

### Inferences
- The mcu-button values look like MCU note numbers in decimal: 94 = 0x5E Play, 93 = 0x5D Stop, 91 = 0x5B Rewind, 92 = 0x5C Fast Forward, 86 = 0x56 Cycle/Loop, 46/47 = 0x2E/0x2F Bank Left/Right, 101 = 0x65 Scrub. So on the Mikro MK3: **Play → Play, Stop → Stop, Restart → Cycle (FL: probably loop or song/pattern toggle), Erase → Rewind, Tap → Fast Forward**. The decimal-to-MCU reading and FL's exact reaction to 0x56 are **inferred**, not documented by NI. The MK3's Mute = 74 and Solo = 81 do not match MCU Mute/Solo (0x10-0x17 / 0x08-0x0F), so NI's mcu-button enumeration may not be a 1:1 MCU note number for every entry. Treat all of these as unverified.
- **Rec is not mapped** in the Mikro MK3 Mackie template, so the official route has no record button unless the user edits the template.
- Pads: on the default page A, pads send only poly aftertouch (notes 12-27) and no note-ons. This explains the "Mackie mode loses the pads" complaint. Selecting page B-H (Group + pad) gives notes again, starting at 24, which does not match FPC's default 36/C3-based layout. This is inferred from the template, not tested on hardware.
- **Screen and LEDs:** nothing in the official route lets FL write the Mikro MK3 display. The display shows NI's MIDI monitor, and the Controller Editor manual describes button LEDs as unassigned off / assigned dim / on bright, settable by MIDI feedback. MCU LED feedback from FL may light Play/Stop, but I found no documentation that it does on the Mikro MK3, and a community author could not get transport LEDs working (see section 4). There are no channel colours on pads.
- No FL-specific features (channel rack navigation, pattern select, mixer, step sequencer on pads, plug-in parameters, browser, undo, tempo, metronome, mute/solo, FPC mapping) exist in any official integration for the MK3 family.

### Gaps
- NI's article does not describe what each button does in FL. The per-button meanings above come from the template file and MCU convention, not from NI or Image-Line documentation.
- I did not verify which XML changes "Host Transport Control" makes, or whether FL's MCU script sends LED feedback that the Mikro MK3 displays.

## 3. NI Controller Editor template / "MIDI mode" layout for FL Studio for the Mikro MK3

### Takeaway
NI provides no FL Studio template for the Mikro MK3, only the generic Mackie Control one. For the MK1-generation Mikro, the NI/Image-Line `FL Studio` template was a full drum-machine and clip-launcher layout. The MK3 community's substitute is _Ram's 7-bank pad template.

### Cited Findings
- No `FL Studio.ncmm3` (or `.ncm3` / `.ncmp`) exists in Controller Editor 2.8.2. `FL Studio.ncmm` (Mikro MK1) uses buttons as notes on MIDI channel 15 (e.g. Main/"METERS" = note 6, "UP" = note 16, "LEFT" = 18, "RIGHT" = 19), which FL's original MASCHINE MIKRO support interprets — Controller Editor 2.8.2 factory content ([NI drivers page](https://support.native-instruments.com/support/solutions/articles/69000882238-native-instruments-drivers-other-files))
- Image-Line's original Mikro (FL 10.5) mapping:
  - arrows + SESSION navigate the session in performance mode and shift keys in drum mode;
  - SCENE triggers a column of clips, +SCENE adds to the already-triggered clips, SAME MODE limits triggering to clips of the same mode, QUEUE queues;
  - MUTE (tap = all, hold + pad = track); METERS shows activity meters;
  - G SNAP follows FL's global snap;
  - pad pressure: four linkable CCs per track in performance mode, a per-pad CC in drum mode;
  - double-tap SCENE / +SCENE / QUEUE / SNAP to lock.

  — [Image-Line forum p=932083](https://forum.image-line.com/viewtopic.php?p=932083)
- Community Mikro MK3 template ("MASCHINE MIKRO MK3 (WIP)", _Ram): Group + pad selects a bank. The banks are:
  - Bank 1: Serato Sample users
  - Bank 2: FPC
  - Bank 3: FPC at velocity 100-127
  - Bank 4: C5-D#6
  - Bank 5: C5-D#6 at velocity 100-127
  - Bank 6: OMNI channel (Channel Rack one-shots play together)
  - Bank 7: OMNI channel at velocity 100-127

  The jog wheel (encoder) = Undo/Redo. A "V2" was posted 2020-02-16 ("partially mapped"). Transport and other button details are only in images I could not read — [Image-Line forum t=213312](https://forum.image-line.com/viewtopic.php?p=1438864)

### Inferences
- The project's Ex-Machina firmware already exceeds every official MK3 FL option for pads (note 36 base fits FPC) and transport (Play/Stop/Rec). Unlike the Mackie route, it does not need NI's Controller Editor or NI's driver/agent to be running, because NI's MIDI mode runs in the host-side editor process (`docs/research-sources.md`).

### Gaps
- I could not read _Ram's full button / transport map (images, login-restricted replies).

## 4. Known limitations stated in docs and forums

### Takeaway
Limitations stated or reported:
- The official route needs NI's Controller Editor, MIDI mode (SHIFT + Project) and FL's Mackie Control Universal type.
- It is transport only and loses pad notes on the default page.
- Shift and the arrow buttons send no MIDI, and there is no screen integration.
- Transport LED feedback is unresolved even for community scripts.

### Cited Findings
- Community debug script `device_Aram_Debug.py` + `MikroMk3FLStudio.ncc` (user "aram", 2022-08-01):
  - **Setup:** load the .ncc in Controller Editor with a profile set to "Transport + Notes", put the script in FL's `Settings\Hardware` (specific) folder, select the ports and put the device in MIDI Mode.
  - **Open issues:** Shift and the < > arrows send no MIDI; toggling transport LEDs is unresolved (the author asks whether it is MIDI or SysEx).
  - **Author's view:** the vendors are "a bit lazy on the support".

  — [Image-Line forum p=1942132](https://forum.image-line.com/viewtopic.php?p=1942132); [earlier page of the thread, p=1755264](https://forum.image-line.com/viewtopic.php?p=1755264)
- NI's own article states no limitations, but it ties host transport to MIDI mode: the controller controls the Maschine plug-in only in Maschine mode — [NI support article 69000879800](https://support.native-instruments.com/support/solutions/articles/69000879800-setting-up-your-maschine-controller-for-host-transport-control-in-fl-studio)
- An NI community user (not staff) says that Maschine's dedicated functions, including the transport section, are mostly not MIDI-mappable inside Maschine. Deeper "integration" exists only between Maschine and Komplete Kontrol MK2 keyboards — [NI community comment 2211](https://community.native-instruments.com/discussion/comment/2211) (search summary; the page body did not load)
- Retailer and community pages describe the general MK3 + FL workflow as running Maschine as a VST/AU plug-in in FL (multi-out routing, MIDI from FL's step sequencer to Maschine), not as controller integration — [NI community: "The Final Answer! How can i connect Fl studio 21 to maschine mk3?"](https://community.native-instruments.com/discussion/comment/64742/); [zZounds MK3 listing](https://www.zzounds.com/item--NATMASCHMK3)
- A paid third-party product, "FL-MIDI Mode Enhancer RnB vol.1 For the Maschine Mikro", is sold on Gumroad. The page did not render beyond its title, so I could not confirm the device generation, its contents or what it maps — [Gumroad listing](https://uvaiocreative.gumroad.com/l/FL-MIDIModeEnhancerRnBFortheMaschineMikro)

### Inferences
- Everything official depends on NI's host software (Controller Editor / NIHardwareAgent) for MIDI mode, because the stock Mikro MK3 is a HID device. That rules it out on iPad, where FL Studio Mobile also has no controller integrations (`docs/research-sources.md`).
- An FL Studio device script for Ex-Machina would not compete with any official MK3 feature set. The useful precedents are the MK1-era Image-Line Mikro mapping (performance/clip launch, mute via hold + pad, pressure CCs) and the community banks (FPC, omni, undo/redo on the encoder).

### Gaps
- No primary statement from Image-Line or NI explains why MK3-family FL support was never made.
- I found no YouTube or blog walkthrough that verifiably shows an official MK3 → FL mapping beyond NI's transport article.
