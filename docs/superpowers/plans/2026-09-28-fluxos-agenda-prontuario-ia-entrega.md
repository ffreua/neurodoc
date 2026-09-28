# Correções dos fluxos de agenda, prontuário, IA e entrega

## Objetivo

Corrigir os cinco defeitos observados em produção sem relaxar isolamento por clínica,
consentimento de contato, concorrência do prontuário ou imutabilidade documental.

## Evidências e causas

1. O paciente de 29/09 foi atualizado com sucesso antes da versão que passou a
   promover `registration_stage` para `complete`. A data do agendamento não participa
   da lista. O registro ficou legado em `preliminary`, apesar do evento auditável
   `patients.patient_updated`.
2. O formulário clínico de medicação não carrega `medicamentos.js` nem expõe os
   atributos `data-nd-med-*`; por isso nenhuma busca é feita. O portal já usa o
   componente correto e devolve produto e dosagem compactos.
3. `atendimento.js` guarda todo `textarea[name]` da página. Assim, observação de
   medicação, nota de hipótese e outros formulários auxiliares viram falsos rascunhos
   do atendimento.
4. O prompt de resumo está em português, mas não determina que os valores textuais da
   resposta sejam escritos em português brasileiro.
5. A entrega exige `verified_*_at`, porém nenhuma tela normal preenche esses campos.
   O contato real da paciente está autorizado e com ambos os canais ativos, mas sem
   datas de verificação, tornando-o inelegível.

## Implementação

### 1. Cadastro confirmado e contatos existentes

- Criar migração de dados idempotente em `patients/migrations/`.
- Promover somente pacientes preliminares que possuam evento de auditoria bem-sucedido
  `patients.patient_updated`; não promover pré-cadastros que apenas têm agendamento ou
  check-in.
- Para pacientes completos, preencher a data de verificação apenas nos canais já
  habilitados e que possuem endereço/telefone. Registrar o instante da migração, sem
  inventar uma data histórica de conferência que não foi armazenada.
- No cadastro completo novo e na inclusão manual de contato, tratar o ato explícito da
  equipe de habilitar o canal como conferência e registrar `verified_*_at`.
- Ao concluir um pré-cadastro, conferir os canais habilitados do contato do próprio
  paciente. O pré-cadastro inicial continua não verificado e fora da lista.
- Tornar a redação da interface explícita sobre a conferência do telefone/e-mail.

### 2. Autocomplete clínico

- Expor no campo `MedicationForm.name` a URL do catálogo e o destino de dose.
- Delimitar o formulário com `data-nd-med-grupo` e carregar o mesmo
  `catalogs/medicamentos.js` nas telas estruturada e de texto livre.
- Ao escolher Keppra, gravar nome comercial no medicamento e apenas a dosagem compacta
  no campo Dose; manter digitação livre quando não houver item no catálogo.

### 3. Rascunhos e preservação de texto

- Marcar explicitamente os formulários/campos que pertencem ao corpo do atendimento.
- Fazer `campos()` considerar apenas esses elementos, excluindo observações de
  medicação, hipóteses, achados e exames.
- Preservar o salvamento prévio já existente no texto livre antes de incluir medicação
  ou hipótese.
- Remover chaves antigas dos campos auxiliares conhecidos para não deixar a correção
  presa a resíduos já gravados no navegador.

### 4. Português brasileiro na IA

- Acrescentar regra inequívoca ao prompt de resumo: todas as strings de valor devem ser
  escritas em português brasileiro, ainda que o contexto ou as chaves JSON estejam em
  outro idioma.
- Incrementar a versão do prompt para manter rastreabilidade dos artefatos.

## Regressões antes da correção

- `checks/check_precadastro.py`: legado auditado é promovido; pré-cadastro não auditado
  permanece fora; conclusão verifica o contato próprio e o torna elegível.
- `checks/check_nome_do_contato.py`/`checks/check_g7.py`: contatos criados pela interface
  recebem verificação somente nos canais habilitados e entregam documento.
- `checks/check_texto_livre.py`: as duas telas carregam e conectam o autocomplete;
  somente campos clínicos entram no conjunto de rascunho; preservação anterior continua.
- `checks/check_ia_plano.py`: o prompt de resumo contém o contrato pt-BR e sua versão
  mudou.

## Verificação e entrega

1. Rodar primeiro as regressões focadas e confirmar que falham antes do patch.
2. Aplicar o menor patch em cada camada e repetir as regressões focadas.
3. Reproduzir no navegador: Keppra sugere e preenche dose compacta; observação de
   medicação não gera chave nem faixa; salvar texto livre antes de medicação mantém o
   texto; contato confirmado permite envio.
4. Rodar todas as verificações do diretório `checks/` e checagens do Django/migrações.
5. Revisar diff, remover artefatos temporários, versionar, publicar e executar o roteiro
   de deploy documentado, seguido de health checks somente leitura na VPS.
