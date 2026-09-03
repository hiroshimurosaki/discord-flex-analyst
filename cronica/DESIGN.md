# Crônica — o modelo

Como transformar histórico de LoL em uma história de evolução, emoção e
personalidade. Este documento é o contrato: o que é dado, o que é escrito à mão,
o que o código calcula e o que a LLM pode dizer.

---

## 1. O problema, sem enfeite

Um histórico de partidas é uma **lista plana**. Uma história é uma **sequência com
estrutura**: começo, mudança, consequência. Nada na Riot API sabe disso.

Três coisas faltam, e é sobre elas que o projeto inteiro é construído:

| Falta | Quem resolve |
|---|---|
| **Recorte temporal** — 800 partidas não são 800 capítulos. Onde termina uma fase e começa outra? | código (detecção de eras) |
| **Personalidade** — a API sabe que o Lukyy morreu 9 vezes. Não sabe que ele ia morrer de novo porque ele nunca recua. | você (cânone) |
| **Função narrativa** — a partida mais importante da história não é a de maior dano. É a que *significa* algo depois do que veio antes. | código (escalação de momentos) |

O erro que este projeto evita: jogar 800 partidas num prompt e pedir "escreva
nossa história". O que sai é um resumo genérico com números inventados. A saída
boa exige que **a estrutura seja calculada antes de qualquer palavra ser escrita**.

---

## 2. Regra de ouro (herdada, e por um bom motivo)

> **O código calcula. A LLM só narra.**

A LLM nunca vê o banco, nunca vê JSON da Riot, nunca faz uma conta. Ela recebe um
**briefing determinístico** — um texto que você também consegue ler — e devolve prosa.

Isso não é purismo. É a única forma de a história ser **verdadeira**: se a LLM só
pode citar números que estão no briefing, e o briefing é gerado por código
auditável, então nenhum número da história é inventado. E quando você ler algo
estranho no capítulo 7, você abre `saida/briefings/cap07.md` e vê exatamente de
onde veio.

---

## 3. As seis camadas

```
0. CÂNONE          você escreve      canone/*.yaml
   elenco, personalidade, eventos externos, relações
                        |
1. FATOS           Riot API          fatos.db (imutável, só INSERT)
   partidas, participações dos 10, timeline derivada
                        |
2. CRONOLOGIA      determinístico    saida/cronologia.json
   séries temporais -> quebras -> ERAS -> forma de cada era
                        |
3. ROTEIRO         determinístico    saida/roteiro.json
   era -> capítulo; escalação de momentos por FUNÇÃO NARRATIVA
   dossiê de personagem (auto-imagem vs. dado medido)
                        |
4. BRIEFING        determinístico    saida/briefings/capNN.md
   *** o contrato com a LLM: todo número permitido está aqui ***
                        |
5. NARRAÇÃO        LLM               saida/capitulos/capNN.md
   prosa, com a BÍBLIA acumulada dos capítulos anteriores
                        |
6. RENDER          determinístico    saida/livro.md, saida/slides.md
```

Cada camada escreve um arquivo legível e editável. Se a camada 4 está errada, você
corrige a 2 ou a 3 — nunca "briga com o prompt". É isso que faz disso um
**ambiente** em vez de um gerador de texto.

---

## 4. Camada 0 — o cânone (a parte que só você tem)

Um YAML versionado. É a fonte de tudo que a API não sabe.

### 4.1 Elenco: titulares e substitutos

O time canônico são 5 posições com dono. Substituto não é "outro jogador" — é um
**papel narrativo**: alguém que entra quando falta um, e cuja presença muda o time.
O modelo guarda isso explicitamente (`entra_no_lugar_de`), porque "o dia em que o
substituto entrou e vocês ganharam de virada" é um capítulo, não uma linha de tabela.

### 4.2 Personagem: cinco campos que fazem trabalho

```yaml
personagens:
  hiroshi:
    arquetipo: "o motor"           # uma frase; é o rótulo do personagem
    personalidade: "..."           # texto livre: como a pessoa É. A LLM usa pra VOZ.
    se_acha: "..."                 # a AUTO-IMAGEM. O campo mais importante.
    medo: "..."                    # o que ele evita; explica decisões ruins
    bordoes: ["..."]               # o que ele fala. Dá textura imediata.
```

**`se_acha` é o motor emocional do projeto.** O código cruza a auto-imagem com o
dado medido e classifica em três estados:

- **confirmado** — ele se acha o carry e é o carry. Vira orgulho.
- **contradito** — ele se acha o carry e o dado diz que não. Vira *tensão*, que é
  o material narrativo mais valioso que existe.
- **virou verdade** — o dado contradizia no começo e confirma hoje. **Isto é
  literalmente a definição de evolução**, e é o que a história quer mostrar.

Sem esse campo, o texto vira relatório. Com ele, vira personagem.

### 4.3 Eventos externos

Datados, tipados, com envolvidos. `hiato`, `mudanca_vida`, `conquista`, `atrito`,
`piada_interna`, `marco`. O código ancora cada evento na era em que caiu e o
briefing entrega junto dos números daquele período — é assim que "vocês pararam 3
meses" deixa de ser um buraco no gráfico e passa a ser um capítulo.

---

## 5. Camada 1 — fatos

Herdo a decisão certa do projeto anterior: **guardar os 10 participantes**, não só
os membros. Sem os 10 não existe percentil-na-partida nem matchup de rota, e sem
esses dois não existe frase honesta sobre desempenho.

Duas coleções, com pesos narrativos diferentes:

| Coleção | Papel |
|---|---|
| **Flex com 2+ membros** (`em_grupo`) | o fio principal. Vira era, capítulo, momento. |
| **SoloQ de cada membro** | subtrama. Nunca vira capítulo próprio; alimenta o dossiê de personagem ("ele subiu sozinho enquanto o time afundava"). |

Fatos são imutáveis: só `INSERT`. Reescrever uma partida seria reescrever o passado,
e o passado é justamente o que a história está tentando contar.

---

## 6. Camada 2 — cronologia: como 800 partidas viram 12 capítulos

O coração determinístico. Uma era é um trecho contíguo do histórico em que **o time
era a mesma coisa**. Detectar as fronteiras é detectar quando ele deixou de ser.

### 6.1 Quatro geradores de fronteira candidata

| Sinal | Regra | Por que é honesto |
|---|---|---|
| **Hiato** | gap > 21 dias entre partidas consecutivas | não é inferência, é calendário |
| **Troca de elenco** | o quinteto modal da janela muda de forma persistente | mudança de composição É mudança de time |
| **Fronteira de split** | virada de temporada/split | corte que o público já entende |
| **Quebra estatística** | segmentação binária na série de vitórias | ver 6.2 |

### 6.2 A quebra estatística, sem magia

Segmentação binária recursiva sobre a série de resultados (1/0):

1. para cada corte candidato, calcula WR antes e depois;
2. mede a diferença com um **teste z de duas proporções**;
3. aceita o corte com maior significância, se passar do limiar **e** deixar os dois
   lados com no mínimo `MIN_PARTIDAS_ERA` partidas;
4. recorre nos dois lados.

Nenhuma dependência externa, e cada fronteira carrega seu **p-valor no JSON**. Uma
era não é "o que o algoritmo achou": é uma afirmação com força declarada. Se o
p-valor é fraco, o briefing diz "a mudança é sugestiva, não conclusiva" — e a LLM é
obrigada a respeitar isso.

### 6.3 Forma da era (o código decide, a LLM só batiza)

De `delta_wr`, rotatividade de elenco e hiato anterior, cada era é classificada em:

`estreia` · `ascensao` · `plato` · `queda` · `reconstrucao` · `retomada`

Isto é deliberado: **a curva dramática é calculada, não imaginada.** A LLM recebe
"esta era é uma `queda` de -18pp em 34 partidas" e escreve sobre uma queda. Ela não
tem liberdade para decidir que foi uma fase boa porque o texto fluía melhor assim.

---

## 7. Camada 3 — escalação: função narrativa > magnitude

O seletor de momentos não pergunta "qual foi a maior partida?". Pergunta **"que
papel esta cena cumpre na história?"** — e cada papel tem uma query própria:

| Papel | O que seleciona |
|---|---|
| `primeira_vez` | a estreia de algo (primeira partida juntos, primeira do quinteto completo, primeira vitória) |
| `fundo_do_poco` | a pior sequência de derrotas da era |
| `catarse` | a vitória que encerrou a seca |
| `virada` | maior déficit de ouro revertido em vitória |
| `entra_o_substituto` | partida com substituto e resultado notável |
| `recorde` | primeira quebra de um recorde do grupo dentro da era |
| `pico_de_personagem` | o melhor jogo de cada personagem na era |
| `espelho` | **ver 7.1** |
| `queda_livre` | a derrota que fecha a era |

Um capítulo recebe de 3 a 6 momentos, no máximo um por papel. É **casting**: cada
cena entra porque cumpre uma função, não porque o número era grande.

### 7.1 O espelho — o dispositivo central de evolução

Duas partidas, distantes no tempo, com **composição e contexto parecidos e
resultado oposto**. O código procura pares maximizando similaridade (campeões,
roles, elenco presente, duração) e minimizando proximidade temporal, exigindo
resultados invertidos.

Por que isso importa mais que qualquer gráfico: "vocês melhoraram 12pp de winrate"
é uma abstração que ninguém sente. "Em março vocês jogaram essa mesma composição
contra esse mesmo tipo de time e perderam em 24 minutos; em novembro ganharam em 31,
com o Lukyy 40 de farm à frente em vez de 30 atrás" **é a mesma informação, mas
acontecendo com pessoas.** Evolução mostrada, não afirmada.

---

## 8. Camada 4 — o briefing é o contrato

Um markdown por capítulo, com tudo que a LLM pode usar e nada além:

```
# Capítulo 07 — era `ascensao`, 2025-06-02 a 2025-08-19
## Números da era        (WR, delta, p-valor, duração média, elenco)
## Comparação com a era anterior
## Cenas escaladas       (uma seção por momento, com os números da partida)
## Dossiê de personagem  (se_acha vs. medido, com veredito)
## Eventos do cânone     (o que aconteceu fora do jogo neste período)
## Bíblia                (o que já foi contado — NÃO REPETIR)
## Limites               (o que a amostra NÃO permite afirmar)
```

A seção **Limites** é gerada por código a partir dos tamanhos de amostra e
p-valores. É o que impede a história de virar mitologia: quando o dado é fraco, o
briefing diz que é fraco, e a instrução de sistema proíbe cravar.

---

## 9. Camada 5 — a bíblia (por que capítulo 9 não repete capítulo 3)

Narrar 12 capítulos com 12 chamadas independentes produz 12 variações do mesmo
texto. Depois de cada capítulo, o código extrai e acumula:

- **fatos já contados** (nenhuma cena é usada duas vezes)
- **imagens/frases já usadas** (mata a repetição de linguagem)
- **estado emocional** ao fim do capítulo (de onde o próximo começa)
- **promessas em aberto** — "o Lukyy ainda não achou o top dele"

Promessa em aberto é o que dá **direção**: o capítulo seguinte é instruído a pagar
ou a adiar conscientemente. É a diferença entre uma sequência de relatórios e uma
narrativa com arco.

---

## 10. Camada 6 — markdown canônico, slideshow derivado

A fonte é o markdown do capítulo, versionado no Git. Dele saem dois renders:

- `saida/livro.md` — a história corrida, do início até hoje;
- `saida/slides.md` — deck **Marp** (markdown puro + CSS, sem build de JS), com
  slide de título por era, slide de números com SVG gerado por código, slide por
  cena e ficha de personagem.

Os gráficos são SVG determinístico gerado aqui (`render/svg.py`), sem matplotlib:
o deck precisa abrir em qualquer lugar, e um SVG inline sempre abre.

---

## 11. O que este desenho recusa

- **Não pergunta à LLM "o que foi importante"** — isso é a camada 3, e ela é código
  testável. A LLM decide palavras, nunca estrutura.
- **Não inventa causalidade.** Posição na timeline é amostrada a cada 60s. "Ele
  estava tiltado" não é dado. O briefing marca inferência como inferência, e a
  história pode dizer "os dados apontam", nunca "ele estava".
- **Não trata soloq como capítulo.** Vira subtrama de personagem. A história é do
  time; o arco individual serve o arco coletivo.
- **Não materializa nada que não custe caro.** Recordes e percentis se recalculam;
  a cronologia é o único derivado persistido, porque é a espinha da história.
