# Cadastro de paciente — layout, CPF, CEP e plano de saúde

Esta etapa reescreve a tela de cadastro/edição de paciente
(`templates/patients/form.html` + `patients/forms.py`) pensando em quem a
usa no dia a dia: normalmente a secretaria, com o documento do paciente na
mão e o telefone tocando. Segue integralmente o design system Duralux
aplicado em [aplicação integral do design system](design-system-full.md).

## Layout

Antes, todos os campos vinham de `{{ form.as_p }}`: uma coluna só, todas as
barras do mesmo tamanho — a caixa de UF tinha a mesma largura da caixa de
nome. Agora a tela é dividida em cinco seções numeradas, cada uma um `.card`
do tema, e cada campo recebe a largura do dado que guarda:

| Seção | Campos |
| --- | --- |
| 1. Identificação | nome (6/12), CPF (3/12), nascimento (3/12), sexo, estado civil, RG, ocupação (3/12 cada), nome da mãe (6/12) |
| 2. Endereço | CEP (3/12), logradouro (7/12), número (2/12); complemento, bairro e município (3/12 cada), UF (2/12), país (1/12) |
| 3. Atendimento | médico responsável (4/12), origem (3/12), detalhes (5/12) |
| 4. Pagamento | forma de pagamento (3/12) + bloco do plano |
| 5. Observações | observações administrativas (8/12) |

Outros pontos de uso:

- **Exemplo dentro de cada caixa.** Todo campo de texto tem um `placeholder`
  com um exemplo real ("Ex.: Maria Aparecida de Souza", "Ex.: 01310-100",
  "Ex.: 1578"), em vez de uma caixa vazia sem pista do formato esperado.
- **Data de nascimento desconhecida** deixou de poluir a tela: os campos de
  motivo e ano estimado ficam num `collapse` atrás do botão "Não sei a data
  de nascimento", e abrem sozinhos quando já têm valor ou quando a validação
  reclama.
- **UF virou lista** das 27 unidades federativas em vez de um texto livre de
  dois caracteres.
- **Tudo em português.** O `---------` que o Django coloca nos selects deu
  lugar a "Selecione o médico" e "Selecione o plano"; os rótulos derivados
  automaticamente do nome do campo ("Full name", "Birth date") foram
  substituídos por rótulos escritos.
- O botão **Salvar paciente** aparece no cabeçalho da página (fixo, sempre
  visível) e no fim do formulário.

## CPF obrigatório e conferido

- Obrigatório no formulário (DEC-22). O modelo continua aceitando nulo: há
  paciente cadastrado antes desta regra, e torná-lo obrigatório no banco
  invalidaria esses registros.
- Conferido pelos **dígitos verificadores** (`base.validators.is_valid_cpf`,
  que já existia e é o mesmo algoritmo usado no CNPJ da organização).
  Sequências repetidas (`111.111.111-11`) são recusadas.
- **Duplicata bloqueada com nome**: em vez de estourar o
  `UniqueConstraint(tenant, cpf)` como erro de banco, o formulário responde
  "Este CPF já está cadastrado para *Fulano*", que é o que permite à
  secretaria abrir o cadastro certo.
- Máscara enquanto digita (`529.982.247-25`) e conferência no próprio
  navegador ao sair do campo, com a borda vermelha do tema — sem substituir
  a validação do servidor, que é refeita por inteiro.
- O campo é declarado no formulário com `max_length=14` (e não derivado do
  modelo, que tem 11): sem isso o `max_length` do modelo recusaria a
  máscara antes de qualquer limpeza ter a chance de removê-la.

## CEP: base local dos Correios

A base pedida (<https://github.com/Maahzuka/database-CEPS>, `ceps.xlsx`) foi
baixada, conferida e convertida para
`catalogs/data/postal_ranges.csv` (6.614 linhas, 447 KB, versionado e
diffável em vez de uma planilha binária). O comando
`python manage.py import_postal_codes` valida o arquivo inteiro antes de
gravar; sem `--commit` ele apenas confere.

**O que essa base contém, exatamente:** faixas de CEP **por município** —
UF, município, código IBGE, região e se o município é codificado por
logradouro. Ela **não tem logradouro nem bairro**; nenhum registro do
arquivo tem nome de rua. Isso muda o desenho:

| Fonte | Responde | Depende de rede |
| --- | --- | --- |
| `catalogs.PostalCodeRange` (local) | município, UF, código IBGE | não |
| ViaCEP (complemento) | logradouro, bairro | sim |

`integrations.cep.lookup_cep` resolve **primeiro** na base local — é o que
garante que o cadastro continue preenchendo município e UF com a internet
fora — e só chama o ViaCEP para logradouro/bairro, quando o município é
codificado por logradouro. Se o ViaCEP não responder, o endereço volta
mesmo assim, sem logradouro. Nenhum dado do paciente sai do sistema: a
consulta externa leva apenas os oito dígitos do CEP.

Na tela, digitar os 8 dígitos preenche os campos e escreve o que aconteceu
ao lado do título "Endereço":

- `Endereço encontrado (São Paulo/SP).` — logradouro veio junto;
- `CEP geral de Acrelândia/AC — informe o logradouro.` — o município não tem
  CEP por rua, então não há o que preencher (em vez de parecer falha);
- `CEP não encontrado — preencha o endereço à mão.`

Município e UF são sobrescritos pelo CEP (é o que o CEP determina);
logradouro e bairro já digitados são preservados.

## Plano de saúde

Escolher **Plano** em "Forma de pagamento" abre, na mesma tela, o bloco com
os dados da carteirinha:

- **Plano de saúde** — lista dos planos ativos da organização
  (`patients.HealthPlan`, filtrada pelo tenant), rotulada como
  "Operadora — Plano". Não é texto livre.
- **Tipo** — atributo do plano cadastrado. O campo `HealthPlan.kind` foi
  criado nesta etapa (ambulatorial, hospitalar, hospitalar com obstetrícia,
  referência, odontológico, outro, não informado) e aparece como selo assim
  que o plano é escolhido, lido de um `data-kind` já presente no HTML — sem
  uma segunda requisição.
- **Número da carteirinha**, **Início** da vigência e **Validade**.

Regras conferidas no servidor: pagamento por plano exige plano **e**
carteirinha; escolher um plano com pagamento particular é recusado com uma
mensagem que diz o que fazer; validade anterior ao início é recusada.

Paciente e cobertura são gravados **na mesma transação**
(`patients.coverage.set_patient_coverage`): um cadastro marcado como "plano"
nunca fica sem `PatientCoverage`, o que faria a cobrança cair como
particular em `finance.receivables`. Reeditar o cadastro atualiza a
cobertura existente do mesmo plano em vez de empilhar duplicatas, e o
`Patient.active_coverage` — um campo que existia e nunca era preenchido —
passa a apontar para ela.

A lista de planos é mantida pelo responsável da organização; enquanto não
houver nenhum plano cadastrado, o bloco explica isso e orienta a usar
"Particular". A tela de administração dessa lista é a próxima etapa.

## Bug real encontrado e corrigido: datas sumiam ao editar

Abrindo o cadastro recém-criado para edição, a **data de nascimento
aparecia vazia** mesmo estando gravada. Causa: um `<input type="date">` só
aceita `AAAA-MM-DD`, e o Django, sem `format` explícito, renderizava o valor
na localidade pt-BR:

```html
<input type="date" name="birth_date" value="15/07/1990">   <!-- descartado pelo navegador -->
```

O navegador descarta o valor em silêncio, o campo abre vazio e **salvar
apagaria a data já gravada**. O mesmo valia para todo campo nativo de data,
hora e data-hora do produto: vigência de cobertura, data do documento
anexado, regras de disponibilidade da agenda e — pior — o formulário de
**remarcação de consulta**, que abria sem o horário atual.

Corrigido em `base/widgets.py` com `HTML5DateInput`, `HTML5DateTimeInput` e
`HTML5TimeInput`, que fixam a renderização em ISO 8601; os 14 usos nos
formulários passaram a usá-los. A leitura continua tolerante — o pt-BR do
Django aceita tanto `15/07/1990` quanto `1990-07-15`.

Verificado depois da correção:

```
appointment starts_at (UTC): 2026-09-14 12:00:00+00:00
render starts_at: <input type="datetime-local" value="2026-09-14T09:00" ...>
coverage starts_on: <input type="date" value="2024-01-05" ...>
document_date:      <input type="date" value="2025-03-09" ...>
```

(o horário sai convertido para America/Sao_Paulo, como esperado).

## Verificação executada

| Verificação | Resultado |
| --- | --- |
| Base de CEP carregada | 6.614 faixas; `import_postal_codes` valida antes de gravar |
| Resolução local, sem rede | 01310-100→São Paulo/SP, 69945-001→Acrelândia/AC, 30130-010→Belo Horizonte/MG, 20040-020→Rio de Janeiro/RJ, 88010-000→Florianópolis/SC, 58000-000→João Pessoa/PB, 99999-999→Muliterno/RS; entrada inválida→`None` |
| `lookup_cep` com ViaCEP simulado fora do ar | município/UF continuam vindo; logradouro vazio |
| Formulário (`PatientForm`) com dados reais do tenant | 16 casos, 0 falhas: CPF com e sem máscara, dígito errado, dígitos repetidos, curto, vazio, já cadastrado; nascimento ausente com e sem motivo; plano sem plano, sem carteirinha, completo, validade invertida, plano com pagamento particular; país vazio; UF em branco |
| Navegador real (Chrome via CDP) | CEP preenchendo Av. Paulista/Bela Vista/São Paulo/SP; CEP municipal com a mensagem correta; bloco do plano abrindo e mostrando "Tipo: Referência"; cadastro salvo com cobertura, carteirinha e validade; reabertura em edição com todos os campos preenchidos |
| Todas as telas do produto | 59 templates parseiam; 27 páginas renderizam; 26 telas com contexto sintético — 0 falhas |

## O que não foi feito

- **Administração da lista de planos, operadoras e médicos pelo
  proprietário** — próxima etapa, conforme combinado.
- **Logradouro a partir de base local.** O conjunto de dados indicado não
  tem CEP por logradouro; uma base de ruas (DNE dos Correios) é licenciada
  e não é pública. Enquanto ela não existir aqui, logradouro e bairro vêm
  do ViaCEP ou são digitados.

## Correção pós-deploy — pré-cadastro não é ficha confirmada (27/09/2026)

O agendamento por telefone precisa criar uma linha mínima para que o horário
tenha paciente, mas nome e contato não significam que a clínica confirmou a
ficha. A lista administrativa confundia os dois estados porque filtrava só
`status=active` e ignorava `registration_stage`.

- [x] `list_patients` exige agora `registration_stage=complete`, tanto com
  quanto sem busca textual.
- [x] O autocomplete da agenda continua aceitando `preliminary`: assim uma
  segunda marcação reutiliza o pré-cadastro existente em vez de duplicá-lo.
- [x] Um POST válido da ficha pela recepção promove `preliminary` para
  `complete` na mesma transação do salvamento e registra a promoção nos
  metadados da auditoria. Só então o paciente aparece na lista.
- [x] O limite do plano continua contando pré-cadastros ativos; esta mudança
  é de confirmação e visibilidade, não uma forma de contornar a cota.

Evidência focada: seções 6 e 7 de `check_precadastro.py`, `EXIT=0`.
