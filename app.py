from flask import Flask, render_template, request, send_from_directory, redirect, url_for, session
from openai import OpenAI
import base64
import re
import os
import sqlite3
import markdown
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json
import time

client = OpenAI()
UPLOAD_FOLDER = "/tmp/uploads"
SAVED_FOLDER = "/tmp/saved"
DB_PATH = "/tmp/boardbyte.db"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAVED_FOLDER, exist_ok=True)
MAX_IMAGES = 10
MIN_SECONDS_BETWEEN_GENERATIONS = 1.0
PASSWORD_MAX_LENGTH = 72

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret")
app.config["SESSION_COOKIE_NAME"] = "boardbyte_session"
with app.app_context():
    init_db()

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
            last_visited TEXT,
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
    text = re.sub(r"(?m)^(#+)([^#\s])", r"\1 \2", text)
    text = re.sub(r"^(here'?s.*?:)", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"(?m)^\s*[-–—]{3,}\s*$", "", text)
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


@app.route("/")
def index():
    user = get_current_user()
    return render_template("index.html", user=user)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    user = get_current_user()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        pw = password
        errors = []
        if len(pw) < 6:
            errors.append("Password must be at least 6 characters.")
        if len(pw) > PASSWORD_MAX_LENGTH:
            errors.append("Password is too long.")
        if not re.search(r"[a-z]", pw):
            errors.append("Password must contain a lowercase letter.")
        if not re.search(r"[A-Z]", pw):
            errors.append("Password must contain an uppercase letter.")
        if not re.search(r"\d", pw):
            errors.append("Password must contain a number.")
        if not re.search(r"[!@#$%^&*()_\-+=\[\]{};:'\",.<>/?\\|]", pw):
            errors.append("Password must contain a special character.")

        if errors:
            error_text = " ".join(errors)
            return render_template("signup.html", user=user, error=error_text)

        if not email or not password:
            error = "Email and password are required."
            return render_template("signup.html", user=user, error=error)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            error = "Email already registered."
            return render_template("signup.html", user=user, error=error)
        password_hash = generate_password_hash(password)
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, created_at),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        session["user_id"] = user_id
        return redirect(url_for("index"))
    return render_template("signup.html", user=user, error=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    user = get_current_user()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        found = cur.fetchone()
        conn.close()
        if not found or not check_password_hash(found["password_hash"], password):
            error = "Invalid email or password."
            return render_template("login.html", user=user, error=error)
        session["user_id"] = found["id"]
        return redirect(url_for("index"))
    return render_template("login.html", user=user, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/results", methods=["POST"])
def results():
    user = get_current_user()

    last_ts = session.get("last_generation_ts")
    now_ts = time.time()
    if last_ts is not None and now_ts - last_ts < MIN_SECONDS_BETWEEN_GENERATIONS:
        return "Please wait a moment and try again."
    
    session["last_generation_ts"] = now_ts

    mode = request.form.get("mode", "bullet")
    images = request.files.getlist("images")
    images = [i for i in images if i.filename]

    if not images:
        return "No images uploaded."
    
    if len(images) > MAX_IMAGES:
        return f"Please upload at most {MAX_IMAGES} images per generation."

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
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )
    content.append({"type": "text", "text": prompt})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": content}]
        )
    except Exception:
        return "There was an error generating notes (possibly a rate limit)."

    raw = response.choices[0].message.content
    cleaned = clean_markdown(raw)
    notes_html = markdown.markdown(cleaned)

    user = get_current_user()
    image_paths = []
    note_id = None
    created_at = None
    last_visited = None
    note_method = mode.capitalize()
    note_title = f"{mode.capitalize()} notes"

    if user:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO notes (user_id, title, category, content_html, image_paths, created_at, last_visited) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], note_title, mode, notes_html, "[]", now_iso, now_iso),
        )
        conn.commit()
        note_id = cur.lastrowid
        conn.close()

        saved_dir = os.path.join(SAVED_FOLDER, str(user["id"]), str(note_id))
        os.makedirs(saved_dir, exist_ok=True)

        saved_rel_paths = []
        for idx, data in enumerate(image_bytes):
            filename = f"img_{idx}{image_exts[idx]}"
            full_path = os.path.join(saved_dir, filename)
            with open(full_path, "wb") as f:
                f.write(data)
            rel_path = f"{SAVED_FOLDER}/{user['id']}/{note_id}/{filename}"
            saved_rel_paths.append(rel_path)

        image_paths_json = json.dumps(saved_rel_paths)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE notes SET image_paths = ? WHERE id = ?",
            (image_paths_json, note_id),
        )
        conn.commit()
        conn.close()

        image_paths = saved_rel_paths
        created_at = now_iso
        last_visited = now_iso
    else:
        temp_paths = []
        for idx, data in enumerate(image_bytes):
            filename = f"temp_{idx}{image_exts[idx]}"
            full_path = os.path.join(UPLOAD_FOLDER, filename)
            with open(full_path, "wb") as f:
                f.write(data)
            temp_paths.append(f"{UPLOAD_FOLDER}/{filename}")
        image_paths = temp_paths

    return render_template(
        "results.html",
        notes_html=notes_html,
        image_paths=image_paths,
        user=user,
        note_id=note_id,
        note_title=note_title,
        note_method=note_method,
        created_at=created_at,
        last_visited=last_visited,
    )


@app.route("/notes")
def notes():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, category, created_at, last_visited FROM notes WHERE user_id = ? ORDER BY datetime(last_visited) DESC, datetime(created_at) DESC",
        (user["id"],),
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
        (note_id, user["id"]),
    )
    note = cur.fetchone()
    if not note:
        conn.close()
        return redirect(url_for("notes"))

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur.execute("UPDATE notes SET last_visited = ? WHERE id = ?", (now_iso, note_id))
    conn.commit()
    conn.close()

    notes_html = note["content_html"]
    image_paths_json = note["image_paths"] or "[]"
    image_paths = json.loads(image_paths_json)
    created_at = note["created_at"]
    last_visited = now_iso
    note_method = (note["category"] or "").capitalize()
    note_title = note["title"]

    return render_template(
        "results.html",
        notes_html=notes_html,
        image_paths=image_paths,
        user=user,
        note_id=note_id,
        note_title=note_title,
        note_method=note_method,
        created_at=created_at,
        last_visited=last_visited,
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


@app.route("/notes/<int:note_id>/rename", methods=["POST"])
def rename_note(note_id):
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    new_title = request.form.get("title", "").strip()
    source = request.form.get("source", "note")
    if not new_title:
        new_title = "Untitled notes"
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE notes SET title = ? WHERE id = ? AND user_id = ?",
        (new_title, note_id, user["id"]),
    )
    conn.commit()
    conn.close()
    if source == "dashboard":
        return redirect(url_for("notes"))
    return redirect(url_for("note_detail", note_id=note_id))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/saved/<path:filename>")
def saved_file(filename):
    return send_from_directory(SAVED_FOLDER, filename)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
