from flask import Flask, render_template, request, send_from_directory
from openai import OpenAI
import base64
import os

client = OpenAI()
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

def wrap_text(text, width=230):
    wrapped_lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            if len(line) + len(word) + 1 > width:
                wrapped_lines.append(line.rstrip())
                line = word + " "
            else:
                line += word + " "
        wrapped_lines.append(line.rstrip())
    return "\n".join(wrapped_lines)

def build_prompt(mode):
    baserule = ("Rules: Do NOT make up content. Do NOT add introductions or formalities, ONLY provide the notes in the specified format. Nothing else \n\n")
    if mode == "bullet":
        return baserule + "Convert the board content into clean, organized BULLET POINT notes."
    elif mode == "cornell":
        return baserule + ("Convert the board content into CORNELL NOTES format with:\n"
                "- Main Notes\n- Cues/Keywords\n- Summary")
    elif mode == "summary":
        return baserule + "Create a short EXAM REVIEW SUMMARY highlighting only the most testable information."
    elif mode == "definitions":
        return baserule + "Extract ONLY the KEY TERMS and DEFINITIONS from this board. Ignore everything else."
    elif mode == "steps":
        return baserule + "Turn the board into a clear STEP-BY-STEP EXPLANATION of the process."
    else:
        return baserule + "Convert this board into clean, structured class notes."


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results', methods=['POST'])
def results():
    image = request.files['image']
    filename = "uploaded.png"
    image_path = f"uploads/{filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))
    mode = request.form.get("mode", "bullet")

    prompt = build_prompt(mode)

    with open(image_path, "rb") as img_file:
        img_bytes = img_file.read()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    )

    notes = response.choices[0].message.content
    notes = wrap_text(notes)
    return render_template("results.html", notes=notes, image_path=image_path)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
