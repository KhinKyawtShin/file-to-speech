import os
from io import BytesIO
from flask import Flask, render_template, request, send_file, jsonify
import PyPDF2
from gtts import gTTS
from gtts.lang import tts_langs
import threading
import time
import uuid
import tempfile
import logging

# Try to import pydub/ optional though
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("Warning: pydub not available. Large file processing will be limited.")

app = Flask(__name__, template_folder="../templates")

# Allowed file types
ALLOWED_FILE = {"txt", "pdf"}

processing_status = {}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_FILE

# Chunks
def split_text_into_chunks(text, max_chars=4000):
    """Split text into chunks that gTTS can handle"""
    words = text.split()
    chunks = []
    current_chunk = ""
    
    for word in words:
        if len(current_chunk) + len(word) + 1 <= max_chars:
            current_chunk += word + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = word + " "
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def process_large_text_to_speech(text, language, job_id):
    """Process large text in chunks and combine audio files"""
    try:
        processing_status[job_id] = {"status": "processing", "progress": 0}
        
        # Split text into manageable chunks
        chunks = split_text_into_chunks(text)
        total_chunks = len(chunks)
        
        if total_chunks == 0:
            processing_status[job_id] = {"status": "error", "message": "No text to process"}
            return
        
        # Create temporary directory for audio chunks
        # C:\Users\User\AppData\Local\Temp\tmp_sth_not_sure
        temp_dir = tempfile.mkdtemp()
        audio_files = []
        
        # Process each chunk
        for i, chunk in enumerate(chunks):
            try:
                # Update progress
                progress = int((i / total_chunks) * 90)  # Reserve 10% for combining
                processing_status[job_id]["progress"] = progress
                
                tts = gTTS(text=chunk, lang=language, slow=False)
                chunk_filename = os.path.join(temp_dir, f"chunk_{i:04d}.mp3")
                tts.save(chunk_filename)
                audio_files.append(chunk_filename)
                
                # Small delay to prevent overwhelming the API
                time.sleep(0.5)
                
            except Exception as e:
                processing_status[job_id] = {"status": "error", "message": f"Error processing chunk {i+1}: {str(e)}"}
                # Clean up
                for f in audio_files:
                    if os.path.exists(f):
                        os.remove(f)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
                return
        
        # Combine all audio files
        processing_status[job_id]["status"] = "combining"
        processing_status[job_id]["progress"] = 90
        
        if PYDUB_AVAILABLE and len(audio_files) > 1:
            # Use pydub to combine files
            combined_audio = AudioSegment.empty()
            for audio_file in audio_files:
                audio_segment = AudioSegment.from_mp3(audio_file)
                combined_audio += audio_segment
            
            # Save the final combined audio
            output_filename = f"output_{job_id}.mp3"
            combined_audio.export(output_filename, format="mp3")
        else:
            # If pydub is not available or only one file, just use the first/only file
            output_filename = f"output_{job_id}.mp3"
            if audio_files:
                import shutil
                shutil.copy2(audio_files[0], output_filename)
        
        # Clean up temporary files
        for audio_file in audio_files:
            if os.path.exists(audio_file):
                os.remove(audio_file)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)
        
        processing_status[job_id] = {"status": "completed", "filename": output_filename, "progress": 100}
        
        # Clean up old status entries (keep for 1 hour)
        threading.Timer(3600, lambda: processing_status.pop(job_id, None)).start()
        
    except Exception as e:
        processing_status[job_id] = {"status": "error", "message": f"Unexpected error: {str(e)}"}
        logging.error(f"Error in process_large_text_to_speech: {str(e)}")

@app.route('/')
def upload():
    languages = dict(sorted(tts_langs().items(), key=lambda item: item[1]))
    return render_template('upload.html', languages=languages)

@app.route("/", methods=["POST"])
def upload_file():
    if request.method == "POST":
        # Check if a file was uploaded
        if "file" not in request.files:
            return "No file part"

        file = request.files["file"]

        # If no file is selected
        if file.filename == "":
            return "No selected file"

        # If file is valid, process it
        if file and allowed_file(file.filename):
            file_content = file.read()
            
            # Process the file based on its type
            text = ""
            if file.filename.endswith(".txt"):
                try:
                    text = file_content.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        text = file_content.decode("gbk")
                    except UnicodeDecodeError:
                        return "Could not decode file content"
            elif file.filename.endswith(".pdf"):
                pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()

            # Get selected language from form
            language = request.form.get("langOptions", "en")
            
            # Check text length to determine processing method
            text_length = len(text)
            estimated_duration = text_length / 150  # Rough estimate: 150 chars per minute
            
            # If text is small enough, process immediately
            if text_length < 3000:  # Small file - process immediately
                try:
                    tts = gTTS(text, lang=language, slow=False)
                    mp3_filename = f"output_small_{uuid.uuid4()}.mp3"
                    tts.save(mp3_filename)
                    
                    def cleanup_file():
                        if os.path.exists(mp3_filename):
                            os.remove(mp3_filename)
                    
                    # Schedule cleanup after 1 hour
                    threading.Timer(3600, cleanup_file).start()
                    
                    return send_file(mp3_filename, as_attachment=True, download_name="speech.mp3", mimetype="audio/mpeg")
                except Exception as e:
                    return jsonify({"error": f"Error processing file: {str(e)}"})
            
            # For large files, process in background with progress tracking
            job_id = str(uuid.uuid4())
            thread = threading.Thread(target=process_large_text_to_speech, args=(text, language, job_id))
            thread.daemon = True  # Dies when main thread dies
            thread.start()
            
            return jsonify({
                "job_id": job_id,
                "estimated_duration": f"{estimated_duration:.1f} minutes",
                "text_length": text_length,
                "processing": True,
                "chunks_estimated": len(split_text_into_chunks(text))
            })

@app.route("/status/<job_id>")
def get_status(job_id):
    """Get processing status"""
    if job_id in processing_status:
        return jsonify(processing_status[job_id])
    else:
        return jsonify({"status": "not_found"})

@app.route("/download/<job_id>")
def download_file(job_id):
    """Download completed file"""
    if job_id in processing_status and processing_status[job_id]["status"] == "completed":
        filename = processing_status[job_id]["filename"]
        return send_file(filename, as_attachment=True, download_name="speech.mp3", mimetype="audio/mpeg")
    else:
        return "File not ready", 404

if __name__ == "__main__":
    app.run(debug=True, threaded=True)