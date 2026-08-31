from .connection import get_connection

_EFFECT_COLUMNS = [
    "id", "effect_type", "activation_condition", "cost", "targeting", "has_target", "effect",
    "damage_step_category", "usage_limit_text",
]


def insert_pending_effect(
    *,
    card_id: str,
    effect_type: str,
    effect: str,
    activation_condition: str | None = None,
    cost: str | None = None,
    targeting: str | None = None,
    has_target: bool = False,
    confidence_score: float | None = None,
    damage_step_category: str | None = None,
    usage_limit_text: str | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO card_effects_structured (
                card_id, effect_type, activation_condition, cost, targeting,
                has_target, effect, status, confidence_score,
                damage_step_category, usage_limit_text
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s)
            RETURNING id
            """,
            (
                card_id, effect_type, activation_condition, cost, targeting, has_target, effect,
                confidence_score, damage_step_category, usage_limit_text,
            ),
        ).fetchone()
        conn.commit()
        return str(row[0])


def confirm_effect(effect_id: str) -> None:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE card_effects_structured SET status = 'confirmed' WHERE id = %s",
            (effect_id,),
        )
        if cur.rowcount != 1:
            raise ValueError(f"no card_effects_structured row with id={effect_id!r} to confirm")
        conn.commit()


def get_confirmed_effects(card_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, effect_type, activation_condition, cost, targeting, has_target, effect,
                   damage_step_category, usage_limit_text
            FROM card_effects_structured
            WHERE card_id = %s AND status = 'confirmed'
            """,
            (card_id,),
        ).fetchall()
    results = []
    for row in rows:
        row_list = list(row)
        row_list[0] = str(row_list[0])
        results.append(dict(zip(_EFFECT_COLUMNS, row_list)))
    return results
