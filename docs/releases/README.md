# Registro de releases

A seção 18.6 do PRD exige que cada release publicada tenha, **antes** de
`NEURODOC_RELEASE_APPROVED=True`, um arquivo `docs/releases/<SHA>.md` com o
SHA, as evidências de homologação e o responsável que assinou.

A ordem importa. A flag no `.env` é uma trava declarativa: ela não executa
nem comprova homologação nenhuma, e `ops/deploy.py::preflight` só verifica
que alguém a ligou. O que responde "esta versão foi homologada por quem, com
base em quê?" é este diretório — e a pergunta é feita depois do incidente,
quando a flag já está ligada há semanas.

Copiar `TEMPLATE.md`, renomear para o SHA completo de 40 caracteres da
release, preencher, **commitar** e só então ligar a flag. Preflight recusa
repositório com mudança rastreada não commitada, então o registro entra na
mesma árvore que vai ao ar.

A versão de produto segue `docs/operations/versionamento.md`. A versão
atual é a **1.15**. O SHA continua mudando em toda publicação, mesmo
quando `VERSION` não muda.

## O que há aqui

Os registros levam o nome da versão (`1.8-…md`). Os quatro arquivos
nomeados por SHA são builds da **1.0**, de 25 a 28/09/2026, assinados na
VPS a partir do molde por `scripts/setup_deploy.sh` e trazidos para o
repositório depois. As correções de
terceira casa ficam no arquivo da versão menor a que pertencem — a 1.7.1
dentro da 1.7, as 1.8.1 a 1.8.3 dentro da 1.8 — e ganham arquivo próprio
quando pedem homologação própria, como a 1.6.1 e a 1.6.2.

| Versão | Registro |
| --- | --- |
| 1.0 | [`1.0-PRIMEIRO-DEPLOY.md`](1.0-PRIMEIRO-DEPLOY.md), e os builds [`a9172d3`](a9172d3e91d3f5dc11d4aa4ca914861b9c2807e6.md), [`015521f`](015521f54ab35dee1082dcec3e06c55d1b78ff74.md), [`83ff236`](83ff236514bd1f950164a156f850681488d9583f.md) e [`cb78c29`](cb78c299097336e2ea4ea01ca67fc2e4854d12ef.md) |
| 1.1 | [`1.1-SEGUIMENTO.md`](1.1-SEGUIMENTO.md) |
| 1.6 | [`1.6-o-que-a-tela-nao-mostrava.md`](1.6-o-que-a-tela-nao-mostrava.md) |
| 1.6.1 | [`1.6.1-logotipo-por-organizacao.md`](1.6.1-logotipo-por-organizacao.md) |
| 1.6.2 | [`1.6.2-leitura-de-laudo.md`](1.6.2-leitura-de-laudo.md) |
| 1.7 e 1.7.1 | [`1.7-padrao-da-instalacao.md`](1.7-padrao-da-instalacao.md) |
| 1.8 a 1.8.3 | [`1.8-o-que-faltava-para-vender.md`](1.8-o-que-faltava-para-vender.md) |
| 1.9 | [`1.9-o-email-da-clinica.md`](1.9-o-email-da-clinica.md) |
| 1.10 | [`1.10-a-recepcao.md`](1.10-a-recepcao.md) |
| 1.11 | [`1.11-a-caixa-limpa.md`](1.11-a-caixa-limpa.md) |
| 1.12 | [`1.12-o-rodape.md`](1.12-o-rodape.md) |
| 1.12.1 | [`1.12.1-o-despachante.md`](1.12.1-o-despachante.md) |
| 1.12.2 | [`1.12.2-auditoria-lote-1.md`](1.12.2-auditoria-lote-1.md) |
| 1.12.3 | [`1.12.3-auditoria-lote-2.md`](1.12.3-auditoria-lote-2.md) |
| 1.13 | [`1.13-a-agenda.md`](1.13-a-agenda.md) |
| 1.14, 1.14.1, 1.14.2 | [`1.14-excluir-horario.md`](1.14-excluir-horario.md) |
| 1.15 | [`1.15-bloquear-horario.md`](1.15-bloquear-horario.md) |
| 1.24 | [`1.24-o-pedido-pronto.md`](1.24-o-pedido-pronto.md) |
