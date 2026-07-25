# Plano de evolução — três frentes

Escrito em 25/07/2026, a partir de uma sessão de análise sobre o HEAD `5b9b8cd`.
Complemento do [ARQUITETURA.md](ARQUITETURA.md) (que descreve o que o código faz hoje)
e do [bot-lol.md](bot-lol.md) (o briefing original).

**Como usar este arquivo:** cada frente abaixo é independente e pode ser executada em
sessão separada. Cada uma lista as decisões já fechadas (não reabrir sem avisar), os
arquivos que importam, e o que continua em aberto. Números marcados como *estimativa*
não foram medidos contra dados reais — não há banco populado no repositório.

Regra transversal que vale para as três frentes e vem do briefing: **o código calcula,
a LLM só narra.** Nenhuma proposta aqui abre exceção a isso.

---

## Frente A — Análise estatística mais profunda

### O problema

O post atual reporta estatísticas sem contrafactual. "25k de dano" não informa nada
porque não há base de comparação. O salto de qualidade não vem de mais dados brutos —
vem de normalização contextual e de uma métrica que responda "o que decidiu o jogo".

### O que a Riot já entrega e o código ignora

A timeline em `cache/{match_id}_timeline.json` já está em disco para todo jogo em grupo.
`moments.py` usa uma fração dela. Não extraído hoje:

- **`victimDamageReceived[]`** dentro de `CHAMPION_KILL` — quem bateu quanto na vítima,
  com qual habilidade e item. É o dado mais subaproveitado do projeto. Permite
  afirmações verificáveis do tipo "morreu 4x para o mesmo assassino, sempre abaixo de
  30% de HP, sempre na mesma região".
- **`championStats`** por frame (~24 campos: armadura, AP, mana, haste, velocidade).
- **`damageStats`** por frame com breakdown físico/mágico/verdadeiro.
- **`ITEM_PURCHASED`** com timestamp → timing de power spike vs. o esperado do campeão.
- **`WARD_PLACED` / `WARD_KILL`** com posição → cobertura de visão por região e janela.
- Posição dos 10 no frame mais próximo de um `ELITE_MONSTER_KILL` → objetivo contestado
  vs. pego de graça.

### Teto duro (não contornável)

Posição é amostrada a cada 60 segundos. Movimento, rotação e "o jungler estava vindo mas
chegou tarde" são **inferência de baixa resolução**, não dado — e precisam ser marcados
como inferência em qualquer saída.

### Fontes alternativas — investigadas e descartadas

| Fonte | Veredito |
|---|---|
| Replays `.rofl` | Tem tudo (tick ~30/s), mas só no patch de gravação, exige o cliente rodando e o formato é proprietário. Inviável para bot 24/7. |
| Live Client Data API (`127.0.0.1:2999`) | Só durante a partida, no PC de alguém. Não retroativo. |
| OP.GG / U.GG / Porofessor | Usam a **mesma Match-V5**. Não têm dado bruto novo — o valor deles é baseline populacional. Scraping é frágil e questionável de ToS. |

**Conclusão fechada:** não é preciso sair da API oficial. O que falta é baseline, e ele se
constrói dentro do ToS via `League-V4` (lista jogadores por divisão) → `Match-V5` nesses
jogadores. Exige chave de produção e alguns dias de coleta.

### Arquitetura em quatro camadas

1. **Feature extraction** (determinístico, expande `moments.py`) — os itens da lista acima.
2. **Baseline** — interno (jogador vs. ele mesmo e vs. o grupo) e externo (cohort do elo).
   Sem esta camada, a 3 não funciona.
3. **Modelos** — não é LLM:
   - *Win probability model* (gradient boosting sobre features por minuto): dado o estado
     no minuto `t`, qual a probabilidade de vitória.
   - Daí sai **WPA (win probability added)** — a métrica que substitui "maior swing de
     ouro" por "essa briga moveu a probabilidade de vitória de 42% para 78%, o maior
     delta da partida". É a resposta rigorosa para "o que decidiu o jogo".
   - Detecção de outlier por feature ("2.3 desvios acima da sua média de dano/min").
4. **LLM narra a saída dos modelos** — mesma fronteira de hoje (`llm.py`), contexto mais rico.

**Por que modelo tabular e não LLM na camada 3:** calibração. Um win probability model
produz um número auditável contra a realidade (das vezes que disse 70%, o time ganhou
70%?). Isso é verificável e melhora com dado. Um julgamento de LLM não é pontuável.

### Limite honesto a respeitar na narrativa

Precisão alta em **o quê** e **quando**; média em **onde**; **por quê** nunca. Saber que
alguém foi ao rio sozinho aos 23:40 não diz se foi desatenção, leitura errada ou tilt.
Tudo nessa camada é hipótese e deve ser marcado como tal.

### Em aberto

- Tamanho mínimo do cohort externo para o baseline ser confiável.
- Se o WPA por evento deve virar crédito individual por jogador (análogo a plus-minus
  ajustado) — decidir só depois do modelo base existir.

---

## Frente B — Trocar Gemini por Claude e sair do PC local

### Decisões fechadas

- **Assinatura Claude ≠ créditos de API.** Um bot chamando a API programaticamente bila
  contra créditos do console, não contra a assinatura. Confirmar no console antes de
  planejar orçamento.
- **Não é pipeline de agentes.** A tarefa é cálculo determinístico + uma chamada de
  narração. Um loop de agente adiciona custo, latência e não-determinismo com ganho zero,
  e contraria a regra "a LLM só narra". Único lugar onde um agente ganharia espaço: um
  `/semana` (recap semanal) onde exploração aberta do banco *é* o produto.

### O split de hospedagem

| Metade | Requisito | Cabe em cron? |
|---|---|---|
| Slash commands | Responder em <3s: gateway websocket aberto **ou** HTTP interactions endpoint registrado | Não |
| Poller + narrativa | Rodar de 5 em 5 min e postar | Sim |

**Recomendação:** Fly.io ou Railway com volume persistente (~US$0–5/mês). O código atual
roda **sem alteração** — gateway, poller e SQLite no volume funcionam como estão.

A alternativa serverless (HTTP interactions em Cloudflare Workers/Vercel + cron + banco
hospedado tipo Turso) elimina o processo persistente mas exige reescrever `discord_bot.py`
e trocar a camada de banco. Cerca de três vezes o trabalho pelo mesmo resultado nesta escala.

### Modelo e custo

Padrão recomendado: **`claude-opus-5`** (US$5/US$25 por milhão de tokens in/out).

| Modelo | Por análise *(estimativa)* | ~150 análises/mês |
|---|---|---|
| `claude-opus-5` | ~$0.075 | ~US$11 |
| `claude-sonnet-5` | ~$0.030 | ~US$4,50 |
| `claude-haiku-4-5` | ~$0.015 | ~US$2,25 |

*Base da estimativa: ~2.500 tokens de entrada (fatos + perfil vivo + system prompt) e
~2.500 de saída (narrativa do lote + thinking). Não medido contra dados reais.*
A escolha de tier é do usuário — não descer de modelo por custo sem ele decidir.

**Cache de prompt não ajuda aqui:** o mínimo cacheável no Opus 5 é 512 tokens e o único
trecho estável é o system prompt (~350). Cada partida traz fatos únicos.

### Quebras concretas ao migrar `bot_lol/llm.py`

Traduzir o código do Gemini direto quebra em quatro pontos:

1. **`temperature=0.8` retorna 400.** Parâmetros de sampling foram removidos no Opus 5.
   Remover; pedir variação no prompt se necessário.
2. **`thinking_budget=0` não existe.** No Opus 5 thinking está ligado por padrão e
   `max_tokens` limita thinking **+** texto juntos. O `max_output_tokens=4096` atual pode
   truncar no meio da resposta.
3. **Desligar thinking tem armadilha conhecida:** com `thinking: {"type": "disabled"}` o
   modelo às vezes escreve a tool call como texto visível (a chamada nunca roda, sem erro)
   e vaza tags `<thinking>`. Preferir thinking ligado com `effort: "medium"` ou `"low"`.
4. **O JSON do lote melhora:** trocar `response_mime_type="application/json"` +
   `json.loads()` por `client.messages.parse()` com modelo Pydantic — validação de schema
   garantida em vez de torcer pelo formato de saída.

O escopo da mudança é `bot_lol/llm.py` (a fronteira única com o provedor, por desenho) e a
dependência em `requirements.txt` (`google-genai` → `anthropic`). `analise.py`, `post.py` e
o resto do núcleo não são tocados.

### Em aberto

- Confirmar o estado de billing de API no console antes de estimar custo real.
- Escolher entre Fly.io e Railway (não há diferença técnica relevante nesta escala).

---

## Frente C — UX no Discord

Diagnóstico completo com mockups antes/depois:
**https://claude.ai/code/artifact/a649a5e6-e8dc-4895-9f0a-75c56891babe**

### Os achados, por gravidade

1. **A escalação não cabe no celular.** O cabeçalho em `post.py:101` tem largura fixa de
   47 caracteres. Dentro de um bloco ``` o Discord não quebra linha — scrolla na
   horizontal — e num celular cabem ~32-38 caracteres monoespaçados. A coluna `DANO`, que
   decide o MVP, fica fora da tela. **Correção não é encolher a tabela:** é trocar ASCII
   por *embed fields*, que são responsivos nativamente (3 colunas no desktop, 1-2 no
   celular). A mesma doença afeta o duelo de rota e os destaques.
2. **O post só sabe elogiar.** As cinco regras de `_conquistas()` são todas positivas e
   "Destaques" mostra maior dano e maior visão. Numa derrota o post lista cinco coisas
   boas e omite a causa — viés com sinal, não neutralidade. O dado para corrigir já está
   no banco (`challenges_json`) e na timeline (pick-offs em `moments.py`). Regra para
   manter justo: a seção "o que custou" só cita fatos com a mesma dureza dos elogios
   (morte isolada detectada, déficit de ouro@10 contra o oponente direto, percentil na
   partida) e aparece **também nas vitórias**, com o mesmo peso.
3. **A análise individual está paga e ninguém lê.** A LLM já gera e cacheia a análise de
   cada jogador na tabela `analises`; para ver, alguém precisa digitar `/jogador` com o
   nome certo. Um select menu anexado ao post automático resolve sem nenhuma chamada nova.
4. **Não existe onboarding.** Os 8 jogadores são hardcoded na lista `PLAYERS` em
   `scripts/backfill.py`. Para o nono entrar, alguém edita código. Falta `/registrar
   <RiotID#TAG>` chamando `ensure_jogador` (que já existe e já é upsert).
5. **`_embed()` trunca em 4096 caracteres em silêncio**, no meio da palavra — e o final é
   justamente onde ficam os recordes.
6. **Partida solo com dois membros vira dois posts.** Em `_postar_automatico`, um jogo
   fora de grupo gera um embed por membro. Dois amigos na mesma SoloQ em times opostos =
   dois posts da mesma partida. Deveria ser um post só — o confronto direto é o conteúdo
   mais interessante que este bot pode gerar.
7. **Nada é visual.** `moments.team_gold_series()` já calcula a curva de ouro por minuto e
   ela é descartada depois de virar uma frase. matplotlib → `BytesIO` → `discord.File` →
   `embed.set_image()`.

### Comandos propostos

`/registrar` (fecha o achado 4), `/comparar <a> <b>` (em cima de `records.perfil()`, sem
motor novo), `/semana` (recap de 7 dias — uma narrativa por semana em vez de uma por
partida).

### Ordem sugerida

Por impacto na experiência dos oito por hora de trabalho, não por dificuldade:

1. Escalação e duelos viram embed fields — ~1h, só `post.py`.
2. Select menu de jogador no post automático — ~1 tarde, um `discord.ui.View` novo.
3. Bloco "o que custou" — ~meio dia, função irmã de `_conquistas` + pick-offs existentes.
4. `/registrar` — ~1h.
5. Gráfico de ouro como imagem — ~1 tarde.

---

## Pendência anterior (do ARQUITETURA.md)

Continua aberta e independente destas três frentes: **guard-rail de recência no poller**
(`bot_lol/discord_bot.py:399`). Hoje `_poll_cycle` posta todas as partidas novas de uma
rodada; na estreia ou após uma queda isso pode gerar dezenas de embeds e chamadas de LLM
de uma vez. Descartar partidas com `inicio_ts` anterior ao boot do bot. ~10 minutos com
teste.
