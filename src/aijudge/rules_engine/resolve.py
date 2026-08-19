from dataclasses import dataclass

from .chain import Chain
from .models import Effect, EffectType, SpellSpeed
from .priority import can_activate_now
from .segoc import apply_segoc


class UnsupportedScenarioError(Exception):
    """Raised when a resolve_chain scenario describes a step this engine has no rule for."""


@dataclass
class ChainLinkResult:
    link_number: int
    card_name: str
    controller: str


@dataclass
class Violation:
    step_index: int
    reason: str
    detail: str


@dataclass
class ResolutionResult:
    resolution_order: list[ChainLinkResult]
    violation: Violation | None


def _build_effect(data: dict) -> Effect:
    return Effect(
        card_id=data["card_name"],
        card_name=data["card_name"],
        effect_type=EffectType(data["effect_type"]),
        controller=data["controller"],
        spell_speed=SpellSpeed(data.get("spell_speed", SpellSpeed.NORMAL.value)),
        prevents_response=data.get("prevents_response", False),
    )


def _order(chain: Chain) -> list[ChainLinkResult]:
    return [
        ChainLinkResult(link_number=link.link_number, card_name=link.effect.card_name, controller=link.effect.controller)
        for link in chain.resolution_order()
    ]


def resolve_chain(scenario: dict) -> ResolutionResult:
    turn_player = scenario["turn_player"]
    chain = Chain()

    for step_index, step in enumerate(scenario["steps"]):
        kind = step["kind"]
        if kind == "segoc_batch":
            effects = [_build_effect(e) for e in step["effects"]]
            apply_segoc(chain, turn_player=turn_player, triggered_effects=effects)
        elif kind == "activate":
            effect = _build_effect(step["effect"])
            if not can_activate_now(effect.spell_speed, chain):
                violation = Violation(
                    step_index=step_index,
                    reason="priority_violation",
                    detail=(
                        f"{effect.card_name}'s spell speed {effect.spell_speed.value} "
                        "cannot respond to the current chain"
                    ),
                )
                return ResolutionResult(resolution_order=_order(chain), violation=violation)
            chain.add_link(effect)
        else:
            raise UnsupportedScenarioError(f"unrecognized step kind: {kind!r}")

    return ResolutionResult(resolution_order=_order(chain), violation=None)
