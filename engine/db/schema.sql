-- =============================================================================
-- Futbol Haftalık Skor Tahmini ve Takım Analiz Sistemi - PostgreSQL Şeması
-- Hedef Platform: Supabase (PostgreSQL 15+)
-- Kapsam: Süper Lig, Premier League, La Liga, Ligue 1
-- =============================================================================

BEGIN;

-- Otomatik updated_at güncelleme fonksiyonu
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- 1. leagues: Desteklenen 4 ligin temel metadata tablosu
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leagues (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    country VARCHAR(80) NOT NULL,
    season VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 2. teams: Liglerde yer alan takımlar
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    league_id VARCHAR(50) NOT NULL REFERENCES leagues(id) ON DELETE CASCADE ON UPDATE CASCADE,
    name VARCHAR(150) NOT NULL,
    short_name VARCHAR(50),
    logo_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_teams_league_name UNIQUE (league_id, name)
);

-- -----------------------------------------------------------------------------
-- 3. matches: Haftalık fikstür ve maç sonuçları
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    id SERIAL PRIMARY KEY,
    league_id VARCHAR(50) NOT NULL REFERENCES leagues(id) ON DELETE CASCADE ON UPDATE CASCADE,
    home_team_id INT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    away_team_id INT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    match_date TIMESTAMPTZ NOT NULL,
    round INT NOT NULL CHECK (round > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED'
        CHECK (status IN ('SCHEDULED', 'FINISHED', 'POSTPONED')),
    home_score INT NULL CHECK (home_score IS NULL OR home_score >= 0),
    away_score INT NULL CHECK (away_score IS NULL OR away_score >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_matches_different_teams CHECK (home_team_id <> away_team_id),
    CONSTRAINT uq_matches_fixture UNIQUE (league_id, round, home_team_id, away_team_id)
);

-- -----------------------------------------------------------------------------
-- 4. injuries: Oyuncu sakatlık ve ceza durumları
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS injuries (
    id SERIAL PRIMARY KEY,
    team_id INT NOT NULL REFERENCES teams(id) ON DELETE CASCADE ON UPDATE CASCADE,
    player_name VARCHAR(150) NOT NULL,
    position VARCHAR(10) NOT NULL
        CHECK (position IN ('GK', 'DEF', 'MID', 'FW')),
    reason VARCHAR(255) NOT NULL,
    return_date VARCHAR(64),
    impact_level VARCHAR(10) NOT NULL
        CHECK (impact_level IN ('HIGH', 'MEDIUM', 'LOW')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 5. predictions: Maç bazlı skor tahminleri ve olasılık dağılımları
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    match_id INT NOT NULL UNIQUE REFERENCES matches(id) ON DELETE CASCADE ON UPDATE CASCADE,
    predicted_home_score INT NOT NULL CHECK (predicted_home_score >= 0),
    predicted_away_score INT NOT NULL CHECK (predicted_away_score >= 0),
    confidence_rate FLOAT NOT NULL CHECK (confidence_rate >= 0),
    top_scores_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 6. team_analyses: Maç önizleme metinleri ve hücum/savunma reytingleri
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_analyses (
    id SERIAL PRIMARY KEY,
    match_id INT NOT NULL UNIQUE REFERENCES matches(id) ON DELETE CASCADE ON UPDATE CASCADE,
    match_overview_text TEXT NOT NULL,
    home_analysis_text TEXT NOT NULL,
    away_analysis_text TEXT NOT NULL,
    home_offense_rating FLOAT NOT NULL,
    home_defense_rating FLOAT NOT NULL,
    away_offense_rating FLOAT NOT NULL,
    away_defense_rating FLOAT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- İNDEKSLER
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_teams_league_id ON teams(league_id);

CREATE INDEX IF NOT EXISTS idx_matches_league_id ON matches(league_id);
CREATE INDEX IF NOT EXISTS idx_matches_league_round ON matches(league_id, round);
CREATE INDEX IF NOT EXISTS idx_matches_match_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_matches_home_team_id ON matches(home_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_away_team_id ON matches(away_team_id);

CREATE INDEX IF NOT EXISTS idx_injuries_team_id ON injuries(team_id);
CREATE INDEX IF NOT EXISTS idx_injuries_impact_level ON injuries(impact_level);

CREATE INDEX IF NOT EXISTS idx_predictions_updated_at ON predictions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_team_analyses_updated_at ON team_analyses(updated_at DESC);

-- =============================================================================
-- ZAMAN DAMGASI TETİKLEYİCİLERİ (UPDATED_AT TRIGGERS)
-- =============================================================================
DROP TRIGGER IF EXISTS trg_leagues_updated_at ON leagues;
CREATE TRIGGER trg_leagues_updated_at
    BEFORE UPDATE ON leagues
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_teams_updated_at ON teams;
CREATE TRIGGER trg_teams_updated_at
    BEFORE UPDATE ON teams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_matches_updated_at ON matches;
CREATE TRIGGER trg_matches_updated_at
    BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_injuries_updated_at ON injuries;
CREATE TRIGGER trg_injuries_updated_at
    BEFORE UPDATE ON injuries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_predictions_updated_at ON predictions;
CREATE TRIGGER trg_predictions_updated_at
    BEFORE UPDATE ON predictions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_team_analyses_updated_at ON team_analyses;
CREATE TRIGGER trg_team_analyses_updated_at
    BEFORE UPDATE ON team_analyses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- SATIR DÜZEYİNDE GÜVENLİK (ROW LEVEL SECURITY - SALT OKUNUR GENEL ERİŞİM)
-- Yazma (INSERT / UPDATE / DELETE) işlemleri yalnızca RLS'yi aşan service_role
-- anahtarıyla gerçekleştirilebilir.
-- =============================================================================
ALTER TABLE leagues ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS public_read_leagues ON leagues;
CREATE POLICY public_read_leagues ON leagues
    FOR SELECT USING (true);

ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS public_read_teams ON teams;
CREATE POLICY public_read_teams ON teams
    FOR SELECT USING (true);

ALTER TABLE matches ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS public_read_matches ON matches;
CREATE POLICY public_read_matches ON matches
    FOR SELECT USING (true);

ALTER TABLE injuries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS public_read_injuries ON injuries;
CREATE POLICY public_read_injuries ON injuries
    FOR SELECT USING (true);

ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS public_read_predictions ON predictions;
CREATE POLICY public_read_predictions ON predictions
    FOR SELECT USING (true);

ALTER TABLE team_analyses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS public_read_team_analyses ON team_analyses;
CREATE POLICY public_read_team_analyses ON team_analyses
    FOR SELECT USING (true);

-- =============================================================================
-- 4 LİG SABİT BAŞLANGIÇ KAYITLARI (SEED - OTOMATİK DİNAMİK SEZON)
-- =============================================================================
INSERT INTO leagues (id, name, country, season) VALUES
    (
        'super_lig',
        'Süper Lig',
        'Turkey',
        CASE WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 7 THEN EXTRACT(YEAR FROM CURRENT_DATE)::INT || '-' || (EXTRACT(YEAR FROM CURRENT_DATE)::INT + 1) ELSE (EXTRACT(YEAR FROM CURRENT_DATE)::INT - 1) || '-' || EXTRACT(YEAR FROM CURRENT_DATE)::INT END
    ),
    (
        'premier_league',
        'Premier League',
        'England',
        CASE WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 7 THEN EXTRACT(YEAR FROM CURRENT_DATE)::INT || '-' || (EXTRACT(YEAR FROM CURRENT_DATE)::INT + 1) ELSE (EXTRACT(YEAR FROM CURRENT_DATE)::INT - 1) || '-' || EXTRACT(YEAR FROM CURRENT_DATE)::INT END
    ),
    (
        'la_liga',
        'La Liga',
        'Spain',
        CASE WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 7 THEN EXTRACT(YEAR FROM CURRENT_DATE)::INT || '-' || (EXTRACT(YEAR FROM CURRENT_DATE)::INT + 1) ELSE (EXTRACT(YEAR FROM CURRENT_DATE)::INT - 1) || '-' || EXTRACT(YEAR FROM CURRENT_DATE)::INT END
    ),
    (
        'ligue_1',
        'Ligue 1',
        'France',
        CASE WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 7 THEN EXTRACT(YEAR FROM CURRENT_DATE)::INT || '-' || (EXTRACT(YEAR FROM CURRENT_DATE)::INT + 1) ELSE (EXTRACT(YEAR FROM CURRENT_DATE)::INT - 1) || '-' || EXTRACT(YEAR FROM CURRENT_DATE)::INT END
    )
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    country = EXCLUDED.country,
    season = EXCLUDED.season,
    updated_at = NOW();

COMMIT;
