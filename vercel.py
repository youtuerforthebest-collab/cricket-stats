import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional

from flask import Flask, flash, redirect, render_template, request, session, url_for


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Vercel serverless is read-only outside /tmp. Use /tmp there.
IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_RUNTIME_API"))
DATA_DIR = os.path.join("/tmp", "cricket-stats") if IS_VERCEL else os.path.join(BASE_DIR, "data")
DATA_PATH = os.path.join(DATA_DIR, "stats.json")
MASTER_ADMIN_PASSWORD = "Iam@cirs"


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
            json.dump({"leagues": {}}, f, indent=2)


def _load_data() -> Dict[str, Dict]:
    _ensure_data_file()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_data(data: Dict[str, Dict]) -> None:
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


def _is_master() -> bool:
    return bool(session.get("is_master"))


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"\s+", "-", value)
    return value[:40] or "league"


def _get_league(data: Dict[str, Dict]) -> Tuple[Optional[str], Optional[Dict]]:
    league_id = session.get("league_id")
    if not league_id:
        return None, None
    return league_id, data.get("leagues", {}).get(league_id)


def _require_league():
    data = _load_data()
    league_id, league = _get_league(data)
    if not league_id or not league:
        flash("Select a league to continue.", "error")
        return None, None, None
    return data, league_id, league


def _get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


@app.route("/", methods=["GET"])
def home():
    data = _load_data()
    leagues = [
        {"id": league_id, "name": league_data.get("name", league_id)}
        for league_id, league_data in data.get("leagues", {}).items()
    ]
    leagues.sort(key=lambda item: item["name"].lower())
    return render_template("home.html", leagues=leagues)


@app.route("/league/create", methods=["POST"])
def league_create():
    name = request.form.get("league_name", "").strip()
    password = request.form.get("admin_password", "").strip()
    master_password = request.form.get("master_password", "").strip()
    if not name or not password:
        flash("Enter a league name and admin password.", "error")
        return redirect(url_for("home"))

    data = _load_data()
    if not MASTER_ADMIN_PASSWORD:
        master_password = ""
    if master_password and master_password != MASTER_ADMIN_PASSWORD:
        flash("Master password is incorrect.", "error")
        return redirect(url_for("home"))

    if not master_password:
        rate_limits = data.setdefault("rate_limits", {})
        ip = _get_client_ip()
        last_ts = rate_limits.get(ip)
        if last_ts:
            last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < 3600:
                flash("League creation limited to 1 per hour. Try again later.", "error")
                return redirect(url_for("home"))

    league_id = _slugify(name)
    if league_id in data.get("leagues", {}):
        flash("League already exists. Choose a different name.", "error")
        return redirect(url_for("home"))

    data["leagues"][league_id] = {
        "name": name,
        "admin_password": password,
        "orange": {},
        "purple": {},
        "delete_logs": [],
    }
    if not master_password:
        data["rate_limits"][ip] = datetime.now(timezone.utc).timestamp()
    _save_data(data)
    session["league_id"] = league_id
    session["is_admin"] = True
    session["is_master"] = bool(master_password)
    flash("League created. Admin access granted.", "success")
    return redirect(url_for("orange"))


@app.route("/league/login", methods=["POST"])
def league_login():
    league_id = request.form.get("league_id", "")
    role = request.form.get("role", "")
    password = request.form.get("password", "")

    data = _load_data()
    league = data.get("leagues", {}).get(league_id)
    if not league:
        flash("League not found.", "error")
        return redirect(url_for("home"))

    session["league_id"] = league_id
    if role == "admin":
        is_master = MASTER_ADMIN_PASSWORD and password == MASTER_ADMIN_PASSWORD
        if password == league.get("admin_password") or is_master:
            session["is_admin"] = True
            session["is_master"] = bool(is_master)
            flash("Admin access granted.", "success")
            return redirect(url_for("orange"))
        session.pop("league_id", None)
        flash("Incorrect Password", "error")
        return redirect(url_for("home"))

    session["is_admin"] = False
    session["is_master"] = False
    flash("User access granted (view-only).", "info")
    return redirect(url_for("orange"))


@app.route("/league/delete", methods=["POST"])
def league_delete():
    league_id = request.form.get("league_id", "")
    password = request.form.get("password", "")

    data = _load_data()
    league = data.get("leagues", {}).get(league_id)
    if not league:
        flash("League not found.", "error")
        return redirect(url_for("home"))

    is_master = MASTER_ADMIN_PASSWORD and password == MASTER_ADMIN_PASSWORD
    if password != league.get("admin_password") and not is_master:
        flash("Incorrect Password", "error")
        return redirect(url_for("home"))

    data["leagues"].pop(league_id, None)
    _save_data(data)
    if session.get("league_id") == league_id:
        session.clear()
    flash("League deleted.", "success")
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/orange", methods=["GET"])
def orange():
    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))
    leaderboard = sorted(league.get("orange", {}).items(), key=lambda item: item[1], reverse=True)
    return render_template(
        "leaderboard.html",
        page_title="Orange Cap Leaderboard",
        theme="orange",
        metric_label="Runs",
        leaderboard=leaderboard,
        is_admin=_is_admin(),
        route_prefix="orange",
        league_name=league.get("name"),
        delete_logs=league.get("delete_logs", []),
    )


@app.route("/purple", methods=["GET"])
def purple():
    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))
    leaderboard = sorted(league.get("purple", {}).items(), key=lambda item: item[1], reverse=True)
    return render_template(
        "leaderboard.html",
        page_title="Purple Cap Leaderboard",
        theme="purple",
        metric_label="Wickets",
        leaderboard=leaderboard,
        is_admin=_is_admin(),
        route_prefix="purple",
        league_name=league.get("name"),
        delete_logs=league.get("delete_logs", []),
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

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    runs_ok, runs = _parse_int(request.form.get("value", ""))
    if not name or not runs_ok:
        flash("Enter a valid player name and numeric runs.", "error")
        return redirect(url_for("orange"))

    if name in league["orange"]:
        flash("Player already exists. Use edit to adjust runs.", "error")
        return redirect(url_for("orange"))

    league["orange"][name] = runs
    _save_data(data)
    flash("Player added to Orange Cap leaderboard.", "success")
    return redirect(url_for("orange"))


@app.route("/orange/edit", methods=["POST"])
def orange_edit():
    if not _admin_guard():
        return redirect(url_for("orange"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    delta_ok, delta = _parse_int(request.form.get("delta", ""))
    if not name or not delta_ok:
        flash("Enter a valid player name and numeric runs to add.", "error")
        return redirect(url_for("orange"))

    if name not in league["orange"]:
        flash("Player not found. Add them first.", "error")
        return redirect(url_for("orange"))

    league["orange"][name] += delta
    _save_data(data)
    flash("Orange Cap stats updated.", "success")
    return redirect(url_for("orange"))


@app.route("/orange/adjust", methods=["POST"])
def orange_adjust():
    if not _admin_guard():
        return redirect(url_for("orange"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    delta_ok, delta = _parse_int(request.form.get("delta", ""))
    if not name or not delta_ok:
        flash("Enter a valid player name and numeric runs to add.", "error")
        return redirect(url_for("orange"))

    if name not in league["orange"]:
        flash("Player not found. Add them first.", "error")
        return redirect(url_for("orange"))

    league["orange"][name] += delta
    _save_data(data)
    flash("Orange Cap stats updated.", "success")
    return redirect(url_for("orange"))


@app.route("/purple/add", methods=["POST"])
def purple_add():
    if not _admin_guard():
        return redirect(url_for("purple"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    wickets_ok, wickets = _parse_int(request.form.get("value", ""))
    if not name or not wickets_ok:
        flash("Enter a valid player name and numeric wickets.", "error")
        return redirect(url_for("purple"))

    if name in league["purple"]:
        flash("Player already exists. Use edit to adjust wickets.", "error")
        return redirect(url_for("purple"))

    league["purple"][name] = wickets
    _save_data(data)
    flash("Player added to Purple Cap leaderboard.", "success")
    return redirect(url_for("purple"))


@app.route("/purple/edit", methods=["POST"])
def purple_edit():
    if not _admin_guard():
        return redirect(url_for("purple"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    delta_ok, delta = _parse_int(request.form.get("delta", ""))
    if not name or not delta_ok:
        flash("Enter a valid player name and numeric wickets to add.", "error")
        return redirect(url_for("purple"))

    if name not in league["purple"]:
        flash("Player not found. Add them first.", "error")
        return redirect(url_for("purple"))

    league["purple"][name] += delta
    _save_data(data)
    flash("Purple Cap stats updated.", "success")
    return redirect(url_for("purple"))


@app.route("/purple/adjust", methods=["POST"])
def purple_adjust():
    if not _admin_guard():
        return redirect(url_for("purple"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    delta_ok, delta = _parse_int(request.form.get("delta", ""))
    if not name or not delta_ok:
        flash("Enter a valid player name and numeric wickets to add.", "error")
        return redirect(url_for("purple"))

    if name not in league["purple"]:
        flash("Player not found. Add them first.", "error")
        return redirect(url_for("purple"))

    league["purple"][name] += delta
    _save_data(data)
    flash("Purple Cap stats updated.", "success")
    return redirect(url_for("purple"))


def _append_delete_log(league: Dict, player: str, category: str, value: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    league.setdefault("delete_logs", []).append(
        {"player": player, "category": category, "value": value, "ts": ts}
    )
    if len(league["delete_logs"]) > 67:
        league["delete_logs"] = league["delete_logs"][-67:]


@app.route("/orange/delete", methods=["POST"])
def orange_delete():
    if not _admin_guard():
        return redirect(url_for("orange"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    if not name or name not in league["orange"]:
        flash("Player not found.", "error")
        return redirect(url_for("orange"))

    value = league["orange"].pop(name)
    _append_delete_log(league, name, "Orange Cap", value)
    _save_data(data)
    flash("Player deleted from Orange Cap leaderboard.", "success")
    return redirect(url_for("orange"))


@app.route("/purple/delete", methods=["POST"])
def purple_delete():
    if not _admin_guard():
        return redirect(url_for("purple"))

    data, league_id, league = _require_league()
    if not data:
        return redirect(url_for("home"))

    name = request.form.get("name", "").strip()
    if not name or name not in league["purple"]:
        flash("Player not found.", "error")
        return redirect(url_for("purple"))

    value = league["purple"].pop(name)
    _append_delete_log(league, name, "Purple Cap", value)
    _save_data(data)
    flash("Player deleted from Purple Cap leaderboard.", "success")
    return redirect(url_for("purple"))


if __name__ == "__main__":
    app.run(debug=True)
