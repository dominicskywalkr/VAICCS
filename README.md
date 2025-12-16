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

## Custom Vocabulary (Custom Words)

VAICCS includes a lightweight runtime custom vocabulary system to bias recognition toward user-supplied words and to store example audio for each word.

- **Purpose**: provide a small list of words (and optional pronunciations) that can be passed to the Vosk/Kaldi recognizer as a grammar to improve recognition of uncommon or product-specific terms.
- **Storage**: the word/pronunciation map is stored in `custom_vocab.json` (next to `custom_vocab.py`), and audio samples are saved under `custom_vocab_data/<safe_word>/`.
- **Safe folder names**: words are mapped to a filesystem-safe folder name (alphanumeric plus `-` and `_`); see `custom_vocab.py:_word_dir` for details.

GUI Usage (In-app):

- **Open the app**: launch `VAICCS.exe` and use the main window to access configuration and helper dialogs.
- **Open Custom Vocabulary manager**: from the GUI open the Custom Vocabulary dialog (File → Custom Vocabulary or the Tools/Options area where the app exposes the runtime vocabulary manager).
- **Add a word**: click **Add** (or **New Word**), enter the word text and (optionally) a pronunciation / lexicon string, then click **Save** or **Apply**.
- **Attach sample audio**: select a word and use **Add Sample** or **Attach WAV** to browse to a WAV file. The GUI copies the file into `custom_vocab_data/<safe_word>/` (safe folder names use alphanumeric characters plus `-` and `_`).
- **Apply to running recognizer**: click **Apply** or **OK** in the dialog to immediately send the updated word list to the running recognizer; changes are used as a runtime grammar to bias recognition.
- **Persist changes**: use **File → Save Settings As...** to persist GUI settings (the custom vocab path is saved via `CustomVocabManager.serializable_path()`). The word/pronunciation map itself is stored in `custom_vocab.json` next to `custom_vocab.py`.

- **Where files live**: words and pronunciations are stored in `custom_vocab.json`; WAV samples are stored in `custom_vocab_data/<safe_word>/` under the project root.

Developer note (optional):

If you are developing or scripting, `CustomVocabManager` is available as a small helper class. For simple developer usage you can read the saved words and produce a grammar list with `CustomVocabManager.as_word_list()` or export lexicon lines with `export_lexicon_lines()`; however, prefer the GUI for end-user workflows.


This feature biases on-device recognition at runtime — it does not rebuild the Vosk model graph automatically. For permanent model changes, export the lexicon lines and follow Vosk/Kaldi model customization procedures.

## Top Menu (File / Models / View / Help)

The top menubar exposes common actions for configuring the app, managing models, controlling the transcript view, and accessing help/activation. The GUI implementation is in [gui.py](gui.py).

- **File**:
	- **Save Settings** (Ctrl+S): write current settings to the last opened settings file, or prompt Save As if none exists.
	- **Save Settings As...** (Ctrl+Shift+S): open a Save As dialog to export current GUI settings to a JSON file. A copy is also written to `gui_settings.json` for convenience.
	- **Options...**: open the Options dialog where you can set SRT caption duration, configure restricted-word (bleep) replacement modes and preview, and adjust auto-save transcript settings.
	- **Save Transcript As...**: save the current transcript pane contents to a plain text `.txt` file via Save As.
	- **Export Transcript as SRT**: export the transcript to a simple SRT file (each non-empty line becomes a caption with a fixed duration set in Options).
	- **Load Restricted Words File** (checkable): toggle and choose a restricted/bad-words file for the current session. If a file is already loaded the menu lets you Unload, Replace, or Cancel. The file is applied for the session only (see `main.load_bad_words`).
	- **Open Settings...** (Ctrl+O): load a previously saved settings JSON into the session (applies values to the UI; does not automatically persist unless you Save Settings).
	- **Exit** (Alt+F4): quit the app (also ensures the capture engine and automation scheduler are stopped cleanly).

- **Models**:
	- **Vosk Models...**: open the Vosk Model Manager dialog (lists languages and available models fetched from the Vosk model index, shows installed models in `models/`, and supports download/install operations). Use this to point the GUI at an unpacked Vosk model or to install a model into the local `models/` folder.
	- **Hance Models...**: placeholder dialog for future Hance model management (opens the Hance models manager UI if available).

- **View**:
	- **Auto-scroll** (checkable): when enabled the transcript automatically scrolls to show the latest incoming captions. When the user scrolls up this is disabled automatically.
	- **Jump to latest**: immediately jump the transcript to the end and re-enable auto-scroll.

- **Help**:
	- **Activate**: open the activation dialog (activation/licensing UI, if present).
	- **About**: show application information and build details in a small About dialog.

Notes:
- Keyboard shortcuts implemented in the GUI include `Ctrl+S`, `Ctrl+Shift+S` (Save As), `Ctrl+O` (Open Settings), and a binding to ensure Exit runs on `Alt+F4`.
- Many menu actions open modal dialogs or file choosers; settings loaded from JSON are applied to the UI for the session and include optional embedded custom vocabulary and sample audio payloads when present.

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

## Noise Cancelation Tab

The Noise Cancelation tab exposes controls to install and manage a realtime noise-filter that runs before audio reaches the recognizer. The GUI integrates with the helper module `noise_cancel.py` and provides a simple, user-friendly flow:

- **Quick toggle (Main tab)**: there is a checkbutton on the Main tab labeled "Enable Noise Cancelation" to quickly enable or disable the filter while the app is running. This toggle invokes the same install/uninstall code used by the Noise tab.
- **Hance model file**: use the "Browse..." button on the Noise Cancelation tab to select an optional Hance model file. If provided, the UI will attempt to initialize the Hance SDK with that model when installing the filter.
- **Install Noise Filter**: installs the noise-processing wrapper into the app by calling `noise_cancel.install(path)`. On success the status label changes to show the installed state and the quick-toggle is set to enabled.
- **Uninstall**: restores the original audio callback (calls `noise_cancel.uninstall()`), sets the status to "Not installed", and disables the quick-toggle.
- **Status & Notes**: the tab shows a status label (e.g., "Not installed", "Installed (model:xyz)", or "Disabled in Personal/Eval mode"). A small note explains that Hance SDK integration is attempted if available; otherwise the app uses a built-in RMS-based noise-gate fallback.
- **License gating**: Hance/noise controls are disabled in Personal/Eval mode. After activation the GUI calls `refresh_license_state()` to re-enable controls without restarting the app (see activation/Help → Activate).
- **Implementation details**: the noise logic lives in `noise_cancel.py`. If a Hance SDK is available the `HanceProcessor` wrapper will attempt to use the SDK's denoiser; otherwise a lightweight RMS-based noise gate is applied. Installation replaces the `main.callback` handler with a wrapper so audio is filtered before reaching the recognition queue; uninstall restores the original callback.

User tip: prefer the tab's Install/Uninstall controls when selecting a model file; use the Main tab toggle for quick on/off during a session.

## Troubleshooting

- Vosk import failures (native DLL issues) are logged to `vosk_import_error.log` in the EXE directory and/or the current working directory when possible.
- Use the `-show_error` modifier in the shortcut to have the launcher display the log contents in a dialog during startup.
- Common causes: missing native libraries or incompatible Vosk wheel for the target platform. Rebuilding with an appropriate environment (or installing the matching redistributables) usually resolves the issue.

---
Updated: 2025-12-3

Maintainer: Dominic Natoli

