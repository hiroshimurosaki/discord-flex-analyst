# discord-flex-analyst

Bot de Discord que analisa as partidas de LoL do grupo: detecta jogos,
puxa dados da Riot API, calcula estatísticas (determinístico) e gera
análises narradas por LLM. Ver o briefing completo em [bot-lol.md](bot-lol.md)
e como as peças se encaixam em [ARQUITETURA.md](ARQUITETURA.md).

**Filosofia:** cálculo é determinístico; a LLM só narra. Multi-tenant desde
o dia 1; cada partida/participação é um fato imutável. Portável Linux/Windows.

## Como roda (sem PC ligado)

O bot tem duas metades com requisitos opostos, e cada uma mora onde cabe:

| Metade | Onde | Gatilho |
|---|---|---|
| Poller, ingestão, narrativa, post automático | **GitHub Actions** (`.github/workflows/ciclo.yml`) | cron de 5 min |
| Slash commands (`/recordes`, `/perfil`, `/time`, `/jogador`) | **Vercel** (`api/interactions.py`) | HTTP Interactions |
| Estado (o banco) | **o próprio repo** (`data/bot_lol.db`) | commitado a cada ciclo |

O ciclo posta por **webhook** do canal, então não existe processo de bot
conectado. Os slash commands respondem por HTTP, então também não. O banco vive
versionado no repo porque o Actions não tem disco entre runs — e é isso que
permite ao Vercel servir os comandos lendo o mesmo arquivo, sem banco hospedado.

A LLM é o **CLI do Claude Code em modo headless** (`claude -p`), não a API HTTP:
autentica pela assinatura, então o custo fica no plano. Ver `bot_lol/llm.py`.

## Setup local

```bash
python -m venv .venv
# Linux:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code   # a "LLM" do projeto
claude                                      # /login com a conta Pro
cp .env.example .env                        # e preencha (nunca vai pro Git)

python -m scripts.ciclo --dry-run           # roda um ciclo sem postar
```

## Setup em produção

**1. Secrets do repositório** (Settings → Secrets and variables → Actions):

| Secret | De onde vem |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` (validade de 1 ano — anote a data) |
| `RIOT_API_KEY` | **chave de produção**; a de dev expira em 24h e ninguém renova de madrugada |
| `DISCORD_WEBHOOK_URL` | Editar Canal → Integrações → Webhooks → Novo Webhook |

Não defina `ANTHROPIC_API_KEY`: ela tem precedência sobre o token da assinatura
e faria as chamadas caírem em créditos de API.

**2. Vercel** — importe o repo e defina `DISCORD_PUBLIC_KEY` e `DISCORD_APP_ID`
(Developer Portal → General Information) nas variáveis de ambiente. Depois cole
`https://SEU-PROJETO.vercel.app/api/interactions` em *Interactions Endpoint URL*.
O Discord só aceita a URL se ela recusar requests mal assinados — o handler já faz isso.

**3. Registrar os comandos** (uma vez, e sempre que mudarem):

```bash
python -m scripts.registrar_comandos             # na guild: aparece na hora
python -m scripts.registrar_comandos --global    # global: propaga em até 1h
```

## Estrutura

```
bot_lol/
  config.py        # configuração portável + segredos via env/.env
  riot_api.py      # cliente HTTP com rate limit, retry e cache em disco
  ingest.py        # JSON da Riot -> linhas do banco (puro, sem rede)
  poller.py        # uma rodada de polling -> ids de partidas novas
  moments.py       # timeline -> momentos-chave; `derivar()` grava no banco
  records.py       # recordes e perfil; `materializar()` pré-calcula o /recordes
  tendencias.py    # "perfil vivo": forma recente, evolução, matchups
  post.py          # texto determinístico (vira display E contexto da LLM)
  llm.py           # única fronteira com o modelo (claude -p)
  analise.py       # orquestra LLM + cache na tabela `analises`
  embeds.py        # texto -> embeds, partindo em vez de truncar
  interactions.py  # lógica dos slash commands (sem saber de Vercel)
  discord_bot.py   # bot com gateway (opcional; o modo sem PC não usa)
  db/
    schema.sql     # grupos, jogadores, partidas, participacoes, analises,
                   # momentos, recordes
    database.py    # camada de acesso fina (não amarra ao SQLite)
api/
  interactions.py  # casca do Vercel
scripts/
  ciclo.py         # entrypoint do GitHub Actions
  backfill.py      # popula o histórico
  registrar_comandos.py
  compare_llm.py   # calibra modelo/effort com as SUAS partidas
tests/             # testa o que dói se quebrar
```

## Testes

```bash
pytest
```

## Roteiro (marcos)

Fundação ✅ → núcleo de dados ✅ → saída mínima ✅ → ingestão automática ✅ →
narrativa ✅ → detector de tendências ✅ → **execução sem PC (Actions + Vercel) ✅**
→ Fase 2 (quizzes pós-partida).
