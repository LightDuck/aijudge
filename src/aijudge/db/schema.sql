CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    card_text TEXT NOT NULL,
    card_type TEXT NOT NULL,
    attribute TEXT,
    monster_type TEXT,
    level INTEGER,
    rank INTEGER,
    link_rating INTEGER,
    archetype TEXT,
    atk INTEGER,
    def INTEGER,
    ygoprodeck_id TEXT,
    ygoresources_id TEXT,
    source TEXT NOT NULL,
    fetched_at DATE NOT NULL,
    has_errata BOOLEAN NOT NULL DEFAULT FALSE,
    card_materials TEXT
);

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
    effect TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence_score REAL,
    CHECK (status IN ('pending', 'confirmed'))
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
