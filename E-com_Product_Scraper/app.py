"""Display and edit the local product catalog and export CSV files."""

import csv
import json
import secrets
import sqlite3
from hashlib import sha256
from io import StringIO

from flask import (
    Flask, Response, abort, flash, g, redirect, render_template, request,
    session, url_for,
)
from werkzeug.exceptions import HTTPException, SecurityError

from database import connect, initialize
from products import AVAILABILITY, amount_in_pounds, filter_sql, price_summary, validate_product

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost"]
app.config["MAX_CONTENT_LENGTH"] = 32_768
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
FILTER_FIELDS = ("name", "min_price", "max_price", "availability", "category", "min_rating")
PRODUCT_FIELDS = ("name", "price", "availability", "product_url", "category", "rating")
PRODUCT_COLUMNS = "name, price_pence, availability, product_url, category, rating"


def get_db():
    if "db" not in g:
        g.db = connect()
        if not app.config.get("SCHEMA_READY"):
            initialize(g.db)
            app.config["SCHEMA_READY"] = True
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


@app.errorhandler(HTTPException)
def show_http_error(error):
    response = error.get_response()
    if isinstance(error, SecurityError):
        return response  # An untrusted host has no safe URL adapter for templates.
    response.set_data(render_template(
        "error.html", heading=f"{error.code} · {error.name}", message=error.description,
    ))
    return response


@app.errorhandler(sqlite3.Error)
def show_database_error(error):
    app.logger.error("Database operation failed: %s", error)
    code = getattr(error, "sqlite_errorcode", 0) & 255
    busy = code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    message = "The database could not be read or saved. Check the Flask terminal for details."
    if busy:
        message = "The database is busy. Close other database editors, then try again."
    return render_template(
        "error.html", heading="Database unavailable", message=message,
    ), 503 if busy else 500


@app.context_processor
def template_values():
    if "form_token" not in session:
        session["form_token"] = secrets.token_urlsafe(24)
    return {"availability_options": AVAILABILITY, "rating_options": range(1, 6),
            "form_token": session["form_token"]}


@app.before_request
def check_form_token():
    if request.method == "POST":
        token = request.form.get("form_token", "").encode()
        expected = session.get("form_token", "").encode()
        if not expected or not secrets.compare_digest(token, expected):
            abort(400, "Refresh the form and try again.")


@app.template_filter("gbp")
def pounds(pence):
    return "—" if pence is None else f"£{amount_in_pounds(pence):,.2f}"


def read_fields(source, fields):
    return {field: source.get(field, "").strip() for field in fields}


def select_products(connection, where, values):
    return connection.execute(
        "SELECT * FROM products" + where + " ORDER BY name COLLATE NOCASE, id", values
    )


@app.get("/")
def catalog():
    connection = get_db()
    filters = read_fields(request.args, FILTER_FIELDS)
    rows = []
    summary = None
    error = None

    with connection:
        # Keep the listing and its statistics consistent while the scraper writes.
        connection.execute("BEGIN")
        latest = connection.execute("SELECT * FROM latest_scrape WHERE id = 1").fetchone()
        total = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        categories = connection.execute(
            "SELECT category FROM products WHERE category <> '' "
            "GROUP BY casefold(category) ORDER BY casefold(category)"
        ).fetchall()
        try:
            where, values = filter_sql(filters)
        except ValueError as exc:
            error = str(exc)
        else:
            rows = select_products(connection, where, values).fetchall()
            summary = price_summary(connection, where, values)

    return render_template(
        "catalog.html", products=rows, summary=summary, filters=filters,
        latest=latest, total=total, error=error, categories=categories,
    )


def spreadsheet_text(value):
    # Prevent spreadsheet apps from interpreting a product title as a formula.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


@app.get("/export.csv")
def export_csv():
    filters = read_fields(request.args, FILTER_FIELDS)
    try:
        where, values = filter_sql(filters)
    except ValueError as exc:
        abort(400, str(exc))

    rows = get_db().execute("SELECT * FROM products" + where + " ORDER BY id ASC", values)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Product ID", "Product name", "Category", "Price (GBP)", "Availability", "Rating (out of 5)", "Product URL"])
    for row in rows:
        writer.writerow([
            row["id"], spreadsheet_text(row["name"]), spreadsheet_text(row["category"]),
            f'{amount_in_pounds(row["price_pence"]):.2f}', row["availability"],
            row["rating"], row["product_url"],
        ])
    return Response(
        "\ufeff" + output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="products.csv"'},
    )


def find_product(product_id):
    product = get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        abort(404, "This product could not be found.")
    return product


def product_revision(product):
    return sha256(json.dumps(tuple(product)).encode("utf-8")).hexdigest()


def check_product_revision(product_id):
    current_product = find_product(product_id)
    if request.form.get("product_revision") != product_revision(current_product):
        abort(409, "This product changed while the form was open. Reopen it from the catalog.")


@app.route("/products/new", methods=["GET", "POST"])
@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def product_form(product_id=None):
    product = find_product(product_id) if product_id is not None else None
    heading = "Add product" if product is None else "Edit product"
    fields = dict.fromkeys(PRODUCT_FIELDS, "")
    fields["availability"] = AVAILABILITY[0]
    revision = None
    if product is not None:
        fields.update(
            name=product["name"], price=str(amount_in_pounds(product["price_pence"])),
            availability=product["availability"], product_url=product["product_url"],
            category=product["category"], rating=str(product["rating"] or ""),
        )
        revision = product_revision(product)
    error = None
    if request.method == "POST":
        fields = read_fields(request.form, PRODUCT_FIELDS)
        revision = request.form.get("product_revision") if product is not None else None
        try:
            values = validate_product(
                fields["name"], fields["price"], fields["availability"], fields["product_url"],
                fields["category"], fields["rating"],
            )
            connection = get_db()
            with connection:
                if product is None:
                    connection.execute(
                        f"INSERT INTO products ({PRODUCT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)", values
                    )
                else:
                    connection.execute("BEGIN IMMEDIATE")
                    check_product_revision(product_id)
                    connection.execute(
                        "UPDATE products SET name = ?, price_pence = ?, availability = ?, "
                        "product_url = ?, category = ?, rating = ? WHERE id = ?", (*values, product_id),
                    )
        except ValueError as exc:
            error = str(exc)
        except sqlite3.IntegrityError:
            error = "A product with that URL is already saved."
        else:
            flash("Product added." if product is None else "Product updated.")
            return redirect(url_for("catalog"))
    return render_template(
        "product_form.html", heading=heading, fields=fields, error=error, revision=revision,
    )


@app.route("/products/<int:product_id>/delete", methods=["GET", "POST"])
def delete_product(product_id):
    product = find_product(product_id)
    if request.method == "POST":
        connection = get_db()
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            check_product_revision(product_id)
            connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
        flash("Product deleted.")
        return redirect(url_for("catalog"))
    return render_template("delete_product.html", product=product, revision=product_revision(product))


if __name__ == "__main__":
    with app.app_context():
        get_db()
    app.run(host="127.0.0.1", port=5000)
