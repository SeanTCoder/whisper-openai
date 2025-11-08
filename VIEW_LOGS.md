# Viewing Logs and Progress

## Streamlit Terminal Logs

When you run the Streamlit app, all logs are printed to the terminal where you started it:

```bash
streamlit run app.py
```

The logs will show:
- Model loading progress
- Transcription progress (when verbose=True)
- Any errors or warnings
- Debug information

## Viewing Logs in Real-Time

### Option 1: Terminal Output
The terminal where you run `streamlit run app.py` will show all output in real-time.

### Option 2: Streamlit Logs
Streamlit also creates log files. You can find them in:
- `~/.streamlit/logs/` (user directory)
- Or check the terminal output directly

### Option 3: UI Log Display
The app now includes a **"View Transcription Logs"** section that shows:
- Real-time segment transcription progress
- Timestamp information
- Transcribed text as it's processed

## Progress Indicators in the UI

The updated UI now shows:

1. **Toast Notifications** - Pop-up messages for key steps:
   - 📁 File saved
   - 🔄 Model loading
   - 🌍 Language detection
   - 🎤 Transcription started
   - ✅ Completion

2. **Progress Bars** - Visual progress indicators:
   - Model loading progress
   - Transcription progress (estimated based on segments)

3. **Status Messages** - Detailed status updates:
   - Current step information
   - Segment count
   - Completion status

4. **Log Display** - Real-time transcription logs:
   - Shows segments as they're transcribed
   - Displays timestamps and text
   - Updates in real-time (may refresh after completion)

## Troubleshooting

If you don't see progress updates:

1. **Check the terminal** - All logs are printed there
2. **Refresh the browser** - Sometimes UI updates need a refresh
3. **Check the log section** - Expand "View Transcription Logs" in the UI
4. **Enable verbose mode** - The app uses `verbose=True` by default to show progress

## Example Terminal Output

When transcribing, you'll see output like:

```
Loading model...
100%|████████████████| 72.1M/72.1M [00:06<00:00, 11.2MiB/s]
Detecting language using up to the first 30 seconds...
Detected language: English
[00:00.000 --> 00:11.000]  And so my fellow Americans...
[00:11.000 --> 00:22.000]  ask not what your country...
```

This output is captured and displayed in the UI's log section.

