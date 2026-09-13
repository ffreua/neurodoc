# Busca de códigos — CID-10 e TUSS

Uma tela, duas abas: `/app/codigos/`. CID-10 da carga da OMS, TUSS
espelhada da ANS. Evidências: `checks/check_codigos.py`.

## A decisão que mudou no meio

A primeira versão consultava a API da ANS **a cada busca**, e o argumento
era bom: a TUSS muda por resolução normativa, uma cópia local vira
desatualizada sem avisar, e o código glosado só aparece na fatura.

Estava errado, por uma razão que só apareceu ao rodar contra a pilha:

> **O processo web não tem saída para a internet.** Em `docker-stack.yml`,
> `app` está em `traefik_public` e `neurodoc_v1_internal`; quem está em
> `neurodoc_v1_egress` é o `celery_worker`.

Não é acidente de configuração — é o desenho, e ele é bom: o processo que
atende requisição de navegador não conversa com a internet. A chamada
síncrona a partir da view **funcionou parcialmente em desenvolvimento** (a
pilha local tem uma bridge só) e teria falhado por *timeout* no primeiro
dia de produção, com o médico esperando na tela.

O espelho resolve os dois lados, e resolve a desatualização **melhor** do
que a consulta ao vivo resolvia — porque a consulta ao vivo não tinha
resposta para "e quando a ANS estiver fora?".

| | Consulta ao vivo | Espelho local |
| --- | --- | --- |
| Funciona em produção | ❌ sem egresso no web | ✅ |
| Com a internet fora | ❌ | ✅ |
| Velocidade | segundos | **7 ms** medidos |
| Desatualização | nenhuma | visível na tela, semanal |

São 5.967 procedimentos na `tuss-22`. O CID-10 local, que já funcionava
assim desde S03, tem 14.233 — a ordem de grandeza é a mesma.

## Como o espelho é alimentado

`integrations/tuss.py` baixa a tabela página a página (25 por página, ~240
páginas, com pausa de 0,2 s entre elas — duzentas requisições em rajada
contra um serviço público gratuito é abuso) e publica uma
`CatalogRelease` nova, pela mesma maquinaria do CID-10.

Herda daí o que importa: a release anterior vira `superseded` em vez de
sumir, e o registro clínico que apontou para ela continua legível. **Um
pedido emitido no ano passado guarda o código e a descrição daquele
momento** — é isso que o prontuário precisa provar.

A lista inteira é baixada **antes** de qualquer escrita: gravar enquanto
baixa deixaria meia tabela se a rede caísse na página 150, e meia tabela
de procedimentos é pior que nenhuma, porque parece inteira.

- Tarefa: `catalogs.tasks.sync_tuss`, domingo às 4h (`CELERY_BEAT_SCHEDULE`).
- Manual: `python manage.py sync_tuss`, **no worker** — é quem tem egresso.
- Falha é registrada e engolida: a tabela anterior continua ativa e a busca
  continua respondendo. Uma sincronização que estoura derrubaria a tarefa
  periódica, e o sintoma seria uma tabela que para de envelhecer sem
  ninguém perceber.

## Dois defeitos de usabilidade encontrados testando

**A busca era pela frase inteira.** `search_text__contains` com o termo
todo: "esclerose multipla" funcionava porque a descrição é literalmente
isso, e "doenca parkinson" não achava "Doença de Parkinson" — a palavra
"de" no meio quebrava. Passou a exigir **todas as palavras, em qualquer
ordem** (`AND` entre tokens). `AND` e não `OR`: com `OR`, digitar mais
devolveria mais resultados, que é o contrário do que se espera.

**A tabela da ANS abrevia, e o médico não.** `RM - Crânio (encéfalo)` é o
código 41101014, e quem digitava "ressonancia cranio" não achava nada —
concluiria que o sistema não tem o exame. Não é exceção: são 104 linhas
começando com `RX -`, 51 com `US -`, 37 com `RM -`, 29 com `TC -`.

`SEARCH_SYNONYMS` mapeia o que o médico digita para o que a tabela
escreve. Cada token vira "este **ou** aquele", nunca substituição — quem
digita "RM" continua achando "RM". A lista é curta de propósito: sinônimo
é dívida, e uma entrada errada faz a busca trazer o que não foi pedido,
que é pior do que não trazer nada.

Depois: `ressonancia cranio` → 8 resultados com o 41101014 entre eles;
`eletroneuromiografia` → 7; `ultrassom doppler` → 13.

## Decisões menores, e o porquê

**Qualquer vínculo ativo alcança** (`required_capability = None`). Não há
dado de paciente aqui — é catálogo público —, e exigir capacidade clínica
impediria a secretária de conferir um código que o convênio pediu por
telefone.

**Procedimento com vigência encerrada aparece, com marca.** Sumir
esconderia por que a operadora glosou um código que a clínica usou até o
mês passado. Ele vai para o fim da lista, não para fora dela.

**Copiar leva código e descrição juntos.** O código sozinho, colado num
laudo, obriga quem lê a procurar o que ele significa.

**Sem release sincronizada, a resposta é "não sincronizada"** e não uma
lista vazia — que se leria como "esse código não existe".

**A tela diz a procedência e a data.** Quem vê um código faltando precisa
saber de quando é a cópia antes de concluir que o sistema erra.

## O que foi verificado

`checks/check_codigos.py`, oito seções, todas verdes:

| # | Pergunta | Resultado |
| --- | --- | --- |
| 1 | Médico e secretária alcançam? | 200 nos dois |
| 2 | CID por código, nome, acento e duas palavras | G40, G40.0, epilepsia, esclerose multipla, doenca parkinson |
| 3 | TUSS pela abreviação da tabela | `ressonancia cranio` e `RM cranio` acham o 41101014 |
| 4 | Mais palavras restringe? | 20 → 8 |
| 5 | Vigência encerrada some? | Aparece com marca |
| 6 | Termo de um caractere varre o catálogo? | Não |
| 7 | Sem release, diz o quê? | "ainda não foi sincronizada" |
| 8 | A view faz chamada externa? | Não — e a seção falha se alguém reintroduzir |

A seção 8 é a que protege a decisão deste documento: ela lê o código-fonte
de `catalogs/views.py` e falha se `requests` ou uma chamada ao cliente da
ANS reaparecer ali. Sem ela, a próxima pessoa com pressa refaria o caminho
que não funciona em produção.
