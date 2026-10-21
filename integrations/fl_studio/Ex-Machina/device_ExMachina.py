# name=Ex-Machina (Maschine Mikro MK3)
# supportedDevices=Maschine Mikro MK3
"""FL Studio device script for a Maschine Mikro MK3 running the Ex-Machina firmware with its 'FL Studio' preset.

Install: copy this folder to Documents/Image-Line/FL Studio/Settings/Hardware/Ex-Machina/ (integrations/fl_studio/install.sh does it), then in
FL Studio: Options > MIDI Settings, pick the Mikro as input, Controller type "Ex-Machina (Maschine Mikro MK3)", and give the input and the
Mikro's output the same port number (the script talks back through it). Design and button map: docs/fl-studio.md in the Ex-Machina repository."""
import exm_core

ctl = exm_core.Controller()

def OnInit(): ctl.init()
def OnDeInit(): ctl.deinit()
def OnMidiMsg(event): ctl.midi(event)
def OnSysEx(event): ctl.on_sysex(event)
def OnIdle(): ctl.idle()
def OnRefresh(flags): ctl.dirty = True
def OnDoFullRefresh(): ctl.refresh(full=True)
def OnUpdateBeatIndicator(value): ctl.beat_indicator(value)
def OnProjectLoad(status): ctl.dirty = True
