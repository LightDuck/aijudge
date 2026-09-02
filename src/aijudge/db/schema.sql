CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS cards (
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
    card_materials TEXT,
    CHECK (race IN (
        'Normal', 'Field', 'Equip', 'Continuous', 'Quick-Play', 'Ritual', 'Counter',
        'Aqua', 'Beast', 'Beast-Warrior', 'Creator God', 'Cyberse', 'Dinosaur',
        'Divine-Beast', 'Dragon', 'Fairy', 'Fiend', 'Fish', 'Illusion', 'Insect',
        'Machine', 'Plant', 'Psychic', 'Pyro', 'Reptile', 'Rock', 'Sea Serpent',
        'Spellcaster', 'Thunder', 'Warrior', 'Winged Beast', 'Wyrm', 'Zombie'
    ) OR race IS NULL)
);

-- CREATE TABLE IF NOT EXISTS is a no-op on a database where `cards` already
-- exists, so this column addition is applied separately for pre-existing
-- databases; it's already present via the CREATE TABLE above on a fresh one.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS race TEXT;
DO $$ BEGIN
    ALTER TABLE cards ADD CONSTRAINT cards_race_check CHECK (race IN (
        'Normal', 'Field', 'Equip', 'Continuous', 'Quick-Play', 'Ritual', 'Counter',
        'Aqua', 'Beast', 'Beast-Warrior', 'Creator God', 'Cyberse', 'Dinosaur',
        'Divine-Beast', 'Dragon', 'Fairy', 'Fiend', 'Fish', 'Illusion', 'Insect',
        'Machine', 'Plant', 'Psychic', 'Pyro', 'Reptile', 'Rock', 'Sea Serpent',
        'Spellcaster', 'Thunder', 'Warrior', 'Winged Beast', 'Wyrm', 'Zombie'
    ) OR race IS NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS card_errata_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
    errata_date DATE NOT NULL,
    errata_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rulings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
    ruling_text TEXT NOT NULL,
    source TEXT NOT NULL,
    ruling_date DATE,
    embedding VECTOR(384)
);

CREATE TABLE IF NOT EXISTS card_effects_structured (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
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
    CHECK (status IN ('pending', 'confirmed')),
    CHECK (damage_step_category IN ('atk_def_alter', 'negates_activation', 'explicit_permission', 'card_moved_trigger') OR damage_step_category IS NULL)
);

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
