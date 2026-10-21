# SNCR — estado de execução

Registro de continuidade da integração NeuroDoc × SNCR (Anvisa). Leia
antes de retomar o trabalho, **e confira contra o código atual**: este
arquivo resume, não substitui a inspeção.

| Campo | Valor |
| --- | --- |
| Sprint / gate | **Sprint 2 concluída na branch, aguardando o proprietário (Gate 2).** Sprint 3 não iniciada |
| Branch | `sncr/sprint-1` (Sprints 1 e 2), **local, sem push** |
| Commit-base | `0676059` (`main`, 1.21.1 publicada) |
| Produção | **1.21.1** — só a transição da D1. **Nada da integração está em produção**, e nenhuma chamada à API do SNCR de produção foi feita |
| Bloqueio para ativar | **CNPJ da mantenedora** ([PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md)); depois, o teste real (D8) |
| Decisões | [DECISOES.md](DECISOES.md) — D1 a D8 do proprietário, I1 a I13 de implementação |
| Relatório da Sprint 0 | [SPRINT-0-RELATORIO.md](SPRINT-0-RELATORIO.md) |

## Onde está cada coisa

| O quê | Onde |
| --- | --- |
| Transição de 31/10 (D1, em produção) | `documents/sncr_transicao.py`, `documents/templatetags/sncr_transicao.py`, roteiro `check_sncr_transicao` |
| Lista oficial das substâncias controladas (D7) | `catalogs/portaria344.py` (parser estrito do ato), `catalogs/controlados.py` (importação e classificação), comando `import_portaria344` (roda no **worker**), migração `catalogs/0009`, cópia do ato em `catalogs/data/portaria344-rdc1036-2026.html`, roteiro `check_portaria344` |
| App `sncr`: configuração, pedido, bloco, número | `sncr/models.py` (`Configuracao` **desligada** por padrão), migração `sncr/0001` |
| Cliente da API (o único lugar que conhece o formato da Anvisa) | `sncr/cliente.py` — desfechos classificados; o que é suposição até o teste real (D8) está aqui |
| Login Gov.br e pedido de bloco | `sncr/fluxo.py`, `sncr/views.py`, `sncr/urls.py` (`/app/sncr/`), tarefa `sncr/tasks.py` (pedido parado vira incerto) |
| Reserva e consumo de números | `sncr/numeracao.py` — `reservar` (um), `reservar_varios` (um por folha, I12), `consumir`, `marcar_perdido`, `numeros_do_documento` |
| Regra da receita eletrônica | `sncr/receita.py` — itens, quantidade por extenso, classificação, limites (3 medicamentos por emissão; art. 57 por folha) |
| PDF no modelo da Anvisa | `sncr/pdf_oficial.py` + `sncr/modelos/rce_eletronica_anvisa.pdf` (SHA-256 conferido) — uma folha por medicamento |
| Emissão e assinatura | `documents/issuance.py` (`_conteudo_da_receita`, `_reservar_numeros_sncr`, consumo depois de assinado), despacho do PDF em `documents/pdf/prescription.py` |
| Telas | `documents/forms.py` e `templates/documents/medical_form.html` (os 3 medicamentos estruturados, só com o SNCR ligado), `templates/documents/medical_detail.html` + `sncr/templatetags/sncr_receita.py` (números e classificação), link "Numeração SNCR" no menu (`templates/partials/sidebar.html`, `base/context_processors.py`) |
| Roteiros | `check_sncr_numeracao` (Sprint 1, Anvisa simulada), `check_sncr_receita` (Sprint 2, **assinatura PAdES real** com certificado de teste) |

## Sprint 1 — numeração (concluída)

Cliente, login Gov.br com a troca **na requisição** (I5), pedido preso à
sessão do navegador e de uso único, desfecho incerto **sem repetição**
(I6), números com `UNIQUE` e reserva com `skip_locked` só na linha do
número (I7), faixa irreconhecível não utilizável (I8). Anvisa
**simulada** — o teste real é o primeiro pedido em produção (D8).

## Sprint 2 — a receita eletrônica (concluída na branch)

- **Formatos novos** na receita: "Controle especial — eletrônica com
  numeração do SNCR" e "Sujeita à retenção — eletrônica". Só aparecem com
  `Configuracao.ativo`; a receita simples e a RCE impressa não mudaram.
- **Até 3 medicamentos estruturados** (nome, concentração, forma,
  quantidade, posologia); a quantidade ganha o extenso sozinha, com o
  gênero certo.
- **Classificação pela lista oficial** (D7, I11): marca resolvida pela
  CMED; Notificação (A/B fora do adendo) e proscrita recusadas; adendo e
  nome desconhecido exigem a confirmação do médico; controlado na RET
  recusado (FAQ P48).
- **Uma folha por medicamento, cada uma com o seu número SNCR** (I12),
  numa assinatura PAdES só. Faltando número para alguma folha, nenhuma sai
  e nenhum é gasto. Os números são consumidos só depois de assinado e
  ficam em `signature_metadata['sncr']['numeros']`, na ordem das folhas.
- **PDF da RCE escrito sobre o modelo oficial** (I13); a RET, sem modelo
  oficial, com a mesma estrutura desenhada. Sem timbre da clínica (D6).
  Rascunho com "RASCUNHO — SEM VALIDADE" e sem número; número de
  homologação com "HOMOLOGAÇÃO — SEM VALIDADE".
- **A eletrônica não sai em papel nem é retificada** (I10). QR para a
  verificação do NeuroDoc (I9).
- **Evidência:** `check_sncr_receita` verde (inclui assinatura válida e as
  duas folhas conferidas uma a uma); as duas folhas de uma receita de dois
  medicamentos inspecionadas em imagem em 2026-10-21; **bateria completa:
  120 roteiros, nenhuma falha** (2026-10-21, imagem reconstruída).

## Próxima ação exata

1. **Gate 2:** o proprietário aprova a Sprint 2.
2. **Sprint 3** — contingência e preparação:
   - oferecer a receita impressa quando o SNCR falhar ou faltar número,
     com confirmação do médico (cenários 1 e 4 do plano), sem converter
     sozinho;
   - tela de conferência dos pedidos **incertos** e dos números perdidos;
   - retirar o aviso transitório da 1.21.1 **quando** a integração for
     ligada em produção (`documents/sncr_transicao.py`), e não antes;
   - ajuda da central (`base/help_content.py`) e documento de homologação;
   - plano de ativação: `Configuracao.ativo` desligado no deploy, ligado
     só depois do CNPJ e do primeiro bloco real.
3. **Quando o CNPJ chegar:** [PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md); depois,
   o primeiro pedido real em produção, pelo proprietário (D8).

## Pendências

- **CNPJ da mantenedora** — [PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md).
- Prova de login no SNCR de **treinamento**: bloqueada há dias pela
  própria Anvisa ("Erro ao buscar inscrições de conselhos"); substituída
  pela D8.
- A lista de **antimicrobianos e GLP-1** (RET) é outra norma, sem
  catálogo ainda: hoje a RET aceita o que **não** é controlado da
  Portaria 344 e confia no médico para o resto.
- Notificações de Receita (A, B, B2): fora do escopo (D5).

## Riscos registrados

Ver relatório da Sprint 0, seção 8. Acrescentados na Sprint 2:

- **Formato real da resposta da Anvisa** só se conhece no teste real (D8);
  o ajuste fica em `sncr/cliente.py`.
- **Número vira texto no PDF antes de a assinatura terminar.** Se a
  assinatura falhar, a transação devolve os números a livre — seguro
  porque aquele PDF nunca saiu do servidor (`_reservar_numeros_sncr`).
