# Verificações de regressão

Roteiros que exercitam o sistema contra o banco de demonstração
(`seed_demo`), pela camada HTTP, com o cliente de teste do Django.

Não são testes unitários e não substituem uma suíte automatizada — a
DEC-20 registra que nenhuma foi criada nesta fase. São o que existe hoje
para responder "isto continua funcionando?", e cada um tenta **quebrar**
o que verifica, em vez de confirmá-lo.

Estavam num diretório temporário, fora do repositório, até 09/09/2026.
Um diretório temporário some, e com ele sumiria a única regressão que
existe sobre permissões, isolamento entre inquilinos e o portal.

## O que os roteiros deixam para trás

Desde `audit/0003_auditevent_imutavel` a trilha de auditoria é
`INSERT`-only no banco, e o papel da aplicação não tem `UPDATE` nem
`DELETE` sobre ela. Três roteiros limpavam as próprias sobras apagando os
eventos que haviam gerado, para então poder apagar a conta ou a
organização que `AuditEvent.actor`/`AuditEvent.tenant` prendem por
`PROTECT`. O banco passou a recusar isso — e o primeiro atalho que a
proteção quebrou foi o deles, o que é o sinal de que ela funciona.

Agora essas entidades são **aposentadas**: perdem os poderes, devolvem os
identificadores únicos (e-mail, CNPJ, slug) e ficam de pé, com a trilha
intacta apontando para elas. Cada rodada completa deixa, portanto, algumas
contas `aposentado-por-roteiro-*` e organizações `aposentada-por-roteiro-*`
no banco de demonstração. São inofensivas e coerentes — a organização
aposentada mantém o roteiro de exame, justamente porque outros roteiros
varrem todas as clínicas e cobram isso de cada uma.

Elas aparecem como `[roteiro] organizacao de teste aposentada` e
`[roteiro] conta aposentada`, para quem abrir o console não precisar
adivinhar o que são.

**O resto não acumula, e isso foi medido.** Rodar a bateria inteira duas
vezes seguidas deixa paciente, atendimento, anexo, documento e
agendamento exatamente onde estavam. Até 19/09/2026 não era assim: cinco
roteiros que emitem documento deixavam **vinte e dois anexos por rodada**
(o `MedicalDocument` era apagado e o PDF dele ficava órfão, no banco e no
volume de mídia), e o `check_secretary` deixava um paciente por rodada —
o pré-cadastro pela agenda cria paciente junto com o agendamento, e só o
agendamento era devolvido. Paciente ativo conta para o limite do plano
(`tenancy/limits.py`), de modo que aquele acúmulo terminaria fazendo os
roteiros falharem por esgotamento de cota, e não por regressão.

Ao escrever um roteiro novo, meça: conte as linhas antes e depois e
confira que o número voltou. É mais barato que descobrir meses depois,
pela lista de pacientes da clínica de demonstração.

Para zerar, recrie a base: `docker compose down -v`, suba de novo e rode
`seed_demo` (e `import_cmed` no worker, se for exercitar as receitas).

## Como rodar

Todos, ou os que interessam:

```sh
docker compose exec app python manage.py rodar_roteiros
docker compose exec app python manage.py rodar_roteiros planos landing
docker compose exec app python manage.py rodar_roteiros --parar-no-primeiro
```

Uma linha por roteiro, a saída completa só de quem falhou, e código 1 se
algum falhar. Cada um roda em processo próprio — é mais lento do que
carregar todos no mesmo interpretador, e é assim de propósito: eles mexem
em `settings`, criam e apagam registros, e um roteiro que passa por causa
de quem rodou antes não serve para nada.

Enquanto se **escreve** um roteiro, use a forma antiga: `rodar_roteiros`
lê `checks/` de dentro da imagem, e a linha abaixo empurra o arquivo do
disco, de modo que a edição vale sem reconstruir.

```sh
docker compose exec -T app python manage.py shell < checks/check_matrix.py
```

Cada roteiro imprime o que observou, termina em `OK: …` quando passa e
sai com código 1 listando as falhas quando não passa.

## O que cada um cobre

| Roteiro | Assunto |
| --- | --- |
| `check_admin` | Convênios, planos e tabela de honorários — quem pode o quê |
| `check_chave` | Chave-mestra de segredos separada da do PFX, e a rotação |
| `check_agenda` | Tipo de atendimento no modal de marcação |
| `check_bookerr` | Aviso de erro nomeando o campo que falhou |
| `check_cf` | Itens trazidos do atendimento anterior |
| `check_docform` | Formulário de documento por tipo, e retificação |
| `check_g3` | Equipe, papéis, registro profissional, identidade da clínica |
| `check_g45` | Provedor de IA e SMTP por clínica, com os botões de teste |
| `check_g6` | QR, assinatura no PDF, verificação pública, receita em duas vias |
| `check_g7` | Entrega ao paciente: link, segundo fator, revogação |
| `check_g8` | Compactação de anexo e relatório de retenção |
| `check_g9` | Campanhas: consentimento, lista congelada, descadastro |
| `check_foto` | Fotografia do paciente: formatos, papéis, isolamento e remoção |
| `check_g10` | Portal de solicitações e a fila do médico |
| `check_hint` | Máscara de segredo com largura fixa |
| `check_ia_padrao` | Provedor de IA padrão da instalação, e a precedência da clínica |
| `check_instalacao` | Instalacao nova: do zero ao primeiro paciente (exige banco vazio) |
| `check_isolation` | Documento no prontuário do paciente certo |
| `check_links` | Nenhum perfil vê link que não consegue abrir |
| `check_matrix` | A matriz de acesso confere com o PRD seção 4 |
| `check_mfa_certificado` | QR e percurso da MFA, verificação recente e certificado isolado por médico |
| `check_nome_do_contato` | Nome do contato próprio acompanha a ficha e a inclusão de novos contatos funciona |
| `check_notificacoes` | Aviso nomeia o paciente, leva à resolução, e alcança só quem pode agir |
| `check_convite` | Entrada do superadministrador: link, senha, MFA, console |
| `check_landing` | Página de vendas, formulário de contato e a tela de leads |
| `check_ajuda` | Manual e FAQ públicos, e nenhuma captura faltando ou órfã |
| `check_chatbot` | O que o chat manda ao provedor, e o que ele nunca manda |
| `check_codigos` | Busca de CID-10 e TUSS, incluindo a abreviação da tabela |
| `check_email` | O web enfileira, o worker entrega: conta e senha chegam |
| `check_mensageria` | A mensageria da instalacao e a de cada clinica nao se tocam |
| `check_inativacao` | Suspender congela, encerrar fecha, e nada e apagado |
| `check_convite_plano` | Convite carregando o plano, e o console que emite e troca |
| `check_planos` | Limites de plano nas seis portas, e o que acontece ao rebaixar |
| `check_precadastro` | Contato do pré-cadastro e confirmação antes de entrar na lista de pacientes |
| `check_prontuario` | Número do prontuário e documentos por paciente |
| `check_roles` | Resposta de cada papel nas telas principais |
| `check_roteiro` | A clínica nasce com o roteiro de exame instalado |
| `check_resto` | Hábitos, confirmação por e-mail, pedido editável, receita, console |
| `check_secretary` | A secretária trabalha, e não passa do que lhe compete |
| `check_super` | O console da instalação por dentro, e o que ele não mostra |
| `check_tenantb` | A segunda clínica não vê dado da primeira |

## Cuidados

Rodam contra o banco de **demonstração**, não contra um banco de teste
descartável: alguns criam registro e apagam no fim. Um roteiro
interrompido no meio pode deixar sobra — `check_secretary` deixa um
paciente por rodada, porque apaga o horário e não o cadastro (paciente com
atendimento é protegido por `PROTECT`, e apagá-lo apagaria o registro de
que aquele atendimento existiu; o caminho é arquivar).

Nunca rodar contra dado real.
