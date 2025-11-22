from flask import Flask, render_template, request
from openai import OpenAI
import base64
import os

client = OpenAI()
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__)

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
    if mode == "bullet":
        return "Convert the board content into clean, organized BULLET POINT notes."
    elif mode == "cornell":
        return ("Convert the board content into CORNELL NOTES format with:\n"
                "- Main Notes\n- Cues/Keywords\n- Summary")
    elif mode == "summary":
        return "Create a short EXAM REVIEW SUMMARY highlighting only the most testable information."
    elif mode == "definitions":
        return "Extract ONLY the KEY TERMS and DEFINITIONS from this board. Ignore everything else."
    elif mode == "steps":
        return "Turn the board into a clear STEP-BY-STEP EXPLANATION of the process."
    else:
        return "Convert this board into clean, structured class notes."


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results', methods=['POST'])
def results():
    image = request.files['image']
    image_path = "uploads/uploaded.png"
    image.save(image_path)
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
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_base64}"
                        }
                    }
                ]
            }
        ]
    )

    notes = response.choices[0].message.content
    notes = wrap_text(notes)
    return render_template("results.html", notes=notes)

if __name__ == '__main__':
    app.run(debug=True)
