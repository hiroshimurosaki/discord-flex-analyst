-- Schema do bot de análise de LoL — SQLite.
-- Princípios (bot-lol.md): multi-tenant (toda query filtra por grupo),
-- fatos imutáveis (partidas/participacoes só inserem), portável Linux/Windows.
--
-- Entidades (grupos, jogadores) PODEM ser editadas (nick muda etc.).
-- Fatos (partidas, participacoes) NUNCA são editados — só inseridos.

PRAGMA foreign_keys = ON;

-- ============================================================
-- grupos — cada servidor de Discord (a unidade multi-tenant)
-- ============================================================
CREATE TABLE IF NOT EXISTS grupos (
    id                INTEGER PRIMARY KEY,
    nome              TEXT NOT NULL,
    discord_guild_id  TEXT,
    discord_canal_id  TEXT,
    regional          TEXT NOT NULL DEFAULT 'americas',
    platform          TEXT NOT NULL DEFAULT 'br1',
    criado_em         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- jogadores — PUUID ligado a um grupo
-- ============================================================
CREATE TABLE IF NOT EXISTS jogadores (
    id            INTEGER PRIMARY KEY,
    grupo_id      INTEGER NOT NULL REFERENCES grupos(id),
    puuid         TEXT NOT NULL,
    riot_id       TEXT,                     -- ex.: 'Hiroshi#10102'
    nick_display  TEXT NOT NULL,
    ativo         INTEGER NOT NULL DEFAULT 1,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (grupo_id, puuid)
);

-- ============================================================
-- partidas — uma linha por match único (FATO IMUTÁVEL)
-- ============================================================
CREATE TABLE IF NOT EXISTS partidas (
    id             INTEGER PRIMARY KEY,
    grupo_id       INTEGER NOT NULL REFERENCES grupos(id),
    match_id       TEXT NOT NULL,           -- ex.: 'BR1_1234567890'
    queue_id       INTEGER,                 -- 440=Flex, 420=SoloQ, 450=ARAM...
    duracao_seg    INTEGER,
    inicio_ts      INTEGER,                 -- gameStartTimestamp (ms)
    vencedor_team  INTEGER,                 -- 100 / 200
    em_grupo       INTEGER NOT NULL DEFAULT 0,   -- 1 se 2+ membros no mesmo time
    tem_timeline   INTEGER NOT NULL DEFAULT 0,
    processada_em  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (grupo_id, match_id)             -- dedupe por grupo
);

-- ============================================================
-- participacoes — uma linha por jogador-por-partida (FATO IMUTÁVEL)
-- Guarda os 10 participantes; jogador_id NULL = não-membro (oponente/random).
-- Só dados crus: percentis e "melhor do time" são calculados na hora.
-- ============================================================
CREATE TABLE IF NOT EXISTS participacoes (
    id             INTEGER PRIMARY KEY,
    partida_id     INTEGER NOT NULL REFERENCES partidas(id),
    jogador_id     INTEGER REFERENCES jogadores(id),   -- NULL = não-membro
    puuid          TEXT NOT NULL,
    team_id        INTEGER,                 -- 100 / 200
    role           TEXT,                    -- teamPosition (limpar 'Invalid')
    campeao        TEXT,
    win            INTEGER,
    kills          INTEGER,
    deaths         INTEGER,
    assists        INTEGER,
    dano           INTEGER,                 -- totalDamageDealtToChampions
    dano_recebido  INTEGER,                 -- totalDamageTaken
    ouro           INTEGER,                 -- goldEarned
    visao          INTEGER,                 -- visionScore
    farm           INTEGER,                 -- minions + neutros
    kp             REAL,                    -- kill participation (0..1)
    ouro_10        INTEGER,                 -- da timeline (NULL se ausente)
    ouro_15        INTEGER,
    lanediff_10    INTEGER,                 -- vs oponente direto da rota
    challenges_json TEXT,                   -- 125 métricas pré-calculadas (cru, JSON)
    UNIQUE (partida_id, puuid)
);

-- ============================================================
-- analises — cache das narrativas da LLM (1 chamada gera o lote)
-- tipo: 'time' (jogador_id NULL) ou 'individual' (jogador_id preenchido)
-- ============================================================
CREATE TABLE IF NOT EXISTS analises (
    id          INTEGER PRIMARY KEY,
    partida_id  INTEGER NOT NULL REFERENCES partidas(id),
    tipo        TEXT NOT NULL,            -- 'time' | 'individual'
    jogador_id  INTEGER REFERENCES jogadores(id),
    texto       TEXT NOT NULL,
    modelo      TEXT,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- momentos — timeline condensada (DERIVADO, regravável como `analises`)
--
-- A timeline crua vive em cache/ (disco local, fora do Git). Quando o ciclo
-- roda no GitHub Actions esse cache nasce vazio, e sem esta tabela o post
-- perderia a seção "🔑 Momentos-chave" sem emitir erro nenhum.
-- Guardamos o derivado (swing, briga decisiva, objetivos, multikills,
-- pick-offs) em vez do JSON cru: é ordens de grandeza menor e é o que o post
-- realmente usa. `formato` versiona o shape pra dar pra reprocessar.
-- ============================================================
CREATE TABLE IF NOT EXISTS momentos (
    partida_id  INTEGER PRIMARY KEY REFERENCES partidas(id),
    formato     INTEGER NOT NULL DEFAULT 1,
    dados_json  TEXT NOT NULL,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- recordes — Hall da Fama materializado (DERIVADO, regravável)
--
-- `records.recordes_grupo()` varre TODAS as partidas do recorte fazendo ~4-5
-- queries por partida: o custo de responder cresce com o histórico do grupo
-- (ARQUITETURA 6.2). Localmente isso só ficava lento; no handler HTTP do
-- Discord é fatal, porque a resposta tem 3 segundos de prazo.
--
-- A conta continua sendo a mesma — ela só passa a rodar uma vez por ciclo de
-- ingestão (no CI, onde tempo é de graça) em vez de a cada leitura.
-- ============================================================
CREATE TABLE IF NOT EXISTS recordes (
    grupo_id    INTEGER NOT NULL REFERENCES grupos(id),
    recorte     TEXT NOT NULL,           -- 'flex' | 'normais' | 'solo'
    categoria   TEXT NOT NULL,           -- 'maior_dano', 'comeback', ...
    valor       REAL NOT NULL,
    dados_json  TEXT NOT NULL,           -- nick, campeao, partida_id, data, dur...
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (grupo_id, recorte, categoria)
);

-- ============================================================
-- Índices para as queries quentes (sempre por grupo/jogador).
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_analises_partida ON analises(partida_id);
CREATE INDEX IF NOT EXISTS idx_jogadores_grupo   ON jogadores(grupo_id);
CREATE INDEX IF NOT EXISTS idx_partidas_grupo     ON partidas(grupo_id);
CREATE INDEX IF NOT EXISTS idx_partidas_queue     ON partidas(grupo_id, queue_id);
CREATE INDEX IF NOT EXISTS idx_part_partida        ON participacoes(partida_id);
CREATE INDEX IF NOT EXISTS idx_part_jogador        ON participacoes(jogador_id);
CREATE INDEX IF NOT EXISTS idx_part_campeao        ON participacoes(jogador_id, campeao);
