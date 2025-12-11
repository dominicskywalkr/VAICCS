# VAICCS (the Vosk Artificial Intelligence Closed Captioning Software)

This repository provides a live closed-captioning application that can run from a graphical interface (`VAICCS.exe`) 

**Quick overview**
- Real-time captioning using Vosk for on-device speech recognition (optional).
- Audio capture via `sounddevice` (microphone or system loopback on Windows).
- A `VAICCS.exe` application exposes controls for starting/stopping captioning, selecting a Vosk model, choosing audio devices, serial output, and a "Voice Profiles" tab for creating/listing profiles.

**Why use my GUI?**
- Easier model selection and device selection.
- Serial output configuration and quick toggles for common options.
- Built-in voice profile creation and listing without using the CLI.

# Closed Captioning — GUI Guide

This repository offers a live closed-captioning application with a user-friendly GUI (`VAICCS.exe`). The GUI bundles model selection, audio device controls, serial output, and voice-profile management so you can run and configure captioning without using the CLI.

**Quick Overview**
- **Real-time captioning**: on-device speech recognition via `vosk` or demo mode.
- **Audio capture**: uses `sounddevice` (microphone or loopback on Windows).
- **Profiles**: create and match speaker profiles using the GUI.

## GUI Features

- **Main View**: transcript pane, Start/Stop controls, model selection, CPU/thread controls, and audio device combobox.
- **Voice Profiles**: create speaker profiles from WAV files, list existing profiles, and match incoming audio to known speakers.
- **Settings Persistence**: `gui_settings.json` stores window size, last model path, selected device, and serial settings.
- **Serial Output**: toggle serial streaming, configure COM port and baud, and use `serial_helper.py` for robust serial handling.
- **Profanity Filter / Replacement**: optional filtering based on `bad_words.txt` for cleaner output.
	The GUI now provides configurable replacement options under **File → Options**:
	- **Fixed text**: replace each matched word with a fixed string (e.g. `[BLEEP]` or `****`).
	- **Keep first letter**: preserve the first alphanumeric character and mask the rest (mask character is configurable).
	- **Keep last letter**: preserve the last alphanumeric character and mask the rest.
	- **Keep first & last**: preserve both first and last alphanumeric characters and mask the middle.
	- **Remove word**: delete the matched word entirely from the transcript.
	- **Mask character**: a single character (default `*`) used for masking in the keep_* modes.
	- **Preview**: Options shows a live preview of how a sample phrase (e.g. `badword mother-in-law`) will be transformed by the selected settings.

	These settings are applied immediately to the running engine when you press **OK** in the Options dialog and are persisted when you use **File → Save Settings As...**.

	Saved JSON keys related to these options include: `bleep_mode`, `bleep_custom_text`, and `bleep_mask_char`.

- GUI tips:
- Use the **Browse...** button next to the Vosk model field to point to a model directory.
- If a model is already downloaded (marked with a ✓) in the Vosk Model Manager, you can press **Select Installed** or double-click the model to set it as the active model in the GUI. This will populate the Vosk Model path field and update the status.
- If a model is not available or `vosk` is not installed, the GUI offers a demo mode to test capture and display.
- For consistent results on Windows, pick the correct loopback or microphone device from the Audio Input dropdown.

## Voice Profiles (Using the GUI)

- **Create a profile**: open the **Voice Profiles** tab, enter a profile name, add one or more WAV files, then click **Create Profile**. Profiles are saved under `voice_profiles/` as `.npy` embeddings with metadata in `voice_profiles/index.json`.
- **Match audio**: use the GUI's matching tools or run `voice_profiles.py match` from the CLI to find the top-K closest profiles.
- **Storage**: embeddings and metadata allow quick tests in CI using the included `voice_profiles/` fixtures.

## Recommended Voice Profile Collection

**Clip length:**
Aim for 5–15 seconds per clip.
Shorter clips (<3s) often don’t provide enough acoustic detail.
Longer clips (>30s) are fine, but you can break them into smaller segments for more embeddings.


## What VAICCS.exe Provides

- Real-time closed captioning using a Vosk model (on-device speech recognition).
- Audio capture via `sounddevice` (microphone or Windows loopback).
- Transcript terminal with auto-scroll, clear, and save controls.
- Model selection and download manager (install Vosk models into the app's `models/` folder).
- CPU thread controls to tune decoding performance.
- Voice Profiles tab for creating, editing, and matching speaker profiles (store profiles under `voice_profiles/`).
- Runtime custom vocabulary manager (Add words and sample audio to bias recognition).
- Serial output support: export caption text to a serial device (configurable COM port and baud).
- Profanity filtering with configurable replacement modes (fixed text, keep first/last letters, remove, etc.) and live preview.
- Settings persistence when using the GUI Save Settings option.


Once running, use the Main tab to select an audio device and a Vosk model (optional), then press **Start** to begin captioning.

## Autostart & Startup Modifiers

VAICCS supports passing simple modifiers to the executable via the shortcut Target so users can autostart with a saved configuration.

Supported modifiers (append to the shortcut Target after the exe path):

- `-save:"<file>"` — load a saved settings JSON file before the GUI starts. If the file sits next to the exe, pass just the filename. If located elsewhere, pass the full quoted path.
- `-autostart:true` or `-autostart` — after loading `-save` (if present), automatically start the caption engine. The GUI still validates the model path and may prompt or fall back to demo mode.
- `-show_error` — if a native import (e.g., Vosk) fails, the launcher will display the import log to help diagnose issues.

Examples (Windows Shortcut Target):

`"C:\\Program Files\\VAICCS\\VAICCS.exe" -save:"settings.json" -autostart:true -show_error`

`"C:\\Program Files\\VAICCS\\VAICCS.exe" -save:"C:\\Users\\User\\Desktop\\settings.json" -autostart`

Notes about `-save` path resolution:
- If a relative filename is provided (no drive or leading slash), the launcher searches in this order and uses the first match:
  1. EXE directory (so a `settings.json` next to the exe is found)
  2. Current working directory
  3. Application module directory (project root)

## Settings & Persistence

- Use **File → Save Settings As...** to export the current GUI configuration to a JSON file. 
- Saved options include model path, CPU threads, serial port, profile matching, profanity replacement settings, and other settings.

## Voice Profiles (GUI)

- Create profiles from WAV files in the Voice Profiles tab.
- Profiles are stored under `voice_profiles/` and include embeddings and metadata for quick matching.

## Model / Demo Mode

- To use real recognition, download a compatible Vosk model and point the GUI to the unpacked model directory.
- If `vosk` or native dependencies are not available, the GUI can run in demo mode so you can still test audio capture and UI features.

Note: by default, the GUI installs Vosk models into a `models/` folder located next to the application root.

## Troubleshooting

- Vosk import failures (native DLL issues) are logged to `vosk_import_error.log` in the EXE directory and/or the current working directory when possible.
- Use the `-show_error` modifier in the shortcut to have the launcher display the log contents in a dialog during startup.
- Common causes: missing native libraries or incompatible Vosk wheel for the target platform. Rebuilding with an appropriate environment (or installing the matching redistributables) usually resolves the issue.

---
Updated: 2025-12-3

Maintainer: Dominic Natoli

