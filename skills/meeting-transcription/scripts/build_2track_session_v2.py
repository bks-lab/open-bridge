#!/usr/bin/env python3
"""
Build a Teams 2-Track Audio Hijack session — v2 (splitChannels approach).

Replaces v1 (build_2track_session.py) which used 2 separate Recorder branches.
v2 uses AH 4.5.9's native VoIP-recording pattern: one ApplicationSource with
captureEnabled+splitChannels writes a single stereo MP3 — Mic on Left, App
audio on Right. ffmpeg splits it on the worker side.

Inputs:
  ~/Desktop/Source.ah4session   (an existing exported session: keeps the Teams
                                 sourceAppRef + your output device's deviceArchive)

Outputs:
  ~/Desktop/Teams 2-Track.ah4session  (binary plist, importable)

Layout (5 blocks):
  Application(Teams, captureEnabled=1, splitChannels=1)
       │
       ▼
  LevelMeter ──→ Recorder (stereo MP3 to ~/Recordings/meetings/)
       │
       ▼
  ChannelTweaker (mix to mono for live monitoring)
       │
       ▼
  AudioDeviceOutput (headphones)
"""

import plistlib
import uuid
import os
import datetime

SRC = os.path.expanduser("~/Desktop/Source.ah4session")
DST = os.path.expanduser("~/Desktop/Teams 2-Track.ah4session")
RECORDING_FOLDER = "~/Recordings/meetings"


def new_uuid():
    return str(uuid.uuid4()).upper()


def empty_ui_state():
    return {
        "popoverState": {
            "isShown": False,
            "orientation": 1,
            "position": "{0, 0}",
            "state": 0,
        },
        "selected": 0,
    }


def mp3_format(bitrate=256):
    return {
        "class": "AHMP3RecordingFormat",
        "attributes": {"bitrate": bitrate, "fragmented": True},
    }


def recorder_block(node_uuid, x, y, file_name):
    return {
        "geBlockEnabled": True,
        "geBlockOutputUUIDs": [],
        "geBlockPositionX": float(x),
        "geBlockPositionY": float(y),
        "geNodeProperties": {
            "fileName": file_name,
            "folderPathWithTilde": RECORDING_FOLDER,
            "formatOptionsExpanded": True,
            "formatPlist": mp3_format(256),
            "optionsExpanded": True,
            "selectedTab": 1,
            "silenceKillerPlist": {
                "action": 1, "enabled": False, "threshold": -60.0, "time": 2.0,
            },
            "splitterPlist": {"enabled": False, "size": 5.0, "unitsKey": "space*1"},
            "stopperPlist": {"enabled": False, "size": 1.0, "unitsKey": "time*3600"},
            "tagsPlist": {},
        },
        "geNodeUuid": node_uuid,
        "geObjectInfo": "AudioRecorderBlock",
        "geUIState": empty_ui_state(),
    }


def level_meter_block(node_uuid, x, y, outputs):
    return {
        "geBlockEnabled": True,
        "geBlockOutputUUIDs": outputs,
        "geBlockPositionX": float(x),
        "geBlockPositionY": float(y),
        "geNodeProperties": {},
        "geNodeUuid": node_uuid,
        "geObjectInfo": "LevelMeterBlock",
        "geUIState": empty_ui_state(),
    }


def channel_tweaker_block(node_uuid, x, y, outputs):
    # tweakMode=4 in the source session = mix-to-mono (verified empirically)
    return {
        "geBlockEnabled": True,
        "geBlockOutputUUIDs": outputs,
        "geBlockPositionX": float(x),
        "geBlockPositionY": float(y),
        "geNodeProperties": {"tweakMode": 4},
        "geNodeUuid": node_uuid,
        "geObjectInfo": "ChannelTweakerBlock",
        "geUIState": empty_ui_state(),
    }


def main():
    with open(SRC, "rb") as f:
        src = plistlib.load(f)

    src_blocks = src["sessionData"]["geBlocks"]
    app_block = next(b for b in src_blocks if b["geObjectInfo"] == "ApplicationSourceBlock")
    out_block = next(b for b in src_blocks if b["geObjectInfo"] == "AudioDeviceOutputBlock")

    # Fresh UUIDs
    app_uuid    = new_uuid()
    meter_uuid  = new_uuid()
    rec_uuid    = new_uuid()
    tweak_uuid  = new_uuid()
    out_uuid    = new_uuid()

    # Patch ApplicationSource: enable mic capture + keep stereo split
    app_block = {**app_block}
    app_block["geNodeUuid"] = app_uuid
    app_block["geBlockOutputUUIDs"] = [meter_uuid]
    app_block["geBlockPositionX"] = 14.0
    app_block["geBlockPositionY"] = 8.0
    app_block["geUIState"] = empty_ui_state()
    props = {**app_block["geNodeProperties"]}
    props["captureEnabled"] = 1      # Mic on Left channel (VoIP mode)
    props["splitChannels"] = True    # Keep App on Right, do not downmix
    app_block["geNodeProperties"] = props

    # Patch AudioDeviceOutput (keep the source session's deviceArchive)
    out_block = {**out_block}
    out_block["geNodeUuid"] = out_uuid
    out_block["geBlockOutputUUIDs"] = []
    out_block["geBlockPositionX"] = 26.0
    out_block["geBlockPositionY"] = 13.0
    out_block["geUIState"] = empty_ui_state()

    # LevelMeter fan-out: Recorder + ChannelTweaker
    meter = level_meter_block(meter_uuid, 18, 8, [rec_uuid, tweak_uuid])

    # Recorder: stereo MP3, name pattern "%date %time" → "2026-05-24 14-30-15.mp3"
    recorder = recorder_block(rec_uuid, 22, 3, "%date %time")

    # ChannelTweaker (mix to mono) → Output
    tweaker = channel_tweaker_block(tweak_uuid, 22, 13, [out_uuid])

    new_session = {
        "autoStart": 0,
        "automations": {
            "modelItems": [
                {
                    "automationUUID": new_uuid(),
                    "enabled": False,
                    "eventType": "sessionWillStart",
                    "scriptUUID": "builtin_script_open_session_window_000",
                },
            ],
        },
        "geUIState": {
            "libraryAdvancedExpanded": True,
            "libraryAudioUnitsExpanded": True,
            "libraryEffectsExpanded": True,
            "libraryMetersExpanded": True,
            "libraryOutputsExpanded": True,
            "librarySourcesExpanded": True,
        },
        "minimumSupportedVersion": 100,
        "sessionData": {
            "editConnectionMode": False,
            "geBlocks": [
                app_block,
                meter,
                recorder,
                tweaker,
                out_block,
            ],
            "geDocumentVersion": "0.1.0",
            "manualConnectionMode": False,
            "sampleRate": 0,
        },
        "sessionDescription": (
            "Teams 2-Track (v2, splitChannels) — single stereo MP3 to "
            "~/Recordings/meetings/ with Mic on Left + Teams on Right. "
            "ffmpeg splits on the worker host for the WhisperX+pyannote pipeline. "
            "Live monitoring via mono-mixed output to the source session's "
            "output device."
        ),
        "sessionModDate": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        "sessionName": "Teams 2-Track",
        "sessionReopenPopovers": True,
        "sessionSidebarShown": True,
        "sessionSidebarTab": 1,
        "sessionSources": src.get("sessionSources", ""),
        "sessionUUID": new_uuid(),
        "sessionVersion": 100,
        "sessionWindowState": {"frame": "{{120, 222}, {1200, 720}}"},
        "versionFirstLaunched": "4.5.9",
        "versionLastLaunched": "4.5.9",
    }

    with open(DST, "wb") as f:
        plistlib.dump(new_session, f, fmt=plistlib.FMT_BINARY)

    size = os.path.getsize(DST)
    print(f"Wrote {DST} ({size} bytes)")
    print(f"  blocks: {len(new_session['sessionData']['geBlocks'])}")
    print(f"  sessionUUID: {new_session['sessionUUID']}")
    print(f"  App: captureEnabled={props['captureEnabled']} splitChannels={props['splitChannels']}")
    print(f"  Recording target: {RECORDING_FOLDER}/<date time>.mp3 (stereo, 256 kbps)")


if __name__ == "__main__":
    main()
