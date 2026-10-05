
from flask import Flask
import os

app = Flask(
    __name__,
    static_folder="../frontend/static",   # serves CSS/JS from frontend/static
    template_folder="templates",          # backend/templates
    static_url_path="/statics",
)

# ----------------------------
# Secret key for sessions
# ----------------------------
# You MUST set this to use session for login
# In production, use a secure random value
app.secret_key = "supersecretkey123"  # ⚠️ replace with a strong secret in production
# OR generate random: app.secret_key = os.urandom(24)

# ----------------------------
# Uploads folder
# ----------------------------
UPLOAD_FOLDER = os.path.join(os.getcwd(), "..", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------------------
# Register blueprint
# ----------------------------
from routes import main_bp
app.register_blueprint(main_bp)

# ----------------------------
# Optional: default route redirect
# ----------------------------
# ----------------------------
# Default route → Upload page
# ----------------------------
from flask import redirect, url_for

@app.route('/')
def index():
    return redirect(url_for('main.upload_page'))



# ----------------------------
# Run app
# ----------------------------
# if __name__ == "__main__":
#     app.run(debug=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)