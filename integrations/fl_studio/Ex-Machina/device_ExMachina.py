# name=Ex-Machina (Maschine Mikro MK3)
# supportedDevices=Maschine Mikro MK3
"""FL Studio device script for a Maschine Mikro MK3 running the Ex-Machina firmware with its 'FL Studio' preset.

Install: copy this folder to Documents/Image-Line/FL Studio/Settings/Hardware/Ex-Machina/ (integrations/fl_studio/install.sh does it), then in
FL Studio: Options > MIDI Settings, pick the Mikro as input, Controller type "Ex-Machina (Maschine Mikro MK3)", and give the input and the
Mikro's output the same port number (the script talks back through it). Design and button map: docs/fl-studio.md in the Ex-Machina repository."""
import exm_core

ctl = exm_core.Controller()

def guarded(fn):
    """Every FL callback goes through this: an error in the script (a new FL version, an untried case) must not leave the controller dark. The script
    then stands down for good (until it is reloaded): the device leaves host mode, its pads are its own again, the screen says what happened, and
    FL gets the controller's MIDI as from a plain MIDI controller. The error and its traceback go to View > Script output."""
    def run(*a):
        if ctl.broken: return
        try: fn(*a)
        except Exception:
            import traceback; traceback.print_exc()
            ctl.fail()
    return run

OnInit = guarded(lambda: ctl.init())
def OnDeInit():                                       # (also after an error: the device must leave host mode when FL lets the script go)
    try: ctl.deinit() if not ctl.broken else ctl.sysex(exm_core.out.host(0))
    except Exception: pass
OnMidiMsg = guarded(lambda event: ctl.midi(event))
OnSysEx = guarded(lambda event: ctl.on_sysex(event))
OnIdle = guarded(lambda: ctl.idle())
OnRefresh = guarded(lambda flags: setattr(ctl, 'dirty', True))
OnDoFullRefresh = guarded(lambda: ctl.refresh(full=True))
OnUpdateBeatIndicator = guarded(lambda value: ctl.beat_indicator(value))
OnProjectLoad = guarded(lambda status: setattr(ctl, 'dirty', True))
