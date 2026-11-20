# Índice do intercâmbio — lado NeuroDoc

Protocolo em `README.md`. Este é o repositório **público**: achado de
segurança só entra aqui depois de corrigido nos dois sistemas.

## Achados do NeuroDoc (para o ProntDoc avaliar)

| ID | Achado | Severidade | Categoria | Aqui | No ProntDoc |
| --- | --- | --- | --- | --- | --- |
| ND-2026-11-17-01 | [Ctrl+S na tela estruturada enviava o primeiro formulário da aba](achados/2026-11-17-01-ctrl-s-estruturado.md) | alta | perda-de-dado | corrigido | pendente (lido daqui: não afetado, sem abas) |
| ND-2026-11-17-02 | [O roteiro contava os formulários que salvam antes, em vez de conferir cada um](achados/2026-11-17-02-roteiro-contava-formularios.md) | baixa | teste | corrigido | pendente (lido daqui: afetado) |
| ND-2026-11-17-03 | [O relatório da IA ainda recusa com página em branco](achados/2026-11-17-03-relatorio-ia-pagina-crua.md) | baixa | tela | aberto | pendente (lido daqui: afetado) |

## Mudanças do NeuroDoc (para o ProntDoc saber e avaliar)

| ID | Mudança | Tipo | Commit | No ProntDoc |
| --- | --- | --- | --- | --- |
| MD-2026-11-14-01 | [Vigência por período e renovação (1.47)](mudancas/2026-11-14-M01-vigencia-e-renovacao.md) | decisao-comercial | 18efed9, cb2c952 | pendente |
| MD-2026-11-14-02 | [Contrato de adesão 2.2](mudancas/2026-11-14-M02-contrato-2-2.md) | texto | cb2c952 | pendente |
| MD-2026-11-17-01 | [Rodada unificada: segurança (@meirakalile-ship-it), IA por tarefa, parcelamento sem juros (espera a 2.3), TISS ao contratar](mudancas/2026-11-17-M03-rodada-unificada.md) | seguranca + funcionalidade | rodada de 2026-11-17 | feito nos dois na mesma sessão |
| MD-2026-11-18-01 | [Cópia externa: disco ausente sai com código 2](mudancas/2026-11-18-M04-copia-externa-codigo.md) | operação | rodada de 2026-11-18 | feito nos dois na mesma sessão |
| MD-2026-11-18-02 | [Cópia diária dos backups no Cloudflare R2 (desligada até o contrato 2.4)](mudancas/2026-11-18-M05-copia-no-r2.md) | operação + texto | rodada de 2026-11-18 | feito nos dois na mesma sessão |
| MD-2026-11-18-03 | [Contrato 2.4 publicado e cópia dos backups no R2 ligada (trava conferida)](mudancas/2026-11-18-M06-r2-ligado.md) | operação + texto | rodada de 2026-11-18 | feito nos dois (PD-M-2026-11-18-04) |
| MD-2026-11-18-04 | [Dispositivo confiável (sem prazo, a clínica decide) e a chave do segundo fator sem a URL](mudancas/2026-11-18-M07-dispositivo-confiavel.md) | funcionalidade + segurança | rodada de 2026-11-18 | feito nos dois (PD-M-2026-11-18-05) |
| MD-2026-11-18-05 | [Vitrine de vendas, NeuroDoc só de neurologia (ProntDoc para as outras) e 18 páginas de busca](mudancas/2026-11-18-M08-vitrine-de-vendas.md) | vitrine + SEO | rodada de 2026-11-18 | feito nos dois (PD-M-2026-11-18-06) |
| MD-2026-11-18-06 | [Plano e renovação dava 500 para o plano Personalizado](mudancas/2026-11-18-M09-plano-personalizado-500.md) | defeito | rodada de 2026-11-18 | feito nos dois (PD-M-2026-11-18-07) |
| MD-2026-11-19-01 | [Incluir horário fora da cadência deixava um período invisível e recusado](mudancas/2026-11-19-M01-horario-fora-da-cadencia.md) | defeito | rodada de 2026-11-19 | feito nos dois (PD-M-2026-11-19-01) |
| MD-2026-11-19-02 | [Dashboard por clínica e por médico, e mailing com consentimento](mudancas/2026-11-19-M02-dashboard.md) | relatórios | rodada de 2026-11-19 | feito nos dois (PD-M-2026-11-19-02) |
| MD-2026-11-19-03 | [Exames do mais recente ao mais antigo, e medicações agrupadas por situação](mudancas/2026-11-19-M03-ordem-exames-e-medicacoes.md) | prontuário | rodada de 2026-11-19 | feito nos dois (PD-M-2026-11-19-03) |

## Avaliações de registros do ProntDoc

Leitura prévia feita pelo ProntDoc neste repositório em `6b84ec5`; a
conclusão é do NeuroDoc, avaliada em 2026-11-17. Os 17 achados valiam aqui
e foram corrigidos em `b26c256`, adaptados aos dois tipos de atendimento.

| ID do ProntDoc | Registro | Tipo | Leitura prévia | Conclusão aqui | Commit |
| --- | --- | --- | --- | --- | --- |
| PD-2026-11-15-01 | [Finalizar selava a última versão salva e perdia o que foi digitado depois](avaliacoes/2026-11-15-01-finalizar-perde-texto.md) | achado | afetado-provavel | afetado — corrigido | b26c256 |
| PD-2026-11-15-02 | [Ctrl+S sem foco acionava o primeiro formulário da página ("Trazer tudo")](avaliacoes/2026-11-15-02-ctrl-s-primeiro-formulario.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-03 | [Trazer a conduta anterior substituía a conduta de hoje](avaliacoes/2026-11-15-03-conduta-anterior-substitui.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-04 | [Exame, analito, medicação removida, consulta anterior e troca de tipo recarregavam sem salvar o texto](avaliacoes/2026-11-15-04-formularios-sem-salvar-antes.md) | achado | afetado-provavel | afetado — corrigido | b26c256 |
| PD-2026-11-15-05 | [Atendimento finalizado com os campos abertos e oferecendo rascunho](avaliacoes/2026-11-15-05-finalizado-editavel.md) | achado | afetado-provavel | afetado — corrigido | b26c256 |
| PD-2026-11-15-06 | [Recusar a análise da IA era barrado e caía numa página branca](avaliacoes/2026-11-15-06-recusa-da-analise-barrada.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-07 | [O aviso do sino abria o apoio diagnóstico numa tela que o mostrava vazio](avaliacoes/2026-11-15-07-aviso-do-sino-apoio-vazio.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-08 | [A regra contra probabilidade numérica descartava análises com valor de exame em %](avaliacoes/2026-11-15-08-regra-de-probabilidade-recusa-exame.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-09 | [Hipótese com identificador de CID inexistente dava erro 500](avaliacoes/2026-11-15-09-cid-inexistente-erro-500.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-10 | [Gráfico de evolução preso em "Montando o gráfico…" depois da primeira série](avaliacoes/2026-11-15-10-grafico-preso-montando.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-11 | ["Analisar de novo" devolvia a análise antiga depois de mudar hipótese, medicação ou exame](avaliacoes/2026-11-15-11-reanalise-devolve-a-antiga.md) | achado | avaliar | afetado — corrigido | b26c256 |
| PD-2026-11-15-12 | [Apoio diagnóstico pedido em atendimento já finalizado](avaliacoes/2026-11-15-12-analise-em-atendimento-finalizado.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-13 | [Os pacotes XSD da TISS não batem com o manifesto SHA-256 no repositório](avaliacoes/2026-11-15-13-xsd-tiss-hash-por-fim-de-linha.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-14 | [`check_relatorio_ia` calculava a data esperada em UTC](avaliacoes/2026-11-15-14-roteiro-data-em-utc.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-15 | [O procedimento de troca da chave da Asaas não funciona como escrito](avaliacoes/2026-11-15-15-troca-da-chave-asaas.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-16 | [Promessas da página de vendas que o código não cumpre](avaliacoes/2026-11-15-16-promessas-da-vitrine.md) | achado | afetado-confirmado | afetado — corrigido | b26c256 |
| PD-2026-11-15-17 | [`check_tiss_guias` falhava conforme o que tinha rodado antes](avaliacoes/2026-11-15-17-roteiro-guias-paciente-compartilhado.md) | achado | afetado-provavel | afetado — corrigido | b26c256 |
| PD-2026-11-17-18 | [O prazo de rede (60 s) corta antes do prazo da tarefa de IA (75 s)](avaliacoes/2026-11-17-18-prazo-de-rede-menor-que-o-da-tarefa.md) | achado | afetado-provavel | afetado — corrigido | 3858ce4 |
| PD-M-2026-11-15-01 | [TISS e agenda de exames ligados automaticamente com o plano contratado](avaliacoes/2026-11-15-M01-tiss-automatico.md) | mudança | avaliar | adotado (decisão do titular, 2026-11-17) | rodada de 2026-11-17 |
| PD-M-2026-11-15-02 | [Quem abriu o prontuário: leitura na trilha e lista na ficha](avaliacoes/2026-11-15-M02-registro-de-acesso.md) | mudança | avaliar | adotado (decisão do titular, 2026-11-20; MD-2026-11-20-01) | rodada de 2026-11-20 |
| PD-M-2026-11-15-03 | [Apoio diagnóstico: o médico aceita ou recusa cada hipótese; prompt v4](avaliacoes/2026-11-15-M03-apoio-diagnostico-v4.md) | mudança | avaliar | não adotado (só a regra do %, em PD-08) | — |
| MD-2026-11-20-01 | [Auditoria externa de 2026-11-20: segundo fator, admin, acervo, convite, restauração, financeiro, TISS, campanhas, PDF, corrida ao finalizar, trilha, corpo da requisição](mudancas/2026-11-20-M01-auditoria-externa.md) | mudança | feito | feito na mesma rodada (PD-M-2026-11-20-01) | — |
| MD-2026-11-20-02 | [Grafo do código (graphify) e o traçado do vínculo até a permissão](mudancas/2026-11-20-M02-grafo-do-codigo.md) | mudança | feito | feito na mesma rodada (PD-M-2026-11-20-02) | — |
