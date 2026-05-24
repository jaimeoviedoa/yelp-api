from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json

app = FastAPI(title="Yelp Mexican Restaurants API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "db/yelp_reviews.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── ENDPOINT 1: health check ──────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "message": "Yelp API funcionando"}

# ── ENDPOINT 2: reviews ───────────────────────────────────────
@app.get("/reviews")
def get_reviews(
    city: str = Query(None),
    sentiment: str = Query(None),
    factor: str = Query(None),
    limit: int = Query(50)
):
    conn = get_db()
    query = """
        SELECT r.*, rf.factor_dominante, rf.factor_score
        FROM reviews r
        LEFT JOIN review_factors rf ON r.review_id = rf.review_id
        WHERE 1=1
    """
    params = []
    if city:
        query += " AND r.city = ?"
        params.append(city)
    if sentiment:
        query += " AND r.sentiment_binary = ?"
        params.append(sentiment)
    if factor:
        query += " AND rf.factor_dominante = ?"
        params.append(factor)
    query += f" LIMIT {limit}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── ENDPOINT 3: KPIs generales ────────────────────────────────
@app.get("/kpis")
def get_kpis():
    conn = get_db()
    data = {}
    data['total_reviews'] = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    data['total_restaurants'] = conn.execute("SELECT COUNT(DISTINCT business_id) FROM reviews").fetchone()[0]
    data['avg_stars'] = round(conn.execute("SELECT AVG(review_stars) FROM reviews").fetchone()[0], 2)
    data['positive_pct'] = round(
        conn.execute("SELECT COUNT(*) FROM reviews WHERE sentiment_binary='positive'").fetchone()[0]
        / data['total_reviews'] * 100, 1
    )
    data['cities'] = [r[0] for r in conn.execute("SELECT DISTINCT city FROM reviews ORDER BY city").fetchall()]
    conn.close()
    return data

# ── ENDPOINT 4: sentimiento por factor ───────────────────────
@app.get("/factors")
def get_factors():
    conn = get_db()
    rows = conn.execute("""
        SELECT rf.factor_dominante as factor,
               COUNT(*) as total,
               SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) as positives,
               ROUND(AVG(r.review_stars), 2) as avg_stars
        FROM review_factors rf
        JOIN reviews r ON rf.review_id = r.review_id
        WHERE rf.factor_dominante IS NOT NULL
        GROUP BY rf.factor_dominante
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── ENDPOINT 5: taxonomía ─────────────────────────────────────
@app.get("/taxonomy")
def get_taxonomy():
    conn = get_db()
    rows = conn.execute("SELECT * FROM themes_master").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['positive_keywords'] = json.loads(d['positive_keywords'])
        d['negative_keywords'] = json.loads(d['negative_keywords'])
        result.append(d)
    return result

# ── ENDPOINT 6: restaurantes ──────────────────────────────────
@app.get("/restaurants")
def get_restaurants(city: str = Query(None)):
    conn = get_db()
    query = """
        SELECT business_id, business_name, city, state,
               COUNT(*) as total_reviews,
               ROUND(AVG(review_stars), 2) as avg_stars,
               SUM(CASE WHEN sentiment_binary='positive' THEN 1 ELSE 0 END) as positive_reviews
        FROM reviews
        WHERE 1=1
    """
    params = []
    if city:
        query += " AND city = ?"
        params.append(city)
    query += " GROUP BY business_id ORDER BY total_reviews DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
# ── ENDPOINT 7: business metrics ──────────────────────────────
@app.get("/business-metrics")
def get_business_metrics(city: str = Query(None)):
    conn = get_db()
    query = "SELECT * FROM business_metrics WHERE 1=1"
    params = []
    if city:
        query += " AND city = ?"
        params.append(city)
    query += " ORDER BY total_reviews DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── ENDPOINT 8: theme metrics por restaurante ─────────────────
@app.get("/theme-metrics/{business_id}")
def get_theme_metrics(business_id: str):
    conn = get_db()
    rows = conn.execute("""
        SELECT tm.*, t.emoji, t.description
        FROM theme_metrics tm
        LEFT JOIN themes_master t ON tm.theme_id = t.theme_name
        WHERE tm.business_id = ?
        ORDER BY total_mentions DESC
    """, (business_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── ENDPOINT 9: detalle de un restaurante ─────────────────────
@app.get("/restaurant/{business_id}")
def get_restaurant_detail(business_id: str):
    conn = get_db()
    metrics = conn.execute(
        "SELECT * FROM business_metrics WHERE business_id = ?",
        (business_id,)
    ).fetchone()
    reviews = conn.execute("""
        SELECT r.review_id, r.review_stars, r.text, r.date,
               r.sentiment_binary, rf.factor_dominante
        FROM reviews r
        LEFT JOIN review_factors rf ON r.review_id = rf.review_id
        WHERE r.business_id = ?
        ORDER BY r.date DESC
        LIMIT 20
    """, (business_id,)).fetchall()
    conn.close()
    return {
        "metrics": dict(metrics) if metrics else {},
        "recent_reviews": [dict(r) for r in reviews]
    }
@app.get("/intelligence/top-problem-drivers")
def get_top_problem_drivers(city: str | None = None, limit: int = 5):

    conn = get_db()

    query = """
        SELECT
            rf.factor_dominante AS factor,
            COUNT(*) AS negative_reviews
        FROM reviews r
        LEFT JOIN review_factors rf
            ON r.review_id = rf.review_id
        WHERE r.sentiment_binary = 'negative'
          AND rf.factor_dominante IS NOT NULL
          AND rf.factor_dominante != ''
    """

    params = []

    if city:
        query += " AND r.city = ?"
        params.append(city)

    query += """
        GROUP BY rf.factor_dominante
        ORDER BY negative_reviews DESC
        LIMIT ?
    """

    params.append(limit)

    rows = conn.execute(query, params).fetchall()

    conn.close()

    return {
        "city": city if city else "all",
        "limit": limit,
        "top_problem_drivers": [
            {
                "factor": row["factor"],
                "negative_reviews": row["negative_reviews"]
            }
            for row in rows
        ]
    }

@app.get("/restaurant-kpis")
def get_restaurant_kpis(business_name: str):
    conn = get_db()

    row = conn.execute("""
        SELECT
            COUNT(*) AS total_reviews,
            ROUND(AVG(review_stars), 2) AS avg_stars,
            ROUND(
                100.0 * SUM(CASE WHEN sentiment_binary = 'positive' THEN 1 ELSE 0 END) / COUNT(*),
                2
            ) AS positive_pct
        FROM reviews
        WHERE business_name = ?
    """, (business_name,)).fetchone()

    conn.close()

    if not row or row["total_reviews"] == 0:
        return {
            "business_name": business_name,
            "total_reviews": 0,
            "avg_stars": 0,
            "positive_pct": 0,
        }

    return {
        "business_name": business_name,
        "total_reviews": row["total_reviews"],
        "avg_stars": row["avg_stars"],
        "positive_pct": row["positive_pct"],
    }