"""Idempotent, clearly identified demonstration fashion store for AVORA.
Does not create a user, transfer ownership, or enable checkout of fictional stock.
"""

PRODUCTS = (
    ('Burgundy Satin Cowl-Neck Dress', 'Elegant midi dress, soft satin finish, evening and occasion styling. Demo sizes XS–XL.', 49, 'Products', 18),
    ('Blush Street Sneakers', 'Comfortable blush and cream everyday sneakers. Demo sizes UK 3–9.', 39, 'Products', 24),
    ('Quilted Shoulder Bag', 'Compact quilted shoulder bag with a chain strap. Demo one-size style.', 32, 'Products', 16),
    ('Everyday Fashion Styling Bundle', 'Illustrative styling and curated outfit planning for everyday looks.', 20, 'Services', 12),
)


def ensure_velora(db):
    """Add sample fashion store to existing database without resetting anyone's data."""
    current = db.execute("SELECT id FROM providers WHERE owner_id IS NULL AND name=? ORDER BY id LIMIT 1", ('VELORA FASHION',)).fetchone()
    if current:
        pid = current['id']
    else:
        cur = db.execute("""INSERT INTO providers
            (owner_id,name,category,kind,city,country,remote,bio,skills,price,capacity,rating,reviews,verified,featured)
            VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            'VELORA FASHION','Fashion & Clothing','Products','Johannesburg','South Africa',1,
            'Affordable, trend-inspired clothing, shoes and accessories for everyday style. This is an illustrative demonstration shop, not a verified merchant.',
            'fashion,clothing,dresses,streetwear,sneakers,shoes,handbags,accessories,online shopping',
            20,100,0,0,0,1))
        pid = cur.lastrowid
    for title, description, price, kind, stock in PRODUCTS:
        existing = db.execute('SELECT id FROM listings WHERE provider_id=? AND title=?',(pid,title)).fetchone()
        if not existing:
            db.execute('INSERT INTO listings(provider_id,title,description,price,kind,stock) VALUES(?,?,?,?,?,?)',
                       (pid,title,description,price,kind,stock))
    return pid
