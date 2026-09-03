-- Camada 1: FATOS. Só INSERT, nunca UPDATE.
--
-- Uma partida é um evento histórico. Reescrevê-la seria reescrever o passado —
-- e o passado é exatamente o que esta história está tentando contar.
--
-- Single-team de propósito: o projeto anterior era multi-tenant e pagava a
-- complexidade de `grupo_id` em toda query. Aqui o produto é UMA história de UM
-- time; um segundo time é um segundo banco (`CRONICA_BANCO=...`), que é mais
-- simples e não vaza dado entre times por esquecimento de WHERE.

PRAGMA foreign_keys = ON;

-- ============================================================
-- membros — espelho do elenco do cânone, com o PUUID resolvido.
-- `id` é o id do YAML (não um autoincrement): o cânone é a fonte da verdade
-- sobre quem é quem, e assim o join com personagem/dossiê é direto.
-- ============================================================
CREATE TABLE IF NOT EXISTS membros (
    id        TEXT PRIMARY KEY,       -- id do cânone: 'hiroshi', 'lukyy'...
    puuid     TEXT NOT NULL UNIQUE,
    riot_id   TEXT NOT NULL,
    nome      TEXT NOT NULL,
    titular   INTEGER NOT NULL DEFAULT 1,
    role      TEXT
);

-- ============================================================
-- partidas — uma linha por match.
--
-- `n_membros` e `em_grupo` são desnormalizados de propósito: a cronologia
-- ordena e segmenta o histórico de grupo dezenas de vezes por execução, e
-- recontar participantes a cada varredura tornaria a detecção de eras
-- quadrática no histórico sem nenhum ganho.
-- ============================================================
CREATE TABLE IF NOT EXISTS partidas (
    id             INTEGER PRIMARY KEY,
    match_id       TEXT NOT NULL UNIQUE,
    fila           INTEGER NOT NULL,       -- 440 flex, 420 soloq
    inicio_ts      INTEGER NOT NULL,       -- gameStartTimestamp (ms, UTC)
    duracao_seg    INTEGER NOT NULL,
    vencedor_team  INTEGER,                -- 100 | 200 | NULL (remake)
    patch          TEXT,                   -- '15.14' — fronteira de era barata
    n_membros      INTEGER NOT NULL DEFAULT 0,  -- membros no MESMO time
    em_grupo       INTEGER NOT NULL DEFAULT 0,  -- 1 se n_membros >= 2
    coletada_em    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- participacoes — os 10 jogadores, não só os nossos.
--
-- `membro_id NULL` = não-membro. Guardar os 10 é o que permite as duas únicas
-- afirmações de desempenho que são honestas: percentil-dentro-da-partida
-- (você contra os 10 que estavam ali, mesmo patch, mesmo elo) e matchup contra
-- o oponente direto da rota. Guardando só o nosso lado, 25k de dano é um número
-- sem régua — e número sem régua é o que faz a narrativa mentir.
-- ============================================================
CREATE TABLE IF NOT EXISTS participacoes (
    id              INTEGER PRIMARY KEY,
    partida_id      INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
    puuid           TEXT NOT NULL,
    membro_id       TEXT REFERENCES membros(id),   -- NULL = não-membro
    team_id         INTEGER NOT NULL,
    role            TEXT,                  -- teamPosition ('' e 'Invalid' -> NULL)
    campeao         TEXT,
    win             INTEGER NOT NULL,
    kills           INTEGER, deaths INTEGER, assists INTEGER,
    dano            INTEGER,               -- totalDamageDealtToChampions
    dano_recebido   INTEGER,
    ouro            INTEGER,
    visao           INTEGER,
    farm            INTEGER,               -- minions + neutros
    kp              REAL,                  -- kill participation 0..1
    ouro_10         INTEGER,               -- timeline; NULL se ausente
    ouro_15         INTEGER,
    lanediff_10     INTEGER,               -- vs oponente direto da rota
    challenges_json TEXT,                  -- ~125 métricas da Riot, cru
    UNIQUE (partida_id, puuid)
);

-- ============================================================
-- timeline_derivada — o que a timeline diz, condensado.
--
-- A timeline crua é o objeto caro (minuto a minuto, 10 jogadores) e vive em
-- cache/ fora do Git. Guardar o DERIVADO aqui é o que torna o banco
-- autossuficiente: sem esta tabela, apagar o cache faria o seletor `virada`
-- parar de achar viradas — e ele não teria como avisar, só devolveria lista
-- vazia. `formato` versiona o shape pra permitir reprocessar depois.
-- ============================================================
CREATE TABLE IF NOT EXISTS timeline_derivada (
    partida_id   INTEGER PRIMARY KEY REFERENCES partidas(id) ON DELETE CASCADE,
    formato      INTEGER NOT NULL DEFAULT 1,
    deficit_max  INTEGER,     -- maior desvantagem de ouro do NOSSO time (>=0)
    pico_max     INTEGER,     -- maior vantagem de ouro do NOSSO time
    minuto_deficit INTEGER,   -- em que minuto o déficit máximo aconteceu
    dados_json   TEXT NOT NULL,   -- série de ouro por minuto, objetivos, etc.
    criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_partidas_fila    ON partidas(fila, inicio_ts);
CREATE INDEX IF NOT EXISTS idx_partidas_grupo   ON partidas(em_grupo, inicio_ts);
CREATE INDEX IF NOT EXISTS idx_part_partida     ON participacoes(partida_id);
CREATE INDEX IF NOT EXISTS idx_part_membro      ON participacoes(membro_id);
CREATE INDEX IF NOT EXISTS idx_part_campeao     ON participacoes(membro_id, campeao);
