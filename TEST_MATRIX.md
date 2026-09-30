# Matriz de testes — NeuroDoc 1.0

**Resultado apurado em 2026-09-25.** Não existe suíte automatizada, por
decisão registrada (DEC-20); o substituto são os **54 roteiros de
verificação** em `checks/`, rodados por `manage.py rodar_roteiros`.

Legenda de cobertura: **auto** = roteiro na bateria · **manual** = exercitado
nesta auditoria · **nenhuma** = sem cobertura.

---

## Fluxos críticos

| Funcionalidade | Cenário | Tipo | Resultado | Cobertura | Observação |
| --- | --- | --- | --- | --- | --- |
| Entrar | Login + MFA + escolha de organização | integração | ✅ | auto | `check_g3`, `check_roles` |
| Entrar | Senha errada repetida → atraso progressivo | segurança | ✅ | auto | `accounts/throttling.py` |
| Entrar | `/admin/login/` com senha errada | segurança | ✅ | manual | **corrigido nesta auditoria**: agora conta tentativa |
| Entrar | `/admin/` sem MFA | segurança | ✅ | manual | recusa (`is_superuser` **e** `is_verified()`) |
| Entrar | `/admin/login/` com usuário comum e senha correta | segurança | ✅ | manual | não autentica (`is_staff` exigido) |
| Paciente | Cadastro completo | integração | ✅ | auto | `check_g3`, `check_foto` |
| Paciente | Limite do plano nas seis portas | regra | ✅ | auto | `check_planos` |
| Paciente | Nome com aspas (`O'Brien`, `Maria "`) | borda | ✅ | auto | `check_js_atributo` §5 |
| Agenda | Marcar sem sobreposição | concorrência | ✅ | auto | `check_agenda`, `check_bookerr` |
| Agenda | Grade, duração por tipo, bloqueios | regra | ✅ | auto | `check_agenda` |
| Prontuário | Estruturado e texto livre, cópia entre os dois | integração | ✅ | auto | `check_texto_livre`, `check_prontuario` |
| Prontuário | Finalizado não se reescreve | imutabilidade | ✅ | auto | `check_imutabilidade` |
| Exame | Roteiro de 387 nós e 14 escalas | regra | ✅ | auto | `check_roteiro` |
| Documento | Emitir, assinar, QR só em assinado | integração | ✅ | auto | `check_receitas`, `check_g6` |
| Documento | Receita de controle especial em duas vias | regra | ✅ | auto | `check_receitas` |
| **Documento** | **Texto com `<`, `>`, `&` no PDF** | **integridade** | ✅ | **manual** | **defeito encontrado e corrigido**: `T < 38` era silenciosamente apagado |
| Entrega | Link opaco com OTP, contador de tentativas | segurança | ✅ | auto | `check_imutabilidade`, `check_mensageria` |
| Verificação | QR público na farmácia | segurança | ✅ | auto | `check_g6` — nome mascarado, sem conteúdo clínico |
| Portal | Pedido sem conta, janela de 180 dias | regra | ✅ | auto | `check_portal_retorno`, `check_g10` |
| Portal | Limite por IP na identificação | segurança | ✅ | auto | `check_g10` |
| Financeiro | Recebível, pagamento, ajuste | integração | ✅ | auto | bateria |
| **Financeiro** | **Valor digitado com vírgula (`150,00`)** | **borda** | ✅ | **auto** | `check_dinheiro` — **defeito encontrado e corrigido**: devolvia 500 |
| **Financeiro** | **Valor vazio, `NaN`, infinito, 14 dígitos, negativo** | **borda** | ✅ | **auto** | `check_dinheiro` — `NaN` era **aceito** antes |
| **Sistema** | **Data padrão das telas entre 21h e meia-noite** | **fuso** | ✅ | **auto** | `check_dinheiro` §6 — lia UTC, abria em "amanhã" |
| Indicadores | Consumo do plano e período | integração | ✅ | auto | `check_planos` |
| Exportação | MD e JSON, capacidade, expiração 24 h | segurança | ✅ | auto | `check_exportacao` |
| **Exportação** | **Baixar o acervo clínico sem `READ_CLINICAL`** | **autorização** | ✅ | **auto** | `check_exportacao` — **defeito encontrado e corrigido**: a capacidade valia só para pedir |
| IA | Gate por plano nas duas camadas | autorização | ✅ | auto | `check_ia_plano` (8 seções) |
| **IA** | **`base_url` apontado para a rede interna do servidor** | **SSRF** | ✅ | **auto** | `check_decisoes` — lista de permissão; provado que **nenhum pacote sai** |
| **IA** | **Mensagem de erro distinguindo 401/404/429** | **oráculo** | ✅ | **auto** | `check_decisoes` §6 — uma mensagem só |
| **Arquivos** | **Coleta de lixo do disco agendada** | **operação** | ✅ | **auto** | `check_decisoes` §7-9 — semanal, em ensaio |
| **IA** | **Nome de paciente com aspa na lista do chat** | **XSS** | ✅ | **manual** | **defeito encontrado e corrigido**, provado em Chromium |
| Chat da equipe | Conversa por par, fronteira entre clínicas | isolamento | ✅ | auto | `check_mensagens` |
| Códigos | Busca CID-10 e TUSS | integração | ✅ | auto | `check_codigos` |
| Ajuda | 23 artigos, 47 capturas, nenhuma órfã | integração | ✅ | auto | `check_ajuda` |
| Contrato | Aceite obrigatório, SHA-256, via por e-mail | regra | ✅ | auto | `check_contrato` |
| Console | `/instalacao/` com MFA | segurança | ✅ | auto | `check_super`, `check_instalacao` |
| Backup | Restaurador carrega, trava única | operação | ✅ | auto | `check_backup` |
| **Backup** | **`age` presente na VPS** | **operação** | ✅ | **manual** | **defeito encontrado e corrigido** no `setup_deploy.sh` |

## Segurança transversal

| Frente | Cenário | Tipo | Resultado | Cobertura |
| --- | --- | --- | --- | --- |
| Isolamento | Paciente/documento de outra clínica | IDOR | ✅ | auto (`check_isolation`, `check_tenantb`) |
| Autorização | Matriz de capacidades por papel | autorização | ✅ | auto (`check_matrix`, `check_roles`, `check_secretary`) |
| SQL | Injeção | segurança | ✅ | manual — **zero superfície** (0 `.raw()`, 0 `RawSQL`, 0 `.extra()`) |
| XSS | Template | segurança | ✅ | manual — 2 `\|safe`, ambos escapados antes |
| XSS | Cliente (16 arquivos `.js`) | segurança | ✅ | auto (`check_js_atributo`) |
| CSV | Injeção de fórmula | segurança | ✅ | auto (`check_exportacao`) |
| **Logs** | **Segredo e PII no alerta de erro** | **vazamento** | ✅ | **auto** (`check_alerta_erro`, novo) |
| Perímetro | Agente de captura, IP atrás do proxy | segurança | ✅ | auto (`check_perimetro`) |
| Segredos | No repositório e no histórico | segurança | ✅ | manual |
| Portabilidade | Caixa Windows→Linux | build | ✅ | manual — 802 imports + 527 referências, 0 divergências |

## Infraestrutura

| O quê | Cenário | Tipo | Resultado | Cobertura |
| --- | --- | --- | --- | --- |
| Migrations | Banco vazio → 86 migrations | integração | ✅ | manual |
| Migrations | Pendentes | build | ✅ | manual (`makemigrations --check`) |
| Configuração | `check --deploy` em produção | build | ✅ | manual (2 avisos deliberados) |
| Build | Imagem Docker | build | ✅ | manual |
| Dependências | `pip-audit` | segurança | ⚠️ | manual — 2 pacotes com aviso (auditoria §13) |
| Sintaxe | 479 arquivos `.py` | build | ✅ | manual |

## Lacunas conhecidas

| Área | Por que não há cobertura | Risco |
| --- | --- | --- |
| Desempenho sob carga | Nenhum roteiro mede tempo | Clínica de 12.000 pacientes não foi exercitada |
| Concorrência real | Os roteiros são sequenciais; só `check_mensageria` usa threads | 7 achados não verificados (auditoria §25.2) |
| Transações parciais | Nenhum roteiro derruba a transação no meio | 7 achados não verificados |
| Frontend em navegador | `check_mobile` e `check_links` olham o HTML, não executam a página | Erro de JS em produção |
| Captura local retirada | `check_captura_removida` verifica menu, rotas pública/interna e ajuda | Tabelas legadas permanecem somente leitura para preservar proveniência |
| Grade da agenda | `appointments_outside_rules` nunca é chamado | Encurtar a grade não avisa sobre consultas órfãs |
| Tratamento de erro | Sem `handler404`/`handler500` próprios | 8 achados não verificados |
