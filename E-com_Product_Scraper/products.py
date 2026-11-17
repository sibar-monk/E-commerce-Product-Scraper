"""Validate product fields and share the SQL used by the dashboard and CSV."""

import re
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit, urlunsplit

AVAILABILITY = ("In stock", "Out of stock")


def price_to_pence(value):
    if not re.fullmatch(r"(?:[0-9]{1,8}(?:\.[0-9]{1,2})?|\.[0-9]{1,2})", value):
        raise ValueError("Enter a price like 12.50, with up to two decimal places.")
    pounds, _, pence = value.partition(".")
    return int(pounds or "0") * 100 + int(pence.ljust(2, "0"))


def amount_in_pounds(pence):
    return (Decimal(str(pence)) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_url(value):
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise ValueError("Enter a valid HTTP or HTTPS product URL.")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
        raise ValueError("Enter a valid HTTP or HTTPS product URL.")
    # Keep the query because it may contain an actual product ID.
    port = parts.port
    default_port = 443 if parts.scheme == "https" else 80
    host = parts.netloc.lower()
    if port == default_port:
        host = host.rsplit(":", 1)[0]
    return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))


def validate_attributes(category="", rating=""):
    category = " ".join(category.split())
    if len(category) > 100:
        raise ValueError("Keep the category within 100 characters.")
    if rating in ("", None):
        rating = None
    elif str(rating) in ("1", "2", "3", "4", "5"):
        rating = int(rating)
    else:
        raise ValueError("Choose a rating from 1 to 5, or leave it unrecorded.")
    return category, rating


def validate_product(name, price, availability, url, category="", rating=""):
    name = name.strip()
    if not name:
        raise ValueError("Enter a product name.")
    if availability not in AVAILABILITY:
        raise ValueError("Choose a valid availability status.")
    category, rating = validate_attributes(category, rating)
    return name, price_to_pence(price.strip()), availability, normalize_url(url.strip()), category, rating


def filter_sql(filters):
    conditions = []
    values = []
    if filters["name"]:
        conditions.append("instr(casefold(name), ?) > 0")
        values.append(filters["name"].casefold())
    minimum = price_to_pence(filters["min_price"]) if filters["min_price"] else None
    maximum = price_to_pence(filters["max_price"]) if filters["max_price"] else None
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Minimum price must be at or below maximum price.")
    if minimum is not None:
        conditions.append("price_pence >= ?")
        values.append(minimum)
    if maximum is not None:
        conditions.append("price_pence <= ?")
        values.append(maximum)
    if filters["availability"]:
        if filters["availability"] not in AVAILABILITY:
            raise ValueError("Choose a valid availability filter.")
        conditions.append("availability = ?")
        values.append(filters["availability"])
    if filters.get("category"):
        conditions.append("casefold(category) = ?")
        values.append(filters["category"].casefold())
    if filters.get("min_rating"):
        _, rating = validate_attributes(rating=filters["min_rating"])
        conditions.append("rating >= ?")
        values.append(rating)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    # SQL fragments above are fixed strings. Form values are bound separately.
    return where, values


def price_summary(connection, where="", values=()):
    # Use the same SQL calculation in the terminal and the Flask catalog.
    return connection.execute(
        "SELECT COUNT(*) AS count, MIN(price_pence) AS cheapest, "
        "MAX(price_pence) AS most_expensive, AVG(price_pence) AS average "
        "FROM products" + where, values,
    ).fetchone()
