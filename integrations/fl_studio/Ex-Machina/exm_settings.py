"""Settings of the Ex-Machina FL Studio script: edit the values here (in FL's Hardware folder) and reload the script (MIDI Settings > Update MIDI scripts)."""

STEP_VELOCITY = True            # a step set from a pad takes the pad's velocity (a hard hit makes an accent); False: FL's default velocity
FOCUS_WINDOWS = True            # Step / Select / Mute / Solo / Pattern bring the Channel Rack to the front, Group the Mixer, Plug-in the plug-in's window
GRAPH_EDITOR = True             # editing a held step with the encoder opens FL's graph editor on that parameter
LOOP_RECORD_ON_CONNECT = False  # switch FL's loop recording on when the script starts (as FLkey does); off by default: it changes a setting of FL's
SCORE_LOG_SECONDS = 300         # Shift + Play: how much of what was just played goes into the pattern
MESSAGE_SECONDS = 1.5           # how long a value or a message stays on the screen
STRIP_BAR = True                # the touch-strip LEDs show the encoder's value, or the song position while FL plays
HINT_BAR = True                 # messages also go to FL's hint bar
