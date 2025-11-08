# Important: Restart Required for Large File Upload

## The Issue
You're seeing "File must be 200.0MB or smaller" because Streamlit needs to be restarted for the configuration changes to take effect.

## Solution

1. **Stop the current Streamlit app** (press Ctrl+C in the terminal where it's running)

2. **Restart Streamlit:**
   ```bash
   source venv/bin/activate
   streamlit run app.py
   ```

3. **The upload limit is now set to 2GB** (2000 MB) in `.streamlit/config.toml`

## Configuration File
The configuration file `.streamlit/config.toml` has been created with:
```toml
[server]
maxUploadSize = 2000  # 2GB
maxMessageSize = 2000
```

## How Large File Processing Works

Once you restart and upload a file >200MB:

1. **Automatic Detection**: The app detects files >200MB
2. **Chunking**: Files are split into 10-minute chunks using ffmpeg
3. **Parallel Processing**: 5 threads process chunks simultaneously
4. **Temporal Stitching**: Results are combined maintaining correct time order
5. **Progress Tracking**: Real-time updates for each chunk

## Troubleshooting

If you still see the 200MB limit after restarting:
- Make sure `.streamlit/config.toml` exists in the project root
- Check that the file contains `maxUploadSize = 2000`
- Try clearing Streamlit cache: `streamlit cache clear`
- Restart Streamlit completely

