import pandas as pd
import sqlite3
import json
import os

# Rutas
DATA_PATH = "data/TFM-datos"
DB_PATH = "db/yelp_reviews.db"

os.makedirs("db", exist_ok=True)

print("Leyendo parquets...")
df = pd.read_parquet(f"{DATA_PATH}/yelp_mexican_with_factors.parquet")
tf = pd.read_parquet(f"{DATA_PATH}/taxonomy_factors.parquet")
tk = pd.read_parquet(f"{DATA_PATH}/taxonomy_keywords.parquet")

conn = sqlite3.connect(DB_PATH)

# ── TABLA 1: reviews ──────────────────────────────────────────
print("Creando tabla reviews...")
reviews = df[[
    'review_id', 'business_id', 'name', 'city', 'state',
    'categories', 'review_stars', 'text', 'clean_text',
    'date', 'sentiment_binary', 'review_length', 'word_count'
]].copy()
reviews.rename(columns={'name': 'business_name'}, inplace=True)
reviews.to_sql('reviews', conn, if_exists='replace', index=False)
print(f"  → {len(reviews)} filas")

# ── TABLA 2: sentiment_analysis ───────────────────────────────
print("Creando tabla sentiment_analysis...")
sentiment = df[[
    'review_id', 'sentiment', 'sentiment_binary', 'review_stars'
]].copy()
sentiment.rename(columns={
    'sentiment': 'vader_compound',
    'sentiment_binary': 'predicted_sentiment'
}, inplace=True)
sentiment.to_sql('sentiment_analysis', conn, if_exists='replace', index=False)
print(f"  → {len(sentiment)} filas")

# ── TABLA 3: review_factors ───────────────────────────────────
print("Creando tabla review_factors...")
factors = df[[
    'review_id', 'factor_dominante', 'factor_score',
    'factor_matches', 'n_factor_matches'
]].copy()
factors.to_sql('review_factors', conn, if_exists='replace', index=False)
print(f"  → {len(factors)} filas")

# ── TABLA 4: themes_master ────────────────────────────────────
print("Creando tabla themes_master...")
themes = tf.copy()
themes['positive_keywords'] = themes['keywords_positivos'].apply(
    lambda x: json.dumps(list(x)) if hasattr(x, '__iter__') and not isinstance(x, str) else json.dumps([str(x)])
)
themes['negative_keywords'] = themes['keywords_negativos'].apply(
    lambda x: json.dumps(list(x)) if hasattr(x, '__iter__') and not isinstance(x, str) else json.dumps([str(x)])
)

themes = themes[['factor', 'emoji', 'descripcion', 'positive_keywords', 'negative_keywords']]
themes.rename(columns={'factor': 'theme_name', 'descripcion': 'description'}, inplace=True)
themes.to_sql('themes_master', conn, if_exists='replace', index=False)
print(f"  → {len(themes)} filas")

# ── TABLA 5: taxonomy_keywords ────────────────────────────────
print("Creando tabla taxonomy_keywords...")
tk.to_sql('taxonomy_keywords', conn, if_exists='replace', index=False)
print(f"  → {len(tk)} filas")
# ── TABLA 6: business_metrics ─────────────────────────────────
print("Creando tabla business_metrics...")
business_metrics = conn.execute("""
    SELECT 
        r.business_id,
        r.business_name,
        r.city,
        r.state,
        COUNT(*) as total_reviews,
        ROUND(AVG(r.review_stars), 2) as avg_stars,
        ROUND(AVG(s.vader_compound), 3) as avg_sentiment_score,
        SUM(CASE WHEN r.review_stars >= 4 THEN 1 ELSE 0 END) as promoters,
        SUM(CASE WHEN r.review_stars <= 2 THEN 1 ELSE 0 END) as detractors,
        ROUND(
            (SUM(CASE WHEN r.review_stars >= 4 THEN 1.0 ELSE 0 END) / COUNT(*) * 100) -
            (SUM(CASE WHEN r.review_stars <= 2 THEN 1.0 ELSE 0 END) / COUNT(*) * 100)
        , 1) as nps_score,
        ROUND(AVG(r.review_stars), 2) as csat_score,
        SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) as positive_count,
        SUM(CASE WHEN r.sentiment_binary='negative' THEN 1 ELSE 0 END) as negative_count,
        ROUND(SUM(CASE WHEN r.sentiment_binary='positive' THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as positive_percentage
    FROM reviews r
    LEFT JOIN sentiment_analysis s ON r.review_id = s.review_id
    GROUP BY r.business_id
    ORDER BY total_reviews DESC
""").fetchall()

pd.DataFrame(business_metrics, columns=[
    'business_id', 'business_name', 'city', 'state',
    'total_reviews', 'avg_stars', 'avg_sentiment_score',
    'promoters', 'detractors', 'nps_score', 'csat_score',
    'positive_count', 'negative_count', 'positive_percentage'
]).to_sql('business_metrics', conn, if_exists='replace', index=False)
print(f"  → {len(business_metrics)} restaurantes")

# ── TABLA 7: theme_metrics ────────────────────────────────────
print("Creando tabla theme_metrics...")
theme_metrics = conn.execute("""
    SELECT
        r.business_id,
        rf.factor_dominante as theme_id,
        COUNT(*) as total_mentions,
        SUM(CASE WHEN r.sentiment_binary='positive' THEN 1 ELSE 0 END) as positive_mentions,
        SUM(CASE WHEN r.sentiment_binary='negative' THEN 1 ELSE 0 END) as negative_mentions,
        ROUND(SUM(CASE WHEN r.sentiment_binary='positive' THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as positive_percentage,
        ROUND(AVG(s.vader_compound), 3) as avg_sentiment_score
    FROM review_factors rf
    JOIN reviews r ON rf.review_id = r.review_id
    LEFT JOIN sentiment_analysis s ON r.review_id = s.review_id
    WHERE rf.factor_dominante IS NOT NULL
    GROUP BY r.business_id, rf.factor_dominante
    ORDER BY total_mentions DESC
""").fetchall()

pd.DataFrame(theme_metrics, columns=[
    'business_id', 'theme_id', 'total_mentions',
    'positive_mentions', 'negative_mentions',
    'positive_percentage', 'avg_sentiment_score'
]).to_sql('theme_metrics', conn, if_exists='replace', index=False)
print(f"  → {len(theme_metrics)} filas")

conn.close()
print("\n✅ Base de datos creada en db/yelp_reviews.db")