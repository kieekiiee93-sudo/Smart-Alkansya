from io import BytesIO
from PIL import Image
import os
import sqlite3
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "alkansya.db")

def init_db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)

    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                source TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

CAMERA_PAGE = """
<!DOCTYPE html>
<html lang="tl">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart Alkansya</title>
<style>
body {
  margin: 0; padding: 20px;
  background: #071014; color: #eaffff;
  font-family: Arial, sans-serif; text-align: center;
}
.card {
  max-width: 480px; margin: 15px auto;
  padding: 18px; border-radius: 16px;
  background: #101e24; border: 1px solid #00ffee;
}
h1 { color: #00ffee; }
video, canvas {
  width: 100%; border-radius: 12px;
  background: #000;
}
button, select {
  margin: 6px; padding: 12px;
  border: 0; border-radius: 9px;
  font-size: 16px;
}
button { background: #00ffee; color: #001012; }
#balance { font-size: 30px; color: #00ffee; }
#status { color: #b8cccc; }
</style>
</head>
<body>
<h1>💰 Smart Alkansya</h1>

<div class="card">
  <p>Kasalukuyang ipon</p>
  <div id="balance">₱0.00</div>
</div>

<div class="card">
  <video id="video" autoplay playsinline></video>
  <p id="status">Handa nang buksan ang camera.</p>
  <button id="start">Buksan ang Camera</button>
  <button id="capture">Kumuha ng Larawan</button>
  <canvas id="canvas" hidden></canvas>
</div>

<div class="card">
  <h3>Test mode lamang</h3>
  <p>Pumili ng halaga para subukan ang ledger.</p>
  <select id="amount">
    <option value="1">₱1</option>
    <option value="5">₱5</option>
    <option value="10">₱10</option>
    <option value="20">₱20</option>
    <option value="50">₱50</option>
    <option value="100">₱100</option>
    <option value="500">₱500</option>
    <option value="1000">₱1,000</option>
  </select>
  <button id="add">Test: Idagdag sa Ipon</button>
  <p id="message"></p>
</div>

<script>
const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const statusText = document.getElementById("status");
const message = document.getElementById("message");

document.getElementById("start").onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false
    });
    video.srcObject = stream;
    statusText.textContent = "Camera ay gumagana.";
  } catch (err) {
    statusText.textContent =
      "Hindi mabuksan ang camera. Gumamit ng HTTPS at payagan ang camera permission.";
  }
};

document.getElementById("capture").onclick = async () => {
  if (!video.videoWidth) {
    statusText.textContent = "Buksan muna ang camera.";
    return;
  }

  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;

  canvas.getContext("2d").drawImage(
    video, 0, 0, canvas.width, canvas.height
  );

  statusText.textContent = "Ipinapadala ang larawan...";

  canvas.toBlob(async (blob) => {
    if (!blob) {
      statusText.textContent = "Hindi makuha ang larawan.";
      return;
    }

    const formData = new FormData();
    formData.append("photo", blob, "money.jpg");

    try {
      const response = await fetch("/api/upload-image", {
        method: "POST",
        body: formData
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || "Upload failed.");
      }

      statusText.textContent =
        "Upload successful! Hindi pa nakikilala ang halaga ng pera.";
    } catch (error) {
      statusText.textContent = "Upload error: " + error.message;
    }
  }, "image/jpeg", 0.85);
};

document.getElementById("add").onclick = async () => {
  message.textContent = "Pinoproseso...";
  try {
    const res = await fetch("/api/test-add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        amount: Number(document.getElementById("amount").value)
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "May error.");
    message.textContent = "Naidagdag ang test amount.";
    await refreshBalance();
  } catch (err) {
    message.textContent = err.message;
  }
};

refreshBalance();
</script>
</body>
</html>
"""

@app.get("/")
def home():
    return render_template_string(CAMERA_PAGE)

@app.get("/health")
def health():
    return jsonify({"status": "ok", "project": "Smart Alkansya"})

@app.get("/api/balance")
def balance():
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions"
        ).fetchone()
    return jsonify({"balance": row[0]})

@app.post("/api/test-add")
def test_add():
    data = request.get_json(silent=True) or {}

    try:
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Hindi wastong halaga."}), 400

    allowed = {1, 5, 10, 20, 50, 100, 200, 500, 1000}
    if amount not in allowed:
        return jsonify({"error": "Hindi suportadong test amount."}), 400

    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO transactions (amount, source) VALUES (?, ?)",
            (amount, "manual_test")
        )

    return jsonify({"success": True, "added": amount})


@app.post("/api/recognize")
def recognize_money():
    if "image" not in request.files:
        return jsonify({
            "success": False,
            "error": "Walang larawang natanggap."
        }), 400

    file = request.files["image"]

    try:
        image = Image.open(file.stream)
        image.verify()

        # Re-open and validate image dimensions.
        file.stream.seek(0)
        image = Image.open(file.stream).convert("RGB")

        width, height = image.size

        if width < 100 or height < 100:
            return jsonify({
                "success": False,
                "error": "Masyadong maliit ang larawan."
            }), 400

        # Recognition model will be connected in the next step.
        return jsonify({
            "success": True,
            "uploaded": True,
            "recognized": False,
            "width": width,
            "height": height,
            "message": (
                "Natanggap ang larawan. "
                "Hindi pa naka-install ang money recognition model."
            )
        })

    except Exception:
        return jsonify({
            "success": False,
            "error": "Hindi mabasa ang larawan. Subukan ulit."
        }), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
  
