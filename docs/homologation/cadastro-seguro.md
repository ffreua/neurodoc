# Cadastro seguro: e-mail descartável, CPF e o aviso de encerramento

**Versão:** 1.32 (2026-11-02). **Roteiro:** `checks/check_cadastro_seguro.py`.

## Por que

Em 2026-11-02, três clínicas foram criadas com **CNPJ inventado** e caixa de
**e-mail descartável** (mailinator.com e guerrillamailblock.com), pelo botão
do plano Gratuito. Elas foram encerradas no console com o motivo "CNPJ
falso". Foram três pedidos, atendidos juntos:

1. recusar no cadastro o e-mail de serviço descartável, com uma lista que se
   atualiza sozinha e avisa quando não consegue;
2. aceitar o **CPF** do médico que atende como pessoa física, sempre
   conferindo os dígitos verificadores, além do CNPJ;
3. avisar por e-mail o responsável quando a clínica é **encerrada**, com a
   justificativa.

## 1. E-mail descartável (`catalogs/descartaveis.py`)

**Fonte:** `github.com/Validemailchecker/disposable-email-domains`, arquivo
`data/domains.txt` (licença MIT, atualizado todo dia pela fonte, 220.678
domínios em 2026-11-02).

**Atualização:** `catalogs.tasks.sincronizar_dominios_descartaveis`, todo
**domingo às 03h30**, no worker (que tem a saída para a internet). Também
roda pelo botão **Atualizar agora** em `/instalacao/operacao/` e pelo
comando `sincronizar_descartaveis` (no contêiner do worker). Primeira carga
local: 10 s; repetição sem mudança: 6 s.

**Conferência antes de valer.** A lista baixada só substitui a anterior se:

| Regra | Por quê |
| --- | --- |
| é texto UTF-8, um domínio por linha, com no máximo 0,5% de linhas inválidas | acima disso, o formato da fonte mudou |
| tem pelo menos 50 mil domínios | abaixo disso, é página de erro ou arquivo truncado |
| não encolheu mais de 30% em relação à atual | lista dessas cresce; encolher de uma vez liberaria tudo o que saiu |
| não traz gmail.com, outlook.com, hotmail.com, yahoo.com, icloud.com, com ou com.br | se traz, está corrompida |
| tem até 40 MB | dez vezes o tamanho atual já não é a mesma lista |

Se qualquer regra falhar, ou se a rede, o HTTP ou o banco falharem, a lista
anterior continua valendo, o motivo aparece no console e **todo
superadministrador recebe e-mail** dizendo de quando é a lista em uso. A
gravação é feita pela diferença, numa transação só: quem se cadastra no
meio da troca vê a lista inteira, a anterior ou a nova.

**Falsos positivos.** A lista pública trazia **bol.com.br** (o e-mail
gratuito do UOL) e domínios de clínicas e escritórios brasileiros reais.
Duas exceções vencem a lista:

- `SEMPRE_LIBERADOS`, em código: os provedores grandes, nacionais e
  estrangeiros, entre eles o bol.com.br;
- os **domínios liberados no console**, em `/instalacao/operacao/`, para o
  médico cujo domínio corporativo foi recusado por engano. Valem na hora,
  sem deploy, e a troca vai para a trilha.

A comparação vale para o domínio e para qualquer domínio pai: `x@abc.mailinator.com`
é recusado, e `x@mail.bol.com.br` passa.

**Onde a recusa vale:**

- o cadastro de clínica (`OrganizationSignupForm`) e o serviço
  `accept_platform_invitation`, como segunda barreira;
- o aceite de convite de equipe com conta nova (`AcceptInvitationAccountForm`
  e `accept_collaborator_invitation_new_user`);
- a emissão do convite de equipe, salvo quando a conta já existe.

A recusa não gasta o convite e não cria conta. A trilha registra
`accounts.email_descartavel_recusado` com o **domínio**, nunca com o endereço.

**Onde a recusa não vale, de propósito:**

- **contas que já existem** continuam entrando: a recusa vale para quem
  entra pela primeira vez;
- o **formulário de contato** da página de vendas, que não cria conta: um
  contato perdido por falso positivo é uma falha que ninguém vê;
- **lista vazia**, como numa instalação nova antes da primeira carga, não
  recusa nada. A recusa é uma defesa a mais, e não a condição para alguém
  conseguir se cadastrar. O console mostra "Lista vazia".

**Mensagem na tela:** "Este provedor de e-mail não é aceito para cadastro:
ele é um serviço de e-mail temporário ou descartável, e não é considerado
confiável. Use outro e-mail válido — o do seu consultório, da sua
instituição ou de um provedor como Gmail ou Outlook. Se o seu domínio foi
recusado por engano, escreva para contato@neurodoc.app.br."

## 2. CNPJ ou CPF (`tenancy.Tenant`)

O cadastro tem um campo só, **CNPJ ou CPF**. O número de dígitos diz o que
é: 14 é CNPJ e 11 é CPF, com ou sem máscara. Nos dois casos, os dígitos
verificadores da Receita são conferidos. O CPF repetido é recusado, como já
era o CNPJ repetido.

O **contrato de adesão não muda**. Ele já qualificava a CONTRATANTE como "a
pessoa física ou jurídica (...) CPF ou CNPJ".

**No banco:** duas colunas, `cnpj` e `cpf`, com três restrições
(`tenancy/0020`). Cada documento é único quando preenchido, e há
**exatamente um** dos dois. Toda organização anterior tem CNPJ, então nada
foi reescrito.

**Onde aparece:**

| Lugar | Pessoa jurídica | Pessoa física |
| --- | --- | --- |
| Identidade da clínica | CNPJ formatado | CPF formatado |
| Via do contrato por e-mail | `CNPJ:` | `CPF:` |
| Console: Organizações e Contratos | CNPJ | CPF, com o selo "pessoa física" |
| Declaração de comparecimento | CNPJ | **nada**: o CPF do médico não vai para um papel que o paciente leva |
| Tela de clínica encerrada | pede o nome e o CNPJ, ou o CPF |
| Admin técnico | as duas colunas, com busca |

**Fora desta mudança:** o prestador do **TISS** já aceitava pessoa física
com CPF, num cadastro próprio, e o **SNCR** usa o CNPJ da mantenedora
(ProntDoc). Nenhum dos dois lê o documento da organização.

**LGPD:** o CPF do responsável pessoa física é dado pessoal do contratante,
tratado para execução do contrato. Ele aparece só para quem administra a
organização e para o superadministrador.

## 3. E-mail de encerramento (`tenancy/encerramento.py`)

Ao mudar o estado para **Encerrada** no console, **cada responsável ativo**
da organização recebe um e-mail:

- **Assunto:** "NeuroDoc — encerramento da organização …".
- **Conteúdo:** a data e a **justificativa**, que é o motivo escrito no
  console. O e-mail também diz que os registros não foram apagados, lembra
  o prazo de 90 dias da cláusula 13.1 para pedir a exportação e indica a
  quem escrever.
- **Remetente:** o da instalação, e não o SMTP da própria clínica.
- **Quem não recebe:** médicos e secretárias. Suspender não manda nada.

O formulário de estado avisa que o motivo vai por e-mail ao responsável.
O console diz quantos e-mails saíram, e a trilha registra
`tenancy.encerramento_avisado` com a contagem, sem os endereços.

As três clínicas falsas foram encerradas **antes** desta versão e não
recebem nada. O aviso vale para os encerramentos a partir de agora.

## Homologação

- `check_cadastro_seguro.py`: 70 conferências, todas aprovadas.
- Bateria completa na imagem da 1.32, em quatro lotes: **149 roteiros**.
  148 passaram. `check_intervalos_e_ficha` falhou na seção 5b porque o
  banco local tem uma consulta de demonstração marcada exatamente para
  hoje, 02/11. Essa consulta foi criada em 22/10, e o roteiro supõe um dia
  sem consulta. Nenhum arquivo da agenda foi alterado.
- Download real no worker local: 220.678 domínios gravados. mailinator.com,
  guerrillamailblock.com, yopmail.com e 10minutemail.com são recusados;
  bol.com.br, gmail.com e o domínio de uma clínica real passam.
