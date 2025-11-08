# Whisper Web UI

A simple web interface for transcribing audio files using OpenAI Whisper.

## How to Run

1. **Activate the virtual environment:**
   ```bash
   source venv/bin/activate
   ```

2. **Start the Streamlit app:**
   ```bash
   streamlit run app.py
   ```

3. **Open your browser:**
   The app will automatically open in your default browser at `http://localhost:8501`
   
   If it doesn't open automatically, navigate to that URL manually.

## Features

- 📤 **Upload audio files** (MP3, WAV, FLAC, M4A, OGG, WMA, AAC)
- 🎯 **Select model** (tiny, base, small, medium, large, turbo)
- 🌍 **Language detection** or manual language selection
- 🔄 **Transcribe or Translate** to English
- ⏱️ **Word-level timestamps** (optional)
- 💾 **Download results** in multiple formats:
  - TXT (plain text)
  - JSON (full transcription data)
  - SRT (subtitle format)

## Usage Tips

- **For English audio:** Use the `turbo` model (default) for best speed
- **For non-English audio:** Use `medium` or `large` models for better accuracy
- **For translation:** Select "translate" task and use `medium` or `large` models
- **For faster processing:** Use smaller models (`tiny`, `base`, `small`)
- **For better accuracy:** Use larger models (`medium`, `large`)

## Troubleshooting

- If the app doesn't start, make sure you've activated the virtual environment
- If you get an error about ffmpeg, make sure it's installed: `brew install ffmpeg`
- Large audio files may take longer to process
- The first time you use a model, it will be downloaded automatically

