# Política de conteúdo (CSP)

**Roteiro:** `checks/check_csp.py` · **Módulos:** `base/csp.py`,
`base/csp_views.py`, `static/duralux/nd-inline.js` ·
**Chave:** `CSP_ENFORCE` (padrão **`False`** — modo de relatório)

Todas as outras defesas tentam impedir que script estranho entre: escape
do template, validação de entrada, sanitização. Esta parte do princípio de
que uma delas vai falhar um dia, e diz ao navegador o que ele pode
executar **mesmo que** o script chegue à página.

Num prontuário isso pesa mais que na média: a sessão que uma injeção
sequestraria abre o histórico clínico inteiro de uma clínica.

---

## 1. Começa relatando, e essa é a decisão central

Política aplicada de saída quebra **em silêncio e de longe**: o navegador
simplesmente não executa, sem erro na tela, e a que falha é aquela que
ninguém abriu na semana da publicação.

Em modo de relatório o navegador **obedece normalmente e avisa** o que
teria bloqueado. Colhe-se o inventário real, com o sistema em uso, e só
então se fecha.

| Estado | Cabeçalho enviado |
| --- | --- |
| `CSP_ENFORCE=False` (padrão) | `Content-Security-Policy-Report-Only` |
| `CSP_ENFORCE=True` | `Content-Security-Policy` |

**Diferente do HSTS, este dá para voltar.** O navegador não guarda a
instrução: trocar para `False` e republicar desfaz na hora.

### O roteiro de quem vai ligar

1. Publicar como está (relatando) e usar o sistema normalmente.
2. Depois de algumas semanas, ler o log da aplicação procurando `csp:`.
3. Cada linha diz a diretiva violada e o recurso bloqueado. Se não houver
   nenhuma vinda de tela nossa, `CSP_ENFORCE=True` e republicar.
4. Qualquer surpresa: `False` de volta, e republicar.

## 2. O trabalho de verdade foi o HTML, não o cabeçalho

Antes desta entrega havia **13 atributos de evento** (`onclick`,
`onsubmit`, `onchange`, `onerror`) espalhados pelos templates.

Atributo de evento **é** script embutido, e o nonce **não o cobre** — o
único jeito de mantê-lo seria `script-src 'unsafe-inline'`, que desliga
exatamente a proteção que a política existe para dar.

Os treze viraram atributos `data-nd-*`, com o comportamento em
`static/duralux/nd-inline.js`:

| Atributo | O que faz | Onde estava |
| --- | --- | --- |
| `data-nd-print` / `data-nd-close` | imprime / fecha a janela | resumo do atendimento |
| `data-nd-confirm="pergunta"` | confirma antes de enviar o formulário | financeiro (5 lugares) |
| `data-nd-autosubmit` | envia o formulário ao trocar o campo | agenda, retornos, grade |
| `data-nd-fallback="id"` | retrato que não carregou some e a inicial aparece | ficha do paciente, atendimento |
| `data-nd-copy="id"` | copia o valor de um campo | convites do console |

Tudo delegado no documento, para valer também para o que nasce depois —
dentro de um modal carregado por `fetch`, por exemplo.

Os **8 blocos `<script>` inline** que restam são legítimos e receberam
`nonce="{{ nd_csp_nonce }}"`.

**O roteiro varre os templates no disco**, e não o HTML renderizado: um
`onclick` num canto que nenhuma asserção abre continuaria lá e apareceria
só no dia em que a política fosse aplicada.

## 3. Zero recursos externos

Conferido antes de escrever a política: esta instalação não carrega **um
único** recurso de terceiro — nem fonte, nem CDN, nem ícone. É isso que
permite uma política estrita sem exceção nenhuma.

Se alguém acrescentar um `<script src="https://cdn…">` amanhã, o modo de
relatório avisa antes de quebrar.

## 4. As diretivas

| Diretiva | Valor | Por quê |
| --- | --- | --- |
| `default-src` | `'self'` | o padrão fecha; cada exceção abaixo é deliberada |
| `script-src` | `'self' 'nonce-…'` | **a diretiva que justifica o trabalho todo.** Sem `unsafe-inline` e sem `unsafe-eval` |
| `style-src` | `'self' 'unsafe-inline'` | concessão declarada — ver abaixo |
| `img-src` | `'self' data: blob:` | `data:` para o QR gerado em memória, `blob:` para o recorte do retrato |
| `connect-src` | `'self'` | cobre fetch, XHR e o SSE do chat e da IA |
| `object-src` | `'none'` | `<embed>`/`<object>` não existem, e são porta clássica de plugin |
| `base-uri` | `'self'` | impede que uma injeção redirecione todo `src` relativo da página |
| `form-action` | `'self'` | impede que um formulário passe a postar para fora |
| `frame-ancestors` | `'none'` | repete o `X-Frame-Options` na linguagem do padrão atual |
| `upgrade-insecure-requests` | — | sub-recurso em HTTP não é buscado em HTTP |

### A concessão de `style-src`, declarada em vez de escondida

São **70 atributos `style="..."`** nas telas, quase todos uma largura
mínima ou uma cor de faixa. Fechar exigiria reescrever setenta trechos de
HTML para ganhar pouco: CSS injetado faz defacement e algum vazamento por
seletor; script injetado faz o que quiser com a sessão.

Fechar `script-src` primeiro é onde está o valor. `style-src` fica anotado
como aperto futuro — honestamente, e com uma asserção no roteiro para que
continue sendo **uma escolha** e não um esquecimento.

## 5. O nonce

Sorteado por `secrets.token_urlsafe(16)` — 128 bits — a **cada resposta**,
no middleware, **antes** da view, porque o template o lê enquanto
renderiza.

Nonce fixo seria `unsafe-inline` com um passo a mais: o atacante lê o
nonce da própria página e usa. O roteiro pede cinco respostas e cobra
cinco nonces diferentes, e confere que o do cabeçalho é o mesmo do HTML —
se divergirem, a política aplicada apaga o script da tela sem uma mensagem
sequer.

A política só vai em resposta **HTML**. Em JSON ou PDF não protege nada e
engorda toda requisição da API.

## 6. O coletor, em `/csp-report/`

O modo de relatório só vale se alguém ler os relatórios.

- **Sem sessão e sem CSRF**, porque é assim que o navegador manda. Exigir
  qualquer das duas faria o endereço recusar exatamente o que existe para
  receber — e a política pareceria limpa por nunca receber notícia.
- **Log, não tabela.** Relatório de CSP é ruído de alta frequência: uma
  extensão de navegador injeta script em toda página e gera um relatório
  por carregamento, para sempre. A decisão que interessa se toma lendo uma
  semana de log, não consultando cinco anos de linhas.
- Ser aberto obriga o resto: **teto de 30 por IP por minuto**, corpo
  limitado a 8 KB, e só quatro campos indo para o log. Sem isso seria um
  canal de inserir texto arbitrário no log da instalação.
- `script-sample` **não** é registrado: alguns navegadores o mandam, e ele
  traria trecho da página para dentro do log.
- O teto **falha aberto**, ao contrário do limite de convites: aqui o pior
  caso de não conseguir contar é log a mais, e o pior caso de fechar é
  perder o relatório que denunciaria a tela quebrada.

## 7. O que o roteiro cobra

`docker compose exec app python manage.py rodar_roteiros csp`

| Seção | Asserções |
| --- | --- |
| 1 | **`script-src` sem `unsafe-inline` nem `unsafe-eval`**, as demais diretivas, nenhuma origem externa, e a concessão de `style-src` como escolha explícita |
| 2 | cinco respostas, cinco nonces, com entropia |
| 3 | começa em modo de relatório, e `CSP_ENFORCE` nasce desligado |
| 4 | **varredura dos templates**: nenhum atributo de evento sobrando |
| 5 | varredura dos templates: nenhum `<script>` inline sem nonce |
| 6 | o nonce do cabeçalho é o mesmo do HTML |
| 7 | resposta JSON não leva política |
| 8 | o coletor aceita sem sessão, recusa lixo, e tem teto por IP |
| 9 | as telas continuam de pé com os `data-nd-*`, e o `<noscript>` continua oferecendo o botão |
