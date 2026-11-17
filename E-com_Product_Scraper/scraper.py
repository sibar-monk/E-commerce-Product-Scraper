"""Save catalog pages and resume interrupted runs from SQLite."""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import sleep
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from checkpoint import (
    CheckpointError, ScrapeProgress, begin_checkpoint_write, clear_checkpoint, read_checkpoint,
    save_checkpoint,
)
from database import connect, initialize
from products import amount_in_pounds, normalize_url, price_summary, validate_attributes, validate_product

DEFAULT_URL = "https://books.toscrape.com/"
TARGET = 30
CARD = "article.product_pod"
TITLE_LINK = "h3 a"
PRICE = ".price_color"
STOCK = ".availability"
NEXT_LINK = "li.next a"
RATING = ".star-rating"
CATEGORY = "ul.breadcrumb li:nth-child(3) a"
RATING_VALUES = {"One": "1", "Two": "2", "Three": "3", "Four": "4", "Five": "5"}
INSERT_PRODUCT = """
    INSERT INTO products (name, price_pence, availability, product_url, category, rating)
    VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(product_url) DO NOTHING
"""


def fetch_page(url):
    response = requests.get(url, timeout=15, allow_redirects=False)
    retry_after = response.headers.get("Retry-After")
    if response.status_code in (429, 503) and retry_after:
        raise ValueError(f"HTTP {response.status_code}. Wait as directed by Retry-After {retry_after!r}.")
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}. Use the final permitted page URL.")
    if response.encoding in (None, "ISO-8859-1"):
        response.encoding = "utf-8"
    return response.text


def parse_page(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    books = soup.select(CARD)
    if not books:
        raise ValueError("No product cards matched the expected HTML layout.")
    products = []
    invalid = 0
    for book in books:
        link = book.select_one(TITLE_LINK)
        price = book.select_one(PRICE)
        stock = book.select_one(STOCK)
        href = link.get("href", "").strip() if link else ""
        if not href or price is None or stock is None:
            invalid += 1
            continue
        try:
            stars = book.select_one(RATING)
            classes = stars.get("class", []) if stars else []
            rating = next((number for word, number in RATING_VALUES.items() if word in classes), "")
            products.append(validate_product(
                link.get("title", "").strip() or link.get_text(" ", strip=True),
                price.get_text(strip=True).removeprefix("£").strip(),
                " ".join(stock.get_text(" ", strip=True).split()),
                urljoin(base_url, href),
                book.get("data-category", ""), rating,
            ))
        except ValueError:
            invalid += 1
    if not products:
        raise ValueError(f"No valid products could be read from this page ({invalid} invalid cards).")
    next_link = soup.select_one(NEXT_LINK)
    next_href = next_link.get("href", "").strip() if next_link else None
    if next_link is not None and not next_href:
        raise ValueError("The Next link is present but has no usable address.")
    return products, invalid, next_href


def complete_categories(connection, rows, start_url, delay):
    """Read missing categories from same-site detail pages before saving this page."""
    categories = {}
    completed = []
    for row in rows:
        product_url = row[3]
        category = row[4]
        if not category:
            existing = connection.execute(
                "SELECT category FROM products WHERE product_url = ?", (product_url,),
            ).fetchone()
            category = categories.get(product_url) or (existing["category"] if existing else "")
        if not category:
            if urlsplit(product_url)[:2] != urlsplit(start_url)[:2]:
                raise ValueError("A product detail link points outside the starting site.")
            sleep(delay)
            try:
                soup = BeautifulSoup(fetch_page(product_url), "html.parser")
                link = soup.select_one(CATEGORY)
                category = link.get_text(" ", strip=True) if link else ""
                if not category:
                    raise ValueError("No category matched the expected detail-page layout.")
                category, _ = validate_attributes(category)
            except (requests.RequestException, ValueError) as error:
                raise ValueError(f"Category request failed for {product_url}: {error}") from error
        categories[product_url] = category
        completed.append((*row[:4], category, row[5]))
    return completed


def next_page(progress, start_url, next_link, html_files, max_pages, stop_at_target):
    if html_files:
        if progress.pages == max_pages:
            return None, "Source pages ended."
        if not next_link:
            return progress.url, ""

    if not html_files and stop_at_target and len(progress.seen_products) >= TARGET:
        return None, "Collection target reached."
    if not next_link:
        return None, "Source pages ended."
    if progress.pages == max_pages:
        return None, f"Page limit reached ({max_pages})."
    try:
        next_url = normalize_url(urljoin(progress.url, next_link))
    except ValueError as error:
        raise ValueError("The Next link is invalid.") from error
    if not html_files and urlsplit(next_url)[:2] != urlsplit(start_url)[:2]:
        raise ValueError("The Next link points outside the starting site.")
    if not html_files and next_url in progress.visited_pages:
        raise ValueError("The Next link points to a page already read.")
    return next_url, ""


def save_summary(connection, source, progress, message, *, report_shortfall=True):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    found = len(progress.seen_products)
    if report_shortfall and found < TARGET:
        message += f" Found {found} of the {TARGET} required distinct books this run."

    connection.execute(
        "REPLACE INTO latest_scrape "
        "(id, finished_at, source, pages_read, added, duplicates, invalid, unique_found, message) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (timestamp, source, progress.pages, progress.added, progress.duplicates,
         progress.invalid, found, message),
    )
    return timestamp, message


def print_summary(connection, source, progress, summary):
    timestamp, message = summary
    prices = price_summary(connection)
    print(f"Latest scrape | {timestamp}")
    print(f"Source: {source}")
    print(f"Pages read: {progress.pages} | New books saved: {progress.added} | "
          f"Duplicates skipped: {progress.duplicates}")
    print(f"Invalid cards skipped: {progress.invalid} | "
          f"Distinct valid books this run: {len(progress.seen_products)}")
    print(f"Current database total: {prices['count']}")
    print(message)
    if prices["count"]:
        print("Prices in the whole database (GBP): "
              f"cheapest {amount_in_pounds(prices['cheapest'])} | "
              f"most expensive {amount_in_pounds(prices['most_expensive'])} | "
              f"average {amount_in_pounds(prices['average'])}")


def restore_progress(snapshot, start_url, max_pages, local_files):
    progress = ScrapeProgress.decode(snapshot)
    try:
        progress.url = normalize_url(progress.url)
        if not 0 < progress.pages < max_pages:
            raise ValueError("Invalid saved page number.")
        if not local_files and urlsplit(progress.url)[:2] != urlsplit(start_url)[:2]:
            raise ValueError("Saved page is outside the starting site.")
    except (TypeError, ValueError) as error:
        raise CheckpointError("Saved page is invalid. Use --fresh with the same options.") from error
    return progress


def run_scrape(connection, start_url, html_files, max_pages, *, stop_at_target=True,
               fresh=False, delay=2, fetch_categories=False):
    source = "Local HTML files" if html_files else start_url
    file_paths = [str(path.resolve()) for path in html_files or []]
    run_key = json.dumps([start_url, file_paths, max_pages, stop_at_target])
    if fresh:
        with connection:
            clear_checkpoint(connection, run_key)
    snapshot = read_checkpoint(connection, run_key)
    progress = ScrapeProgress(start_url)
    if snapshot is not None:
        progress = restore_progress(snapshot, start_url, max_pages, html_files)
        print(f"Resuming at page {progress.pages + 1} after {progress.pages} saved page(s).")

    while True:
        index = progress.pages
        page_label = file_paths[index] if html_files else progress.url
        try:
            print(f"Reading catalog page {index + 1}...", flush=True)
            if html_files:
                html = Path(page_label).read_text(encoding="utf-8-sig")
            else:
                if index:
                    sleep(delay)
                html = fetch_page(progress.url)
            rows, skipped, next_link = parse_page(html, progress.url)
            if fetch_categories and not html_files:
                print("Checking categories on product detail pages...", flush=True)
                rows = complete_categories(connection, rows, start_url, delay)
        except (requests.RequestException, OSError, ValueError, KeyboardInterrupt) as error:
            reason = "Interrupted by user." if isinstance(error, KeyboardInterrupt) else str(error)
            message = f"Stopped at page {index + 1} ({page_label}). {reason}"
            if snapshot:
                message += f" Run the same command to resume from page {index + 1}."
            with connection:
                begin_checkpoint_write(connection, run_key, snapshot)
                summary = save_summary(connection, source, progress, message)
            print_summary(connection, source, progress, summary)
            return 130 if isinstance(error, KeyboardInterrupt) else 1

        with connection:
            begin_checkpoint_write(connection, run_key, snapshot)
            inserted = 0
            for row in rows:
                saved = connection.execute(INSERT_PRODUCT, row).rowcount
                inserted += saved
                if not saved:
                    # Fill missing attributes on older rows, preserving existing edits.
                    connection.execute(
                        "UPDATE products SET category = CASE WHEN category = '' THEN ? ELSE category END, "
                        "rating = COALESCE(rating, ?) WHERE product_url = ?",
                        (row[4], row[5], row[3]),
                    )
            progress.visited_pages.add(progress.url)
            progress.pages += 1
            progress.added += inserted
            progress.duplicates += len(rows) - inserted
            progress.invalid += skipped
            progress.seen_products.update(row[3] for row in rows)
            navigation_failed = False
            try:
                next_url, message = next_page(
                    progress, start_url, next_link, html_files, max_pages, stop_at_target,
                )
            except ValueError as error:
                navigation_failed = True
                next_url, message = None, f"Stopped after page {progress.pages}. {error}"
            if next_url:
                progress.url = next_url
                snapshot = progress.encode()
                save_checkpoint(connection, run_key, snapshot)
                message = f"Page {progress.pages} saved. Next unfinished page is {progress.pages + 1}."
                save_summary(connection, source, progress, message, report_shortfall=False)
            else:
                clear_checkpoint(connection, run_key)
                summary = save_summary(connection, source, progress, message)

        if not next_url:
            print_summary(connection, source, progress, summary)
            return 1 if navigation_failed or len(progress.seen_products) < TARGET else 0


def main():
    parser = argparse.ArgumentParser(description="Import books into the local SQLite catalog.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Permitted start URL or base URL for HTML")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--html", nargs="+", type=Path, help="Local UTF-8 HTML files in page order")
    mode.add_argument("--pages", type=int, help="Read up to this many web pages, even past 30 books")
    mode.add_argument("--max-pages", type=int, default=5, help="Page cap when targeting 30 books")
    parser.add_argument("--delay", type=float, default=2, help="Seconds between web requests (at least 2)")
    parser.add_argument("--no-details", action="store_true", help="Skip category detail requests; still read listing ratings")
    parser.add_argument("--fresh", action="store_true", help="Start over with these options and keep existing books")
    args = parser.parse_args()
    page_limit = args.pages if args.pages is not None else args.max_pages
    if page_limit < 1:
        parser.error("--pages and --max-pages must be at least 1.")
    if not isfinite(args.delay) or args.delay < 2:
        parser.error("--delay must be a finite number of at least 2 seconds.")
    try:
        start_url = normalize_url(args.url.strip())
    except ValueError as error:
        parser.error(str(error))
    try:
        with closing(connect()) as connection:
            initialize(connection)
            return run_scrape(
                connection, start_url, args.html, len(args.html) if args.html else page_limit,
                stop_at_target=args.pages is None, fresh=args.fresh, delay=args.delay,
                fetch_categories=not args.no_details and urlsplit(start_url).hostname == "books.toscrape.com",
            )
    except CheckpointError as error:
        print(f"Checkpoint error: {error}", file=sys.stderr)
        return 1
    except sqlite3.Error as error:
        print(f"SQLite error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Scrape interrupted. Run the same command to use saved progress.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
