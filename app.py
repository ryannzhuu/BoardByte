from flask import Flask, render_template, request
from openai import OpenAI
import base64

client = OpenAI()
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/results', methods=['POST'])
def results():
    image = request.files['image']
    image_path = "uploaded.png"
    image.save(image_path)

    import base64
    with open(image_path, "rb") as img_file:
        img_bytes = img_file.read()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Turn these board notes into clean, structured class notes."},
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
    return render_template("results.html", notes=notes)


if __name__ == '__main__':
    app.run(debug=True)
