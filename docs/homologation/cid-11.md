# CID-11 ao lado da CID-10

Pedido do Dr. Fernando em 2026-11-10 (1.44): além da CID-10, que está nas
hipóteses diagnósticas, na busca de pacientes por diagnóstico e na busca de
códigos, o sistema passa a oferecer a **CID-11** — **mantendo a CID-10**.
Evidências: `checks/check_cid11.py`.

## O que mudou para quem usa

- **Apoio → Busca de códigos** tem três abas: **CID-10**, **CID-11** e
  **TUSS**. A CID-11 se busca pelo código (`8A60`, `8A60.0`, com ou sem o
  ponto) ou pelo nome, sem acento.
- **Hipóteses do atendimento** (primeira consulta, seguimento e texto
  livre): ao lado do campo de busca há a escolha **CID-10 / CID-11**. A
  busca procura só na classificação escolhida, e o navegador lembra a
  última escolha. A hipótese gravada com código da CID-11 aparece com a
  marca **CID-11** na lista e no resumo do caso.
- **Pacientes por diagnóstico**: aceita código das duas classificações; pelo
  nome, procura nas duas de uma vez.
- **Documentos** (pedido de exames, solicitação de cirurgia, a conduta): a
  hipótese escolhida sai com o rótulo da classificação dela — "CID-10: G35 —
  …" ou "CID-11: 8A40 — …".

## O que não mudou

A CID-10 continua onde estava, e continua sendo o padrão: a busca sem
escolha é CID-10, o formulário abre na CID-10, e nenhuma hipótese já
registrada foi tocada. **O sistema não converte código de uma classificação
para a outra** — a correspondência entre elas não é de um para um, e
convertê-la sozinho seria escrever no prontuário um diagnóstico que o médico
não escolheu. Um atendimento pode ter hipóteses das duas.

O faturamento TISS não usa CID (nenhuma versão do padrão tem o campo), e a
declaração de comparecimento continua sem diagnóstico.

## As decisões

**O código diz de qual classificação é; não há coluna nova no prontuário.**
Na CID-10 o código começa por letra e número (`G40`); na CID-11, a segunda
posição é sempre letra (`8A60`, `BA00`). As duas formas não se cruzam —
o roteiro confere isso contra as duas cargas inteiras, código por código.
`catalogs/cid.py::sistema_do_codigo` lê as três primeiras posições, e vale
também para o código escrito à mão e para o agrupamento (`8A00.0&XK9J`).
Uma coluna "sistema" em `EncounterDiagnosis` teria de ser preenchida para
as hipóteses existentes, entraria na discussão do `content_hash` dos
atendimentos finalizados, e poderia **discordar do código** ao lado dela.
Sem migração no prontuário, o hash dos finalizados não muda.

**A carga vem da planilha oficial da OMS, que mora no repositório.**
`catalogs/data/SimpleTabulation-ICD-11-MMS-pt.xlsx` — a "tabulação simples"
da CID-11 MMS **2025-01** em português, baixada de icd.who.int, com o
`readme` da OMS ao lado. O SHA-256 da planilha está em código
(`CID11_SHA256`) e é conferido antes de gravar. A instalação a recebe
sozinha, na subida (`ops/runtime.py` → `ensure_cid11`), como a CID-10: só
quando não há CID-11 ativa, e sem derrubar a subida se algo falhar.

**A leitura é estrita.** Coluna faltando, código fora da forma, código
repetido ou planilha com menos de 15 mil códigos: nada é gravado. Uma
CID-11 pela metade seria pior do que nenhuma — o código ausente pareceria
não existir.

**Entram os capítulos 1 a 25, e só as categorias com código.** Ficam fora:

| Fora | Por quê |
| --- | --- |
| Capítulos e blocos | não têm código; ninguém registra hipótese num bloco |
| Capítulo X (códigos de extensão) | só valem **acompanhando** outro código — lateralidade, gravidade, agente —, e na busca apareceriam como se fossem diagnóstico |
| Capítulo 26 (medicina tradicional) e seção V (funcionalidade) | não são diagnóstico do consultório de neurologia; a tela diz que ficaram fora |

Quem precisa do código de extensão o escreve à mão no campo do código: o
agrupamento é aceito, lido como CID-11 e impresso como foi escrito.

**671 títulos estão em inglês, e a tela avisa.** São categorias residuais
("outros especificados", "não especificado") que a OMS ainda não traduziu:
a planilha as traz com o título em português vazio. Elas entram com o
título em inglês **da própria planilha**. Deixá-las de fora faria o código
parecer inexistente; traduzir por conta própria seria alterar a
classificação, e a licença (CC BY-ND 3.0 IGO) não permite obra derivada.
Nenhuma delas está no capítulo 8, o das doenças do sistema nervoso.

**Uma classificação por busca.** O autocomplete da hipótese procura em uma
de cada vez (`?sistema=cid11`; qualquer outro valor é CID-10). Misturar as
duas na mesma lista poria `G35` e `8A40` lado a lado para a mesma doença, e
a escolha entre elas passaria a ser acidente de clique.

**A escolha da classificação não é gravada no servidor.** O campo
`cid_sistema` do formulário existe para o `cid.js` ler; o que vai ao
prontuário é o código. A última escolha fica no navegador
(`localStorage`), e sem ele o formulário abre na CID-10.

## Versão nova da CID-11

Quando a OMS publicar a seguinte, baixe a tabulação simples em português e:

```bash
docker compose exec app python manage.py import_cid11 \
    --arquivo /caminho/SimpleTabulation-ICD-11-MMS-pt.xlsx --versao 2026-01 --dry-run
```

Sem `--dry-run`, a versão nova passa a ser a ativa e a anterior fica como
substituída. O que já está no prontuário não muda: a hipótese guarda o
código e a descrição do dia em que foi escrita.

## Licença e atribuição

CID-11 para Estatísticas de Mortalidade e de Morbidade (CID-11 MMS),
Organização Mundial da Saúde, licença **CC BY-ND 3.0 IGO**. A tela de busca
traz a atribuição, a versão e o link para icd.who.int. O conteúdo é exibido
como foi publicado; o sistema só retira os traços de indentação que a
planilha põe antes do título para desenhar a hierarquia.

## Roteiro

`check_cid11.py`, em nove seções: a leitura do código; a carga (SHA-256,
licença, nada do capítulo X, a hierarquia, o residual em inglês); a busca
(a CID-10 como sempre, uma classificação por vez); as rotas e a tela de
três abas; a hipótese nos dois tipos de tela de atendimento, com o POST
antigo sem o campo novo; pacientes por diagnóstico; o rótulo nos
documentos; a leitura estrita da planilha; e a subida que não sobrepõe nem
derruba.
