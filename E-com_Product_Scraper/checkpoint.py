"""Store page-level progress in the same database as the catalog."""

import json
from dataclasses import asdict, dataclass, field


class CheckpointError(ValueError):
    """The saved progress is invalid or has changed in another process."""


@dataclass
class ScrapeProgress:
    url: str
    pages: int = 0
    added: int = 0
    duplicates: int = 0
    invalid: int = 0
    seen_products: set[str] = field(default_factory=set)
    visited_pages: set[str] = field(default_factory=set)

    def encode(self):
        data = asdict(self)
        data["seen_products"] = sorted(self.seen_products)
        data["visited_pages"] = sorted(self.visited_pages)
        return json.dumps(data)

    @classmethod
    def decode(cls, snapshot):
        try:
            data = json.loads(snapshot)
            for key in ("seen_products", "visited_pages"):
                urls = data[key]
                if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
                    raise ValueError("Invalid saved URL list.")
                data[key] = set(urls)
            progress = cls(**data)
            if not isinstance(progress.url, str):
                raise ValueError("Invalid saved page URL.")
            counters = (progress.pages, progress.added, progress.duplicates, progress.invalid)
            if any(type(count) is not int or count < 0 for count in counters):
                raise ValueError("Invalid saved count.")
        except (ValueError, TypeError, KeyError) as error:
            raise CheckpointError("Saved progress could not be read. Use --fresh with the same options.") from error
        return progress


def read_checkpoint(connection, run_key):
    row = connection.execute(
        "SELECT progress FROM scrape_checkpoints WHERE run_key = ?", (run_key,),
    ).fetchone()
    return row["progress"] if row else None


def begin_checkpoint_write(connection, run_key, snapshot):
    connection.execute("BEGIN IMMEDIATE")
    if read_checkpoint(connection, run_key) != snapshot:
        raise CheckpointError("This checkpoint changed in another process. Rerun the same command.")


def save_checkpoint(connection, run_key, snapshot):
    connection.execute(
        "INSERT INTO scrape_checkpoints (run_key, progress) VALUES (?, ?) "
        "ON CONFLICT(run_key) DO UPDATE SET progress = excluded.progress",
        (run_key, snapshot),
    )


def clear_checkpoint(connection, run_key):
    connection.execute("DELETE FROM scrape_checkpoints WHERE run_key = ?", (run_key,))
