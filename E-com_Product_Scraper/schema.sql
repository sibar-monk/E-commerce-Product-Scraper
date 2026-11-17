CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    price_pence INTEGER NOT NULL CHECK (typeof(price_pence) = 'integer' AND price_pence >= 0),
    availability TEXT NOT NULL CHECK (availability IN ('In stock', 'Out of stock')),
    product_url TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT '' CHECK (length(category) <= 100),
    rating INTEGER CHECK (rating IS NULL OR (typeof(rating) = 'integer' AND rating BETWEEN 1 AND 5))
);

CREATE TABLE IF NOT EXISTS latest_scrape (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    finished_at TEXT NOT NULL,
    source TEXT NOT NULL,
    pages_read INTEGER NOT NULL,
    added INTEGER NOT NULL,
    duplicates INTEGER NOT NULL,
    invalid INTEGER NOT NULL,
    unique_found INTEGER NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_checkpoints (
    run_key TEXT PRIMARY KEY,
    progress TEXT NOT NULL
);
