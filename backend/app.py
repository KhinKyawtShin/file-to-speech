import os
from io import BytesIO
from flask import Flask, render_template, request, send_file
import PyPDF2
from gtts import gTTS

app = Flask(__name__, template_folder="../templates")

# Allowed file types
ALLOWED_FILE = {"txt", "pdf"}

# Check if the uploaded file has the correct extension
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_FILE

@app.route('/')
def upload():
    return render_template('upload.html')

@app.route("/", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        # Check if a file was uploaded
        if "file" not in request.files:
            return "No file part"

        file = request.files["file"]

        # If no file is selected
        if file.filename == "":
            return "No selected file"

        # If file is valid, process it in memory
        if file and allowed_file(file.filename):
            file_content = file.read()  # Read file into memory
            # Process the file based on its type
            text = ""
            if file.filename.endswith(".txt"):
                try:
                    text = file_content.decode("utf-8")  # Try decoding with UTF-8
                except UnicodeDecodeError:
                    try:
                        text = file_content.decode("gbk")  # Try with gbk encoding
                    except UnicodeDecodeError:
                        return "Could not decode file content"
            elif file.filename.endswith(".pdf"):
                # Extract text from PDF using PyPDF2
                pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()

            # Convert text to speech using gTTS
            tts = gTTS(text, lang="zh")

            # Save the MP3 file to disk
            mp3_filename = "output.mp3"
            tts.save(mp3_filename)

            # Return the MP3 as a downloadable file
            return send_file(mp3_filename, as_attachment=True, download_name="speech.mp3", mimetype="audio/mpeg")

if __name__ == "__main__":
    app.run(debug=True)
