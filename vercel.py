import json
import os
from typing import Dict, Tuple

from flask import Flask, flash, redirect, render_template, request, session, url_for


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_PATH = os.path.join(DATA_DIR, "stats.json")


app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = "change-this-in-production"


def _ensure_data_file() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_PATH):
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump({"orange": {}, "purple": {}}, f, indent=2)


def _load_data() -> Dict[str, Dict[str, int]]:
    _ensure_data_file()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_data(data: Dict[str, Dict[str, int]]) -> None:
    _ensure_data_file()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _parse_int(value: str) -> Tuple[bool, int]:
    try:
        return True, int(value)
    except (TypeError, ValueError):
        return False, 0


def _is_admin() -> bool:
    return bool(session.get("is_admin"))


@app.route("/", methods=["GET"])
def home():
    return render_template("home.html")


@app.route("/login", methods=["POST"])
def login():
    role = request.form.get("role", "")
    password = request.form.get("password", "")

    if role == "admin":
        if password == "3524":
            session["is_admin"] = True
            flash("Admin access granted.", "success")
            return redirect(url_for("orange"))
        flash("Incorrect Password", "error")
        return redirect(url_for("home"))

    session["is_admin"] = False
    flash("User access granted (view-only).", "info")
    return redirect(url_for("orange"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/orange", methods=["GET"])
def orange():
    data = _load_data()
    leaderboard = sorted(
        data.get("orange", {}).items(), key=lambda item: item[1], reverse=True
    )
    return render_template(
        "leaderboard.html",
        page_title="Orange Cap Leaderboard",
        theme="orange",
        metric_label="Runs",
        leaderboard=leaderboard,
        is_admin=_is_admin(),
        route_prefix="orange",
    )


@app.route("/purple", methods=["GET"])
def purple():
    data = _load_data()
    leaderboard = sorted(
        data.get("purple", {}).items(), key=lambda item: item[1], reverse=True
    )
    return render_template(
        "leaderboard.html",
        page_title="Purple Cap Leaderboard",
        theme="purple",
        metric_label="Wickets",
        leaderboard=leaderboard,
        is_admin=_is_admin(),
        route_prefix="purple",
    )


def _admin_guard():
    if not _is_admin():
        flash("Admin access required for this action.", "error")
        return False
    return True


@app.route("/orange/add", methods=["POST"])
def orange_add():
    if not _admin_guard():
        return redirect(url_for("orange"))

    name = request.form.get("name", "").strip()
    runs_ok, runs = _parse_int(request.form.get("value", ""))
    if not name or not runs_ok:
        flash("Enter a valid player name and numeric runs.", "error")
        return redirect(url_for("orange"))

    data = _load_data()
    if name in data["orange"]:
        flash("Player already exists. Use edit to adjust runs.", "error")
        return redirect(url_for("orange"))

    data["orange"][name] = runs
    _save_data(data)
    flash("Player added to Orange Cap leaderboard.", "success")
    return redirect(url_for("orange"))


@app.route("/orange/edit", methods=["POST"])
def orange_edit():
    if not _admin_guard():
        return redirect(url_for("orange"))

    name = request.form.get("name", "").strip()
    delta_ok, delta = _parse_int(request.form.get("delta", ""))
    if not name or not delta_ok:
        flash("Enter a valid player name and numeric runs to add.", "error")
        return redirect(url_for("orange"))

    data = _load_data()
    if name not in data["orange"]:
        flash("Player not found. Add them first.", "error")
        return redirect(url_for("orange"))

    data["orange"][name] += delta
    _save_data(data)
    flash("Orange Cap stats updated.", "success")
    return redirect(url_for("orange"))


@app.route("/purple/add", methods=["POST"])
def purple_add():
    if not _admin_guard():
        return redirect(url_for("purple"))

    name = request.form.get("name", "").strip()
    wickets_ok, wickets = _parse_int(request.form.get("value", ""))
    if not name or not wickets_ok:
        flash("Enter a valid player name and numeric wickets.", "error")
        return redirect(url_for("purple"))

    data = _load_data()
    if name in data["purple"]:
        flash("Player already exists. Use edit to adjust wickets.", "error")
        return redirect(url_for("purple"))

    data["purple"][name] = wickets
    _save_data(data)
    flash("Player added to Purple Cap leaderboard.", "success")
    return redirect(url_for("purple"))


@app.route("/purple/edit", methods=["POST"])
def purple_edit():
    if not _admin_guard():
        return redirect(url_for("purple"))

    name = request.form.get("name", "").strip()
    delta_ok, delta = _parse_int(request.form.get("delta", ""))
    if not name or not delta_ok:
        flash("Enter a valid player name and numeric wickets to add.", "error")
        return redirect(url_for("purple"))

    data = _load_data()
    if name not in data["purple"]:
        flash("Player not found. Add them first.", "error")
        return redirect(url_for("purple"))

    data["purple"][name] += delta
    _save_data(data)
    flash("Purple Cap stats updated.", "success")
    return redirect(url_for("purple"))


if __name__ == "__main__":
    app.run(debug=True)
