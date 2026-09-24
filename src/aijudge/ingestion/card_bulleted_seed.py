import json
from pathlib import Path

from aijudge.db.bullet_categories_repo import get_all_bullet_categories
from aijudge.db.card_bulleted_repo import upsert_card_bulleted_rows

DEFAULT_FIXTURE_PATH = Path(__file__).parent / "data" / "card_bulleted.json"


class UnknownBulletCategoryError(ValueError):
    pass


def seed_card_bulleted(path: Path = DEFAULT_FIXTURE_PATH) -> int:
    """Load the card_bulleted fixture into the DB. Safe to re-run: rows are
    upserted on their passcode, `note` is never overwritten, and rows absent
    from the fixture are left alone. Every category code is checked before
    anything is written, so a fixture/legend mismatch can't cause a partial load."""
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    category_ids = {c["code"]: c["id"] for c in get_all_bullet_categories()}
    unknown = sorted({e["category_code"] for e in entries} - category_ids.keys())
    if unknown:
        raise UnknownBulletCategoryError(f"fixture uses bullet category codes missing from bullet_category: {unknown}")
    return upsert_card_bulleted_rows([
        {
            "ygoprodeck_id": e["ygoprodeck_id"],
            "bullet_category_id": category_ids[e["category_code"]],
            "reason": e["reason"],
        }
        for e in entries
    ])
