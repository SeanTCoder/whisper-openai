import streamlit as st
import whisper
import tempfile
import os
import sys
import io
import json
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
import threading
import time
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess

# Page configuration
st.set_page_config(
    page_title="Whisper Speech Transcription",
    page_icon="🎤",
    layout="wide"
)

# Storage directory for transcriptions
STORAGE_DIR = Path("transcriptions")
STORAGE_DIR.mkdir(exist_ok=True)
TRANSCRIPTIONS_FILE = STORAGE_DIR / "transcriptions.json"

# Helper functions for storage
def load_transcriptions():
    """Load stored transcriptions from JSON file"""
    if TRANSCRIPTIONS_FILE.exists():
        try:
            with open(TRANSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_transcription(transcription_data):
    """Save a transcription to storage"""
    transcriptions = load_transcriptions()
    transcriptions.append(transcription_data)
    with open(TRANSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(transcriptions, f, indent=2, ensure_ascii=False)

# Configuration for large file processing
CHUNK_SIZE_MB = 200  # Maximum chunk size in MB
MAX_WORKERS = 5  # Number of parallel threads
CHUNK_DURATION_SECONDS = 600  # 10 minutes per chunk (adjust based on file size)

def get_file_duration(file_path):
    """Get the duration of an audio/video file in seconds using ffprobe"""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        # Try alternative method if ffprobe fails
        try:
            # Use ffmpeg to get duration
            cmd = [
                "ffmpeg",
                "-i", file_path,
                "-f", "null",
                "-"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, stderr=subprocess.STDOUT)
            # Parse duration from ffmpeg output (format: Duration: HH:MM:SS.mmm)
            for line in result.stdout.split('\n'):
                if 'Duration:' in line:
                    time_str = line.split('Duration:')[1].split(',')[0].strip()
                    parts = time_str.split(':')
                    hours = float(parts[0])
                    minutes = float(parts[1])
                    seconds = float(parts[2])
                    return hours * 3600 + minutes * 60 + seconds
        except:
            pass
        return None

def split_file_into_chunks(file_path, chunk_duration=CHUNK_DURATION_SECONDS):
    """Split a large file into time-based chunks using ffmpeg"""
    duration = get_file_duration(file_path)
    if duration is None:
        # Fallback: estimate based on file size (rough estimate)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        # Rough estimate: 1MB per minute for audio
        duration = file_size_mb * 60
    
    chunks = []
    chunk_dir = tempfile.mkdtemp()
    num_chunks = int(duration / chunk_duration) + 1
    
    for i in range(num_chunks):
        start_time = i * chunk_duration
        end_time = min((i + 1) * chunk_duration, duration)
        
        chunk_path = os.path.join(chunk_dir, f"chunk_{i:04d}.wav")
        
        # Extract chunk using ffmpeg
        cmd = [
            "ffmpeg",
            "-i", file_path,
            "-ss", str(start_time),
            "-t", str(end_time - start_time),
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",  # Overwrite output file
            chunk_path
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            chunks.append({
                "path": chunk_path,
                "index": i,
                "start_time": start_time,
                "end_time": end_time
            })
        except subprocess.CalledProcessError as e:
            st.warning(f"Failed to create chunk {i}: {e}")
            continue
    
    return chunks, chunk_dir

def transcribe_chunk(chunk_info, model, transcribe_options, progress_callback=None):
    """Transcribe a single chunk"""
    try:
        result = model.transcribe(chunk_info["path"], **transcribe_options)
        
        # Adjust timestamps to account for chunk offset
        if result.get("segments"):
            for segment in result["segments"]:
                segment["start"] += chunk_info["start_time"]
                segment["end"] += chunk_info["start_time"]
                if segment.get("words"):
                    for word in segment["words"]:
                        word["start"] += chunk_info["start_time"]
                        word["end"] += chunk_info["start_time"]
        
        return {
            "chunk_index": chunk_info["index"],
            "start_time": chunk_info["start_time"],
            "result": result,
            "success": True
        }
    except Exception as e:
        return {
            "chunk_index": chunk_info["index"],
            "start_time": chunk_info["start_time"],
            "error": str(e),
            "success": False
        }

def combine_chunk_results(chunk_results):
    """Combine transcription results from multiple chunks, maintaining temporal order"""
    # Sort by chunk index to maintain order
    chunk_results.sort(key=lambda x: x["chunk_index"])
    
    all_segments = []
    all_text_parts = []
    language = None
    total_duration = 0
    
    for chunk_result in chunk_results:
        if not chunk_result["success"]:
            continue
        
        result = chunk_result["result"]
        
        if language is None:
            language = result.get("language")
        
        # Collect segments
        if result.get("segments"):
            all_segments.extend(result["segments"])
        
        # Collect text
        text = result.get("text", "").strip()
        if text:
            all_text_parts.append(text)
        
        # Update total duration
        total_duration = max(total_duration, result.get("duration", 0) + chunk_result["start_time"])
    
    # Combine text
    combined_text = " ".join(all_text_parts)
    
    # Sort segments by start time
    all_segments.sort(key=lambda x: x.get("start", 0))
    
    return {
        "text": combined_text,
        "segments": all_segments,
        "language": language,
        "duration": total_duration
    }

def create_docx(transcription_text, filename, metadata=None, segments=None):
    """Create a DOCX file from transcription text with timestamps"""
    doc = Document()
    
    # Add title
    title = doc.add_heading('Transcription', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Add metadata if provided
    if metadata:
        doc.add_paragraph(f"Source File: {metadata.get('filename', 'Unknown')}")
        doc.add_paragraph(f"Language: {metadata.get('language', 'Unknown')}")
        doc.add_paragraph(f"Duration: {metadata.get('duration', 0):.2f} seconds")
        doc.add_paragraph(f"Date: {metadata.get('date', 'Unknown')}")
        doc.add_paragraph("")  # Empty line
    
    # Add transcription text with timestamps if segments are provided
    if segments:
        doc.add_heading('Transcription with Timestamps', level=1)
        for segment in segments:
            start = segment.get('start', 0)
            end = segment.get('end', 0)
            text = segment.get('text', '').strip()
            
            # Format timestamp
            def format_time(seconds):
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                secs = int(seconds % 60)
                millis = int((seconds % 1) * 1000)
                if hours > 0:
                    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
                return f"{minutes:02d}:{secs:02d}.{millis:03d}"
            
            timestamp = f"[{format_time(start)} --> {format_time(end)}]"
            para = doc.add_paragraph()
            para.add_run(timestamp).bold = True
            para.add_run(f" {text}")
            doc.add_paragraph("")  # Empty line between segments
        
        doc.add_paragraph("")  # Empty line
        doc.add_heading('Plain Text (No Timestamps)', level=1)
    
    # Add plain transcription text
    doc.add_paragraph(transcription_text)
    
    # Save to BytesIO
    docx_buffer = io.BytesIO()
    doc.save(docx_buffer)
    docx_buffer.seek(0)
    return docx_buffer

# Title and description
st.title("🎤 Whisper Speech Transcription")
st.markdown("Upload an audio file (MP3, WAV, FLAC, etc.) to transcribe or translate speech to text.")

# Add tabs for main transcription and history
tab1, tab2 = st.tabs(["🎤 Transcribe", "📚 Stored Transcriptions"])

# Sidebar for settings
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Model selection
    model_options = {
        "tiny": "Tiny (39M params) - Fastest, least accurate",
        "base": "Base (74M params) - Fast, good balance",
        "small": "Small (244M params) - Good accuracy",
        "medium": "Medium (769M params) - Better accuracy",
        "large": "Large (1550M params) - Best accuracy, slowest",
        "turbo": "Turbo (809M params) - Optimized for speed (default)"
    }
    
    selected_model = st.selectbox(
        "Select Model",
        options=list(model_options.keys()),
        index=5,  # Default to turbo
        format_func=lambda x: f"{x} - {model_options[x].split(' - ')[1]}"
    )
    
    st.caption(model_options[selected_model])
    
    # Task selection
    task = st.radio(
        "Task",
        options=["transcribe", "translate"],
        help="Transcribe: Keep original language. Translate: Translate to English."
    )
    
    # Language selection
    language = st.selectbox(
        "Language (optional - leave as 'Auto-detect' to detect automatically)",
        options=["Auto-detect"] + ["English", "Spanish", "French", "German", "Japanese", "Chinese", "Korean", "Italian", "Portuguese", "Russian", "Arabic", "Hindi", "Dutch", "Polish", "Turkish", "Swedish", "Norwegian", "Danish", "Finnish", "Greek", "Czech", "Hungarian", "Romanian", "Thai", "Vietnamese", "Indonesian", "Malay", "Hebrew", "Ukrainian", "Catalan", "Basque", "Galician", "Welsh", "Irish", "Scottish Gaelic", "Breton", "Esperanto", "Latin", "Yiddish", "Afrikaans", "Albanian", "Amharic", "Armenian", "Assamese", "Azerbaijani", "Bashkir", "Belarusian", "Bengali", "Bosnian", "Bulgarian", "Burmese", "Cantonese", "Castilian", "Croatian", "Estonian", "Faroese", "Flemish", "Georgian", "Gujarati", "Haitian", "Haitian Creole", "Hausa", "Hawaiian", "Icelandic", "Javanese", "Kannada", "Kazakh", "Khmer", "Lao", "Latvian", "Letzeburgesch", "Lingala", "Lithuanian", "Luxembourgish", "Macedonian", "Malagasy", "Malayalam", "Maltese", "Mandarin", "Maori", "Marathi", "Moldavian", "Moldovan", "Mongolian", "Myanmar", "Nepali", "Nynorsk", "Occitan", "Panjabi", "Pashto", "Persian", "Punjabi", "Pushto", "Sanskrit", "Serbian", "Shona", "Sindhi", "Sinhala", "Sinhalese", "Slovak", "Slovenian", "Somali", "Spanish", "Sundanese", "Swahili", "Tagalog", "Tajik", "Tamil", "Tatar", "Telugu", "Tibetan", "Turkmen", "Urdu", "Uzbek", "Valencian", "Yoruba"],
        index=0
    )
    
    # Word timestamps option
    word_timestamps = st.checkbox(
        "Include word-level timestamps",
        value=False,
        help="Extract timestamps for each word (slower but more detailed)"
    )

with tab1:
    # Note about large files
    st.info("ℹ️ **Large File Support**: Files up to 2GB are supported. Files >200MB will be automatically split into chunks and processed in parallel. If you see a 200MB limit, please restart the Streamlit app.")
    
    # File upload - increase size limit for large files
    uploaded_file = st.file_uploader(
        "Upload Audio or Video File",
        type=["mp3", "wav", "flac", "m4a", "ogg", "wma", "aac", "mov", "mp4", "avi", "mkv", "webm", "m4v"],
        help="Supported formats: Audio (MP3, WAV, FLAC, M4A, OGG, WMA, AAC) and Video (MOV, MP4, AVI, MKV, WEBM, M4V). Large files (>200MB) will be automatically split into chunks and processed in parallel. Maximum upload size: 2GB (requires app restart if you see 200MB limit)."
    )

    if uploaded_file is not None:
        # Display file info
        file_details = {
            "Filename": uploaded_file.name,
            "FileType": uploaded_file.type,
            "FileSize": f"{uploaded_file.size / 1024 / 1024:.2f} MB"
        }
        
        st.info(f"📁 **{file_details['Filename']}** ({file_details['FileSize']})")
        
        # Process button
        if st.button("🚀 Transcribe Audio", type="primary", use_container_width=True):
            # Create containers for progress updates
            progress_container = st.container()
            log_container = st.container()
            
            try:
                # Step 1: Save uploaded file
                with progress_container:
                    st.toast("📁 Saving uploaded file...", icon="📁")
                    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_file_path = tmp_file.name
                    st.toast("✅ File saved successfully", icon="✅")
                
                # Step 2: Load model
                with progress_container:
                    st.toast("🔄 Loading model... This may take a moment on first use", icon="🔄")
                    progress_bar = st.progress(0, text="Loading model...")
                    status_text = st.empty()
                    
                    status_text.info("📦 Loading Whisper model (this may download the model on first use)...")
                    model = whisper.load_model(selected_model)
                    
                    progress_bar.progress(100, text="Model loaded!")
                    status_text.success("✅ Model loaded successfully!")
                    st.toast("✅ Model loaded!", icon="✅")
                
                # Step 3: Prepare transcription options
                transcribe_options = {
                    "task": task,
                    "word_timestamps": word_timestamps,
                    "verbose": True  # Enable verbose to get progress updates
                }
                
                if language != "Auto-detect":
                    transcribe_options["language"] = language
                    st.toast(f"🌍 Language set to: {language}", icon="🌍")
                else:
                    st.toast("🔍 Auto-detecting language...", icon="🔍")
                
                # Step 4: Check file size and decide on processing method
                file_size_mb = uploaded_file.size / (1024 * 1024)
                use_chunking = file_size_mb > CHUNK_SIZE_MB
                
                if use_chunking:
                    # Large file: Use chunking and parallel processing
                    with progress_container:
                        st.toast("📦 Large file detected! Splitting into chunks...", icon="📦")
                        transcription_progress = st.progress(0, text="Preparing chunks...")
                        transcription_status = st.empty()
                        transcription_status.info(f"📦 File is {file_size_mb:.2f} MB. Splitting into chunks for parallel processing...")
                        
                        # Split file into chunks
                        chunks, chunk_dir = split_file_into_chunks(tmp_file_path)
                        num_chunks = len(chunks)
                        
                        transcription_progress.progress(10, text=f"Created {num_chunks} chunks. Starting parallel transcription...")
                        transcription_status.info(f"🔄 Processing {num_chunks} chunks in parallel using {MAX_WORKERS} threads...")
                        
                        # Process chunks in parallel
                        chunk_results = []
                        completed_chunks = 0
                        
                        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                            # Submit all chunks
                            future_to_chunk = {
                                executor.submit(transcribe_chunk, chunk, model, transcribe_options): chunk
                                for chunk in chunks
                            }
                            
                            # Process completed chunks as they finish
                            for future in as_completed(future_to_chunk):
                                chunk_result = future.result()
                                chunk_results.append(chunk_result)
                                completed_chunks += 1
                                
                                # Update progress
                                progress_pct = 10 + int((completed_chunks / num_chunks) * 85)
                                transcription_progress.progress(
                                    progress_pct / 100,
                                    text=f"Processing chunks... {completed_chunks}/{num_chunks} completed"
                                )
                                
                                if chunk_result["success"]:
                                    st.toast(f"✅ Chunk {chunk_result['chunk_index'] + 1}/{num_chunks} completed", icon="✅")
                                else:
                                    st.warning(f"⚠️ Chunk {chunk_result['chunk_index'] + 1} failed: {chunk_result.get('error', 'Unknown error')}")
                        
                        # Combine results
                        transcription_progress.progress(95, text="Combining results...")
                        transcription_status.info("🔗 Combining transcription results from all chunks...")
                        result = combine_chunk_results(chunk_results)
                        
                        # Clean up chunk files
                        import shutil
                        try:
                            shutil.rmtree(chunk_dir)
                        except:
                            pass
                        
                        transcription_progress.progress(100, text="Transcription complete!")
                        transcription_status.success(f"✅ Transcription completed! Processed {num_chunks} chunks with {len(result.get('segments', []))} total segments.")
                        st.toast("✅ All chunks processed and combined!", icon="✅")
                else:
                    # Small file: Use standard processing
                    with progress_container:
                        st.toast("🎤 Starting transcription...", icon="🎤")
                        transcription_progress = st.progress(0, text="Initializing transcription...")
                        transcription_status = st.empty()
                        transcription_status.info("🎤 Transcribing audio... This may take a while depending on file size.")
                        
                        # Create a collapsible log section
                        with st.expander("📋 View Transcription Logs (Real-time Progress)", expanded=True):
                            log_placeholder = st.empty()
                            log_output = []
                            
                            # Capture stdout to show transcription progress
                            class ProgressCapture:
                                def __init__(self):
                                    self.lines = []
                                    self.placeholder = log_placeholder
                                    self.segment_count = 0
                                
                                def write(self, text):
                                    if text.strip():
                                        # Parse segment lines (format: [00:00.000 --> 00:11.000] text)
                                        line = text.strip()
                                        self.lines.append(line)
                                        
                                        # Count segments
                                        if "-->" in line and "]" in line:
                                            self.segment_count += 1
                                            # Update progress estimate (rough estimate: 5% per segment)
                                            estimated_progress = min(95, self.segment_count * 5)
                                            transcription_progress.progress(
                                                estimated_progress / 100, 
                                                text=f"Transcribing... ({self.segment_count} segments processed)"
                                            )
                                        
                                        # Update log display (show last 15 lines)
                                        display_lines = self.lines[-15:]
                                        self.placeholder.code("\n".join(display_lines), language="text")
                                
                                def flush(self):
                                    pass
                            
                            progress_capture = ProgressCapture()
                            
                            # Transcribe with verbose output captured
                            with redirect_stdout(progress_capture):
                                with redirect_stderr(progress_capture):
                                    result = model.transcribe(tmp_file_path, **transcribe_options)
                            
                            # Final log update
                            if progress_capture.lines:
                                log_placeholder.code("\n".join(progress_capture.lines[-20:]), language="text")
                    
                        transcription_progress.progress(100, text="Transcription complete!")
                        transcription_status.success(f"✅ Transcription completed! Processed {len(result.get('segments', []))} segments.")
                        st.toast("✅ Transcription complete!", icon="✅")
                
                # Step 5: Clean up
                os.unlink(tmp_file_path)
                
                # Step 6: Save transcription to storage
                transcription_metadata = {
                    "id": str(int(time.time())),
                    "filename": uploaded_file.name,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "language": result.get("language", "Unknown"),
                    "duration": result.get("duration", 0),
                    "segments_count": len(result.get("segments", [])),
                    "model": selected_model,
                    "task": task,
                    "text": result["text"],
                    "full_result": result  # Store full result for JSON download
                }
                save_transcription(transcription_metadata)
                st.toast("💾 Transcription saved to storage", icon="💾")
                
                # Display results
                st.balloons()  # Celebration animation
                st.success("🎉 Transcription completed successfully!")
                
                # Main transcription text
                st.subheader("📝 Transcription")
                st.text_area(
                    "Transcribed Text",
                    value=result["text"],
                    height=200,
                    label_visibility="collapsed"
                )
                
                # Additional information
                with st.expander("ℹ️ Additional Information"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.metric("Detected Language", result.get("language", "N/A"))
                        st.metric("Duration", f"{result.get('duration', 0):.2f} seconds")
                    
                    with col2:
                        st.metric("Segments", len(result.get("segments", [])))
                        if result.get("language"):
                            # Get language probability if available
                            st.metric("Task", task.capitalize())
                
                # Segments with timestamps
                if result.get("segments"):
                    st.subheader("⏱️ Segments with Timestamps")
                    
                    for i, segment in enumerate(result["segments"]):
                        start_time = segment.get("start", 0)
                        end_time = segment.get("end", 0)
                        
                        # Format time
                        def format_time(seconds):
                            hours = int(seconds // 3600)
                            minutes = int((seconds % 3600) // 60)
                            secs = int(seconds % 60)
                            if hours > 0:
                                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                            return f"{minutes:02d}:{secs:02d}"
                        
                        st.markdown(f"**{format_time(start_time)} → {format_time(end_time)}**")
                        st.write(segment.get("text", ""))
                        
                        if word_timestamps and segment.get("words"):
                            st.caption("Words: " + " | ".join([
                                f"{w.get('word', '')} ({w.get('start', 0):.2f}s)"
                                for w in segment.get("words", [])[:10]  # Show first 10 words
                            ]))
                        
                        if i < len(result["segments"]) - 1:
                            st.divider()
                
                # Download options
                st.subheader("💾 Download Results")
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    # Create TXT with timestamps
                    txt_content = ""
                    if result.get("segments"):
                        # Add header
                        txt_content += f"Transcription: {uploaded_file.name}\n"
                        txt_content += f"Language: {result.get('language', 'Unknown')}\n"
                        txt_content += f"Duration: {result.get('duration', 0):.2f} seconds\n"
                        txt_content += f"Date: {transcription_metadata['date']}\n"
                        txt_content += "=" * 50 + "\n\n"
                        
                        # Add segments with timestamps
                        txt_content += "TRANSCRIPTION WITH TIMESTAMPS:\n"
                        txt_content += "-" * 50 + "\n\n"
                        for segment in result["segments"]:
                            start = segment.get('start', 0)
                            end = segment.get('end', 0)
                            text = segment.get('text', '').strip()
                            
                            # Format timestamp
                            def format_time(seconds):
                                hours = int(seconds // 3600)
                                minutes = int((seconds % 3600) // 60)
                                secs = int(seconds % 60)
                                millis = int((seconds % 1) * 1000)
                                if hours > 0:
                                    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
                                return f"{minutes:02d}:{secs:02d}.{millis:03d}"
                            
                            txt_content += f"[{format_time(start)} --> {format_time(end)}] {text}\n\n"
                        
                        txt_content += "\n" + "=" * 50 + "\n\n"
                        txt_content += "PLAIN TEXT (NO TIMESTAMPS):\n"
                        txt_content += "-" * 50 + "\n\n"
                    
                    # Add plain text
                    txt_content += result["text"]
                    
                    st.download_button(
                        label="📄 Download as TXT",
                        data=txt_content,
                        file_name=f"{Path(uploaded_file.name).stem}_transcription.txt",
                        mime="text/plain"
                    )
                
                with col2:
                    # Create DOCX file with timestamps
                    docx_buffer = create_docx(
                        result["text"],
                        uploaded_file.name,
                        {
                            "filename": uploaded_file.name,
                            "language": result.get("language", "Unknown"),
                            "duration": result.get("duration", 0),
                            "date": transcription_metadata["date"]
                        },
                        segments=result.get("segments")
                    )
                    st.download_button(
                        label="📝 Download as DOCX",
                        data=docx_buffer.getvalue(),
                        file_name=f"{Path(uploaded_file.name).stem}_transcription.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                
                with col3:
                    # Create JSON output
                    json_output = json.dumps(result, indent=2, ensure_ascii=False)
                    st.download_button(
                        label="📊 Download as JSON",
                        data=json_output,
                        file_name=f"{Path(uploaded_file.name).stem}_transcription.json",
                        mime="application/json"
                    )
                
                with col4:
                    # Create SRT subtitle format
                    if result.get("segments"):
                        srt_content = ""
                        for i, segment in enumerate(result["segments"], 1):
                            start = segment.get("start", 0)
                            end = segment.get("end", 0)
                            
                            def format_srt_time(seconds):
                                hours = int(seconds // 3600)
                                minutes = int((seconds % 3600) // 60)
                                secs = int(seconds % 60)
                                millis = int((seconds % 1) * 1000)
                                return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
                            
                            srt_content += f"{i}\n"
                            srt_content += f"{format_srt_time(start)} --> {format_srt_time(end)}\n"
                            srt_content += f"{segment.get('text', '')}\n\n"
                        
                        st.download_button(
                            label="📺 Download as SRT",
                            data=srt_content,
                            file_name=f"{Path(uploaded_file.name).stem}_subtitles.srt",
                            mime="text/plain"
                        )
            
            except Exception as e:
                st.error(f"❌ Error during transcription: {str(e)}")
                st.exception(e)

with tab2:
    st.header("📚 Stored Transcriptions")
    st.markdown("View and download your previously completed transcriptions.")
    
    transcriptions = load_transcriptions()
    
    if not transcriptions:
        st.info("📭 No stored transcriptions yet. Complete a transcription to see it here.")
    else:
        # Sort by date (newest first)
        transcriptions.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        st.metric("Total Transcriptions", len(transcriptions))
        
        # Search/filter
        search_term = st.text_input("🔍 Search transcriptions", placeholder="Search by filename or date...")
        
        # Filter transcriptions
        filtered_transcriptions = transcriptions
        if search_term:
            filtered_transcriptions = [
                t for t in transcriptions
                if search_term.lower() in t.get("filename", "").lower() 
                or search_term.lower() in t.get("date", "").lower()
                or search_term.lower() in t.get("text", "").lower()
            ]
        
        if not filtered_transcriptions:
            st.warning("No transcriptions found matching your search.")
        else:
            for idx, trans in enumerate(filtered_transcriptions):
                with st.expander(
                    f"📄 {trans.get('filename', 'Unknown')} - {trans.get('date', 'Unknown date')}",
                    expanded=False
                ):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        st.write(f"**Language:** {trans.get('language', 'Unknown')}")
                        st.write(f"**Duration:** {trans.get('duration', 0):.2f} seconds")
                        st.write(f"**Segments:** {trans.get('segments_count', 0)}")
                        st.write(f"**Model:** {trans.get('model', 'Unknown')}")
                        st.write(f"**Task:** {trans.get('task', 'transcribe').capitalize()}")
                    
                    with col2:
                        st.write(f"**Date:** {trans.get('date', 'Unknown')}")
                        st.write(f"**ID:** {trans.get('id', 'Unknown')}")
                    
                    # Preview text
                    text_preview = trans.get('text', '')[:500]  # First 500 chars
                    st.text_area(
                        "Preview",
                        value=text_preview + ("..." if len(trans.get('text', '')) > 500 else ""),
                        height=100,
                        disabled=True,
                        label_visibility="collapsed"
                    )
                    
                    # Download buttons
                    st.subheader("💾 Download")
                    dl_col1, dl_col2, dl_col3, dl_col4 = st.columns(4)
                    
                    with dl_col1:
                        # Create TXT with timestamps for stored transcription
                        txt_content = ""
                        full_result = trans.get('full_result', {})
                        if full_result.get("segments"):
                            # Add header
                            txt_content += f"Transcription: {trans.get('filename', 'Unknown')}\n"
                            txt_content += f"Language: {trans.get('language', 'Unknown')}\n"
                            txt_content += f"Duration: {trans.get('duration', 0):.2f} seconds\n"
                            txt_content += f"Date: {trans.get('date', 'Unknown')}\n"
                            txt_content += "=" * 50 + "\n\n"
                            
                            # Add segments with timestamps
                            txt_content += "TRANSCRIPTION WITH TIMESTAMPS:\n"
                            txt_content += "-" * 50 + "\n\n"
                            for segment in full_result["segments"]:
                                start = segment.get('start', 0)
                                end = segment.get('end', 0)
                                text = segment.get('text', '').strip()
                                
                                # Format timestamp
                                def format_time(seconds):
                                    hours = int(seconds // 3600)
                                    minutes = int((seconds % 3600) // 60)
                                    secs = int(seconds % 60)
                                    millis = int((seconds % 1) * 1000)
                                    if hours > 0:
                                        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
                                    return f"{minutes:02d}:{secs:02d}.{millis:03d}"
                                
                                txt_content += f"[{format_time(start)} --> {format_time(end)}] {text}\n\n"
                            
                            txt_content += "\n" + "=" * 50 + "\n\n"
                            txt_content += "PLAIN TEXT (NO TIMESTAMPS):\n"
                            txt_content += "-" * 50 + "\n\n"
                        
                        # Add plain text
                        txt_content += trans.get('text', '')
                        
                        st.download_button(
                            label="📄 TXT",
                            data=txt_content,
                            file_name=f"{Path(trans.get('filename', 'transcription')).stem}_transcription.txt",
                            mime="text/plain",
                            key=f"txt_{trans.get('id')}"
                        )
                    
                    with dl_col2:
                        # Create DOCX for stored transcription
                        full_result = trans.get('full_result', {})
                        docx_buffer = create_docx(
                            trans.get('text', ''),
                            trans.get('filename', 'transcription'),
                            {
                                "filename": trans.get('filename', 'Unknown'),
                                "language": trans.get('language', 'Unknown'),
                                "duration": trans.get('duration', 0),
                                "date": trans.get('date', 'Unknown')
                            },
                            segments=full_result.get("segments")
                        )
                        st.download_button(
                            label="📝 DOCX",
                            data=docx_buffer.getvalue(),
                            file_name=f"{Path(trans.get('filename', 'transcription')).stem}_transcription.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"docx_{trans.get('id')}"
                        )
                    
                    with dl_col3:
                        if trans.get('full_result'):
                            json_output = json.dumps(trans['full_result'], indent=2, ensure_ascii=False)
                            st.download_button(
                                label="📊 JSON",
                                data=json_output,
                                file_name=f"{Path(trans.get('filename', 'transcription')).stem}_transcription.json",
                                mime="application/json",
                                key=f"json_{trans.get('id')}"
                            )
                    
                    with dl_col4:
                        # Delete button
                        if st.button("🗑️ Delete", key=f"delete_{trans.get('id')}"):
                            transcriptions.remove(trans)
                            with open(TRANSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
                                json.dump(transcriptions, f, indent=2, ensure_ascii=False)
                            st.success("✅ Transcription deleted!")
                            st.rerun()
                    
                    if idx < len(filtered_transcriptions) - 1:
                        st.divider()

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: gray;'>
        <p>Powered by <a href='https://github.com/openai/whisper' target='_blank'>OpenAI Whisper</a></p>
    </div>
    """,
    unsafe_allow_html=True
)

