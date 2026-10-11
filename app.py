"""
AgroSmart AI - Flask application (routes only; the logic lives in models/ and services/).

Run:  python app.py      then open http://127.0.0.1:5000
"""
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)

import config
from database import db
from models.crop_recommender import CropRecommender
from models.yield_predictor import YieldPredictor
from services import recommendation_service as rs
from services import report_service, soil_analysis, validation as v

app = Flask(__name__)
app.config.update(SECRET_KEY=config.SECRET_KEY, MAX_CONTENT_LENGTH=config.MAX_CONTENT_LENGTH,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.teardown_appcontext(db.close_db)

db.init_db()                       # creates tables on first start; never deletes existing data
recommender = CropRecommender()    # loads the saved model once (not on every request)
predictor = YieldPredictor()
print(f"[AgroSmart AI] crop model: {recommender.status} | yield model: {predictor.status}")

NAV = [("dashboard", "Dashboard", "home"), ("farms", "My Farms", "tractor"), ("soil_health", "Soil Health", "layers"),
       ("crop_recommendations", "Crop Recommendations", "sprout"), ("yield_prediction", "Yield Prediction", "trend"),
       ("fertiliser_guidance", "Fertiliser Guidance", "flask"), ("advisory", "Farming Advisory", "book"),
       ("analytics", "Analytics", "chart"), ("reports", "Reports", "file"), ("about", "About Project", "info"),
       ("settings", "Settings", "gear")]


# ============================================================ security + template helpers
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def csrf_protect():
    """Every POST must carry the secret token that was placed in the form (blocks cross-site form posts)."""
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        if not hmac.compare_digest(sent, session.get("_csrf", "")):
            abort(400)


@app.after_request
def security_headers(resp):
    # Everything the page loads comes from this same server, so we can forbid all other sources.
    csp = ("default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; "
           "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    if request.path.startswith("/welcome"):      # the static landing page uses a few inline style attributes
        csp = csp.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
    resp.headers["Content-Security-Policy"] = csp
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.context_processor
def inject_globals():
    has_demo = db.query("SELECT 1 FROM farms WHERE is_demo = 1 LIMIT 1", one=True) is not None
    return {"csrf_token": csrf_token, "nav_items": NAV, "has_demo": has_demo, "current": request.endpoint}


@app.template_filter("num")
def num_filter(x, digits=2):
    if x is None:
        return "-"
    return f"{x:,.{digits}f}".rstrip("0").rstrip(".") if isinstance(x, float) else f"{x:,}"


@app.template_filter("fromjson")
def fromjson(text):
    return json.loads(text)


@app.errorhandler(400)
def bad_request(_e):
    return render_template("error.html", code=400, title="Form session expired",
                           message="Your form could not be verified (the page may have been open too long). Go back, refresh the page and try again."), 400


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, title="Page not found",
                           message="That page or record does not exist. It may have been deleted."), 404


@app.errorhandler(413)
def too_large(_e):
    return render_template("error.html", code=413, title="Request too large", message="The submitted data was too large."), 413


@app.errorhandler(sqlite3.Error)
def db_error(e):
    app.logger.exception(e)
    return render_template("error.html", code=500, title="Database problem",
                           message="The database could not complete that action. Your data was not changed. Please try again."), 500


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error occurred. Nothing was saved. Please go back and try again."), 500


# ============================================================ small data helpers
def get_farm_or_404(farm_id):
    farm = db.query("SELECT * FROM farms WHERE id = ?", (farm_id,), one=True)
    if farm is None:
        abort(404)
    return farm


def all_farms():
    return db.query("SELECT * FROM farms ORDER BY farm_name COLLATE NOCASE")


def farm_ids():
    return {r["id"] for r in db.query("SELECT id FROM farms")}


def stamp(days_ago=0):
    """Timestamp string in the same format SQLite uses; days_ago lets demo data look like it was recorded earlier."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def save_soil(c, demo=False, days_ago=0):
    result = soil_analysis.analyse(c)
    return db.execute(
        "INSERT INTO soil_analyses(farm_id,nitrogen,phosphorus,potassium,ph,ec,organic_carbon,moisture,soil_temp,"
        "soil_type,location,results_json,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (c["farm_id"], c["nitrogen"], c["phosphorus"], c["potassium"], c["ph"], c.get("ec"), c.get("organic_carbon"),
         c.get("moisture"), c.get("soil_temp"), c["soil_type"], c["location"], json.dumps(result), int(demo), stamp(days_ago)))


def save_rec(c, demo=False, days_ago=0):
    result = rs.build_recommendation(recommender, c)
    return db.execute(
        "INSERT INTO crop_recommendations(farm_id,nitrogen,phosphorus,potassium,ph,temperature,humidity,rainfall,soil_type,"
        "top_crop,results_json,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (c["farm_id"], c["nitrogen"], c["phosphorus"], c["potassium"], c["ph"], c["temperature"], c["humidity"],
         c["rainfall"], c.get("soil_type"), result["candidates"][0]["crop"], json.dumps(result), int(demo), stamp(days_ago)))


def save_yield(c, demo=False, days_ago=0):
    result, err = rs.build_yield(predictor, c)
    if err:
        return None, err
    new_id = db.execute(
        "INSERT INTO yield_predictions(farm_id,crop,state,season,area_input,area_unit,area_ha,irrigation,historical_yield,"
        "yield_t_ha,yield_low,yield_high,total_tonnes,mode,results_json,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (c["farm_id"], c["crop"], c["state"], c["season"], c["area"], c["area_unit"], c["area_ha"], c["irrigation"],
         c.get("historical_yield"), result["yield_t_ha"], result["yield_low"], result["yield_high"], result["total_tonnes"],
         result["mode"], json.dumps(result), int(demo), stamp(days_ago)))
    return new_id, None


def show_errors(errors):
    for e in errors:
        flash(e, "danger")


# ============================================================ dashboard
def season_info():
    month = datetime.now().month
    adv = rs.advisory()
    if 6 <= month <= 10:
        now = "Kharif season (June to October)"
    elif month >= 11 or month <= 2:
        now = "Rabi season (November to March)"
    else:
        now = "Zaid / Summer season (March to June)"
    return {"now": now, "month_name": datetime.now().strftime("%B"),
            "reminder": adv["seasonal_reminders"][str(month)], "seasons": adv["seasons"]}


@app.route("/")
def dashboard():
    counts = {t: db.query(f"SELECT COUNT(*) c, SUM(is_demo) d FROM {t}", one=True)
              for t in ("farms", "soil_analyses", "crop_recommendations", "yield_predictions")}
    counts = {k: {"total": r["c"], "demo": r["d"] or 0} for k, r in counts.items()}

    recent = db.query(
        "SELECT 'Soil analysis' AS kind, s.id, f.farm_name AS label, s.created_at, s.is_demo, 'soil' AS rk "
        "FROM soil_analyses s JOIN farms f ON f.id = s.farm_id "
        "UNION ALL SELECT 'Crop recommendation', r.id, COALESCE(f.farm_name, 'No farm linked'), r.created_at, r.is_demo, 'rec' "
        "FROM crop_recommendations r LEFT JOIN farms f ON f.id = r.farm_id "
        "UNION ALL SELECT 'Yield estimate', y.id, f.farm_name, y.created_at, y.is_demo, 'yield' "
        "FROM yield_predictions y JOIN farms f ON f.id = y.farm_id "
        "UNION ALL SELECT 'Farm added', id, farm_name, created_at, is_demo, 'farm' FROM farms "
        "ORDER BY created_at DESC LIMIT 8")

    # soil nutrient summary: how many analyses fall in Low / Medium / High for N, P, K
    summary = {k: {"Low": 0, "Medium": 0, "High": 0} for k in ("Nitrogen (N)", "Phosphorus (P)", "Potassium (K)")}
    alerts, seen = [], set()
    for row in db.query("SELECT s.id, s.farm_id, s.results_json, s.is_demo, f.farm_name FROM soil_analyses s "
                        "JOIN farms f ON f.id = s.farm_id ORDER BY s.created_at DESC"):
        res = json.loads(row["results_json"])
        for p in res["parameters"]:
            if p["label"] in summary:
                summary[p["label"]][p["rating"]] += 1
        if row["farm_id"] not in seen:          # alerts only from the latest analysis of each farm
            seen.add(row["farm_id"])
            if res["flags"]:
                alerts.append({"level": "warning", "text": f"{row['farm_name']}: " + " ".join(res["flags"]),
                               "link": url_for("soil_report", analysis_id=row["id"])})
    for f in db.query("SELECT id, farm_name FROM farms WHERE id NOT IN (SELECT farm_id FROM soil_analyses)"):
        alerts.append({"level": "info", "text": f"{f['farm_name']} has no soil analysis yet.", "link": url_for("soil_health", farm_id=f["id"])})

    crops = db.query("SELECT top_crop, COUNT(*) c FROM crop_recommendations GROUP BY top_crop ORDER BY c DESC LIMIT 8")
    yields = db.query("SELECT y.crop, y.yield_t_ha, y.mode, y.is_demo, f.farm_name FROM yield_predictions y "
                      "JOIN farms f ON f.id = y.farm_id ORDER BY y.created_at DESC LIMIT 8")
    chart_data = {
        "nutrients": summary,
        "crops": [{"crop": rs.crop_info().get(r["top_crop"], {}).get("display_name", r["top_crop"]), "count": r["c"]} for r in crops],
        "yields": [{"label": f"{r['crop']} ({r['farm_name'][:18]})", "value": r["yield_t_ha"], "mode": r["mode"]} for r in reversed(yields)],
    }
    return render_template("dashboard.html", counts=counts, recent=recent, alerts=alerts[:6], season=season_info(),
                           chart_data=chart_data)


LANDING_DIR = config.BASE_DIR / "static" / "landing"


@app.route("/welcome/")           # /welcome redirects here, so the page's relative file links work
def welcome():
    return send_from_directory(LANDING_DIR, "index.html")


@app.route("/welcome/<path:filename>")
def welcome_asset(filename):
    return send_from_directory(LANDING_DIR, filename)


# ============================================================ farms
@app.route("/farms")
def farms():
    q = (request.args.get("q") or "").strip()[:80]
    if q:
        like = f"%{q}%"
        rows = db.query("SELECT * FROM farms WHERE farm_name LIKE ? OR farmer_name LIKE ? OR location LIKE ? "
                        "ORDER BY farm_name COLLATE NOCASE", (like, like, like))
    else:
        rows = all_farms()
    return render_template("farms.html", farms=rows, q=q)


def _farm_form(farm=None):
    return render_template("farm_form.html", farm=farm, form=request.form if request.method == "POST" else (dict(farm) if farm else {}),
                           soil_types=v.SOIL_TYPES, irrigation=v.IRRIGATION, seasons=v.SEASONS, units=v.AREA_UNITS,
                           default_unit=db.get_pref("default_area_unit", "hectare"))


@app.route("/farms/new", methods=["GET", "POST"])
def farm_new():
    if request.method == "POST":
        c, errors = v.validate_farm(request.form)
        if errors:
            show_errors(errors)
            return _farm_form()
        new_id = db.execute("INSERT INTO farms(farm_name,farmer_name,location,area,area_unit,soil_type,irrigation,season,notes) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (c["farm_name"], c["farmer_name"], c["location"], c["area"], c["area_unit"], c["soil_type"],
                             c["irrigation"], c["season"], c["notes"]))
        flash(f"Farm '{c['farm_name']}' was created.", "success")
        return redirect(url_for("farm_details", farm_id=new_id))
    return _farm_form()


@app.route("/farms/<int:farm_id>")
def farm_details(farm_id):
    farm = get_farm_or_404(farm_id)
    soil = db.query("SELECT * FROM soil_analyses WHERE farm_id = ? ORDER BY created_at DESC", (farm_id,))
    recs = db.query("SELECT * FROM crop_recommendations WHERE farm_id = ? ORDER BY created_at DESC", (farm_id,))
    yields = db.query("SELECT * FROM yield_predictions WHERE farm_id = ? ORDER BY created_at DESC", (farm_id,))
    return render_template("farm_details.html", farm=farm, soil=soil, recs=recs, yields=yields,
                           area_ha=v.area_to_hectare(farm["area"], farm["area_unit"]), crop_info=rs.crop_info())


@app.route("/farms/<int:farm_id>/edit", methods=["GET", "POST"])
def farm_edit(farm_id):
    farm = get_farm_or_404(farm_id)
    if request.method == "POST":
        c, errors = v.validate_farm(request.form)
        if errors:
            show_errors(errors)
            return _farm_form(farm)
        db.execute("UPDATE farms SET farm_name=?, farmer_name=?, location=?, area=?, area_unit=?, soil_type=?, irrigation=?, "
                   "season=?, notes=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (c["farm_name"], c["farmer_name"], c["location"], c["area"], c["area_unit"], c["soil_type"],
                    c["irrigation"], c["season"], c["notes"], farm_id))
        flash("Farm details updated.", "success")
        return redirect(url_for("farm_details", farm_id=farm_id))
    return _farm_form(farm)


@app.route("/farms/<int:farm_id>/delete", methods=["POST"])
def farm_delete(farm_id):
    farm = get_farm_or_404(farm_id)
    n = sum(db.query(f"SELECT COUNT(*) c FROM {t} WHERE farm_id = ?", (farm_id,), one=True)["c"]
            for t in ("soil_analyses", "crop_recommendations", "yield_predictions"))
    db.execute("DELETE FROM farms WHERE id = ?", (farm_id,))      # related records are removed by ON DELETE CASCADE
    flash(f"Farm '{farm['farm_name']}' and its {n} related record(s) were deleted.", "success")
    return redirect(url_for("farms"))


# ============================================================ soil health
@app.route("/soil", methods=["GET", "POST"])
def soil_health():
    farms_list = all_farms()
    if request.method == "POST":
        c, errors = v.validate_soil(request.form, farm_ids())
        if errors:
            show_errors(errors)
        else:
            new_id = save_soil(c)
            flash("Soil analysis completed and saved.", "success")
            return redirect(url_for("soil_report", analysis_id=new_id))
    recent = db.query("SELECT s.*, f.farm_name FROM soil_analyses s JOIN farms f ON f.id = s.farm_id "
                      "ORDER BY s.created_at DESC LIMIT 8")
    form = request.form if request.method == "POST" else request.args
    selected = form.get("farm_id", type=int)
    farm = next((f for f in farms_list if f["id"] == selected), None)
    return render_template("soil_health.html", farms=farms_list, recent=recent, form=form, selected_farm=farm,
                           soil_types=v.SOIL_TYPES, limits=v.SOIL_LIMITS)


@app.route("/soil/<int:analysis_id>")
def soil_report(analysis_id):
    rec = db.query("SELECT * FROM soil_analyses WHERE id = ?", (analysis_id,), one=True) or abort(404)
    farm = get_farm_or_404(rec["farm_id"])
    return render_template("soil_report.html", rec=rec, farm=farm, res=json.loads(rec["results_json"]),
                           rid=report_service.report_id("soil", rec["id"]))


# ============================================================ crop recommendations
@app.route("/recommendations", methods=["GET", "POST"])
def crop_recommendations():
    if request.method == "POST":
        c, errors = v.validate_crop_inputs(request.form, farm_ids())
        if errors:
            show_errors(errors)
        else:
            new_id = save_rec(c)
            flash("Crop recommendations generated and saved.", "success")
            return redirect(url_for("recommendation_result", rec_id=new_id))
    profiles = recommender.bundle["profiles"]
    info = rs.crop_info()
    examples = [{"label": info[k]["display_name"],
                 "values": {"nitrogen": p["N"][2], "phosphorus": p["P"][2], "potassium": p["K"][2], "temperature": p["temperature"][2],
                            "humidity": p["humidity"][2], "ph": p["ph"][2], "rainfall": p["rainfall"][2]}}
                for k, p in profiles.items() if k in ("rice", "chickpea", "banana", "cotton")]
    return render_template("crop_recommendations.html", farms=all_farms(), form=request.form if request.method == "POST" else request.args,
                           soil_types=v.SOIL_TYPES, examples=examples, metrics=recommender.metrics,
                           recent=db.query("SELECT r.*, f.farm_name FROM crop_recommendations r LEFT JOIN farms f ON f.id = r.farm_id "
                                           "ORDER BY r.created_at DESC LIMIT 6"), info=info)


@app.route("/recommendations/<int:rec_id>")
def recommendation_result(rec_id):
    rec = db.query("SELECT * FROM crop_recommendations WHERE id = ?", (rec_id,), one=True) or abort(404)
    farm = db.query("SELECT * FROM farms WHERE id = ?", (rec["farm_id"],), one=True) if rec["farm_id"] else None
    res = json.loads(rec["results_json"])
    return render_template("recommendation_result.html", rec=rec, farm=farm, res=res, metrics=recommender.metrics,
                           rid=report_service.report_id("rec", rec["id"]),
                           chart_data={"candidates": [{"crop": c["display_name"], "score": c["score"]} for c in res["candidates"]],
                                       "factors": [{"label": f["label"], "impact": f["impact_pct"]} for f in res["candidates"][0]["factors"]]})


# ============================================================ yield prediction
@app.route("/yield", methods=["GET", "POST"])
def yield_prediction():
    if request.method == "POST":
        c, errors = v.validate_yield(request.form, farm_ids(), predictor.crops, predictor.states, predictor.seasons)
        if errors:
            show_errors(errors)
        else:
            new_id, err = save_yield(c)
            if err:
                flash(err, "danger")
            else:
                flash("Yield estimate generated and saved.", "success")
                return redirect(url_for("yield_result", pred_id=new_id))
    return render_template("yield_prediction.html", farms=all_farms(), form=request.form if request.method == "POST" else request.args,
                           crops=predictor.crops, states=predictor.states, seasons=predictor.seasons, units=v.AREA_UNITS,
                           irrigation=v.IRRIGATION, metrics=predictor.metrics,
                           default_unit=db.get_pref("default_area_unit", "hectare"),
                           recent=db.query("SELECT y.*, f.farm_name FROM yield_predictions y JOIN farms f ON f.id = y.farm_id "
                                           "ORDER BY y.created_at DESC LIMIT 6"))


@app.route("/yield/<int:pred_id>")
def yield_result(pred_id):
    rec = db.query("SELECT * FROM yield_predictions WHERE id = ?", (pred_id,), one=True) or abort(404)
    farm = get_farm_or_404(rec["farm_id"])
    res = json.loads(rec["results_json"])
    return render_template("yield_result.html", rec=rec, farm=farm, res=res, metrics=predictor.metrics,
                           rid=report_service.report_id("yield", rec["id"]),
                           chart_data={"series": (res.get("history") or {}).get("series", []), "estimate": rec["yield_t_ha"],
                                       "low": rec["yield_low"], "high": rec["yield_high"], "crop": rec["crop"], "state": rec["state"]})


# ============================================================ fertiliser guidance + advisory
@app.route("/fertiliser")
def fertiliser_guidance():
    analyses = db.query("SELECT s.id, s.created_at, s.is_demo, f.farm_name FROM soil_analyses s JOIN farms f ON f.id = s.farm_id "
                        "ORDER BY s.created_at DESC")
    aid = request.args.get("analysis_id", type=int)
    crop = request.args.get("crop") or ""
    info = rs.crop_info()
    if crop and crop not in info:
        crop = ""
    guidance, selected, farm = None, None, None
    if aid:
        selected = db.query("SELECT * FROM soil_analyses WHERE id = ?", (aid,), one=True)
        if selected is None:
            flash("That soil analysis does not exist.", "danger")
        else:
            res = json.loads(selected["results_json"])
            guidance = rs.fertiliser_guidance(res, crop or None)
            farm = get_farm_or_404(selected["farm_id"])
    return render_template("fertiliser_guidance.html", analyses=analyses, selected=selected, guidance=guidance, farm=farm,
                           crop=crop, crops=info, resources=rs.advisory()["resources"])


@app.route("/advisory")
def advisory():
    adv = rs.advisory()
    info = rs.crop_info()
    crop = request.args.get("crop") or ""
    if crop not in info:
        crop = ""
    return render_template("advisory.html", adv=adv, crops=info, crop=crop, crop_adv=adv["crops"].get(crop),
                           crop_info=info.get(crop), season=season_info())


# ============================================================ analytics
def _scope(alias, farm_id, demo):
    conds, params = [], []
    if farm_id:
        conds.append(f"{alias}.farm_id = ?")
        params.append(farm_id)
    if demo == "exclude":
        conds.append(f"{alias}.is_demo = 0")
    elif demo == "only":
        conds.append(f"{alias}.is_demo = 1")
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


@app.route("/analytics")
def analytics():
    return render_template("analytics.html", farms=all_farms(), crops=predictor.crops, states=predictor.states,
                           demo_default=db.get_pref("analytics_demo", "all"))


@app.route("/api/analytics")
def api_analytics():
    farm_id = request.args.get("farm_id", type=int)
    demo = request.args.get("demo", "all")
    if demo not in ("all", "exclude", "only"):
        demo = "all"
    out = {}

    where, params = _scope("s", farm_id, demo)
    soil = db.query(f"SELECT s.id, s.nitrogen, s.phosphorus, s.potassium, s.ph, s.is_demo, f.farm_name FROM soil_analyses s "
                    f"JOIN farms f ON f.id = s.farm_id{where} ORDER BY s.created_at", params)
    edges = [4.0 + 0.5 * i for i in range(12)]       # pH bins 4.0 ... 9.5
    labels = [f"{e:.1f}-{e + 0.5:.1f}" for e in edges]
    counts = [0] * len(edges)
    for r in soil:
        idx = min(max(int((r["ph"] - 4.0) // 0.5), 0), len(edges) - 1)
        counts[idx] += 1
    out["ph"] = {"labels": labels, "counts": counts, "n": len(soil)}
    out["npk"] = [{"label": f"{r['farm_name'][:16]} #{r['id']}", "N": r["nitrogen"], "P": r["phosphorus"], "K": r["potassium"]} for r in soil[-12:]]

    where, params = _scope("r", farm_id, demo)
    recs = db.query(f"SELECT r.top_crop, COUNT(*) c FROM crop_recommendations r{where} GROUP BY r.top_crop ORDER BY c DESC", params)
    info = rs.crop_info()
    out["recs"] = [{"crop": info.get(r["top_crop"], {}).get("display_name", r["top_crop"]), "count": r["c"]} for r in recs]

    where, params = _scope("y", farm_id, demo)
    ys = db.query(f"SELECT y.crop, AVG(y.yield_t_ha) a, COUNT(*) c, MAX(y.mode = 'baseline') b FROM yield_predictions y{where} "
                  f"GROUP BY y.crop ORDER BY a DESC", params)
    out["yields"] = [{"crop": r["crop"], "avg": round(r["a"], 2), "n": r["c"], "baseline": bool(r["b"])} for r in ys]

    conds, params = [], []
    if farm_id:
        conds.append("id = ?")
        params.append(farm_id)
    if demo == "exclude":
        conds.append("is_demo = 0")
    elif demo == "only":
        conds.append("is_demo = 1")
    fwhere = (" WHERE " + " AND ".join(conds)) if conds else ""
    farms_rows = db.query(f"SELECT farm_name, area, area_unit FROM farms{fwhere}", params)
    out["areas"] = sorted(({"farm": f["farm_name"], "ha": round(v.area_to_hectare(f["area"], f["area_unit"]), 3)} for f in farms_rows),
                          key=lambda d: -d["ha"])

    # Historical yield comparison: REAL dataset records for a crop+state, plus your own estimates for it
    crop, state = request.args.get("crop", ""), request.args.get("state", "")
    hist = None
    if crop in predictor.crops and state in predictor.states:
        h = predictor.history(crop, state)
        where, params = _scope("y", farm_id, demo)
        extra = (" AND " if where else " WHERE ") + "y.crop = ? AND y.state = ?"
        mine = db.query(f"SELECT y.yield_t_ha, y.created_at FROM yield_predictions y{where}{extra}", params + [crop, state])
        hist = {"crop": crop, "state": state, "series": h["series"] if h else [], "estimates": [m["yield_t_ha"] for m in mine]}
    out["history"] = hist
    out["demo_count"] = sum(1 for r in soil if r["is_demo"])
    out["total_soil"] = len(soil)
    return jsonify(out)


# ============================================================ reports
REPORT_TABLES = {"soil": "soil_analyses", "rec": "crop_recommendations", "yield": "yield_predictions"}


@app.route("/reports")
def reports():
    kind = request.args.get("kind", "")
    items = []
    for k, label, sql in (
            ("soil", "Soil analysis", "SELECT s.id, s.created_at, s.is_demo, f.farm_name, 'ph ' || s.ph AS detail FROM soil_analyses s JOIN farms f ON f.id = s.farm_id"),
            ("rec", "Crop recommendation", "SELECT r.id, r.created_at, r.is_demo, COALESCE(f.farm_name,'No farm linked') farm_name, 'top: ' || r.top_crop AS detail FROM crop_recommendations r LEFT JOIN farms f ON f.id = r.farm_id"),
            ("yield", "Yield estimate", "SELECT y.id, y.created_at, y.is_demo, f.farm_name, y.crop || ', ' || y.state AS detail FROM yield_predictions y JOIN farms f ON f.id = y.farm_id")):
        if kind and kind != k:
            continue
        for r in db.query(sql):
            items.append({"kind": k, "label": label, "id": r["id"], "rid": report_service.report_id(k, r["id"]), "created": r["created_at"],
                          "demo": r["is_demo"], "farm": r["farm_name"], "detail": r["detail"]})
    items.sort(key=lambda d: d["created"], reverse=True)
    return render_template("reports.html", items=items, kind=kind)


@app.route("/reports/<kind>/<int:record_id>.pdf")
def report_pdf(kind, record_id):
    if kind not in REPORT_TABLES:
        abort(404)
    rec = db.query(f"SELECT * FROM {REPORT_TABLES[kind]} WHERE id = ?", (record_id,), one=True) or abort(404)
    farm = db.query("SELECT * FROM farms WHERE id = ?", (rec["farm_id"],), one=True) if rec["farm_id"] else None
    pdf, rid = report_service.build_pdf(kind, rec, farm)
    resp = app.response_class(pdf, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{rid}.pdf"'
    return resp


# ============================================================ about + settings + demo mode
@app.route("/about")
def about():
    return render_template("about.html", cm=recommender.metrics, ym=predictor.metrics,
                           importances=recommender.importances, yield_factors=predictor.factor_importance(),
                           cstatus=recommender.status, ystatus=predictor.status)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        unit = request.form.get("default_area_unit", "")
        demo = request.form.get("analytics_demo", "")
        if unit in v.AREA_UNITS and demo in ("all", "exclude", "only"):
            db.set_pref("default_area_unit", unit)
            db.set_pref("analytics_demo", demo)
            flash("Settings saved.", "success")
        else:
            flash("Invalid settings value.", "danger")
        return redirect(url_for("settings"))
    n_demo = db.query("SELECT COUNT(*) c FROM farms WHERE is_demo = 1", one=True)["c"]
    n_user = db.query("SELECT COUNT(*) c FROM farms WHERE is_demo = 0", one=True)["c"]
    return render_template("settings.html", units=v.AREA_UNITS, unit=db.get_pref("default_area_unit", "hectare"),
                           demo_pref=db.get_pref("analytics_demo", "all"), n_demo=n_demo, n_user=n_user,
                           db_path=str(config.DATABASE))


@app.route("/demo/load", methods=["POST"])
def demo_load():
    """Add illustrative sample records. User records are never modified or removed."""
    existing = db.query("SELECT COUNT(*) c FROM farms WHERE is_demo = 1", one=True)["c"]
    if existing and request.form.get("replace") != "1":
        flash("Demo data is already loaded. Confirm 'replace demo data' to reload it (your own records are never touched).", "warning")
        return redirect(url_for("settings"))
    if existing:
        db.execute("DELETE FROM farms WHERE is_demo = 1")          # only demo-flagged farms (cascade removes their demo records)
        db.execute("DELETE FROM crop_recommendations WHERE is_demo = 1")
    demo = json.loads((config.DATA_DIR / "demo_farms.json").read_text())
    added = {"farms": 0, "soil": 0, "recs": 0, "yields": 0}
    for entry in demo["farms"]:
        f = entry["farm"]
        farm_id = db.execute("INSERT INTO farms(farm_name,farmer_name,location,area,area_unit,soil_type,irrigation,season,notes,is_demo) "
                             "VALUES(?,?,?,?,?,?,?,?,?,1)", (f["farm_name"], f["farmer_name"], f["location"], f["area"], f["area_unit"],
                                                            f["soil_type"], f["irrigation"], f["season"], f["notes"]))
        added["farms"] += 1
        for s in entry["soil"]:
            save_soil({**s, "farm_id": farm_id}, demo=True, days_ago=s["days_ago"])
            added["soil"] += 1
        for r in entry["recommendations"]:
            save_rec({**r, "farm_id": farm_id, "soil_type": f["soil_type"]}, demo=True, days_ago=r["days_ago"])
            added["recs"] += 1
        for y in entry["yields"]:
            c = {**y, "farm_id": farm_id, "area_ha": v.area_to_hectare(y["area"], y["area_unit"])}
            _, err = save_yield(c, demo=True, days_ago=y["days_ago"])
            added["yields"] += 0 if err else 1
    flash(f"Demo data loaded: {added['farms']} farms, {added['soil']} soil analyses, {added['recs']} recommendations, "
          f"{added['yields']} yield estimates. All are labelled DEMO.", "success")
    return redirect(url_for("dashboard"))


@app.route("/demo/remove", methods=["POST"])
def demo_remove():
    db.execute("DELETE FROM farms WHERE is_demo = 1")
    db.execute("DELETE FROM crop_recommendations WHERE is_demo = 1")
    flash("Demo records were removed. Your own records were not touched.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/reset", methods=["POST"])
def reset_all():
    if request.form.get("confirm_text", "").strip() != "DELETE":
        flash("Nothing was deleted. Type DELETE (capital letters) to confirm.", "warning")
        return redirect(url_for("settings"))
    for t in ("yield_predictions", "crop_recommendations", "soil_analyses", "farms"):
        db.execute(f"DELETE FROM {t}")
    flash("All farms and records were deleted.", "success")
    return redirect(url_for("settings"))


if __name__ == "__main__":
    # debug=False on purpose: the debugger allows remote code execution if exposed.
    app.run(host=config.HOST, port=config.PORT, debug=False)
