"""Export independent reviewer judgments as JSON Lines for study analysis."""

import argparse
import json
from pathlib import Path

try:
    from .server import db_connection
except ImportError:
    from server import db_connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reviews.jsonl"))
    parser.add_argument("--include-drafts", action="store_true")
    args = parser.parse_args()
    query = """SELECT reviewers.display_name AS reviewer, reviews.question_id,
        reviews.status, reviews.version, reviews.saved_at, reviews.submitted_at,
        reviews.payload FROM reviews JOIN reviewers ON reviewers.id=reviews.reviewer_id"""
    if not args.include_drafts:
        query += " WHERE reviews.status='submitted'"
    query += " ORDER BY reviews.question_id, reviewers.display_name"
    with db_connection() as db, args.output.open("w", encoding="utf-8") as output:
        rows = db.execute(query).fetchall()
        for row in rows:
            record = {key: row[key] for key in row.keys() if key != "payload"}
            record.update(json.loads(row["payload"]))
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Exported {len(rows)} reviews to {args.output}")


if __name__ == "__main__":
    main()
