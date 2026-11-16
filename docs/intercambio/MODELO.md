---
id: PD-AAAA-MM-DD-NN          # PD- (achado do ProntDoc) ou ND- (do NeuroDoc)
data: AAAA-MM-DD
origem: neurodoc              # prontdoc | neurodoc
severidade: alta              # critica | alta | media | baixa
categoria: perda-de-dado      # perda-de-dado | seguranca | caminho | execucao | tela | texto | operacao
sigiloso: nao                 # sim = não vai à pasta pública do NeuroDoc antes de corrigido
estado_aqui: corrigido        # corrigido | aberto | aceito-como-esta
commit_aqui: <sha>
roteiro_aqui: checks/<arquivo>.py
no_outro: afetado-provavel    # afetado-provavel | afetado-confirmado | nao_afetado | ja_corrigido | avaliar
---

# Título curto do defeito

## O que acontecia
Cenário concreto: o que a pessoa fazia → o que dava errado.

## Causa
Arquivo e linha, e o porquê.

## Correção aqui
O que mudou, e o roteiro que tenta quebrar de novo.

## No outro sistema
O código equivalente lido do outro repositório (arquivo:linha, commit lido),
e a diferença que pode tornar o achado inaplicável.
