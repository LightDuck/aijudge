"""Real ygoresources ruling texts and Konami ids shared by the rulings tests.

Copied verbatim from the app database's `rulings` rows (source db.ygoresources)
on 2026-10-05. Names come from https://db.ygoresources.com/data/idx/card/name/en.
"""

AMAZONESS_CALL_KONAMI_ID = 13174
AMAZONESS_QUEEN_KONAMI_ID = 8963
DIGITRON_KONAMI_ID = 13192

AMAZONESS_CALL_RULING_2017 = (
    "Q: I activate the second effect of <<13174>>, targeting an <<8963>> on my field. If my opponent chains "
    "<<5505>> and takes control of <<8963>>, how does the effect of <<13174>> resolve?\n"
    "A: Even if your opponent has taken control of the monster targeted with the second effect of <<13174>> when "
    "that effect resolves, the effect is applied normally. In this scenario, monsters on your field other than the "
    "targeted monster cannot attack this turn. (If you regain control of that <<8963>> this turn using an effect "
    "such as <<5682>>, etc., then it can attack all monsters on your opponent's field once each.)"
)

AMAZONESS_CALL_RULING_2026 = (
    "Q: I activate the『You can banish this card from your Graveyard, then target 1 \"Amazoness\" monster you "
    "control; this turn, that monster can attack all monsters your opponent controls, once each, also other "
    "monsters you control cannot attack』effect of <<13174>> in my Graveyard and targeted an <<8963>> that's "
    "face-up in my Monster Zone.\n\n"
    "If the opponent activates <<5914>> in response, and the targeted <<8963>> is returned to the hand and is no "
    "longer on the field, what happens to the effect's resolution?\n"
    "A: In the situation of the question, the <<8963>> that was targeted by the effect of <<13174>> activated in "
    "the Graveyard is no longer on the field, so as a result the『that monster can attack all monsters your "
    "opponent controls, once each』effect won'tbe applied, but the『this turn, other monsters you control "
    "cannot attack』effect will be applied, so your monsters can no longer attack this turn."
)

DIGITRON_RULING_2019 = (
    "Q: I Link Summon a <<13489>>, using a <<13034>> and <<13192>> as materials. At this time, can I activate 2 "
    "copies of <<14436>>?\n"
    "A: You can activate 2 copies of <<14436>> in the same Chain when you successfully Link Summon a monster. (In "
    "this scenario, since <<13034>> and <<13192>> were both sent to the Graveyard as materials, each of them can "
    "be targeted by the effect of <<14436>>.)"
)

# A real slice of /data/idx/card/name/en ({name: [konami_id, ...]}), covering
# every id the rulings above reference, plus Cyber Angel Benten's two names
# for the renamed-card case.
NAME_INDEX_SLICE = {
    "Amazoness Call": [13174],
    "Amazoness Queen": [8963],
    "Enemy Controller": [5505],
    "Remove Brainwashing": [5682],
    "Compulsory Evacuation Device": [5914],
    "Security Dragon": [13489],
    "Link Spider": [13034],
    "Digitron": [13192],
    "Cynet Cascade": [14436],
    "Cyber Angel - Benten": [6845],
    "Cyber Angel Benten": [6845],
}
