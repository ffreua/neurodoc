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

## Sprint 2 — guias (30/10/2026, ainda na versão 1.30)

| Entrega | Situação | Onde | Roteiro |
| --- | --- | --- | --- |
| Guia de Consulta e de SP/SADT, com numeração da clínica sob trava | implementado | `tiss/models.py` (`Guia`, `ItemGuia`, `Sequencia`), `tiss/migrations/0002` | `check_tiss_guias` |
| Preenchimento a partir do que existe: convênio do horário, carteira, credenciamento único da operadora, médico do horário como executante/solicitante, tipo de consulta | implementado | `tiss/guias.py::criar_guia` | `check_tiss_guias` |
| **Vínculo com a cobrança do check-in** — nenhum recebível novo; um recebível em no máximo um item (serviço e banco); cancelar solta | implementado | `ItemGuia.recebivel`, `tiss_item_recebivel_uniq` | `check_tiss_guias` |
| Procedimentos com busca TUSS e **vigência na data do serviço**; preço do contrato com a origem; valor diferente só com motivo; fator e arredondamento uma vez | implementado | `tiss/guias.py` (`conferir_codigo`, `preco_contratado`, `gravar_item`) | `check_tiss_guias` |
| Pendências legíveis, por quem resolve (recepção, médico, gestor), e domínios conferidos contra o XSD da versão do credenciamento | implementado | `tiss/guias.py::pendencias`, `tiss/forms_guia.py` | `check_tiss_guias` |
| Fechar congela (snapshot); revisão substitui sem reescrever; cancelar com motivo | implementado | `guias.fechar`, `abrir_revisao`, `cancelar` | `check_tiss_guias` |
| Indicação clínica só pelo médico, com autoria; a tela da guia sem prontuário | implementado | `guias.registrar_indicacao`, `views_guia.IndicacaoView` | `check_tiss_guias` |
| Impressão nos modelos oficiais (Consulta p.469, SP/SADT p.520), numeração dos campos, continuação em folhas, tarja no rascunho | implementado | `tiss/impressao.py` | `check_tiss_guias` |
| Atalhos: ficha do paciente (Gerar guia, Guias), modal da agenda, atendimento (os dois tipos) | implementado | templates | `check_tiss_guias` |
| Matriz de campos por versão | documentado | `docs/tiss/CAMPOS.md` | — |

**Verificação:** bateria completa na imagem com a Sprint 2, 143 roteiros,
nenhuma falha (30/10/2026). Não publicada.

**Decisões desta sprint:**

- **Sem campo de CID**: nenhuma versão das duas guias o tem.
- **Item só do que foi realizado**: guia sem horário nasce sem item; a de
  Consulta de um horário **com check-in** nasce com a consulta cobrada.
- **Procedimentos solicitados (campos 24–28 do papel) = os realizados**:
  o NeuroDoc não guarda pedido de exame como lista estruturada para a
  guia, e a clínica que solicita e executa lista os mesmos; a quantidade
  autorizada fica em branco.
- **Exame sem cobrança no financeiro ainda**: a SP/SADT de um exame não
  cria recebível; a origem do recebível de exame é a reserva de recurso
  (Sprint 4).

## Sprint 3 — próxima

XML de cada versão a partir do snapshot da guia fechada, validado pelos
bytes contra o XSD da versão; hash TISS (A3 p.48-49) com vetores de
teste; lotes de até 100 guias do mesmo tipo e credenciamento (ou o limite
menor da operadora); fila com filtros; ciclos (1–último dia, 15–14,
manual); geração no worker, artefato imutável com SHA-256; protocolo e
resultado registrados à mão.
