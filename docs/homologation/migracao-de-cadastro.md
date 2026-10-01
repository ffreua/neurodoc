# Migração do cadastro de pacientes

**Roteiros:** `checks/check_importacao.py`, `checks/check_nome_caixa_alta.py` ·
**Módulos:** `patients/importacao.py`, `patients/naming.py`,
`patients/management/commands/import_pacientes_xml.py`

Duas entregas que chegaram juntas porque dependem uma da outra: o nome do
paciente passou a ter **uma forma só**, e o cadastro do sistema anterior
foi migrado nessa forma.

---

## 1. O nome em caixa alta

Três pessoas cadastram e saem três grafias — "maria da silva", "MARIA DA
SILVA", "Maria Da  Silva". A lista de pacientes vira um mosaico, e o
documento impresso herda a pressa de quem digitou.

A forma canônica é **caixa alta, sem espaço sobrando**
(`patients/naming.py::normalizar_nome`), e ela é **gravada**, não apenas
exibida.

**A alternativa foi apresentada e recusada.** Guardar a grafia original e
aplicar caixa alta na tela seria reversível; gravar não é. A escolha foi
do responsável pelo produto em 30/09/2026, e a consequência está escrita
no módulo: **"Nakagawa" e "NAKAGAWA" passam a ser a mesma coisa**, e nome
próprio não se reconstrói por regra — não há como saber se "DA" era "da"
ou "Da", nem se "MCDONALD" era "McDonald". A rede de segurança foi o
backup cifrado tomado imediatamente antes de publicar.

| Decisão | Por quê |
| --- | --- |
| O acento permanece ("JOSÉ") | Tirar acento não é padronizar aparência, é escrever o nome errado |
| Espaço em excesso some | Dois espaços não aparecem na tela; aparecem na busca, quando ninguém acha "Maria  Silva" procurando "Maria Silva" |
| Normaliza no `clean()` **e** no `save()` | Paciente nasce por quatro caminhos e só um passa por formulário: o pré-cadastro da agenda, a importação e a semeadura não chamam `full_clean()` |
| O nome da mãe acompanha | Sai na mesma receita; padronizar um e não o outro daria "MARIA DA SILVA, filha de joana silva" |
| O contato do **próprio paciente** acompanha | Ele guarda uma cópia do nome e aparece no comprovante de entrega de documento |
| O contato de um **parente** não acompanha | Tem nome próprio; padronizar aparência não autoriza reescrever o nome de quem cuida do paciente |

**Um defeito que isto introduziu, e que o roteiro existente pegou:** o
contato do próprio paciente nascia com o nome **digitado** enquanto a
ficha já fora canonizada — divergentes desde o primeiro segundo, nos dois
caminhos de criação. Corrigido para derivar da ficha.

## 2. A migração do sistema anterior

2.223 fichas num XML. O comando:

```
python manage.py import_pacientes_xml --clinica <slug> --arquivo <x.xml>
python manage.py import_pacientes_xml --clinica <slug> --arquivo <x.xml> --gravar
```

**Ensaio por padrão.** Sem `--gravar`, lê, traduz, aponta todo conflito e
não escreve nada. A assimetria é deliberada: ensaiar de novo custa um
minuto, desfazer uma importação errada custa uma restauração de backup.

**Pode ser repetido.** A ficha é casada pelo `legacy_id` — o número dela
no sistema de origem, guardado em coluna própria
(`patients/0011_ficha_vinda_de_outro_sistema`). Rodar duas vezes atualiza
em vez de duplicar, e é isso que permite retomar uma importação que falhou
no meio. Casar por nome não serve (homônimo existe) e por CPF também não
(37 fichas vieram sem).

### A regra de tradução

Quando o dado antigo cabe num campo do NeuroDoc **sem interpretação**, ele
entra no campo. Quando exigiria interpretar, entra como texto nas
observações administrativas, onde um humano o lê e decide. **Jogar fora é
a única coisa que não se faz** — o dado existia, e quem apagar não saberá
o que apagou.

| XML | NeuroDoc |
| --- | --- |
| NOME | `full_name`, na forma canônica |
| DT_NASC | `birth_date`; data impossível vira ausência **com o motivo escrito**, não exceção |
| CPF | `cpf` |
| SEXO, ESTADO_CIVIL | `sex_at_registration`, `marital_status` |
| PROFISSAO, IDENTIDADE | `occupation`, `identity_number` |
| ENDERECO | `street` + `number` + `complement` (81% vêm como `RUA X, 295 AP 804`) |
| CEP, BAIRRO, MUNICIPIO, UF | `postal_code`, `district`, `city`, `state` |
| TEL_OUTRO, TEL_RES, EMAIL | contato do próprio paciente |
| RESPONSAVEL + RESPONSAVEL_PAR | segundo contato |
| INDICACAO | `referral_details` (texto integral) + `referral_source` (heurística) |
| NUM_ICLIN | `legacy_id` |
| CANCELADO=S | `status=archived`, com o motivo |
| NUM_PRONTUARIO, CONV_NOME | observações administrativas |

### As três decisões que mais pesam

**Ninguém nasce autorizado a receber mensagem.** `sms_enabled`,
`email_enabled` e `authorized_for_documents` entram **desligados**. O
sistema anterior não registrou consentimento algum, e importar um telefone
não é a pessoa pedindo para ser chamada nele. A secretária liga a
autorização quando falar com cada um — que é o momento em que ela existe.
É a asserção mais importante do roteiro: errar aqui é mandar SMS para duas
mil pessoas que nunca autorizaram.

**O convênio não virou convênio.** O arquivo traz `PARTICULAR`,
`FAMILIAR`, `GRATUIDADE` e `DESCONTO MEDICO 50%` — nenhum é operadora de
saúde; são categorias de cobrança daquela clínica. Criar `Insurer` e
`HealthPlan` a partir disso encheria o cadastro de convênios que não
existem. `payment_category` fica particular para todos.

**A indicação erra para "Outro".** Mil duzentos e vinte e sete valores
distintos, quase todos o nome de quem encaminhou. O texto inteiro é
preservado; a classificação é heurística declarada, e quando não reconhece
usa o valor que **não afirma nada**.

### O que o comando nunca faz

Apagar, arquivar quem estava ativo, ou tocar ficha que não veio desta
importação. **Paciente cadastrado aqui não é sobrescrito nem com o mesmo
CPF** — a ficha importada entra sem CPF, com o conflito escrito nela, e a
decisão fica com quem conhece as duas pessoas.

### O defeito que o teste pegou

**85 fichas trazem, no campo "responsável", o nome do próprio paciente.**

Sem guarda, a gravação do responsável casava com o contato do próprio
paciente **pelo nome**, trocava a relação dele de "Próprio paciente" para
"Responsável" e **apagava o telefone recém-gravado**. Na segunda execução,
aí sim, estourava com dois contatos de mesmo nome — e o erro aparecia
longe da causa.

É o tipo de defeito que uma importação de duas mil fichas esconde bem:
nada falha, e seis meses depois o paciente liga e o telefone na ficha
está em branco.

## 3. O que o arquivo real continha

| | |
| --- | --- |
| Fichas | 2.223 (2 sem nome, ignoradas) |
| CPF | 2.186, **todos com dígito verificador válido** |
| Datas de nascimento | 2.217, todas legíveis, nenhuma no futuro |
| CPF repetido | 4 (8 fichas) |
| Canceladas | 4 → arquivadas |
| Responsável homônimo | 85 |
| Codificação | UTF-8 íntegro, zero caractere corrompido |

Resultado da importação: **2.221 fichas, 2.440 contatos, nenhum autorizado
a receber mensagem.** Segunda execução: 0 criados, 2.221 atualizados.

## 4. O que os roteiros cobram

`rodar_roteiros importacao nome_caixa_alta`

| Roteiro | Seções |
| --- | --- |
| `check_nome_caixa_alta` | a função isolada (acento, espaço, idempotência); os quatro caminhos de criação, inclusive `save(update_fields=...)`; o formulário; o nome da mãe; o contato próprio acompanhando e o do parente não; a busca continuando a achar; e nenhuma ficha antiga fora do padrão |
| `check_importacao` | as traduções isoladas; a ficha completa; **ninguém autorizado a mensagem**; o responsável homônimo; o responsável de verdade; a repetição sem duplicar; o CPF repetido; a ficha daqui não sobrescrita; sem nome / cancelado / sem nascimento; e o ensaio que não escreve |
