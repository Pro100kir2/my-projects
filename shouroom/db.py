import psycopg2
from config import DB_CONFIG

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_or_create_category(name):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM categories WHERE name=%s", (name,))
    row = cur.fetchone()

    if row:
        cat_id = row[0]
    else:
        cur.execute(
            "INSERT INTO categories (name) VALUES (%s) RETURNING id",
            (name,)
        )
        cat_id = cur.fetchone()[0]
        conn.commit()

    cur.close()
    conn.close()
    return cat_id

def save_product(title, category, url, price, description, image):
    conn = get_conn()
    cur = conn.cursor()

    cat_id = get_or_create_category(category)

    cur.execute("""
        INSERT INTO products
        (title, category_id, avito_url, price, description, image_url)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (avito_url) DO NOTHING
    """, (title, cat_id, url, price, description, image))

    conn.commit()
    cur.close()
    conn.close()

