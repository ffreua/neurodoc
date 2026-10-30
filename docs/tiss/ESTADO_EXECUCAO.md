# TISS — estado da execução

Onde retomar o módulo de faturamento TISS. A revisão que precedeu o código,
com as fontes oficiais e os hashes, está em `REVISAO_SPRINT1.md`.

Classificação usada abaixo, a do prompt do módulo: **implementado**,
**validado por XSD**, **validado por regras**, **aceito em homologação da
operadora** e **liberado em produção** são coisas diferentes.

## Sprint 1 — fundação (versão 1.30, 30/10/2026)

| Entrega | Situação | Onde | Roteiro |
| --- | --- | --- | --- |
| Espelho TUSS que não esvazia a busca e guarda a vigência por código | implementado | `integrations/tuss.py`, `catalogs/migrations/0010` | `check_tuss_vigencia` |
| Três chaves: plano (`tiss` em `plans.py`), clínica (`Tenant.tiss_liberado`) e instalação (`tiss.Configuracao`) | implementado | `tenancy/plans.py`, `tenancy/context.py`, `ops/superadmin.py` | `check_tiss_liberacao` |
| Capacidades `TISS_VIEW/PREPARE/CLOSE/EXPORT/CONFIGURE`, sem `READ_CLINICAL` | implementado | `tenancy/permissions.py` | `check_tiss_liberacao` |
| Segundo fator de novo após 10 min sem uso, **só na área TISS** (A9, req. 83) | implementado | `tiss/views.py::TissView` | `check_tiss_liberacao` |
| Forma de cobrança por atendimento (particular / convênio + cobertura), até o check-in | implementado | `scheduling` (modelo, serviço, painel do modal), `finance/receivables.py::_price_for` | `check_forma_de_cobranca` |
| Prestador (PJ/PF, CNPJ alfanumérico), credenciamento por operadora, profissional (interno ou externo) | implementado | `tiss/models.py`, `tiss/forms.py`, `templates/tiss/` | `check_tiss_liberacao`, `check_tiss_versoes` |
| Sete pacotes XSD oficiais (3.04.00 a 4.03.00) com manifesto SHA-256, parser sem rede e sem DTD | implementado | `tiss/versoes.py`, `tiss/xsd/` | `check_tiss_versoes` |
| Anexo do pedido como caso negativo | validado por XSD (reprovado, como deve) | `tiss/exemplos/anexo_reprovado_4_01_00.xml` | `check_tiss_versoes` |
| Catálogo das operadoras ativas da ANS no cadastro de convênio | implementado | `catalogs.OperadoraAns`, `import_operadoras_ans`, tarefa semanal | `check_operadoras_ans` |

**Verificação:** bateria completa na imagem da 1.30, 142 roteiros, nenhuma
falha (30/10/2026). **Não publicada**: vai para produção junto da Sprint 2,
por decisão do responsável.

**O que ainda não existe:** guia, item, lote, XML gerado, hash TISS,
impressão, agenda de recurso (EEG/ENMG/PSG) e o vínculo guia ↔ recebível.
São as Sprints 2 a 4.

### Para ligar numa clínica (quando houver guia para emitir)

1. `python manage.py import_operadoras_ans` **no worker** (ou esperar a
   tarefa de segunda-feira, 05h).
2. Console → *Operação* → Faturamento TISS → digitar `LIGAR` e o motivo.
3. Console → *Organizações* → a clínica (Completo ou Personalizado) →
   *TISS* → motivo → *Liberar TISS*.
4. Na clínica, quem tem o papel de dono ou gestor: *Faturamento TISS* →
   prestador → credenciamento por operadora → profissionais.

Desligar: o mesmo cartão, um clique. Nada é apagado.

### Decisões tomadas nesta sprint

- **Chave da instalação fora do contexto de permissões.** Ler a linha da
  configuração em toda requisição custaria uma consulta a toda tela de
  `/app/`; ela é conferida nas telas e tarefas do TISS e no menu, só para
  quem tem a capacidade.
- **Forma de cobrança é ação do horário, não campo obrigatório ao marcar.**
  O formulário rápido de marcação é desenhado para não pedir forma de
  pagamento ao telefone (`scheduling/forms.py::QuickBookingForm`). Vazio é
  "não informado", e nele vale a regra antiga — só que agora
  determinística (a cobertura ativa da ficha primeiro).
- **`row_version` não muda na troca de forma de cobrança**, para não
  invalidar os lembretes já agendados.
- **Reconfirmação pelo segundo fator.** Quem não tem TOTP configurado é
  levado a configurar ao entrar na área TISS — é o comportamento da tela
  de reconfirmação existente, e o A9 recomenda o segundo fator.

## Sprint 2 — próxima

Guia de Consulta e SP/SADT: botão na ficha administrativa do paciente,
formulário progressivo com o que já existe (cobertura, credenciamento,
profissional), itens com busca TUSS e vigência na data do serviço, preço do
honorário com origem visível, pendências legíveis, snapshot no fechamento,
impressão nos modelos oficiais (A4 p.469 e p.520) e o vínculo com o
recebível — sem criar cobrança nova para consulta já cobrada.
