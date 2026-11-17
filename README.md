# Product Research Web-Scraping Tool

Project Name: **E-commerce Product Scraper & SQL Database**.

Collect book information from the permitted [Books to Scrape practice website](https://books.toscrape.com/), save it in SQLite, and use Flask to search, edit and export it. The source contains demonstration prices and ratings, not real market evidence.

This package contains only the application and submission files. The Word guides, automated tests and GitHub test workflow remain in the earlier full package. All application features are retained.

## 1. Install and run

Extract the ZIP and open the **Product-Research-Tool** folder in VS Code. Open **Terminal → New Terminal**. Run these commands from the folder containing `app.py` and `requirements.txt`. Use Python 3.12 for the tested setup.

**Windows PowerShell**

```powershell
py -3.12 -m venv project_venv
.\project_venv\Scripts\python.exe -m pip install -r requirements.txt
.\project_venv\Scripts\python.exe scraper.py
.\project_venv\Scripts\python.exe app.py
```

**Linux or macOS**

```sh
python3.12 -m venv project_venv
./project_venv/bin/python -m pip install -r requirements.txt
./project_venv/bin/python scraper.py
./project_venv/bin/python app.py
```

These commands use the virtual environment directly; activation is unnecessary. You can also select its interpreter in VS Code. In the examples below, `python` means this virtual environment's interpreter.

Open **http://127.0.0.1:5000/** while Flask is running. Press **Ctrl+C** in that terminal to stop Flask. To scrape again while Flask runs, use a second terminal, then refresh the browser.

`requirements.txt` retains the previous version pins. The main dependencies are requests, Beautiful Soup and Flask; their dependencies are also pinned. SQLite, CSV and pathlib are included in Python. No password or `.env` file is needed.

## 2. What the tool does

- Follows catalog Next links and collects the full title, GBP price, stock status and product URL.
- Reads listing star ratings and, for Books to Scrape, categories from product detail pages.
- Saves records locally in `products.db`, which is created automatically.
- Provides Add, View, Edit and Delete operations through Flask.
- Searches titles and filters by minimum/maximum price, stock, category and minimum rating.
- Calculates count, minimum, maximum and average prices using SQL. Flask also shows the products at the price extremes.
- Exports either the full catalog or the filtered results to CSV, sorted by Product ID (lowest first). Clear headings group the name, category, price, stock and rating together, with the long URL last.
- Keeps completed catalog pages and their checkpoints when a later page fails.
- Prevents duplicate product URLs across runs.

The terminal and Flask show the latest scrape counts. Terminal price statistics cover the entire database; Flask statistics follow the active filters. Select **Clear** to compare the whole catalog in both places.

## 3. Try the main features

1. Run `python scraper.py`. A fresh successful default run normally reads two catalog pages and saves 40 books, meeting the requirement for at least 30.
2. Start Flask and check the database total, Latest scrape panel, source links and price statistics.
3. Run the same scrape again. With unchanged data, expect zero new rows, 40 duplicates and the same database total.
4. Search for `light`, set price bounds to `10` and `60`, and choose **In stock**. Also try **Category: Poetry** and **Minimum rating: 3 / 5 or higher**. Select **Apply**.
5. Download **Export filtered CSV** and **Export all CSV**. The filtered export uses the same conditions as the displayed results.
6. Select **Clear**, then **Add product**. Try `Mentor Demo Book`, price `0.01`, `Out of stock`, URL `https://example.com/mentor-demo-book`, category `Poetry` and rating `4`. Find it, edit its price and rating, then delete it using the confirmation page.

CSV prices are written with two decimal places and the heading states GBP. Ratings stay numeric under **Rating (out of 5)**. CSV is plain data: it cannot save column widths, fonts or colours. In Excel or LibreOffice, widen the name column, wrap long text and format the price column to two decimal places for comfortable viewing. Save as an Excel workbook if you want to keep that display formatting. The 5 / 5 filter has no “or higher” suffix.

Category matching ignores case and matches the whole category. Minimum rating means at least the selected number of stars. Missing attributes display **not recorded** and are blank in CSV. Unknown ratings do not match a minimum-rating filter. Add/Edit can supply missing attributes.

![Catalog and SQL statistics](screenshots/01-catalog-first-run.png)

![Search, attribute filters and CSV export](screenshots/02-search-and-filter.png)

These screenshots use saved practice-site catalog pages and 14 retrieved detail pages; some demonstration categories remain unrecorded.

## 4. Choose the source and page count

| Command | Purpose |
|---|---|
| `python scraper.py` | Stop after a complete catalog page brings the run to at least 30 distinct books, with a five-page cap. |
| `python scraper.py --pages 5` | Read up to five catalog pages even after reaching 30 books. Stop earlier if the catalog ends or a page fails. |
| `python scraper.py --max-pages 10` | Keep the 30-book target but allow up to ten catalog pages to reach it. |
| `python scraper.py --pages 5 --delay 5` | Wait five seconds between web requests. The default and minimum are two seconds. |
| `python scraper.py --no-details` | Skip category detail requests; still collect the required fields and available listing ratings. |
| `python scraper.py --fresh` | Start this scrape from page 1 while keeping existing database records. |

Use either `--pages` or `--max-pages`, not both. A run below 30 distinct books reports the shortfall and exits with status 1. A failed run also reports failure even if earlier pages already supplied 30 books.

The first 40-book import normally makes 42 requests: two catalog pages and 40 category detail pages. Allow a few minutes. Progress messages appear in the terminal. Known categories are reused, so a repeat run normally needs only the two catalog requests. `--no-details` leaves new categories unrecorded; a later normal scrape fills missing categories.

For another permitted site with compatible HTML and GBP prices, use `python scraper.py --url "https://permitted.example/catalog/"` with its real permitted URL. Different layouts require adapting the named selectors and extraction in `scraper.py`. This is not a universal scraper: arbitrary layouts, JavaScript-only catalogs and other currencies are not automatically supported. The category detail parser runs only for the Books to Scrape host.

Import instructor-provided UTF-8 HTML in page order:

```sh
python scraper.py --url "https://books.toscrape.com/" --html page1.html page2.html
```

Use the original first-page URL so relative product links resolve correctly. Compatible Next links should identify subsequent original page URLs when their paths differ. Local imports never make web requests. Normal saved listings contain ratings but usually omit categories. Instructor-authored cards may supply `data-category="Poetry"` and an element such as `<p class="star-rating Four"></p>`; these attributes are optional.

Scrape only permitted sources and respect their stated limits. A delay alone does not grant permission. The scraper stops on restrictions, HTTP errors and redirects; it does not bypass them. Follow any reported `Retry-After` instruction before retrying.

## 5. Failures, checkpoints and duplicates

Each successful catalog page, its products, checkpoint and summary are committed in one SQLite transaction. A timeout, file error, changed layout or failed category request leaves the current page unfinished and preserves earlier committed pages. Details from the unfinished page may need fetching again. If the first page fails, the next attempt starts from page 1.

Correct the cause, then rerun the **same command** to resume. Keep the same starting URL, page settings and local file paths/order. You can change `--delay` or add `--no-details` without changing checkpoint identity. Use `--fresh` for a new pass or unreadable progress. Checkpoints track position; they cannot repair HTML or bypass access restrictions.

Individual malformed cards are skipped and counted. A page with no valid products or an existing Next link with an empty address fails before saving that page. Invalid, repeated or off-site navigation stops the run while keeping the current page's valid records. If Next disappears entirely, the scraper cannot distinguish a real last page from some layout changes; check unexpected shortfalls.

Duplicate URLs skip the INSERT. A repeat scrape fills only a blank category or NULL rating and preserves names, prices, stock and already recorded attributes. **Duplicates skipped** counts skipped inserts even when a missing attribute is filled. Deleting a row or changing its URL permits the original URL to be imported again.

To demonstrate recovery, use a fresh project copy and save the first two catalog pages separately. Initially leave `missing-page.html` absent:

```sh
python scraper.py --html page1.html missing-page.html
```

Expect 20 saved books and a page 2 file error. Copy the saved second page to `missing-page.html` and run the exact command again. It should resume at page 2 and reach 40 books if each file contains 20 valid products.

## 6. Files and database design

| File or folder | Purpose |
|---|---|
| `scraper.py` | Requests pages, extracts fields, saves data and prints the scrape summary. |
| `checkpoint.py` | Stores and restores scrape progress. |
| `database.py` | Opens SQLite and initializes or upgrades its tables. |
| `schema.sql` | Defines the products, latest summary and checkpoint tables. |
| `products.py` | Shares validation, parameterized SQL filters and price statistics. |
| `app.py` | Runs Flask, CRUD operations and CSV downloads. |
| `templates/` | Five separate HTML files for the shared layout, catalog, Add/Edit, Delete and error pages. |
| `static/style.css` | Styles the pages for desktop and narrow screens. |
| `requirements.txt` | Pins the Python dependencies. |
| `.gitignore` | Excludes generated data and virtual environments during normal Git use. |
| `screenshots/` | Two screenshots for the required submission evidence. |
| `README.md` | Installation, use, verification and submission instructions. |

Each product has an integer primary key and a unique URL. Prices are stored as integer pence; SQL calculates `MIN`, `MAX` and `AVG`, with the average rounded for display. Category is text of up to 100 characters. Rating is an integer from 1 to 5 or NULL when unknown. SQL CHECK constraints validate stored values, and user input is passed as bound SQL parameters.

The database initialization files are supplied instead of a prefilled database. Run `python database.py` to initialize explicitly; starting the scraper or app also initializes it. The database stays beside the Python files regardless of the terminal's working directory.

## 7. Updating and troubleshooting

Stop Flask and the scraper, then back up your existing project and `products.db`. If moving to this extracted folder, copy the backed-up database beside `app.py`. Keep your virtual environment or create one using section 1. Dependency pins are unchanged. Run `python database.py` to add missing category/rating columns without deleting records or checkpoints, then `python scraper.py --fresh` to fill missing attributes. Reopen old forms after restarting Flask.

| Problem | Action |
|---|---|
| Missing module | Use the virtual environment interpreter and install `requirements.txt`. |
| Port 5000 already in use | Stop the other Flask process or run `python -m flask --app app run --port 5001`. |
| Form asks to refresh, or HTTP 409 | Reopen the form; its token expired or the record changed after you opened it. |
| Database busy | Close database editors or wait for another write to finish, then retry. |
| Request or layout failure | Read the reported URL and reason, fix the source issue and rerun. `--no-details` can finish the core import when only category pages fail. |
| Unreadable checkpoint | Add `--fresh` to the same command; saved products remain. |

The application passed 38 automated checks on Python 3.12/Linux, plus browser checks for editing, filters, CSV and narrow-screen layouts. The test files are intentionally excluded from this smaller ZIP. Native Windows and macOS were not executed. The live category test retrieved 14 detail pages before a timeout, so a complete live category import was not verified in that review; saved HTML and controlled responses covered the remaining behavior.

## 8. Screenshots

01_fresh_run_scraper-py.png | Showing a fresh successful default scraper.py run output.
02_fresh_run_flask_app-py.png | After scraper.py run, showing a fresh successful flask on app.py run output _Flasked site display on localhost.
03_fresh_run_flask-py.png | After scraper.py run, showing a fresh successful flask on app.py run output_ scrol down.
04_running_scraper-py_after_first_app-py_flask_run.png | After first app.py run, running the scraper.py again and its terminal output.
05_search-products_app-py.png | Searchiing Products onto the Flasked site display.
06_export-all-csv_downloaded.png | Exporting the resultant data in a csv file, downloaded.
07_export-filtered-csv_downloaded.png | Exporting the resultant filtered data in a csv file, downloaded.
08_add-product-demo.png | Adding Products. 
09_finding-added-demo-product.png | Finding Added Products. 
10_editing-feature-price-to-product-demo.png | Editing Added Products. 
11_product-demo-Deleted.png | Deleting Added Products. 