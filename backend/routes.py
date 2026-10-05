# backend/routes.py
from flask import Blueprint, request, Response, stream_with_context, jsonify, current_app, render_template, flash, redirect, url_for, session, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import pandas as pd
from datetime import datetime, timedelta
from threading import Event
import os, io, json, csv, uuid





from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


main_bp = Blueprint("main", __name__)
limiter = Limiter(key_func=get_remote_address)

ALLOWED_EXTENSIONS = {"csv", "xls", "xlsx", "tsv"}

uploaded_df = None
uploaded_filename = None

# ----------------------------
# FILE STORAGE PATHS
# ----------------------------
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
ACTIVITY_FILE = os.path.join(DATA_DIR, "activities.json")

os.makedirs(DATA_DIR, exist_ok=True)

# ----------------------------
# FILE HELPERS
# ----------------------------
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4, default=str)

# ----------------------------
# HELPERS
# ----------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please login to continue.", "error")
            return redirect(url_for("main.login"))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------
# AUTH
# ----------------------------
@main_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if "username" in session:
        return redirect(url_for("main.upload_page"))

    users = load_json(USERS_FILE)

    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()

        if username in users and check_password_hash(users[username]["password"], password):
            session["username"] = username
            session["email"] = users[username]["email"]
            session["account_type"] = users[username].get("account_type", "basic")

            # update last login
            users[username]["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_json(USERS_FILE, users)

            flash("Login successful!", "success")
            return redirect(url_for("main.upload_page"))

        flash("Invalid credentials", "error")

    return render_template("login.html")


@main_bp.route("/register", methods=["GET", "POST"])
def register():
    users = load_json(USERS_FILE)

    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()
        confirm = request.form.get("confirm_password").strip()
        email = request.form.get("email").strip()

        if username in users:
            flash("Username exists", "error")
        elif password != confirm:
            flash("Passwords mismatch", "error")
        else:
            users[username] = {
                "password": generate_password_hash(password),
                "email": email,
                "account_type": "basic",
                "joined": datetime.now().strftime("%Y-%m-%d"),
                "last_login": None
            }
            save_json(USERS_FILE, users)

            flash("Registered successfully", "success")
            return redirect(url_for("main.login"))

    return render_template("register.html")


@main_bp.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("main.login"))

# ----------------------------
# PROFILE
# ----------------------------
@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    users = load_json(USERS_FILE)
    activities_data = load_json(ACTIVITY_FILE)

    username = session["username"]

    # SETTINGS UPDATE
    if request.method == "POST":
        new_email = request.form.get("email")
        new_password = request.form.get("password")
        account_type = request.form.get("account_type")

        users[username]["email"] = new_email
        users[username]["account_type"] = account_type

        if new_password:
            users[username]["password"] = generate_password_hash(new_password)

        save_json(USERS_FILE, users)
        flash("Profile updated!", "success")
        return redirect(url_for("main.profile"))

    user_data = users.get(username, {})

    # format last login
    last_login = user_data.get("last_login")
    last_login_dt = datetime.strptime(last_login, "%Y-%m-%d %H:%M:%S") if last_login else None

    # activities
    activities = activities_data.get(username, [])

    # convert datetime string → datetime object
    for act in activities:
        act["datetime"] = datetime.strptime(act["datetime"], "%Y-%m-%d %H:%M:%S")

    user = {
        "username": username,
        "email": user_data.get("email"),
        "account_type": user_data.get("account_type"),
        "last_login": last_login_dt
    }

    stats = {
        "uploaded_datasets": len(activities),
        "total_rows": sum(a.get("rows", 0) for a in activities),
        "total_columns": sum(a.get("columns", 0) for a in activities),
        "total_interactions": len(activities)
    }

    return render_template("profile.html", user=user, stats=stats, activities=activities)

# ----------------------------
# UPLOAD
# ----------------------------
@main_bp.route("/upload")
@login_required
def upload_page():
    return render_template("upload.html")


@main_bp.route("/upload", methods=["POST"])
@login_required
def upload_file():
    global uploaded_df, uploaded_filename

    if "file" not in request.files:
        return jsonify({"error": "No file attached"}), 400

    file = request.files["file"]

    if not file or file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type"}), 400

    # Save file
    os.makedirs(current_app.config.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)
    filename = secure_filename(file.filename)
    save_path = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), filename)
    file.save(save_path)

    # ----------------------------
    # ORIGINAL ANALYSIS LOGIC (RESTORED)
    # ----------------------------
    try:
        from upload_analyzer import UploadAnalyzer
        analyzer = UploadAnalyzer(save_path)
        meta = analyzer.file_metadata()
        uploaded_df = analyzer.df.copy()
    except Exception:
        try:
            uploaded_df = pd.read_csv(save_path)
            meta = {
                "rows": uploaded_df.shape[0],
                "columns": uploaded_df.shape[1],
                "duplicates": int(uploaded_df.duplicated().sum()),
                "missing_percent": (uploaded_df.isna().sum() / max(1, len(uploaded_df)) * 100).round(2).to_dict()
            }
        except Exception as e:
            return jsonify({"error": f"Failed to analyze file: {str(e)}"}), 500

    uploaded_filename = filename
    preview_df = uploaded_df.head(5).fillna("").to_dict(orient="records")

    missing_map = meta.get("missing_percent", {}) if isinstance(meta, dict) else {}
    avg_missing = round(sum(missing_map.values()) / max(1, len(missing_map)), 2) if missing_map else 0.0

    # ----------------------------
    # ✅ FIX: SAVE ACTIVITY (JSON PERSISTENCE)
    # ----------------------------
    activities = load_json(ACTIVITY_FILE)
    username = session.get("username")

    if username not in activities:
        activities[username] = []

    activities[username].insert(0, {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": "Upload",
        "filename": filename,
        "rows": int(meta.get("rows", uploaded_df.shape[0])),
        "columns": int(meta.get("columns", uploaded_df.shape[1])),
        "status": "Success"
    })

    # keep last 20
    activities[username] = activities[username][:20]

    save_json(ACTIVITY_FILE, activities)

    # ----------------------------
    # RESPONSE (UNCHANGED → FRONTEND SAFE)
    # ----------------------------
    return jsonify({
        "filename": filename,
        "message": "Uploaded",
        "health": {
            "rows": int(meta.get("rows", uploaded_df.shape[0])),
            "columns": int(meta.get("columns", uploaded_df.shape[1])),
            "duplicates": int(meta.get("duplicates", int(uploaded_df.duplicated().sum()))),
            "missing_percent": avg_missing,
            "missing_per_column": missing_map
        },
        "preview": preview_df
    }), 200

# ----------------------------
# Upload AI Insights
# ----------------------------
@main_bp.route("/upload/ai-insights", methods=["POST"])
@login_required
def upload_ai_insights():
    body = request.get_json() or {}
    filename = body.get("filename")

    df = None
    if filename:
        path = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), filename)
        if not os.path.exists(path):
            return jsonify({"error": "file not found"}), 404
        try:
            df = pd.read_csv(path)
        except Exception as e:
            return jsonify({"error": f"Failed to load file: {str(e)}"}), 500
    else:
        global uploaded_df
        if uploaded_df is None:
            return jsonify({"error": "No file uploaded"}), 400
        df = uploaded_df

    try:
        dtypes = df.dtypes.astype(str).to_dict()
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        categorical_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        duplicates = int(df.duplicated().sum())
        missing_percent = (df.isna().sum() / max(1, len(df)) * 100).round(2).to_dict()
    except Exception as e:
        return jsonify({"error": f"Insights error: {str(e)}"}), 500

    return jsonify({
        "summary": {
            "rows": int(len(df)),
            "columns": int(df.shape[1]),
            "duplicates": duplicates
        },
        "dtypes": dtypes,
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "missing_percent": missing_percent
    }), 200




# ----------------------------
# CleanerAnalyzer wrapper (adapts functions to method-style used by routes)
# ----------------------------

# Import functional analyzers
import cleaner_analyzer as ca

@main_bp.route("/cleaner")
@login_required
def cleaner_page():
    return render_template("cleaner.html")


class CleanerAnalyzer:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy() if df is not None else pd.DataFrame()

    def get_html(self):
        return ca.df_preview_html(self.df)

    def summary(self):
        return ca.df_summary(self.df)

    # actions: each returns a new DataFrame (the cleaner_analyzer functions)
    def remove_duplicates(self):
        return ca.remove_duplicates(self.df)

    def drop_missing(self):
        return ca.drop_missing_rows(self.df, how="any")

    def fill_mean(self):
        return ca.fill_missing_df(self.df, method="mean")

    def fill_median(self):
        return ca.fill_missing_df(self.df, method="median")

    def fill_mode(self):
        return ca.fill_missing_df(self.df, method="mode")

    def remove_outliers(self):
        return ca.remove_outliers_iqr(self.df)

    def normalize(self):
        return ca.normalize_df(self.df)

    def standardize(self):
        return ca.standardize_df(self.df)

    def trim_spaces(self):
        return ca.trim_spaces_df(self.df)

    def to_lowercase(self):
        return ca.to_lowercase_df(self.df)

    def to_uppercase(self):
        return ca.to_uppercase_df(self.df)

    def remove_special_chars(self):
        return ca.remove_special_chars_df(self.df)

    def drop_column(self, column: str):
        return ca.drop_column_df(self.df, column)

    def convert_dtype(self, column: str, dtype: str):
        return ca.convert_dtype_df(self.df, column, dtype)

    def regex_replace(self, column: str, pattern: str, replacement: str):
        return ca.regex_replace_df(self.df, column, pattern, replacement)

    def extract_substring(self, column: str, start: int, end: int = None):
        return ca.extract_substring_df(self.df, column, start, end)

    def format_date(self, column: str, fmt: str):
        return ca.format_date_df(self.df, column, fmt)

    def auto_clean(self):
        new_df, summary = ca.auto_clean_pipeline(self.df)
        return new_df, summary

# ----------------------------
# Cleaner integration routes (use module-level cleaner_df as working state)
# ----------------------------
@main_bp.route("/load_uploaded", methods=["GET"])
def load_uploaded():
    global uploaded_df, cleaner_df
    if uploaded_df is None:
        return jsonify({"error": "No file uploaded yet"}), 400
    cleaner_df = uploaded_df.copy()
    analyzer = CleanerAnalyzer(cleaner_df)
    try:
        preview_html = analyzer.get_html()
    except Exception:
        preview_html = cleaner_df.head(10).to_html(classes="table-auto", index=False)
    return jsonify({"preview_html": preview_html, "summary": analyzer.summary(), "filename": uploaded_filename}), 200

@main_bp.get("/clean/reset")
def reset_cleaner():
    global uploaded_df, cleaner_df
    if uploaded_df is None:
        return jsonify({"error": "No uploaded dataset to reset"}), 400
    cleaner_df = uploaded_df.copy()
    return jsonify({"message": "Cleaner dataset reset to original upload"}), 200


@main_bp.route("/clean/data")
def clean_data():
    global cleaner_df

    if cleaner_df is None:
        return jsonify({
            "error": "No data loaded",
            "rows": 0,
            "columns": 0,
            "types": {},
            "data": []
        }), 400

    # Column types mapping
    types = {col: str(dtype) for col, dtype in cleaner_df.dtypes.items()}

    # Convert df to records (preview)
    records = cleaner_df.head(200).to_dict(orient="records")

    return jsonify({
        "rows": len(cleaner_df),
        "columns": len(cleaner_df.columns),
        "types": types,      # <-- REQUIRED for your right panel
        "data": records
    })



# ----------------------------
# Cleaner action endpoints helper & route implementations
# ----------------------------
def _clean_action(func):
    """Helper decorator for cleaner actions that receive a CleanerAnalyzer and must return a DataFrame."""
    def wrapper():
        global cleaner_df
        if cleaner_df is None:
            return jsonify({"error": "No dataset loaded into cleaner"}), 400
        analyzer = CleanerAnalyzer(cleaner_df)
        try:
            result = func(analyzer)
            # result may be DataFrame or (DataFrame, summary)
            if isinstance(result, tuple):
                # e.g., auto_clean returns (df, summary)
                new_df, maybe_summary = result
            else:
                new_df = result
                maybe_summary = None
            cleaner_df = new_df.copy().reset_index(drop=True)
            analyzer = CleanerAnalyzer(cleaner_df)
            response = {"preview_html": analyzer.get_html(), "summary": analyzer.summary()}
            # if caller returned a summary explicitly, include it
            if maybe_summary is not None:
                response["summary"] = maybe_summary
            return jsonify(response), 200
        except Exception as e:
            return jsonify({"error": f"Cleaner action failed: {str(e)}"}), 500
    wrapper.__name__ = func.__name__
    return wrapper

@main_bp.post("/clean/remove_duplicates")
@_clean_action
def clean_remove_duplicates(analyzer): return analyzer.remove_duplicates()

@main_bp.post("/clean/drop_missing")
@_clean_action
def clean_drop_missing(analyzer): return analyzer.drop_missing()

@main_bp.post("/clean/fill_mean")
@_clean_action
def clean_fill_mean(analyzer): return analyzer.fill_mean()

@main_bp.post("/clean/fill_median")
@_clean_action
def clean_fill_median(analyzer): return analyzer.fill_median()

@main_bp.post("/clean/fill_mode")
@_clean_action
def clean_fill_mode(analyzer): return analyzer.fill_mode()

@main_bp.post("/clean/remove_outliers")
@_clean_action
def clean_remove_outliers(analyzer): return analyzer.remove_outliers()

@main_bp.post("/clean/normalize")
@_clean_action
def clean_normalize(analyzer): return analyzer.normalize()

@main_bp.post("/clean/standardize")
@_clean_action
def clean_standardize(analyzer): return analyzer.standardize()

@main_bp.post("/clean/trim_spaces")
@_clean_action
def clean_trim_spaces(analyzer): return analyzer.trim_spaces()

@main_bp.post("/clean/to_lowercase")
@_clean_action
def clean_to_lowercase(analyzer): return analyzer.to_lowercase()

@main_bp.post("/clean/to_uppercase")
@_clean_action
def clean_to_uppercase(analyzer): return analyzer.to_uppercase()

@main_bp.post("/clean/remove_special_chars")
@_clean_action
def clean_remove_special_chars(analyzer): return analyzer.remove_special_chars()


# ----------------------------
# Column / dtype / regex / substring / date routes
# ----------------------------
@main_bp.route("/clean/drop_column", methods=["POST", "GET"])
def route_drop_column():
    global cleaner_df
    column = request.args.get("column") or request.form.get("column")
    if not column:
        return jsonify({"error": "Missing column parameter"}), 400
    if cleaner_df is None:
        return jsonify({"error": "No dataset loaded into cleaner"}), 400
    if column not in cleaner_df.columns:
        return jsonify({"error": f"Column '{column}' not found"}), 404
    analyzer = CleanerAnalyzer(cleaner_df)
    try:
        cleaner_df = analyzer.drop_column(column).copy().reset_index(drop=True)
        return jsonify({"preview_html": analyzer.get_html(), "summary": analyzer.summary()}), 200
    except Exception as e:
        return jsonify({"error": f"Drop column failed: {str(e)}"}), 500

@main_bp.route("/clean/convert_dtype", methods=["POST", "GET"])
def route_convert_dtype():
    global cleaner_df
    column = request.args.get("column") or request.form.get("column")
    dtype = request.args.get("dtype") or request.form.get("dtype")
    if not column or not dtype:
        return jsonify({"error": "Missing column or dtype parameter"}), 400
    if cleaner_df is None:
        return jsonify({"error": "No dataset loaded into cleaner"}), 400
    if column not in cleaner_df.columns:
        return jsonify({"error": f"Column '{column}' not found"}), 404
    try:
        cleaner_df = CleanerAnalyzer(cleaner_df).convert_dtype(column, dtype).copy().reset_index(drop=True)
        analyzer = CleanerAnalyzer(cleaner_df)
        return jsonify({"preview_html": analyzer.get_html(), "summary": analyzer.summary()}), 200
    except Exception as e:
        return jsonify({"error": f"Convert dtype failed: {str(e)}"}), 500

@main_bp.route("/clean/regex_replace", methods=["POST", "GET"])
def route_regex_replace():
    global cleaner_df
    column = request.args.get("column") or request.form.get("column")
    pattern = request.args.get("pattern") or request.form.get("pattern")
    replacement = request.args.get("replacement") or request.form.get("replacement")
    if column is None or pattern is None or replacement is None:
        return jsonify({"error": "Missing parameters"}), 400
    if cleaner_df is None:
        return jsonify({"error": "No dataset loaded into cleaner"}), 400
    if column not in cleaner_df.columns:
        return jsonify({"error": f"Column '{column}' not found"}), 404
    try:
        cleaner_df = CleanerAnalyzer(cleaner_df).regex_replace(column, pattern, replacement).copy().reset_index(drop=True)
        analyzer = CleanerAnalyzer(cleaner_df)
        return jsonify({"preview_html": analyzer.get_html(), "summary": analyzer.summary()}), 200
    except Exception as e:
        return jsonify({"error": f"Regex replace failed: {str(e)}"}), 500

@main_bp.route("/clean/extract_substring", methods=["POST", "GET"])
def route_extract_substring():
    global cleaner_df
    column = request.args.get("column")
    start = request.args.get("start")
    end = request.args.get("end")
    if column is None or start is None:
        return jsonify({"error": "Missing parameters"}), 400
    if cleaner_df is None:
        return jsonify({"error": "No dataset loaded into cleaner"}), 400
    if column not in cleaner_df.columns:
        return jsonify({"error": f"Column '{column}' not found"}), 404
    try:
        start = int(start)
        end = int(end) if end is not None else None
        cleaner_df = CleanerAnalyzer(cleaner_df).extract_substring(column, start, end).copy().reset_index(drop=True)
        analyzer = CleanerAnalyzer(cleaner_df)
        return jsonify({"preview_html": analyzer.get_html(), "summary": analyzer.summary()}), 200
    except Exception as e:
        return jsonify({"error": f"Extract substring failed: {str(e)}"}), 500

@main_bp.route("/clean/format_date", methods=["POST", "GET"])
def route_format_date():
    global cleaner_df
    column = request.args.get("column")
    fmt = request.args.get("format")
    if column is None or fmt is None:
        return jsonify({"error": "Missing parameters"}), 400
    if cleaner_df is None:
        return jsonify({"error": "No dataset loaded into cleaner"}), 400
    if column not in cleaner_df.columns:
        return jsonify({"error": f"Column '{column}' not found"}), 404
    try:
        cleaner_df = CleanerAnalyzer(cleaner_df).format_date(column, fmt).copy().reset_index(drop=True)
        analyzer = CleanerAnalyzer(cleaner_df)
        return jsonify({"preview_html": analyzer.get_html(), "summary": analyzer.summary()}), 200
    except Exception as e:
        return jsonify({"error": f"Format date failed: {str(e)}"}), 500


# ----------------------------
# ADVANCED CLEANING ROUTES
# ----------------------------

@main_bp.post("/clean/remove_empty_columns")
@_clean_action
def clean_remove_empty_columns(analyzer):
    return ca.remove_empty_columns_df(analyzer.df)


@main_bp.post("/clean/smart_fill_missing")
@_clean_action
def clean_smart_fill_missing(analyzer):
    return ca.smart_fill_missing_df(analyzer.df)


@main_bp.post("/clean/knn_fill_missing")
@_clean_action
def clean_knn_fill_missing(analyzer):
    return ca.knn_fill_missing_df(analyzer.df)


@main_bp.post("/clean/remove_correlated")
@_clean_action
def clean_remove_correlated(analyzer):
    return ca.remove_highly_correlated_df(analyzer.df)


@main_bp.post("/clean/robust_scale")
@_clean_action
def clean_robust_scale(analyzer):
    return ca.robust_scale_df(analyzer.df)


@main_bp.post("/clean/fix_dtypes")
@_clean_action
def clean_fix_dtypes(analyzer):
    return ca.auto_fix_dtypes(analyzer.df)


@main_bp.post("/clean/remove_constant_columns")
@_clean_action
def clean_remove_constant_columns(analyzer):
    return ca.remove_constant_columns_df(analyzer.df)


@main_bp.post("/clean/clean_column_names")
@_clean_action
def clean_clean_column_names(analyzer):
    return ca.clean_column_names_df(analyzer.df)


@main_bp.post("/clean/remove_html_tags")
@_clean_action
def clean_remove_html_tags(analyzer):
    return ca.remove_html_tags_df(analyzer.df)


@main_bp.post("/clean/remove_extra_whitespace")
@_clean_action
def clean_remove_extra_whitespace(analyzer):
    return ca.remove_extra_whitespace_df(analyzer.df)



# @main_bp.route("/clean/download", methods=["GET"])
# def download_cleaned():
#     global cleaner_df
#     if cleaner_df is None:
#         return jsonify({"error": "No dataset"}), 400
#     try:
#         csv_bytes = ca.df_to_csv_bytes(cleaner_df)
#         return send_file(
#             io.BytesIO(csv_bytes),
#             mimetype="text/csv",
#             as_attachment=True,
#             download_name="cleaned_dataset.csv"
#         )
#     except Exception as e:
#         return jsonify({"error": f"Failed to generate CSV: {str(e)}"}), 500

@main_bp.route("/clean/download", methods=["GET"])
def download_cleaned():
    global cleaner_df

    if cleaner_df is None or len(cleaner_df) == 0:
        return jsonify({"error": "No dataset"}), 400

    try:
        import io

        # ✅ SAFE direct pandas export (NO helper)
        buffer = io.StringIO()
        cleaner_df.to_csv(buffer, index=False)
        buffer.seek(0)

        return send_file(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            mimetype="text/csv",
            as_attachment=True,
            download_name="cleaned_dataset.csv"
        )

    except Exception as e:
        print("EXPORT ERROR:", e)
        return jsonify({"error": str(e)}), 500
@main_bp.route("/clean/auto", methods=["POST"])
def route_auto():
    global cleaner_df
    if cleaner_df is None:
        return jsonify({"error": "No dataset"}), 400
    analyzer = CleanerAnalyzer(cleaner_df)
    try:
        new_df, summary = analyzer.auto_clean()
        cleaner_df = new_df.copy().reset_index(drop=True)
        preview = ca.df_preview_html(cleaner_df)
        return jsonify({"preview_html": preview, "summary": summary}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------------------
# Formula generator (server-side)
# ----------------------------
@main_bp.route("/formula/generate", methods=["POST"])
def formula_generate():
    data = request.get_json() or {}
    q = data.get("query", "")
    ql = q.strip().lower()
    tokens = ql.split()
    if not tokens:
        return jsonify({"error": "Empty query"}), 400
    func = tokens[0]
    col = " ".join(tokens[1:])

    global cleaner_df
    df = cleaner_df if cleaner_df is not None else uploaded_df
    if df is None:
        return jsonify({"error": "No dataset"}), 400

    # find best matching column index
    col_idx = -1
    for i, c in enumerate(df.columns):
        if c.lower() == col.lower():
            col_idx = i; break
    if col_idx == -1:
        for i, c in enumerate(df.columns):
            if col.lower() in c.lower() or c.lower() in col.lower():
                col_idx = i; break
    if col_idx == -1:
        return jsonify({"error": f'Column \"{col}\" not found'}), 400

    def col_letter(n):
        s=""
        while n>=0:
            s = chr((n%26)+65) + s
            n = n//26 - 1
        return s

    start = 2
    end = max(2, df.shape[0] + 1)
    rng = f"{col_letter(col_idx)}{start}:{col_letter(col_idx)}{end}"
    mapping = {
        "sum": f"=SUM({rng})",
        "avg": f"=AVERAGE({rng})",
        "average": f"=AVERAGE({rng})",
        "min": f"=MIN({rng})",
        "max": f"=MAX({rng})",
        "count": f"=COUNT({rng})",
        "trim": f"=ARRAYFORMULA(TRIM({rng}))"
    }
    out = mapping.get(func, None)
    if not out:
        return jsonify({"error": "Could not parse query"}), 400
    return jsonify({"formula": out}), 200


# ----------------------------
# Optional CSV upload endpoint (used by cleaner.py earlier)
# ----------------------------
@main_bp.route("/upload/csv", methods=["POST"])
def upload_csv_endpoint():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded"}), 400
    try:
        df = pd.read_csv(f)
    except Exception as e:
        return jsonify({"error": "Failed to parse CSV", "detail": str(e)}), 400
    global uploaded_df, cleaner_df, uploaded_filename
    uploaded_df = df.copy()
    cleaner_df = df.copy()
    uploaded_filename = getattr(f, "filename", "uploaded.csv")
    return jsonify({"ok": True, "rows": int(df.shape[0]), "cols": int(df.shape[1])}), 200


@main_bp.route("/clean/preview", methods=["GET"])
def clean_preview():
    global cleaner_df

    if cleaner_df is None:
        return jsonify({"html": "", "health": {}, "types": {}, "error": "no dataframe"}), 200

    df = cleaner_df.copy()

    # Columns data types
    types = df.dtypes.astype(str).to_dict()

    # Dataset health information
    health = {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "missing": int(df.isna().sum().sum()),
        "duplicates": int(df.duplicated().sum())
    }

    # Preview HTML (safe)
    html = df.head(30).to_html(classes="preview-table", index=False)

    return jsonify({
        "html": html,
        "health": health,
        "types": types
    }), 200
    
    


# ----------------------------
# Visualizer (Level 1) routes - append this block to backend/routes.py
# ----------------------------
from visualizer import DataVisualizer
from visualizer_analyzer import VisualizerAnalyzer


@main_bp.route('/visualizer')
def visualizer_page():
    return render_template('visualizer.html')

def _select_df(dataset_choice: str):
    global uploaded_df, cleaner_df
    if dataset_choice == 'cleaned':
        return cleaner_df if cleaner_df is not None else uploaded_df
    return uploaded_df if uploaded_df is not None else cleaner_df

@main_bp.route('/visualizer/columns', methods=['GET'])
def visualizer_columns():
    dataset = request.args.get('dataset', 'uploaded')
    df = _select_df(dataset)
    if df is None:
        return jsonify({'numeric': [], 'categorical': []}), 200
    analyzer = VisualizerAnalyzer(df)
    basic = analyzer.basic_summary()
    return jsonify({'numeric': basic.get('numeric_columns', []), 'categorical': basic.get('categorical_columns', [])}), 200

@main_bp.route('/visualizer/preview', methods=['GET'])
def visualizer_preview():
    dataset = request.args.get('dataset', 'uploaded')
    df = _select_df(dataset)
    if df is None:
        return jsonify({"error": "No dataset loaded"}), 400
    analyzer = VisualizerAnalyzer(df)
    return jsonify(analyzer.preview(rows=200)), 200

@main_bp.route('/visualizer/insights', methods=['GET'])
def visualizer_insights():
    dataset = request.args.get('dataset', 'uploaded')
    df = _select_df(dataset)
    if df is None:
        return jsonify({"error": "No dataset loaded"}), 400
    analyzer = VisualizerAnalyzer(df)
    return jsonify(analyzer.insights()), 200

@main_bp.route('/visualizer/plot', methods=['POST'])
def visualizer_plot():
    payload = request.get_json() or {}
    dataset = payload.get('dataset', 'uploaded')
    chart_type = payload.get('chart_type', 'bar')
    column = payload.get('x_column') or payload.get('column')
    y_column = payload.get('y_column')
    df = _select_df(dataset)
    if df is None:
        return jsonify({'error': 'No dataset loaded'}), 400
    try:
        visualizer = DataVisualizer(df)
        img_b64 = visualizer.plot(chart_type=chart_type, column=column, y_column=y_column)
        analyzer = VisualizerAnalyzer(df)
        return jsonify({"image": img_b64, "insights": analyzer.insights()}), 200
    except Exception as e:
        return jsonify({"error": f"Plotting failed: {str(e)}"}), 500

@main_bp.route('/visualizer/plotly', methods=['POST'])
def visualizer_plotly():
    """
    New interactive endpoint: returns Plotly-ready data (traces & layout) + insights.
    Payload JSON:
    {
      dataset: "uploaded"|"cleaned",
      chart_type: "scatter"|"bar"|"histogram"|"line"|"heatmap",
      x_column: "col",
      y_column: "col",
      filters: { col1: value_or_range, ... }
    }
    """
    payload = request.get_json() or {}
    dataset = payload.get('dataset', 'uploaded')
    chart_type = payload.get('chart_type', 'bar')
    x = payload.get('x_column') or payload.get('column')
    y = payload.get('y_column')
    filters = payload.get('filters', None)
    df = _select_df(dataset)
    if df is None:
        return jsonify({'error': 'No dataset loaded'}), 400
    try:
        visualizer = DataVisualizer(df)
        plotly_obj = visualizer.plotly_trace(chart_type=chart_type, x=x, y=y, filters=filters)
        analyzer = VisualizerAnalyzer(df)
        return jsonify({"plotly": plotly_obj, "insights": analyzer.insights()}), 200
    except Exception as e:
        return jsonify({"error": f"Plotly generation failed: {str(e)}"}), 500

@main_bp.route('/visualizer/download', methods=['GET'])
def visualizer_download():
    global cleaner_df, uploaded_df
    if cleaner_df is not None:
        df = cleaner_df
    elif uploaded_df is not None:
        df = uploaded_df
    else:
        return jsonify({"error": "No dataset"}), 400
    try:
        csv_bytes = ca.df_to_csv_bytes(df)
        return send_file(io.BytesIO(csv_bytes), mimetype="text/csv", as_attachment=True, download_name="visualizer_dataset.csv")
    except Exception:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return send_file(io.BytesIO(buf.getvalue().encode('utf-8')), mimetype="text/csv", as_attachment=True, download_name="visualizer_dataset.csv")

# ----------------------------
# AI Chart Builder & helpers
# ----------------------------

from ai_chart_builder import suggest_from_prompt


@main_bp.route('/visualizer/ai', methods=['POST'])
def visualizer_ai():
    """
    POST payload: { "prompt": "show monthly revenue by country", "dataset": "uploaded"|"cleaned" }
    Returns: suggested config + sample plotly traces (if possible)
    """
    body = request.get_json() or {}
    prompt = body.get('prompt', '').strip()
    dataset = body.get('dataset', 'uploaded')
    # select df
    df = uploaded_df if dataset == 'uploaded' else cleaner_df
    if df is None:
        return jsonify({"error": "No dataset loaded"}), 400
    if not prompt:
        return jsonify({"error": "Empty prompt"}), 400
    try:
        config = suggest_from_prompt(df, prompt)
        # Attempt to produce a small sample Plotly object using existing visualizer
        visualizer = DataVisualizer(df)
        # fallback: call plotly_trace for suggested chart; catch exceptions
        try:
            plotly_obj = visualizer.plotly_trace(chart_type=config.get('chart_type'),
                                                 x=config.get('x_column'),
                                                 y=config.get('y_column'),
                                                 color=config.get('color'),
                                                 filters=config.get('filters') or {})
        except Exception as e:
            plotly_obj = {"data": [], "layout": {"title": f"Preview failed: {str(e)}"}}
        analyzer = VisualizerAnalyzer(df)
        return jsonify({"config": config, "plotly": plotly_obj, "insights": analyzer.insights()}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.route('/visualizer/filter-info', methods=['GET'])
def visualizer_filter_info():
    """
    Returns column-level info to help front-end build advanced filters (min/max, unique values preview)
    GET params: dataset=uploaded|cleaned, column=<column>
    """
    dataset = request.args.get('dataset', 'uploaded')
    column = request.args.get('column')
    df = uploaded_df if dataset == 'uploaded' else cleaner_df
    if df is None:
        return jsonify({"error": "No dataset loaded"}), 400
    if not column or column not in df.columns:
        return jsonify({"error": "Missing or invalid column"}), 400
    ser = df[column].dropna()
    info = {}
    try:
        if pd.api.types.is_numeric_dtype(ser):
            info['type'] = 'numeric'
            info['min'] = float(ser.min())
            info['max'] = float(ser.max())
            info['median'] = float(ser.median())
        else:
            info['type'] = 'categorical'
            top = ser.astype(str).value_counts().head(10).to_dict()
            info['top_values'] = {k: int(v) for k, v in top.items()}
    except Exception as e:
        info['error'] = str(e)
    return jsonify(info), 200



# ----------------------------
# AI Insights, Story Mode & Dashboard persistence routes
# ----------------------------

from ai_insights import full_insights, recommend_charts

# ai-insights
@main_bp.route('/visualizer/ai-insights', methods=['GET','POST'])
def visualizer_ai_insights():
    """
    GET or POST: { dataset: 'uploaded'|'cleaned' }
    Returns: insights (full_insights) + sample plotly for first recommended chart
    """
    body = request.get_json(silent=True) or {}
    dataset = request.args.get('dataset') or body.get('dataset') or 'uploaded'
    df = uploaded_df if dataset == 'uploaded' else cleaner_df
    if df is None:
        return jsonify({"error":"No dataset loaded"}), 400
    try:
        ins = full_insights(df)
        # try to build preview plot for first recommendation
        sample_plot = {"data": [], "layout": {}}
        recs = ins.get('recommendations', [])
        if recs:
            v = DataVisualizer(df)
            first = recs[0]
            try:
                sample_plot = v.plotly_trace(chart_type=first.get('type'), x=first.get('x'), y=first.get('y'), color=first.get('color'), filters=first.get('filters'))
            except Exception as e:
                sample_plot = {"data": [], "layout": {"title": f"Preview generation failed: {str(e)}"}}
        return jsonify({"insights": ins, "preview": sample_plot}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# story mode: accepts a simple script (list of instructions) or a plain text prompt.
@main_bp.route('/visualizer/story', methods=['POST'])
def visualizer_story():
    """
    POST: { dataset:'uploaded', script: '... or list...' }
    Returns: ordered list of {config, caption}
    """
    body = request.get_json() or {}
    dataset = body.get('dataset', 'uploaded')
    script = body.get('script', '') or body.get('prompt', '')
    df = uploaded_df if dataset == 'uploaded' else cleaner_df
    if df is None:
        return jsonify({"error":"No dataset loaded"}), 400
    try:
        # Strategy: use recommend_charts + map script lines to suggestions
        recs = recommend_charts(df, max_recs=6)
        slides = []
        # if user provided script lines, try map each line to a rec
        if script and '\n' in script:
            lines = [l.strip() for l in script.splitlines() if l.strip()]
            for i, ln in enumerate(lines):
                cfg = recs[i] if i < len(recs) else recs[0] if recs else {}
                slides.append({"config": cfg, "caption": ln})
        else:
            # auto story from recommendations
            for r in recs:
                caption = r.get('reason') or f"Chart: {r.get('type')}"
                slides.append({"config": r, "caption": caption})
        return jsonify({"slides": slides}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------------------
# Dashboard persistent store (simple file-based)
# ----------------------------
# Safe fallback path — no app context required
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DASHBOARD_DIR, exist_ok=True)
STORE_FILE = os.path.join(DASHBOARD_DIR, "dashboard_store.json")

def _read_store():
    if not os.path.exists(STORE_FILE):
        return {}
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _write_store(d):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

@main_bp.route('/dashboard/save', methods=['POST'])
def dashboard_save():
    """
    Payload: { id?: optional, title, cards: [ {img: dataUrl, meta: {...}} ] }
    Returns: {ok: True, id: dashboard_id}
    """
    body = request.get_json() or {}
    title = body.get('title', 'Dashboard')
    cards = body.get('cards', [])
    store = _read_store()
    did = str(body.get('id') or int(pd.Timestamp.now().timestamp()))
    store[did] = {"id": did, "title": title, "cards": cards}
    _write_store(store)
    return jsonify({"ok": True, "id": did}), 200

@main_bp.route('/dashboard/load', methods=['GET'])
def dashboard_load():
    did = request.args.get('id')
    if not did:
        return jsonify({"error":"Missing id"}), 400
    store = _read_store()
    dash = store.get(did)
    if not dash:
        return jsonify({"error":"Not found"}), 404
    return jsonify(dash), 200

@main_bp.route('/dashboard/list', methods=['GET'])
def dashboard_list():
    store = _read_store()
    out = [{"id":v.get('id'), "title": v.get('title'), "cards_count": len(v.get('cards',[]))} for v in store.values()]
    return jsonify({"dashboards": out}), 200

@main_bp.route('/dashboard/delete', methods=['POST'])
def dashboard_delete():
    body = request.get_json() or {}
    did = body.get('id')
    if not did:
        return jsonify({"error":"Missing id"}), 400
    store = _read_store()
    if did in store:
        del store[did]
        _write_store(store)
        return jsonify({"ok": True}), 200
    return jsonify({"error":"Not found"}), 404



# ----------------------------
# jpscraper page routes
# ----------------------------

@main_bp.route("/jpscraper")
def jpscraper_page():
    return render_template("jpscraper.html")




# # ==============================
# # SCRAPER FACTORY (PORTALS)
# # ==============================
# def get_scraper(portal: str):
#     portal = (portal or "").lower()

#     if portal == "simplyhired":
#         return SimplyHiredScraper(headless=False)

#     # if portal == "indeed":
#     #     return IndeedScraper(headless=False)

#     # if portal == "linkedin":
#     #     return LinkedInScraper(headless=False)

#     # if portal == "glassdoor":
#     #     return GlassdoorScraper(headless=False)

#     # if portal == "wellfound":
#     #     return WellfoundScraper(headless=False)

#     raise Exception(f"Invalid portal: {portal}")


# # ==============================
# # MAIN UNIFIED SCRAPER API (NEW FRONTEND)
# # ==============================
# @main_bp.route("/api/scrape")
# def scrape_api():

#     portal = request.args.get("portal")
#     job = request.args.get("job", "").strip()
#     location = request.args.get("location", "").strip()
#     full = request.args.get("full", "false").lower() in ("1", "true", "yes")
#     pages = int(request.args.get("pages", "1"))

#     if not job or not location:
#         return {"error": "job + location required"}, 400

#     scraper = get_scraper(portal)

#     def generate():

#         try:
#             for event in scraper.scrape_stream(
#                 job=job,
#                 location=location,
#                 full_job=full,
#                 max_pages=pages
#             ):

#                 # ALWAYS normalize output
#                 if isinstance(event, (dict, list)):
#                     payload = event
#                 else:
#                     payload = {"log": str(event)}

#                 yield f"data: {json.dumps(payload)}\n\n"

#         except Exception as e:
#             yield f"data: {json.dumps({'log': f'FATAL: {str(e)}', 'done': True})}\n\n"

#         finally:
#             try:
#                 scraper.close()
#             except:
#                 pass

#     return Response(stream_with_context(generate()), mimetype="text/event-stream")

# # ----------------------------
# # simplyhired routes
# # ----------------------------

# @main_bp.route("/api/simplyhired", methods=["GET"])
# def simplyhired_api():
#     job = request.args.get("job", "").strip()
#     location = request.args.get("location", "").strip()
#     full = request.args.get("full", "false").lower() in ("1", "true", "yes")
#     pages = int(request.args.get("pages", "1"))

#     if not job or not location:
#         return {"error": "Provide both 'job' and 'location' query params"}, 400

#     def stream():
#         scraper = SimplyHiredScraper(headless=False)
#         for step in scraper.scrape_stream(job=job, location=location, full_job=full, max_pages=pages):
#             # Make sure step is a dict or list
#             if isinstance(step, dict) or isinstance(step, list):
#                 json_step = json.dumps(step)
#             else:
#                 # fallback: wrap string into object
#                 json_step = json.dumps({"log": str(step)})

#             yield f"data: {json_step}\n\n"

#     return Response(stream_with_context(stream()), mimetype="text/event-stream")
from simplyhired import SimplyHiredScraper
from wellfound import WellfoundScraper
from ziprecruiter import ZipRecruiterScraper
from rozee import RozeeScraper
from workable import WorkableScraper
# ==============================
# SCRAPER FACTORY   
# ==============================
def get_scraper(portal: str):
    portal = (portal or "").lower()

    if portal == "simplyhired":
        return SimplyHiredScraper(headless=False)

    elif portal == "wellfound":
        return WellfoundScraper(headless=False)

    elif portal == "ziprecruiter":
        return ZipRecruiterScraper(headless=False)
    
    elif portal == "rozee":
        return RozeeScraper(headless=False)
    
    elif portal == "workable":
        return WorkableScraper(headless=False)

    raise Exception(f"Invalid portal: {portal}") 

  



# ==============================
# UNIFIED SCRAPER API (FIXED)
# ==============================
@main_bp.route("/api/scrape")
def scrape_api():

    portal = request.args.get("portal")
    job = request.args.get("job", "").strip()
    location = request.args.get("location", "").strip()
    full = request.args.get("full", "false").lower() in ("1", "true", "yes")
    pages = int(request.args.get("pages", "1"))

    if not portal:
        return {"error": "portal required"}, 400

    if not job or not location:
        return {"error": "job + location required"}, 400

    scraper = get_scraper(portal)

    def generate():

        try:
            for event in scraper.scrape_stream(
                job=job,
                location=location,
                full_job=full,
                max_pages=pages
            ):

                if isinstance(event, dict):
                    payload = event
                else:
                    payload = {"log": str(event)}

                yield f"data: {json.dumps(payload)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'log': str(e), 'done': True})}\n\n"

        finally:
            try:
                scraper.close()
            except:
                pass

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# ==============================
# workable DIRECT STREAM
# ==============================

@main_bp.route("/api/workable")
def workable_api():

    job = request.args.get("job", "").strip()
    location = request.args.get("location", "").strip()
    full = request.args.get("full", "false").lower() in ("1", "true", "yes")
    pages = int(request.args.get("pages", "1"))

    if not job:
        return {"error": "job required"}, 400

    def stream():

        scraper = WorkableScraper(headless=False)

        try:
            for step in scraper.scrape_stream(
                job=job,
                location=location,
                full_job=full,
                max_pages=pages
            ):
                yield f"data: {json.dumps(step)}\n\n"

        finally:
            scraper.close()

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream"
    )
# ==============================
# ROZEE DIRECT STREAM
# ==============================
@main_bp.route("/api/rozee")
def rozee_api():

    job = request.args.get("job", "").strip()
    location = request.args.get("location", "").strip()

    full = request.args.get(
        "full",
        "false"
    ).lower() in ("1", "true", "yes")

    pages = int(
        request.args.get("pages", "1")
    )

    if not job:
        return {"error": "job required"}, 400

    def stream():

        scraper = RozeeScraper(headless=False)

        try:

            for step in scraper.scrape_stream(
                job=job,
                location=location,
                full_job=full,
                max_pages=pages
            ):

                yield f"data: {json.dumps(step)}\n\n"

        finally:
            scraper.close()

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream"
    )

# ==============================
# ZIPRECRUITER STREAM API
# ==============================
from flask import request, Response, stream_with_context, json
from ziprecruiter import ZipRecruiterScraper


@main_bp.route("/api/ziprecruiter")
def ziprecruiter_api():

    job = request.args.get("job", "").strip()
    location = request.args.get("location", "").strip()
    full = request.args.get("full", "false").lower() in ("1", "true", "yes")
    pages = int(request.args.get("pages", "1"))

    if not job or not location:
        return {"error": "job + location required"}, 400

    def stream():

        scraper = ZipRecruiterScraper(headless=False)

        try:
            for event in scraper.scrape_stream(
                job=job,
                location=location,
                full_job=full,
                max_pages=pages
            ):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'log': str(e), 'done': True})}\n\n"

        finally:
            scraper.close()

    return Response(stream_with_context(stream()), mimetype="text/event-stream")

# ==============================
# WELLFOUND DIRECT STREAM
# ==============================
@main_bp.route("/api/wellfound")
def wellfound_api():

    job = request.args.get("job", "").strip()
    location = request.args.get("location", "").strip()

    full = request.args.get(
        "full",
        "false"
    ).lower() in ("1", "true", "yes")

    pages = int(
        request.args.get("pages", "1")
    )

    if not job or not location:
        return {
            "error": "job + location required"
        }, 400

    def stream():

        scraper = WellfoundScraper(
            headless=False
        )

        try:

            for step in scraper.scrape_stream(
                job=job,
                location=location,
                full_job=full,
                max_pages=pages
            ):

                yield f"data: {json.dumps(step)}\\n\\n"

        finally:
            scraper.close()

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream"
    )





# ==============================
# SIMPLYHIRE DIRECT STREAM (FIXED SAFETY)
# ==============================
@main_bp.route("/api/simplyhired")
def simplyhired_api():

    job = request.args.get("job", "").strip()
    location = request.args.get("location", "").strip()
    full = request.args.get("full", "false").lower() in ("1", "true", "yes")
    pages = int(request.args.get("pages", "1"))

    if not job or not location:
        return {"error": "job + location required"}, 400

    def stream():
        scraper = SimplyHiredScraper(headless=False)

        try:
            for step in scraper.scrape_stream(job, location, full, pages):
                yield f"data: {json.dumps(step)}\n\n"
        finally:
            scraper.close()

    return Response(stream_with_context(stream()), mimetype="text/event-stream")





# ----------------------------
# routes ai_engine.py (FIXED + PRO)
# ----------------------------
 
from collections import Counter
 
# ----------------------------
# GLOBAL SKILLS
# ----------------------------
SKILL_KEYWORDS = [
    "python","sql","aws","react","node",
    "docker","kubernetes","java","c++",
    "javascript","typescript","mongodb",
    "firebase","unity","c#","ai","ml"
]

# ----------------------------
# UTILS
# ----------------------------
def extract_skills(text):
    if not text:
        return []
    text = text.lower()
    return list(set([k for k in SKILL_KEYWORDS if k in text]))

def calculate_match(job, resume_skills):
    if not resume_skills:
        return 0

    job_text = json.dumps(job).lower()

    matches = sum(1 for s in resume_skills if s in job_text)

    return round((matches / len(resume_skills)) * 100)

def skill_gap(job, resume_skills):
    job_skills = job.get("skills", [])
    return list(set(job_skills) - set(resume_skills))

def estimate_salary(job):
    if job.get("salary"):
        return job["salary"]

    title = (job.get("title") or "").lower()

    base = 40000
    if "senior" in title:
        base += 40000
    elif "junior" in title:
        base += 10000
    else:
        base += 25000

    return f"${base}-{base+20000}"

def generate_summary(job, resume_skills=None):
    score = calculate_match(job, resume_skills or [])
    return f"{job.get('title','Role')} at {job.get('company','Company')} | Match: {score}%"

# ----------------------------
# RESUME ANALYSIS
# ----------------------------
 
 
from collections import Counter
import re 

 
# ==============================
# ANALYZE RESUME (TEXT)
# ==============================
@main_bp.route("/api/analyze_resume_text", methods=["POST"])
def analyze_resume_text():
    data = request.json
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    # CLEAN & NORMALIZE
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r'(\b\w\s)+\w\b', lambda m: m.group(0).replace(" ", ""), text)
    text = re.sub(r'\s+', ' ', text).lower()

    # SKILL KB
    SKILL_KB = {
        # Frontend
        "react": ["react", "reactjs"], "next.js": ["next", "nextjs"], "vue": ["vue", "vuejs"],
        "angular": ["angular"], "javascript": ["javascript", "js"], "typescript": ["typescript", "ts"],
        "html": ["html"], "css": ["css"], "tailwind": ["tailwind"], "bootstrap": ["bootstrap"],

        # Backend
        "node.js": ["node", "nodejs", "node.js"], "express": ["express"], "django": ["django"],
        "flask": ["flask"], "fastapi": ["fastapi"], "spring boot": ["spring", "springboot"],
        "laravel": ["laravel"], "php": ["php"], "graphql": ["graphql"], "rest api": ["api","rest api"],

        # Mobile
        "flutter": ["flutter"], "react native": ["react native"], "android": ["android"], "kotlin": ["kotlin"],
        "ios": ["ios"], "swift": ["swift"], "java": ["java"],

        # Game Dev
        "unity": ["unity"], "unreal": ["unreal"], "c#": ["c#", "csharp"], "photon": ["photon"], "playfab": ["playfab"],

        # Data / AI / ML
        "python": ["python"], "sql": ["sql"], "power bi": ["power bi", "powerbi"], "excel": ["excel"],
        "pandas": ["pandas"], "numpy": ["numpy"], "matplotlib": ["matplotlib"], "plotly": ["plotly"],
        "machine learning": ["ml", "machine learning"], "deep learning": ["deep learning"],

        # Databases
        "mysql": ["mysql"], "postgresql": ["postgresql", "postgres"], "mongodb": ["mongodb"], "firebase": ["firebase"],

        # DevOps / Cloud
        "aws": ["aws"], "docker": ["docker"], "kubernetes": ["kubernetes", "k8s"], "ci/cd": ["ci","cd"],

        # Scraping / Lead Gen
        "web scraping": ["scraping", "data scraping"], "selenium": ["selenium"], "scrapy": ["scrapy"],
        "lead generation": ["lead generation", "lead"], "crm": ["crm"], "sales": ["sales"], "linkedin": ["linkedin"]
    }

    # SKILL EXTRACTION
    skills_with_score = {}
    for skill, aliases in SKILL_KB.items():
        total_score = 0
        for alias in aliases:
            pattern = rf"\b{re.escape(alias)}\b"
            occurrences = len(re.findall(pattern, text))
            if occurrences:
                score = 1 + (occurrences * 0.5)
                # context boosts
                if "skill" in text: score += 1
                if "experience" in text: score += 0.5
                if "project" in text: score += 0.7
                total_score += score
        if total_score > 0:
            skills_with_score[skill] = round(total_score, 2)

    skills_found = list(skills_with_score.keys())

    # EXPERIENCE DETECTION
    experience_years = 0
    for pattern in [r"(\d+)\+?\s+years", r"(\d+)\s+yrs", r"(\d+)\s+year experience"]:
        matches = re.findall(pattern, text)
        if matches:
            experience_years = max([int(m) for m in matches])
            break

    # EDUCATION
    education = []
    if any(k in text for k in ["bachelor", "bs"]): education.append("bachelor")
    if any(k in text for k in ["master", "ms"]): education.append("master")
    if "phd" in text: education.append("phd")

    # ROLE DETECTION
    ROLE_MAP = {
        "Data Analyst": ["python", "sql", "power bi", "excel"],
        "Frontend Developer": ["react", "javascript"],
        "Backend Developer": ["node.js", "api"],
        "Game Developer": ["unity", "c#"],
        "ML Engineer": ["machine learning", "python"]
    }

    role_scores = {role: round(sum(skills_with_score.get(s,0) for s in req_skills),2) 
                   for role, req_skills in ROLE_MAP.items() if any(skills_with_score.get(s,0) for s in req_skills)}
    roles = sorted(role_scores, key=role_scores.get, reverse=True)

    # STRENGTH SCORE
    strength_score = min(100, int(sum(skills_with_score.values())*2 + (20 if experience_years>2 else 0)))

    return jsonify({
        "skills": skills_found,
        "skill_scores": skills_with_score,
        "roles": roles,
        "role_scores": role_scores,
        "experience_years": experience_years,
        "education": education,
        "strength_score": strength_score,
        "total_skills": len(skills_found),
        "raw_length": len(text)
    })

# ==============================
# ENRICH JOBS
# ==============================
@main_bp.route("/api/enrich_jobs", methods=["POST"])
def enrich_jobs_api():
    data = request.json
    jobs = data.get("jobs", [])
    resume_skills = data.get("resume_skills", [])

    for job in jobs:
        job["skills"] = job.get("skills") or extract_skills(job.get("description") or job.get("snippet") or "")
        job["score"] = calculate_match(job, resume_skills)
        job["salary_estimate"] = estimate_salary(job)
        job["skill_gap"] = skill_gap(job, resume_skills)

    return jsonify({"jobs": jobs})

# ==============================
# SUMMARY
# ==============================
@main_bp.route("/api/summary", methods=["POST"])
def summary_api():
    data = request.json
    job = data.get("job")
    resume_skills = data.get("resume_skills", [])
    if not job:
        return jsonify({"error": "Job missing"}), 400
    return jsonify({"summary": generate_summary(job, resume_skills)})

# ==============================
# RANK JOBS
# ==============================
@main_bp.route("/api/rank_jobs", methods=["POST"])
def rank_jobs_api():
    jobs = request.json.get("jobs", [])
    ranked = sorted(jobs, key=lambda x: x.get("score",0), reverse=True)
    return jsonify({"jobs": ranked})

# ==============================
# DASHBOARD / ANALYTICS
# ==============================
@main_bp.route("/api/analytics", methods=["POST"])
@main_bp.route("/api/dashboard", methods=["POST"])
def dashboard_api():
    jobs = request.json.get("jobs", [])
    skill_counter = Counter()
    company_counter = Counter()
    location_counter = Counter()

    for j in jobs:
        for s in j.get("skills", []):
            skill_counter[s] += 1
        if j.get("company"): company_counter[j["company"]] += 1
        if j.get("location"): location_counter[j["location"]] += 1

    return jsonify({
        "skills": skill_counter.most_common(10),
        "companies": company_counter.most_common(5),
        "locations": location_counter.most_common(5)
    })

# ==============================
# AI INSIGHT (TRENDING SKILLS + ROLES)
# ==============================
@main_bp.route("/api/ai_insight", methods=["POST"])
def ai_insight_api():
    jobs = request.json.get("jobs", [])
    if not jobs:
        return jsonify({"insight": "No jobs to analyze"})

    skill_counter = Counter()
    role_counter = Counter()

    # Count skills and roles
    ROLE_MAP = {
        "Data Analyst": ["python", "sql", "power bi", "excel"],
        "Frontend Developer": ["react", "javascript"],
        "Backend Developer": ["node.js", "api"],
        "Game Developer": ["unity", "c#"],
        "ML Engineer": ["machine learning", "python"]
    }

    for job in jobs:
        for s in job.get("skills", []):
            skill_counter[s] += 1
        for role, skills in ROLE_MAP.items():
            if any(sk in job.get("skills",[]) for sk in skills):
                role_counter[role] += 1

    top_skills = [s[0] for s in skill_counter.most_common(5)]
    top_roles = [r[0] for r in role_counter.most_common(3)]

    return jsonify({
        "insight": f"🔥 Trending skills: {', '.join(top_skills)} | Top roles: {', '.join(top_roles)}"
    })

# ==============================
# EXPORT CSV
# ==============================

@main_bp.route("/api/export/csv", methods=["POST"])
def export_csv():

    data = request.json or {}
    jobs = data.get("jobs", [])

    if not jobs:
        return jsonify({"error": "No jobs found"}), 400

    rows = []

    for job in jobs:
        rows.append({
            "Title": job.get("title", ""),
            "Company": job.get("company", ""),
            "Location": job.get("location", ""),
            "Match Score": job.get("score", 0),
            "Salary": job.get("salary_estimate", ""),
            "Skills": ", ".join(job.get("skills", [])),
            "Skill Gap": ", ".join(job.get("skill_gap", [])),
            "URL": job.get("url", ""),
            "Description": job.get("description") or job.get("snippet") or ""
        })

    df = pd.DataFrame(rows)

    output = io.StringIO()

    df.to_csv(output, index=False, encoding="utf-8-sig")

    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)

    filename = f"jobs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


# ==============================
# EXPORT EXCEL
# ==============================
@main_bp.route("/api/export/excel", methods=["POST"])
def export_excel():

    data = request.json or {}
    jobs = data.get("jobs", [])

    if not jobs:
        return jsonify({"error": "No jobs found"}), 400

    rows = []

    for i, job in enumerate(jobs, start=1):

        rows.append({
            "#": i,
            "Title": job.get("title", ""),
            "Company": job.get("company", ""),
            "Location": job.get("location", ""),
            "Match Score": job.get("score", 0),
            "Salary": job.get("salary_estimate", ""),
            "Skills": ", ".join(job.get("skills", [])),
            "Skill Gap": ", ".join(job.get("skill_gap", [])),
            "URL": job.get("url", ""),
            "Description": job.get("description") or job.get("snippet") or ""
        })

    df = pd.DataFrame(rows)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        df.to_excel(writer, sheet_name="Jobs", index=False)

        workbook = writer.book
        sheet = writer.sheets["Jobs"]

        # AUTO WIDTH
        for column_cells in sheet.columns:
            length = max(len(str(cell.value or "")) for cell in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(length + 5, 60)

        # FREEZE HEADER
        sheet.freeze_panes = "A2"

    output.seek(0)

    filename = f"jobs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )



# =========================
# 🧭 PAGES
# =========================

@main_bp.route("/leadgenai")
def scraper_page():
    return render_template("leadgenai.html", active="scraper")

# =========================
# 🔍 Lead Gen AI API
# =========================

from leadgenai import scrape_google_maps_stream
from scraper_analyzer import analyze
@main_bp.route("/scrape-stream", methods=["POST"])
def scrape_stream():
    data = request.json
    urls = data.get("urls", [])

    def generate():
        total = len(urls)
        count = 0

        for result in scrape_google_maps_stream(urls):
            count += 1

            yield f"data: {json.dumps({
                'type': 'progress',
                'current': count,
                'total': total
            })}\n\n"

            yield f"data: {json.dumps({
                'type': 'data',
                'row': analyze([result])[0]
            })}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


# =========================
# 📁 EXPORT CSV
# =========================

@main_bp.route("/export/csv", methods=["POST"])
def exportlead_csv():
    data = request.json.get("data", [])

    if not data:
        return jsonify({"error": "No data"}), 400

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=data.csv"}
    )



from leadownerai import stream_process


# =========================
# PAGE
# =========================
@main_bp.route("/leadownerai")
def leadownerai_page():
    return render_template("leadownerai.html")


# =========================
# STREAM (FIXED SSE + SAFE FLUSH)
# =========================

@main_bp.route("/lead-owner-stream", methods=["POST"])
def lead_owner_stream():

    data = request.get_json()
    urls = data.get("urls", [])

    if not urls:
        return jsonify({"error": "No URLs"}), 400

    def generate():

        for item in stream_process(urls):

            # ALWAYS SAFE JSON STRING
            yield f"data: {json.dumps(item)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )