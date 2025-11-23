from flask import Flask, render_template, request, send_from_directory, redirect, url_for, session
from openai import OpenAI
import json
import base64
import re
import os
import sqlite3
import markdown
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

client = OpenAI()
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = "boardbyte.db"

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret")
app.config["SESSION_COOKIE_NAME"] = "boardbyte_session"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password_hash TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            category TEXT,
            content_html TEXT,
            image_paths TEXT,
            created_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
    conn.close()

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

def clean_markdown(text):
    text = re.sub(r'(?m)^(#+)([^#\s])', r'\1 \2', text)
    text = re.sub(r"^(here'?s.*?:)", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r'(?m)^\s*[-–—]{3,}\s*$', '', text)
    text = text.encode("utf-8", "replace").decode("utf-8")
    return text.strip()

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def save_note(user_id, title, category, content_html):
    if not user_id:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notes (user_id, title, category, content_html, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, title, category, content_html, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

@app.route("/")
def index():
    user = get_current_user()
    return render_template("index.html", user=user)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            return "Email and password required."
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            return "Email already registered."
        password_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, datetime.utcnow().isoformat())
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        session["user_id"] = user_id
        return redirect(url_for("index"))
    return """
    <h2>Sign Up</h2>
    <form method="POST">
        <input type="email" name="email" placeholder="Email" required><br><br>
        <input type="password" name="password" placeholder="Password" required><br><br>
        <button type="submit">Create Account</button>
    </form>
    <p><a href="/login">Already have an account? Log in</a></p>
    """

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        conn.close()
        if not user or not check_password_hash(user["password_hash"], password):
            return "Invalid email or password."
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return """
    <h2>Log In</h2>
    <form method="POST">
        <input type="email" name="email" placeholder="Email" required><br><br>
        <input type="password" name="password" placeholder="Password" required><br><br>
        <button type="submit">Log In</button>
    </form>
    <p><a href="/signup">Need an account? Sign up</a></p>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/results", methods=["POST"])
def results():
    mode = request.form.get("mode", "bullet")
    images = request.files.getlist("images")
    images = [i for i in images if i.filename]

    if not images:
        return "No images uploaded."

    image_bytes = []
    image_exts = []
    encoded_images = []

    for img in images:
        name, ext = os.path.splitext(img.filename)
        if not ext:
            ext = ".png"
        data = img.read()
        image_bytes.append(data)
        image_exts.append(ext)
        encoded = base64.b64encode(data).decode("utf-8")
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

    raw = response.choices[0].message.content
    cleaned = clean_markdown(raw)
    notes_html = markdown.markdown(cleaned)

    user = get_current_user()
    image_paths = []

    if user:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO notes (user_id, title, category, content_html, image_paths, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], f"{mode.capitalize()} notes", mode, notes_html, "[]", datetime.utcnow().isoformat())
        )
        conn.commit()
        note_id = cur.lastrowid
        conn.close()

        saved_dir = os.path.join("saved", str(user["id"]), str(note_id))
        os.makedirs(saved_dir, exist_ok=True)

        saved_rel_paths = []
        for idx, data in enumerate(image_bytes):
            filename = f"img_{idx}{image_exts[idx]}"
            full_path = os.path.join(saved_dir, filename)
            with open(full_path, "wb") as f:
                f.write(data)
            rel_path = f"saved/{user['id']}/{note_id}/{filename}"
            saved_rel_paths.append(rel_path)

        image_paths_json = json.dumps(saved_rel_paths)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE notes SET image_paths = ? WHERE id = ?",
            (image_paths_json, note_id)
        )
        conn.commit()
        conn.close()

        image_paths = saved_rel_paths
    else:
        temp_paths = []
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        for idx, data in enumerate(image_bytes):
            filename = f"temp_{idx}{image_exts[idx]}"
            full_path = os.path.join(UPLOAD_FOLDER, filename)
            with open(full_path, "wb") as f:
                f.write(data)
            temp_paths.append(f"uploads/{filename}")
        image_paths = temp_paths

    return render_template(
        "results.html",
        notes_html=notes_html,
        image_paths=image_paths,
        user=user
    )

@app.route("/notes")
def notes():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, category, created_at FROM notes WHERE user_id = ? ORDER BY datetime(created_at) DESC",
        (user["id"],)
    )
    rows = cur.fetchall()
    conn.close()
    return render_template("notes.html", user=user, notes=rows)

@app.route("/notes/<int:note_id>")
def note_detail(note_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user["id"])
    )
    note = cur.fetchone()
    conn.close()

    if not note:
        return redirect(url_for("notes"))

    notes_html = note["content_html"]
    image_paths_json = note["image_paths"] or "[]"
    image_paths = json.loads(image_paths_json)

    return render_template(
        "results.html",
        notes_html=notes_html,
        image_paths=image_paths,
        user=user
    )

@app.route("/notes/<int:note_id>/delete", methods=["POST"])
def delete_note(note_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user["id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("notes"))

@app.route("/saved/<path:filename>")
def saved_file(filename):
    base_dir = os.path.join("saved")
    return send_from_directory(base_dir, filename)

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
