# Crônica

Transforma o histórico de LoL de um time em uma **história linear de evolução**:
capítulos em markdown que viram slideshow.

Não é um analisador de partidas. É o contrário: o átomo aqui é uma **era**, e
uma partida só aparece quando cumpre uma função na narrativa. O desenho e o
porquê de cada decisão estão em [DESIGN.md](DESIGN.md) — leia antes de mexer no
código, porque quase tudo aqui é opinião defensável e não convenção.

**A regra que atravessa tudo:** o código calcula, a LLM só narra. Ela nunca vê o
banco nem faz uma conta — recebe um briefing determinístico que você também
consegue ler. Se um número não está no briefing, ele não pode aparecer na
história.

## O pipeline

```
canone/time.yaml     você escreve: elenco, personalidade, eventos fora do jogo
        |
        v
scripts.coletar      Riot API -> dados/fatos.db   (imutável, só INSERT)
        |
        v
scripts.construir    eras -> capítulos -> cenas escaladas -> BRIEFINGS
        |                                        (nenhuma chamada de modelo)
        v
scripts.narrar       briefing + bíblia -> saida/capitulos/capNN.md
        |
        v
scripts.renderizar   -> saida/livro.md + saida/slides.md (Marp)
```

## Comece pelo demo (não precisa de chave)

Antes de gastar a chave da Riot, veja a coisa inteira funcionando com um
histórico sintético que tem estrutura plantada — hiato, troca de elenco, subida,
queda — para você conferir se a detecção de eras acha o que está lá:

```bash
pip install -r requirements.txt
python -m scripts.demo --limpar               # ~800 partidas, 5 eras plantadas
python -m scripts.construir canone/demo.yaml  # eras + briefings
less saida/briefings/cap05.md                 # *** leia isto ***
python -m scripts.narrar     canone/demo.yaml # aqui entra o modelo
python -m scripts.renderizar canone/demo.yaml
```

`saida/briefings/capNN.md` é o arquivo mais importante do projeto. Ele é o
contrato: tudo que a história vai poder dizer está ali, e nada além.

## Com os seus dados

```bash
cp canone/exemplo.yaml canone/time.yaml
$EDITOR canone/time.yaml                      # a parte que só você tem
python -m scripts.validar_canone canone/time.yaml

export RIOT_API_KEY=...                       # nunca commite a chave
python -m scripts.coletar canone/time.yaml    # idempotente; re-rodar retoma
python -m scripts.quinteto                    # quem é o time canônico, segundo os dados
python -m scripts.construir canone/time.yaml
python -m scripts.narrar     canone/time.yaml
python -m scripts.renderizar canone/time.yaml
```

Depois:

```bash
npx @marp-team/marp-cli@latest saida/slides.md -o saida/slides.html
npx @marp-team/marp-cli@latest saida/slides.md --pdf
```

### Preencher o cânone

`canone/exemplo.yaml` vem com os 8 jogadores e as grafias exatas dos Riot IDs;
os campos de personagem estão como `TODO`. O campo que faz mais trabalho é
**`se_acha`** — a auto-imagem de cada um, escrita com as palavras dele. O código
cruza ela com o desempenho medido e emite um veredito:

| veredito | significa |
|---|---|
| `confirmado` | ele se acha X e sempre foi X |
| `contradito` | ele se acha X e nunca foi X |
| `virou_verdade` | **não era X, hoje é X — evolução medida** |
| `desmentido_pelo_tempo` | era X, hoje não é mais |

Para o veredito existir, a auto-imagem precisa de uma alegação **mensurável** em
`afirma` (vocabulário fechado: `dano`, `carrega`, `rota`, `visao`, `farm`,
`kda`, `morre_pouco`, `kp`). Sem ela, a narração pode relacionar a frase com os
números, mas não pode dizer que é verdadeira ou falsa.

## Ajustes que você provavelmente vai querer

| Quero | Onde |
|---|---|
| mais/menos capítulos | `scripts.construir --min-partidas N` (padrão 12) |
| incluir jogos de 2-3 pessoas, não só 5 | `--min-membros N` (padrão 2) |
| mudar o tom da história | `voz:` no cânone (vai no prompt de todo capítulo) |
| deck sem a prosa, só a estrutura | `scripts.renderizar --sem-prosa` |
| reescrever um capítulo | apague `saida/capitulos/capNN.md` e rode `narrar` |
| reescrever tudo do zero | `scripts.narrar --refazer` |

Sensibilidade da detecção de eras: `cronica/cronologia/eras.py`, no topo
(`HIATO_DIAS`, `ALFA`, `DELTA_WR_NOTAVEL`...). Todos explícitos porque todos
são opinião.

## LLM

É o **CLI do Claude Code em modo headless** (`claude -p`), não a API HTTP: ele
autentica pela assinatura, então o custo fica no plano.

```bash
npm install -g @anthropic-ai/claude-code
claude          # /login
```

Não defina `ANTHROPIC_API_KEY`: ela tem precedência sobre o token da assinatura
e faria as chamadas caírem em créditos de API. `narracao/llm.py` já a remove do
ambiente do subprocesso.

## Estrutura

```
cronica/
  config.py            caminhos portáveis, segredos por ambiente
  canone/              camada 0: o que a API não sabe (YAML validado)
  fatos/               camada 1: Riot -> SQLite (ingest é PURO, sem rede)
  cronologia/          camada 2: séries, detecção de eras, dossiê de personagem
  roteiro/             camada 3: escalação de cenas + o briefing
  narracao/            camada 5: fronteira da LLM + bíblia de continuidade
  render/              camada 6: livro.md, slides Marp, SVG por código
scripts/               um comando por camada + demo + validador
tests/                 testa o que dói se quebrar (50 testes, 0.1s)
```

## Testes

```bash
python -m pytest tests/ -q
```

## Chave da Riot

Nunca no código, nunca no Git. `RIOT_API_KEY` no ambiente ou num `.env` local.
A chave de **dev expira em 24h** — a primeira coleta de 8 jogadores leva horas
por causa do rate limit, então vale pedir chave de produção antes de começar.
