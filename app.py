from flask import Flask, render_template, request, send_from_directory
from openai import OpenAI
import base64
import os

client = OpenAI()
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def build_prompt(mode):
    base = "Rules: Do NOT make up content. Do NOT add introductions. ONLY provide the notes in the requested format.\n\n"

    if mode == "bullet":
        return base + "Convert all board content into clean BULLET POINT notes."
    elif mode == "cornell":
        return base + "Convert all board content into CORNELL NOTES format with: Main Notes, Cues, and Summary."
    elif mode == "summary":
        return base + "Create a short EXAM REVIEW SUMMARY of the most important testable information."
    elif mode == "definitions":
        return base + "Extract ONLY KEY TERMS and DEFINITIONS. One per line."
    elif mode == "steps":
        return base + "Convert the board into a clear STEP-BY-STEP explanation."
    else:
        return base + "Convert the board content into clean, structured notes."

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results', methods=['POST'])
def results():
    mode = request.form.get("mode", "bullet")
    images = request.files.getlist("images")
    images = [i for i in images if i.filename]

    if not images:
        return "No images uploaded."

    image_paths = []
    encoded_images = []

    for idx, img in enumerate(images):
        name, ext = os.path.splitext(img.filename)
        if not ext:
            ext = ".png"
        filename = f"img_{idx}{ext}"
        path = os.path.join(UPLOAD_FOLDER, filename)
        img.save(path)
        image_paths.append(f"{UPLOAD_FOLDER}/{filename}")

        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            encoded_images.append(encoded)

    prompt = build_prompt(mode)

    content = []
    for b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })
    content.append({"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": content}]
    )

    return render_template(
        "results.html",
        notes=response.choices[0].message.content,
        image_paths=image_paths
    )

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
