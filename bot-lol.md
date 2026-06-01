# Projeto: Bot de Análise de LoL para Discord

> **Para o Claude Code:** Este documento descreve um projeto a ser construído do zero.
> Leia tudo antes de começar. No fim há uma seção **"PERGUNTE ANTES DE ASSUMIR"** com
> os pontos onde você NÃO deve adivinhar — pare e pergunte ao usuário.
> O usuário é confortável com Git e linha de comando. Responda em português.

---

## 1. O que é o projeto (visão de uma frase)

Um bot de Discord que detecta automaticamente quando os amigos de um grupo jogam
League of Legends, puxa os dados da partida pela API oficial da Riot, calcula
estatísticas e gera análises (brutas e interpretadas por uma LLM), postando no
canal do Discord — e, numa segunda fase, gera quizzes pós-partida interativos.

## 2. Objetivos e filosofia

- **Começar simples, evoluir em marcos.** O primeiro marco que importa é "o bot
  postou a stat de uma partida real no nosso canal" — feio, sem IA, sem tendências.
  Resista à tentação de construir tudo de uma vez.
- **Cálculo é determinístico; narrativa é LLM.** NUNCA peça à LLM para calcular
  números. Ela só narra números que o código já calculou. Isso mantém o projeto
  barato, rápido e confiável.
- **"Aprendizado" = memória externa, não fine-tuning.** O bot "conhece" os jogadores
  porque acumula fatos num banco e os injeta no prompt — não porque o modelo treina.
- **Honestidade estatística.** Amostras pequenas geram incerteza; o bot mostra isso
  (faixas de confiança, contagem de jogos) em vez de cravar números frágeis.

## 3. Escala pretendida

- **Agora:** 1 grupo (o do usuário, 8 jogadores), rodando no PC pessoal Linux dele.
- **Futuro:** escalar para outros grupos. Por isso o design é **multi-tenant desde o
  dia 1** (conceito de "grupo" no modelo de dados), mesmo que só haja um grupo agora.
- **NÃO** construa a infraestrutura de multi-grupo de verdade ainda (onboarding de
  outros servidores, etc.) — apenas modele os dados de forma que isso seja possível
  depois sem reescrever.

## 4. Decisões de arquitetura JÁ TOMADAS (não reabra sem avisar)

| Decisão | Escolha | Motivo |
|---|---|---|
| Linguagem | **Python** | Reaproveita script existente; forte em dados; bom SDK de LLM e Discord |
| Banco | **SQLite** | Um arquivo, zero config, idêntico em Linux/Windows |
| Acesso a dados | Camada fina própria | Não amarrar ao SQLite; permitir migrar a Postgres se escalar |
| Ambiente | venv + versões travadas | Reprodutível entre SOs |
| Provedor LLM inicial | **Gemini (tier gratuito)** | 1.500 req/dia grátis; volume do projeto é ~10/semana |
| Abstração de LLM | Função única `analisar(contexto) -> texto` | Trocar de provedor = trocar 1 função, não o projeto |
| Segredos | Variáveis de ambiente / arquivo de config local | Fora do Git; portável |
| Repositório | **Privado** no início | Abrir depois, sem chaves no histórico |
| Hospedagem | PC pessoal do usuário (Linux agora) | Custo zero; carga é mínima |

## 5. Requisito transversal: PORTABILIDADE LINUX + WINDOWS

O usuário roda em **Linux agora**, mas quer poder rodar em **Windows** também.
Princípios obrigatórios em todo o código:
- **Nunca** hardcode caminhos de arquivo no estilo de um SO (`/home/...` ou `C:\...`).
  Use construção de caminho portável e caminhos relativos/config.
- Isole a lógica de "rodar 24/7 como serviço" numa **borda fina** fora do código do
  bot. O bot é só um programa que roda; *como* ele é mantido vivo (systemd no Linux,
  serviço/tarefa no Windows) é uma receita externa trocável por SO.
- Não dependa de nada específico da máquina do usuário.

## 6. Nível de rigor de engenharia (calibrado para projeto pessoal sério)

**"Disciplina leve":**
- **FAÇA desde já:** separar config de código; travar versões de dependência;
  estrutura de pastas clara; testes **apenas** no que dói se quebrar silenciosamente
  → o **motor de stats** e o **parsing de partida** (lógica pura, fácil de testar).
- **NÃO faça agora (evite over-engineering):** cobertura total de testes, CI/CD,
  containers/Docker, abstrações "para o futuro". Adicione quando a dor aparecer.
- Regra mental: **teste o que calcula, não o que conversa.** O motor de percentis
  merece teste; a chamada da LLM e o post no Discord você valida rodando e olhando.

## 7. Já existe um script base (reaproveitar)

O usuário já tem um script Python (`flex_analyzer.py`) que:
- Resolve PUUID via account-v1 (Riot ID = gameName + tagLine).
- Puxa IDs de partida (match-v5) e baixa cada match JSON, com **cache em disco**.
- Puxa **timeline** (minuto-a-minuto) das partidas em grupo.
- Calcula: WR individual, duplas, escalações de 5, WR por duração ("afoga no late"),
  percentis de desempenho por partida em 3 visões (vs 10 / vs colegas / vs mesma
  role), "melhor do time" por métrica, e um teste solo-vs-grupo.
- Lida com rate limit (chave de dev: 20 req/s, 100 req/2min) e tem retry em 429/5xx.

**Peça esse arquivo ao usuário no início** — ele é a base do "motor de stats" e da
camada de ingestão. Não reescreva do zero; refatore para escrever no banco em vez de
gerar JSON/txt soltos.

## 8. Detalhes técnicos da Riot API (contexto que economiza erros)

- **Roteamento:** o grupo joga no servidor **BR**. account-v1 e match-v5 usam o
  roteamento REGIONAL = `americas`. (platform = `br1` para endpoints legados.)
- **Chave de dev expira em 24h** — inútil para um bot 24/7. Para produção, o usuário
  precisará solicitar uma **chave de produção** à Riot (processo no portal deles;
  aprovam projetos de comunidade, mas há regras de uso e o usuário ainda não fez isso
  — ver "Pergunte antes de assumir").
- **Detecção de partida nova = polling.** Não há webhook. O bot checa periodicamente
  os IDs recentes de cada jogador; ID novo → processa.
- **Deduplicação:** quando 2+ amigos jogam juntos, a mesma partida aparece para todos.
  Processar **uma vez só** (cruzar os 10 PUUIDs da partida com a tabela de jogadores).
- **Timeline registra posição a cada 1 min** (não contínuo). Eventos de morte trazem a
  coordenada do óbito (mais confiável que a posição amostrada). Relevante para a
  detecção de pick-off no quiz (fase 2) — tratar pick-off como "melhor palpite", não
  como verdade cravada.
- **Roles vêm sujas:** a API marca muitos jogos como `Invalid` (modos especiais,
  remakes). Filtrar/limpar ao inferir a role principal.

## 9. Dados reais do grupo (para seed inicial e contexto)

Servidor: **BR**. 8 jogadores (Riot IDs exatos — atenção às grafias):

| Nick exibição | Riot ID | Role principal (observada) | WR (todas filas) | Jogos |
|---|---|---|---|---|
| Hiroshi | `Hiroshi#10102` | Jungle/Mid (flex) | 57.1% | 224 |
| Qiak | `Qiak#000` | ADC (BOTTOM) | 50.6% | 160 |
| Nyachi | `Nyachi#mee` | ADC (BOTTOM) | 45.2% | 146 |
| Thokyru | `Thokyru#BR1` | Support (UTILITY) | 58.6% | 140 |
| Nashorn | `Nashorn#Shiro` | Jungle | 54.0% | 124 |
| Lukyy | `Lukyy#Luky` | Top | 34.9% | 109 |
| Yuya Freecss | `Yuya Freecss#BR1` | Flex (Top/Mid) | 59.8% | 107 |
| Top Mogger | `Top Mogger#Dasky` | Top | 56.0% | 100 |

**Atenção às grafias:** "Yuya Freecss" tem dois `s`; "Lukyy#Luky" tem dois `y` no nome
e um no tag. Confirme com o usuário se a API não resolver algum PUUID.

Insights já levantados (úteis para a "voz" do bot e o detector de tendências, fase
posterior): o grupo "afoga no late" (WR cai de 66% sub-20min para 41% em 35min+);
Hiroshi é o motor de dano/ouro do time; Thokyru é o rei da visão; Nyachi rende bem
solo mas despenca em grupo; Lukyy é o jogador em desenvolvimento (baixo solo E grupo).

## 10. Modelo de dados (ponto de partida — detalhar com o usuário)

Quatro tabelas centrais. Regra de ouro: **toda query filtra por grupo; cada linha é um
fato imutável (só insere, nunca edita).**

- `grupos` — cada servidor de Discord (id, nome, canal de post, etc.)
- `jogadores` — PUUID, riot_id, nick de exibição, grupo_id
- `partidas` — uma linha por match único (match_id, queue, duração, timestamp, vencedor…)
- `participacoes` — uma linha por jogador-por-partida (jogador_id, partida_id, campeão,
  role, kills/deaths/assists, dano, ouro, visão, farm, e percentis calculados…)

Fase 2 adiciona: `palpites` (quem, qual partida, qual opção do quiz, acertou?).
**Detalhe os campos exatos junto com o usuário antes de criar o schema** — é a decisão
mais cara de mudar depois.

## 11. Roteiro de construção (ordem dos marcos)

1. **Fundação** — estrutura de pastas, ambiente (venv + deps travadas), schema do
   banco, camada de acesso a dados, `.gitignore` protegendo segredos ANTES do 1º commit.
2. **Núcleo de dados** — adaptar o `flex_analyzer` para escrever no banco (não JSON solto).
3. **Ingestão** — poller (checa IDs novos por jogador) + fila com deduplicação.
4. **Saída mínima** — bot postando stats **BRUTAS** de uma partida real no Discord,
   **sem LLM**. ESTE É O PRIMEIRO MARCO QUE IMPORTA. Valida a pipeline ponta a ponta.
5. **Narrativa** — plugar a LLM atrás da função `analisar()`; análises interpretadas.
6. **Detector de tendências** — só depois de acumular dados. Calcula (sem LLM):
   evolução por campeão ("aprendendo Brand"), janelas recente-vs-antiga ("melhorei"),
   matchup por oponente direto ("perco pra Irelia"), padrões condicionais por jogador.
   Atualiza um "perfil vivo" por jogador, que vira contexto do prompt da LLM.
7. **FASE 2 — Quizzes pós-partida** (ver seção 12).

A cada marco o usuário tem algo funcionando. Nunca o deixe semanas sem ver resultado.

## 12. Fase 2 — Quizzes pós-partida (detalhar quando chegar a vez)

**Ideia:** antes de revelar a análise, o bot pergunta no Discord (botões/select menus
nativos), ex.: "Qual briga decidiu o jogo? a) Dragão 12:32 b) Barão 16:23 c) pick do
Nasus 22:32 d) quadra do Qiak". Pessoas votam, o bot registra quem votou no quê, e
revela a resposta dos dados.

**Detecção de momentos-chave (a peça reutilizável — serve ao post normal E ao quiz):**
- **Objetivos** (Dragão/Barão/Arauto): fácil e confiável — eventos explícitos na timeline.
- **Swing de ouro**: o melhor sinal de "o que decidiu" — achar o intervalo de 1-2 min
  onde a diferença de ouro entre times mais virou. Robusto.
- **Multikills** ("quadra do Qiak"): contar kills de um jogador numa janela curta. Fácil.
- **Pick-off** (morte isolada longe do time): heurística usando a coordenada do evento
  de morte + posição amostrada. Terá falsos +/–; tratar como "melhor palpite", não pilar.

**Cuidado conceitual:** "qual briga decidiu" é parcialmente subjetivo. O bot deve usar
o swing de ouro como "resposta dos dados" com humildade ("os dados apontam X como o
maior swing"), não bancar dono da verdade — a discordância é parte da graça.

**O que os palpites destravam (guardar tudo):** precisão de leitura de jogo por pessoa
(proxy de game sense), vieses individuais (ex.: alguém superestima as próprias plays),
percepção coletiva vs. realidade, e calibração que vira dica de treino. Encaixa no
modelo multi-tenant como a tabela `palpites`.

**Complexidade nova:** o bot deixa de ser "dispara e esquece" e passa a ter **estado
interativo** (pergunta, espera votos ao longo de minutos, fecha votação, revela).
É categoria diferente de código. Por isso é fase 2 — construa a detecção de eventos
primeiro (no marco 5/6), o quiz embrulha ela depois.

## 13. Custos (contexto, já validado)

- Discord: grátis (bot conecta por saída; **não** precisa abrir portas/expor IP).
- Riot API: grátis (mas precisa de chave de produção para 24/7 — ver seção 14).
- LLM: tier gratuito do Gemini cobre o volume (~10 análises/semana << 1.500/dia).
- Hospedagem: PC do usuário, custo zero. Projetar para sobreviver a quedas:
  estado persistente em disco/banco, nada crítico só na RAM, **reinício automático**.

## 14. PERGUNTE ANTES DE ASSUMIR (não adivinhe nestes pontos)

1. **Chave de produção da Riot:** o usuário já solicitou? Está usando chave de dev
   (expira 24h) ou de produção? Isso afeta se o bot pode rodar 24/7 de verdade.
2. **Chaves/tokens:** peça (não invente) a chave da Riot, a chave do Gemini e o token
   do bot de Discord — e confirme o método de armazenamento (env vars vs arquivo).
3. **O script `flex_analyzer.py` existente:** peça o arquivo antes de recriar o motor
   de stats. Refatore-o, não reescreva.
4. **Schema do banco:** confirme os campos exatos de cada tabela com o usuário antes de
   criar — é a decisão mais cara de mudar. Liste sua proposta e peça validação.
5. **Servidor/canal de Discord:** peça o ID do servidor e do canal onde o bot posta.
6. **Frequência de polling:** confirme (ex.: a cada 2 min? 5 min?) — afeta uso da API.
7. **Quais filas analisar:** todas (Flex, Solo, normais, ARAM) ou só algumas? O grupo
   joga muito junto; confirme se ARAM/normais entram ou só ranqueadas.
8. **Nome do repositório/projeto** e a estrutura de pastas preferida, se houver.
9. **Gerenciador de ambiente Python:** venv tradicional + requirements, ou uma
   ferramenta mais moderna? Confirme a preferência do usuário.
10. **Política de "quando o bot fala":** comenta toda partida em grupo ou só as
    "dignas de nota"? Comece simples, mas confirme a intenção.

## 15. Lembretes finais de postura

- Pare e pergunte nos pontos da seção 14 em vez de assumir.
- Construa marco a marco (seção 11); valide cada um rodando antes de seguir.
- Mantenha tudo portável Linux/Windows (seção 5).
- Cálculo determinístico; LLM só narra (seção 2).
- Proteja segredos antes do primeiro commit.
- Não faça over-engineering; "disciplina leve" (seção 6).