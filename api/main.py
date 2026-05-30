from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import requests

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

@app.get("/")
def root():
    return {"status": "ok", "message": "Yelp API funcionando"}

@app.get("/reviews")
def get_reviews(
    city: str = Query(None),
    sentiment: str = Query(None),
    factor: str = Query(None),
    business_id: str = Query(None),
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
    if business_id:
        query += " AND r.business_id = ?"
        params.append(business_id)

    query += f" LIMIT {limit}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/kpis")
def get_kpis():
    conn = get_db()
    data = {}
    data["total_reviews"] = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    data["total_restaurants"] = conn.execute("SELECT COUNT(DISTINCT business_id) FROM reviews").fetchone()[0]
    data["avg_stars"] = round(conn.execute("SELECT AVG(review_stars) FROM reviews").fetchone()[0], 2)
    data["positive_pct"] = round(
        conn.execute("SELECT COUNT(*) FROM reviews WHERE sentiment_binary='positive'").fetchone()[0]
        / data["total_reviews"] * 100,
        1
    )
    data["cities"] = [r[0] for r in conn.execute("SELECT DISTINCT city FROM reviews ORDER BY city").fetchall()]
    conn.close()
    return data

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

@app.get("/taxonomy")
def get_taxonomy():
    conn = get_db()
    rows = conn.execute("SELECT * FROM themes_master").fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        d["positive_keywords"] = json.loads(d["positive_keywords"])
        d["negative_keywords"] = json.loads(d["negative_keywords"])
        result.append(d)

    return result

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
            "positive_pct": 0
        }

    return {
        "business_name": business_name,
        "total_reviews": row["total_reviews"],
        "avg_stars": row["avg_stars"],
        "positive_pct": row["positive_pct"]
    }

@app.get("/intelligence/top-problem-drivers")
def get_top_problem_drivers(
    city: str = Query("all"),
    business_id: str = Query("all"),
    limit: int = Query(5)
):
    conn = get_db()
    query = """
        SELECT rf.factor_dominante as factor,
               COUNT(*) as negative_reviews
        FROM review_factors rf
        JOIN reviews r ON rf.review_id = r.review_id
        WHERE r.sentiment_binary = 'negative'
        AND rf.factor_dominante IS NOT NULL
    """
    params = []

    if city != "all":
        query += " AND r.city = ?"
        params.append(city)

    if business_id != "all":
        query += " AND r.business_id = ?"
        params.append(business_id)

    query += " GROUP BY rf.factor_dominante ORDER BY negative_reviews DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return {
        "city": city,
        "limit": limit,
        "top_problem_drivers": [dict(r) for r in rows]
    }

@app.get("/intelligence/top-satisfaction-drivers")
def get_top_satisfaction_drivers(
    city: str = Query("all"),
    business_id: str = Query("all"),
    limit: int = Query(5)
):
    conn = get_db()
    query = """
        SELECT rf.factor_dominante as factor,
               COUNT(*) as positive_reviews
        FROM review_factors rf
        JOIN reviews r ON rf.review_id = r.review_id
        WHERE r.sentiment_binary = 'positive'
        AND rf.factor_dominante IS NOT NULL
    """
    params = []

    if city != "all":
        query += " AND r.city = ?"
        params.append(city)

    if business_id != "all":
        query += " AND r.business_id = ?"
        params.append(business_id)

    query += " GROUP BY rf.factor_dominante ORDER BY positive_reviews DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return {
        "city": city,
        "limit": limit,
        "top_satisfaction_drivers": [dict(r) for r in rows]
    }

@app.get("/intelligence/topics")
def get_intelligence_topics(business_id: str = Query("all")):
    conn = get_db()

    extra = " AND r.business_id = ?" if business_id != "all" else ""
    params = [business_id] if business_id != "all" else []

    themes = conn.execute(f"""
        SELECT rf.factor_dominante as id,
               rf.factor_dominante as label,
               COUNT(*) as mentions,
               SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) as positive_mentions,
               SUM(CASE WHEN r.sentiment_binary='negative' THEN 1 ELSE 0 END) as negative_mentions,
               ROUND(SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as sentiment
        FROM review_factors rf
        JOIN reviews r ON rf.review_id = r.review_id
        WHERE rf.factor_dominante IS NOT NULL{extra}
        GROUP BY rf.factor_dominante
        ORDER BY mentions DESC
    """, params).fetchall()

    deep_dive = {}

    for theme in themes:
        tid = theme["id"]
        rparams = ([business_id, tid] if business_id != "all" else [tid])
        rextra = " AND r.business_id = ?" if business_id != "all" else ""

        reviews = conn.execute(f"""
            SELECT r.text, r.review_stars, r.date, r.sentiment_binary as sentiment
            FROM reviews r
            JOIN review_factors rf ON r.review_id = rf.review_id
            WHERE rf.factor_dominante IS NOT NULL{rextra}
            AND rf.factor_dominante = ?
            ORDER BY r.date DESC
            LIMIT 5
        """, rparams).fetchall()

        deep_dive[tid] = {
            "positive": [],
            "negative": [],
            "reviews": [dict(r) for r in reviews]
        }

    conn.close()

    return {
        "themes": [dict(t) for t in themes],
        "deepDiveData": deep_dive
    }

@app.get("/intelligence/market-position")
def get_market_position(business_id: str = Query("all")):
    conn = get_db()

    extra = " AND r.business_id = ?" if business_id != "all" else ""
    params = [business_id] if business_id != "all" else []

    factors = conn.execute(f"""
        SELECT rf.factor_dominante as factor,
               COUNT(*) as total,
               SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) as positives,
               ROUND(SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as sentiment_pct
        FROM review_factors rf
        JOIN reviews r ON rf.review_id = r.review_id
        WHERE rf.factor_dominante IS NOT NULL{extra}
        GROUP BY rf.factor_dominante
        ORDER BY total DESC
    """, params).fetchall()

    factors_list = [dict(f) for f in factors]

    avg_sentiment = (
        sum(f["sentiment_pct"] for f in factors_list) / len(factors_list)
        if factors_list else 0
    )

    strengths = [
        f for f in factors_list
        if f["sentiment_pct"] >= 60 and f["total"] >= 3
    ]

    quick_wins = [
        f for f in factors_list
        if f["sentiment_pct"] >= 60 and f["total"] < 3
    ]

    critical = [
        f for f in factors_list
        if f["sentiment_pct"] < 40 and f["total"] >= 3
    ]

    monitor = [
        f for f in factors_list
        if f["sentiment_pct"] < 60 and f["total"] < 3
    ]

    kpis = conn.execute(
        f"SELECT AVG(review_stars) as avg_stars, COUNT(*) as total FROM reviews r WHERE 1=1{extra}",
        params
    ).fetchone()

    conn.close()

    return {
        "market_standing": {
            "your_rating": round(kpis["avg_stars"], 2),
            "category_avg": 3.5,
            "percentile": round(avg_sentiment)
        },
        "share_of_voice": {
            "your_mentions": kpis["total"],
            "category_total": kpis["total"],
            "share": 100
        },
        "sentiment_vs_competition": {
            "your_nps": round(avg_sentiment - 20),
            "competitor_avg": 25,
            "category_avg": 20
        },
        "strengths": strengths,
        "quick_wins": quick_wins,
        "critical_issues": critical,
        "monitor": monitor,
        "action_plan": [
            f"Improve {f['factor']} experience ({f['sentiment_pct']}% positive)"
            for f in critical[:3]
        ]
    }

@app.get("/intelligence/sentiment-radar")
def get_sentiment_radar(business_id: str = Query("all")):
    conn = get_db()

    extra = " AND r.business_id = ?" if business_id != "all" else ""
    params = [business_id] if business_id != "all" else []

    rows = conn.execute(f"""
        SELECT rf.factor_dominante as factor,
               ROUND(SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as sentiment,
               COUNT(*) as mentions
        FROM review_factors rf
        JOIN reviews r ON rf.review_id = r.review_id
        WHERE rf.factor_dominante IS NOT NULL{extra}
        GROUP BY rf.factor_dominante
    """, params).fetchall()

    conn.close()

    return {
        "radar": [dict(r) for r in rows]
    }

@app.get("/intelligence/market-position-web")
def get_market_position_web(
    business_name: str = "Los Agaves",
    city: str = "Santa Barbara",
    category: str = "Mexican restaurant"
):
    api_key = os.getenv("SERPAPI_KEY")

    if not api_key:
        return {"error": "SERPAPI_KEY is not configured"}

    params = {
        "engine": "google_maps",
        "q": f"{category} in {city}",
        "type": "search",
        "api_key": api_key
    }

    response = requests.get("https://serpapi.com/search.json", params=params)
    data = response.json()
    local_results = data.get("local_results", [])

    competitors = []

    for item in local_results[:10]:
        competitors.append({
            "name": item.get("title"),
            "platform": "Google Maps via SerpAPI",
            "rating": item.get("rating"),
            "review_count": item.get("reviews"),
            "address": item.get("address"),
            "source_url": item.get("link"),
            "place_id": item.get("place_id"),
            "data_id": item.get("data_id")
        })

    return {
        "target_business": business_name,
        "city": city,
        "category": category,
        "source": "web_research_serpapi_google_maps",
        "competitors": competitors
    }

@app.get("/intelligence/google-reviews")
def get_google_reviews(
    place_id: str = Query(None),
    data_id: str = Query(None),
    limit: int = Query(10)
):
    api_key = os.getenv("SERPAPI_KEY")

    if not api_key:
        return {"error": "SERPAPI_KEY is not configured"}

    if not place_id and not data_id:
        return {
            "error": "place_id or data_id is required",
            "message": "Use /intelligence/market-position-web first to get place_id or data_id."
        }

    params = {
        "engine": "google_maps_reviews",
        "api_key": api_key,
        "hl": "en",
        "sort_by": "newestFirst",
    }

    if place_id:
        params["place_id"] = place_id

    if data_id:
        params["data_id"] = data_id

    response = requests.get("https://serpapi.com/search.json", params=params)
    data = response.json()

    reviews = data.get("reviews", [])[:limit]
    normalized_reviews = []

    for index, review in enumerate(reviews):
        text = review.get("snippet") or review.get("description") or ""

        if not text:
            continue

        rating = review.get("rating") or 0

        normalized_reviews.append({
            "review_id": f"google_{place_id or data_id}_{index}",
            "business_id": "google_los_agaves",
            "business_name": "Los Agaves",
            "city": "Santa Barbara",
            "state": "CA",
            "categories": "Mexican restaurant",
            "review_stars": rating,
            "text": text,
            "clean_text": text,
            "date": review.get("date") or "",
            "sentiment_binary": "positive" if rating >= 4 else "negative",
            "review_length": len(text),
            "word_count": len(text.split()),
            "factor_dominante": "otros",
            "factor_score": 0,
            "source_platform": "Google Maps"
        })

    return normalized_reviews

@app.get("/reviews-merged")
def get_reviews_merged(
    business_id: str = "yPSejq3_erxo9zdVYTBnZA",
    data_id: str = "0x80e914e9c7e7e80b:0x4810338ea9f4deba",
    limit: int = 100
):
    google_reviews = get_google_reviews(
        data_id=data_id,
        limit=20
    )

    merged_reviews = []

    if isinstance(google_reviews, list):
        merged_reviews.extend(google_reviews)

    conn = get_db()

    rows = conn.execute("""
        SELECT r.*, rf.factor_dominante, rf.factor_score
        FROM reviews r
        LEFT JOIN review_factors rf ON r.review_id = rf.review_id
        WHERE r.business_id = ?
        LIMIT ?
    """, (business_id, limit)).fetchall()

    conn.close()

    for row in rows:
        review = dict(row)
        review["source_platform"] = "Yelp"
        merged_reviews.append(review)

    return merged_reviews


def get_yelp_reviews_for_merge(business_id="yPSejq3_erxo9zdVYTBnZA", limit=100):
    conn = get_db()
    rows = conn.execute("""
        SELECT r.*, rf.factor_dominante, rf.factor_score
        FROM reviews r
        LEFT JOIN review_factors rf ON r.review_id = rf.review_id
        WHERE r.business_id = ?
        LIMIT ?
    """, (business_id, limit)).fetchall()
    conn.close()

    result = []
    for row in rows:
        review = dict(row)
        review["source_platform"] = "Yelp"
        result.append(review)

    return result

@app.get("/kpis-merged")
def get_kpis_merged(
    business_id: str = "yPSejq3_erxo9zdVYTBnZA",
    yelp_limit: int = 100,
    google_limit: int = 10
):
    yelp_reviews = get_yelp_reviews_for_merge(
        business_id=business_id,
        limit=yelp_limit
    )

    api_key = os.getenv("SERPAPI_KEY")
    google_reviews = []

    if api_key:
        params = {
            "engine": "google_maps_reviews",
            "api_key": api_key,
            "hl": "en",
            "sort_by": "newestFirst",
            "data_id": "0x80e914e9c7e7e80b:0x4810338ea9f4deba"
        }

        response = requests.get("https://serpapi.com/search.json", params=params)
        data = response.json()

        for index, review in enumerate(data.get("reviews", [])[:google_limit]):
            text = review.get("snippet") or review.get("description") or ""

            if not text:
                continue

            rating = review.get("rating") or 0

            google_reviews.append({
                "review_id": f"google_kpis_{index}",
                "business_id": "google_los_agaves",
                "business_name": "Los Agaves",
                "city": "Santa Barbara",
                "state": "CA",
                "categories": "Mexican restaurant",
                "review_stars": rating,
                "text": text,
                "clean_text": text,
                "date": review.get("date") or "",
                "sentiment_binary": "positive" if rating >= 4 else "negative",
                "review_length": len(text),
                "word_count": len(text.split()),
                "factor_dominante": "otros",
                "factor_score": 0,
                "source_platform": "Google Maps"
            })

    reviews = google_reviews + yelp_reviews
    total_reviews = len(reviews)

    if total_reviews == 0:
        return {
            "total_reviews": 0,
            "total_restaurants": 1,
            "avg_stars": 0,
            "positive_pct": 0,
            "cities": [],
            "sources": [],
            "source_breakdown": {}
        }

    avg_stars = round(
        sum(float(r.get("review_stars") or 0) for r in reviews) / total_reviews,
        2
    )

    positive_count = sum(
        1 for r in reviews if r.get("sentiment_binary") == "positive"
    )

    sources = sorted(list(set(
        r.get("source_platform", "Unknown") for r in reviews
    )))

    source_breakdown = {}

    for source in sources:
        source_reviews = [
            r for r in reviews
            if r.get("source_platform", "Unknown") == source
        ]

        source_breakdown[source] = {
            "total_reviews": len(source_reviews),
            "avg_stars": round(
                sum(float(r.get("review_stars") or 0) for r in source_reviews) / len(source_reviews),
                2
            ) if source_reviews else 0
        }

    cities = sorted(list(set(
        r.get("city") for r in reviews if r.get("city")
    )))

    return {
        "total_reviews": total_reviews,
        "total_restaurants": 1,
        "avg_stars": avg_stars,
        "positive_pct": round((positive_count / total_reviews) * 100, 1),
        "cities": cities,
        "sources": sources,
        "source_breakdown": source_breakdown
    }


@app.get("/intelligence/top-satisfaction-drivers-merged")
def get_top_satisfaction_drivers_merged():
    yelp_reviews = get_yelp_reviews_for_merge(
        business_id="yPSejq3_erxo9zdVYTBnZA",
        limit=100
    )

    google_reviews = get_google_reviews(
        data_id="0x80e914e9c7e7e80b:0x4810338ea9f4deba",
        limit=10
    )

    if not isinstance(google_reviews, list):
        google_reviews = []

    reviews = google_reviews + yelp_reviews

    positive_reviews = [
        r for r in reviews if r.get("sentiment_binary") == "positive"
    ]

    factor_counts = {}

    for review in positive_reviews:
        factor = review.get("factor_dominante", "otros")
        factor_counts[factor] = factor_counts.get(factor, 0) + 1

    result = sorted(
        [
            {"factor": factor, "positive_reviews": count}
            for factor, count in factor_counts.items()
        ],
        key=lambda x: x["positive_reviews"],
        reverse=True
    )

    return {"top_satisfaction_drivers": result[:5]}


@app.get("/intelligence/top-problem-drivers-merged")
def get_top_problem_drivers_merged():
    yelp_reviews = get_yelp_reviews_for_merge(
        business_id="yPSejq3_erxo9zdVYTBnZA",
        limit=100
    )

    google_reviews = get_google_reviews(
        data_id="0x80e914e9c7e7e80b:0x4810338ea9f4deba",
        limit=10
    )

    if not isinstance(google_reviews, list):
        google_reviews = []

    reviews = google_reviews + yelp_reviews

    negative_reviews = [
        r for r in reviews if r.get("sentiment_binary") == "negative"
    ]

    factor_counts = {}

    for review in negative_reviews:
        factor = review.get("factor_dominante", "otros")
        factor_counts[factor] = factor_counts.get(factor, 0) + 1

    result = sorted(
        [
            {"factor": factor, "negative_reviews": count}
            for factor, count in factor_counts.items()
        ],
        key=lambda x: x["negative_reviews"],
        reverse=True
    )

    return {"top_problem_drivers": result[:5]}


@app.get("/intelligence/topics-merged")
def get_intelligence_topics_merged():
    yelp_reviews = get_yelp_reviews_for_merge(
        business_id="yPSejq3_erxo9zdVYTBnZA",
        limit=100
    )

    google_reviews = get_google_reviews(
        data_id="0x80e914e9c7e7e80b:0x4810338ea9f4deba",
        limit=10
    )

    if not isinstance(google_reviews, list):
        google_reviews = []

    for r in yelp_reviews:
        r["source_platform"] = "Yelp"

    reviews = google_reviews + yelp_reviews

    factor_map = {}

    for review in reviews:
        factor = review.get("factor_dominante") or "otros"

        if factor not in factor_map:
            factor_map[factor] = {
                "id": factor,
                "label": factor,
                "mentions": 0,
                "positive_mentions": 0,
                "negative_mentions": 0
            }

        factor_map[factor]["mentions"] += 1

        if review.get("sentiment_binary") == "positive":
            factor_map[factor]["positive_mentions"] += 1
        elif review.get("sentiment_binary") == "negative":
            factor_map[factor]["negative_mentions"] += 1

    themes = []

    for item in factor_map.values():
        mentions = item["mentions"]
        positives = item["positive_mentions"]
        item["sentiment"] = round((positives * 100.0 / mentions), 1) if mentions else 0
        themes.append(item)

    themes = sorted(themes, key=lambda x: x["mentions"], reverse=True)

    deep_dive = {}

    for theme in themes:
        tid = theme["id"]
        theme_reviews = [
            r for r in reviews
            if (r.get("factor_dominante") or "otros") == tid
        ][:5]

        normalized_theme_reviews = []

        for r in theme_reviews:
            review = dict(r)
            review["sentiment"] = review.get("sentiment_binary", "unknown")
            review["sentiment_label"] = review.get("sentiment_binary", "unknown")
            normalized_theme_reviews.append(review)

        deep_dive[tid] = {
            "positive": [],
            "negative": [],
            "reviews": normalized_theme_reviews
        }

    return {
        "themes": themes,
        "deepDiveData": deep_dive
    }
