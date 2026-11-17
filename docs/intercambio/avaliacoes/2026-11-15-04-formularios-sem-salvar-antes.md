---
avalia: PD-2026-11-15-04
data_do_registro: 2026-11-15
tipo: achado
origem: prontdoc
conclusao: afetado          # afetado | nao_afetado | ja_corrigido | adotar | nao_adotar | pendente
leitura_previa: afetado-provavel     # o que o ProntDoc viu ao ler este repositório em 6b84ec5
commit_aqui: b26c256
roteiro_aqui: checks/check_intercambio_prontdoc.py §8
---

# Exame, analito, medicação removida, consulta anterior e troca de tipo recarregavam sem salvar o texto

**Registro original:** ProntDoc, `docs/intercambio/achados/2026-11-15-04-formularios-sem-salvar-antes.md` (repositório
privado; leitura pelo remoto `prontdoc`, ver README).

## O que o ProntDoc registrou
O médico escreve meia consulta e inclui um exame: a página recarrega e o texto não chegou ao servidor; sobra só a faixa "Restaurar" do navegador (e nada, noutro computador).

## O que o ProntDoc leu neste repositório
Lido em `upstream/main` 2640f2c (NeuroDoc 1.47), lido só para leitura em 2026-11-15.

Os mesmos parciais existem no NeuroDoc; a tela estruturada tem formulários próprios por aba — conferir cada um.

## Conclusão do NeuroDoc
Avaliado em 2026-11-17 sobre `main` (NeuroDoc 1.47).

**Afetado, nos dois tipos.** No texto livre faltava o atributo em exame,
analito, remover medicação, consulta anterior e apoio da IA. No estruturado
nenhum formulário auxiliar salvava antes (ver PD-01). Agora levam o atributo
também: troca de estrutura, eixo do roteiro de exame, incluir achado,
hipótese, escalas (antes só no texto livre), remover achado e "exame normal"
(estes dois nos modais, fora da raiz). O roteiro deixou de **contar**
formulários e passou a conferir **cada** um: todo formulário de
`/app/clinical/` na tela salva antes, menos o salvamento, o adendo e o
descarte. A contagem antiga passava com um formulário novo sem o atributo
(registrado como ND-2026-11-17-02, para o ProntDoc avaliar o roteiro dele).
