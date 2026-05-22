import sqlite3
import pandas as pd

# =========================
# CONEXIÓN DB
# =========================

conn = sqlite3.connect("db/yelp_reviews.db")

# =========================
# VER TABLAS
# =========================

tables = pd.read_sql("""
SELECT name
FROM sqlite_master
WHERE type='table'
""", conn)

print("\n===== TABLAS =====")
print(tables)

# =========================
# VER ESTRUCTURA
# =========================

for table in tables["name"]:

    print("\n========================")
    print(f"TABLA: {table}")
    print("========================")

    schema = pd.read_sql(
        f"PRAGMA table_info({table})",
        conn
    )

    print(schema)

# =========================
# CERRAR CONEXIÓN
# =========================

conn.close()