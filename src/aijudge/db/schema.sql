CREATE EXTENSION IF NOT EXISTS vector;

-- The card table was originally named `cards`; rename it (and its
-- auto-named constraints) in place on pre-existing databases so existing
-- rows and foreign keys survive. A no-op on a fresh database.
DO $$ BEGIN
    IF to_regclass('public.cards') IS NOT NULL AND to_regclass('public.card') IS NULL THEN
        ALTER TABLE cards RENAME TO card;
        ALTER TABLE card RENAME CONSTRAINT cards_pkey TO card_pkey;
        ALTER TABLE card RENAME CONSTRAINT cards_name_key TO card_name_key;
        ALTER TABLE card RENAME CONSTRAINT cards_race_check TO card_race_check;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS card (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    card_text TEXT NOT NULL,
    card_type TEXT NOT NULL,
    race TEXT,
    attribute TEXT,
    monster_type TEXT,
    level INTEGER,
    rank INTEGER,
    link_rating INTEGER,
    archetype TEXT,
    atk INTEGER,
    def INTEGER,
    ygoprodeck_id TEXT NOT NULL,
    ygoresources_id TEXT,
    source TEXT NOT NULL,
    fetched_at DATE NOT NULL,
    has_errata BOOLEAN NOT NULL DEFAULT FALSE,
    deterministic_parse_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (race IN (
        'Normal', 'Field', 'Equip', 'Continuous', 'Quick-Play', 'Ritual', 'Counter',
        'Aqua', 'Beast', 'Beast-Warrior', 'Creator God', 'Cyberse', 'Dinosaur',
        'Divine-Beast', 'Dragon', 'Fairy', 'Fiend', 'Fish', 'Illusion', 'Insect',
        'Machine', 'Plant', 'Psychic', 'Pyro', 'Reptile', 'Rock', 'Sea Serpent',
        'Spellcaster', 'Thunder', 'Warrior', 'Winged Beast', 'Wyrm', 'Zombie'
    ) OR race IS NULL)
);

-- CREATE TABLE IF NOT EXISTS is a no-op on a database where `card` already
-- exists, so this column addition is applied separately for pre-existing
-- databases; it's already present via the CREATE TABLE above on a fresh one.
ALTER TABLE card ADD COLUMN IF NOT EXISTS race TEXT;
DO $$ BEGIN
    ALTER TABLE card ADD CONSTRAINT card_race_check CHECK (race IN (
        'Normal', 'Field', 'Equip', 'Continuous', 'Quick-Play', 'Ritual', 'Counter',
        'Aqua', 'Beast', 'Beast-Warrior', 'Creator God', 'Cyberse', 'Dinosaur',
        'Divine-Beast', 'Dragon', 'Fairy', 'Fiend', 'Fish', 'Illusion', 'Insect',
        'Machine', 'Plant', 'Psychic', 'Pyro', 'Reptile', 'Rock', 'Sea Serpent',
        'Spellcaster', 'Thunder', 'Warrior', 'Winged Beast', 'Wyrm', 'Zombie'
    ) OR race IS NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Same rationale as the race migration above: applied separately for
-- pre-existing databases. card_materials is dropped outright, not kept
-- for backwards compatibility -- nothing ever populated or read it (see
-- design spec's Data model changes section).
ALTER TABLE card ADD COLUMN IF NOT EXISTS deterministic_parse_eligible BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE card DROP COLUMN IF EXISTS card_materials;

CREATE TABLE IF NOT EXISTS card_errata_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES card (id),
    errata_date DATE NOT NULL,
    errata_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rulings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES card (id),
    ruling_text TEXT NOT NULL,
    source TEXT NOT NULL,
    ruling_date DATE,
    embedding VECTOR(384)
);

CREATE TABLE IF NOT EXISTS card_effects_structured (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES card (id),
    effect_type TEXT NOT NULL,
    activation_condition TEXT,
    cost TEXT,
    targeting TEXT,
    has_target BOOLEAN NOT NULL DEFAULT FALSE,
    effect TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence_score REAL,
    damage_step_category TEXT,
    usage_limit_text TEXT,
    has_effect_choice BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (status IN ('pending', 'confirmed')),
    CHECK (damage_step_category IN ('atk_def_alter', 'negates_activation', 'explicit_permission', 'card_moved_trigger') OR damage_step_category IS NULL)
);

-- Same rationale as the card.race/deterministic_parse_eligible migrations
-- above: applied separately for pre-existing databases, since CREATE TABLE
-- IF NOT EXISTS is a no-op once card_effects_structured already exists.
ALTER TABLE card_effects_structured ADD COLUMN IF NOT EXISTS has_effect_choice BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS rulebook_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_text TEXT NOT NULL,
    source TEXT NOT NULL,
    section_reference TEXT,
    embedding VECTOR(384)
);

CREATE TABLE IF NOT EXISTS qa_test_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_citation TEXT,
    notes TEXT
);

-- Reference table mirroring the "Bullet Category Legend" document: how a
-- card's bulleted effect list behaves (who picks, when, how many). Rows are
-- part of the schema, not ingested data, so they're seeded here and upserted
-- on every run_migrations() -- edit a definition here and re-run migrations.
CREATE TABLE IF NOT EXISTS bullet_categories (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    note TEXT
);

INSERT INTO bullet_categories (code, name, description, note) VALUES
    ('A1', 'Condition-scope · activation',
     'The bullets are alternatives that define a qualifying test — any one of them satisfies it. The test is checked when the effect is activated.',
     NULL),
    ('A2', 'Condition-scope · resolution',
     'Same as A1 (any one bullet qualifies), but the test is checked when the effect resolves.',
     NULL),
    ('B1', 'Player choice · activation',
     'Always choose strictly 1 bullet, at activation ("activate 1 of these effects").',
     NULL),
    ('B2', 'Player choice · resolution',
     'Always choose strictly 1 bullet, at resolution ("apply 1 of these effects").',
     NULL),
    ('C', 'Deterministic branch',
     'No free choice is made by any player. The choice(s) are determined by criteria written on the card.',
     NULL),
    ('D1', 'Mandatory grant',
     '1 or more bullets, granted as a single indivisible bundle: one binary condition on the card either grants all of them or none of them. There is no branch and no scale — the bundle is never split into a subset.',
     'Contrast with C: a card whose criteria select a subset of bullets, or move between them as some value changes, belongs in C, not here, even if the bullets are grant-phrased.'),
    ('D2', 'Optional grant',
     'A player may apply or skip exactly one bullet — a [0:1] choice, made explicit by the card''s own "can apply this/the following effect" wording. The bullet usually follows a mandatory part of the effect, but that part may be absent: the optional bullet can be the effect''s entire content (e.g. Extra Net). The deciding player is not always the card''s controller (Extra Net: the opponent of the player who Summoned). The optional part is always a single effect, never a menu of several.',
     'Contrast with D1: if nothing in the text lets the player opt out of the bullet — once the mandatory part, if any, resolves — it belongs there instead.'),
    ('E1', 'Multi-select · activation',
     'Choose [1:N] non mandatory effect(s) to use, at activation ("activate 1 or 2 / any / 2 of these effects"). The card tells the mechanism with which the effect(s) can be chosen (and possible resolution).',
     NULL),
    ('E2', 'Multi-select · resolution',
     'Same as E1 (choose [1:N] non mandatory effect(s) by the mechanism the card tells), but the effect(s) are chosen at resolution ("apply 1 of these, or both / any of them").',
     NULL),
    ('F', 'Independent effects',
     'Multiple effects with zero impact on each other (unless the card''s usage_limit_text says otherwise). The bullet list is aesthetic rather than functional. Test — both parts must hold: (1) stripping the bullet markers and reading each bullet as a plain sentence doesn''t change what the card does, and (2) if there''s a sentence right before the bullets, it must already be complete on its own — its verb can''t need the bullets to mean anything ("apply the result," "gains this effect," "based on X"). If that sentence is left dangling without the bullets, they''re functional, not aesthetic, and the card belongs wherever that sentence actually points — C, B1/B2, D1/D2, or A — not F.',
     NULL),
    ('G', 'Gemini Monster',
     'Always a Monster Card carrying the Gemini stipulation (type field == Gemini Monster).',
     NULL),
    ('H', 'Purrely',
     'Card name contains "Purrely". Multiple independent bullet lists that fit in two different categories.',
     NULL),
    ('Z', 'Unspecified (pending)',
     'Placeholder. Category still to be defined after this list is reviewed. Also holds cards the first sort could not place.',
     NULL)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    note = EXCLUDED.note;
