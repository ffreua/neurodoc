# Migração do histórico de atendimentos (iClin)

Complemento da [migração de cadastro](migracao-de-cadastro.md). O cadastro
veio primeiro; sem o histórico, o NeuroDoc não sabia quando cada paciente
tinha sido visto pela última vez, e o portal recusava o pedido de receita de
quem consultou na semana anterior à troca de sistema
(`documents/portal_retorno.py`).

**Código:** `clinical/importacao.py` (tradução de uma anotação) e
`clinical/management/commands/import_atendimentos_xml.py` (execução).
**Roteiro:** `checks/check_migracao_atendimentos.py`, com arquivo fictício.

## Decisões (do médico responsável, 2026-11-02)

| Ponto | Decisão |
| --- | --- |
| Forma | Cada anotação vira um atendimento de **texto livre já finalizado**, imutável, com a data e a hora da consulta no iClin |
| Seções | **Diagnósticos** → impressões (o médico não usava CID no iClin); **Prescrição** e **Condutas** → conduta; o resto no corpo, com os títulos e na ordem. São os dois campos que a consulta seguinte copia |
| Medicação | Fica no texto. Não vira a lista estruturada de medicação: seria adivinhar dose e posologia |
| Corte | Até **02/10/2026**, inclusive (`--ate`). Depois disso as consultas já estão no NeuroDoc; e mesmo antes, o dia em que o paciente já tem atendimento escrito aqui é pulado |
| Sem texto | Fica de fora |
| Alerta do iClin | Vai às **observações administrativas** da ficha, uma vez, o mais recente |
| Anexos e documentos | Só **nome e endereço**, escritos no corpo. Os arquivos não são baixados |
| Casamento | Número do iClin (`Patient.legacy_id`) **e** nome; sem isso, nome e nascimento com uma ficha só; o resto fica de fora e é relatado |
| Arquivo original | Guardado pelo médico como documento das evoluções anteriores. **Nunca entra no repositório**; vai à VPS só para rodar e é apagado em seguida |

## O que a gravação não faz

Não passa por `finalize_encounter`. Aquele caminho publica
`clinical.encounter_finalized`, que cria a **cobrança** da consulta e pede o
**resumo à IA** — sete mil cobranças de consultas pagas anos atrás e sete mil
pedidos ao provedor. A linha é gravada já fechada, com o hash calculado pela
mesma função, `legacy_id = iclin:<nº>` (único por clínica no banco, o que
torna a rodada repetível) e **uma** entrada na trilha por rodada
(`clinical.encounters_imported`, com a contagem e o SHA-256 do arquivo).

A tela diz "Histórico migrado do sistema anterior (iClin)" no lugar de
"Registro finalizado em … por …", que afirmaria um fechamento que não
aconteceu aqui; a lista de atendimentos mostra o selo "migrado do iClin".

## Ensaio em produção (2026-11-02, arquivo de 7.714 anotações)

- Pacientes do arquivo: 2.234 — **2.217** casam por número e nome, **14** por
  nome e nascimento, **3** sem ficha.
- Anotações: **7.661** entram; 37 depois do corte; 13 sem texto; 1 no mesmo
  dia de um atendimento já escrito no NeuroDoc; 2 de paciente sem ficha.
- 230 pacientes passam a ter consulta nos últimos 180 dias (portal liberado).

## Gravação em produção (2026-11-02, 00:35)

Backup cifrado tirado imediatamente antes (00:34, sucesso). Gravados
**7.661** atendimentos (22/08/2013 a 01/10/2026), todos finalizados, com o
hash conferido linha a linha depois; **zero** eventos na outbox e **zero**
cobranças ligadas a eles; alerta escrito em **431** fichas. Com o histórico
e as consultas feitas no NeuroDoc desde outubro, **267** pacientes têm
consulta nos últimos 180 dias. O arquivo foi apagado da VPS e do contêiner
ao fim.

## Como rodar

```bash
scp anotacoes.xml deploy@<vps>:/tmp/anot.xml            # chmod 600
C=$(docker ps -q --filter name=neurodoc_v1_app | head -1)
docker exec -i $C sh -c 'umask 077; cat > /tmp/anot.xml' < /tmp/anot.xml
docker exec $C python manage.py import_atendimentos_xml --clinica <slug> \
    --medico <e-mail> --arquivo /tmp/anot.xml --ate 2026-10-02          # ensaio
docker exec $C python manage.py import_atendimentos_xml ... --gravar   # depois do backup
docker exec $C rm -f /tmp/anot.xml; rm -f /tmp/anot.xml
```

O `/tmp` do contêiner é `tmpfs`: `docker cp` escreve por baixo dele e o
arquivo não aparece — por isso a cópia por `cat` de dentro.
