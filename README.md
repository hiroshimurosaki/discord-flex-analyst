# discord-flex-analyst

Bot de Discord que analisa as partidas de LoL do grupo: detecta jogos,
puxa dados da Riot API, calcula estatísticas (determinístico) e gera
análises narradas por LLM. Ver o briefing completo em [bot-lol.md](bot-lol.md).

**Filosofia:** cálculo é determinístico; a LLM só narra. Multi-tenant desde
o dia 1; cada partida/participação é um fato imutável. Portável Linux/Windows.

## Setup

```bash
python -m venv .venv
# Linux:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # e preencha as chaves (o .env nunca vai pro Git)
```

## Estrutura

```
bot_lol/
  config.py        # configuração portável + segredos via env/.env
  db/
    schema.sql     # grupos, jogadores, partidas, participacoes
    database.py    # camada de acesso fina (não amarra ao SQLite)
tests/             # testa o que dói se quebrar (motor de stats, parsing)
flex-analyzer.py   # script base a refatorar -> escrever no banco
```

## Testes

```bash
pytest
```

## Roteiro (marcos)

Fundação ✅ → núcleo de dados (refatorar flex-analyzer p/ o banco) →
ingestão (poller + fila) → saída mínima no Discord (sem LLM) →
narrativa (LLM) → detector de tendências → Fase 2 (quizzes pós-partida).