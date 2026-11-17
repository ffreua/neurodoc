---
id: MD-2026-11-14-01
data: 2026-11-14
origem: neurodoc
tipo: decisao-comercial      # decisao-comercial | funcionalidade | comportamento | texto | operacao
decidido_por: responsável (Dr. Fernando), com o contrato 2.2 da Dra. Karina
commit_aqui: 18efed9, cb2c952 (NeuroDoc 1.47)
roteiro_aqui: checks/check_renovacao.py, checks/check_contratacao.py
no_outro: avaliar
---

# Vigência por período e renovação pelo sistema (1.47)

## Como era
Todo plano pago valia 12 meses; semestral e trimestral eram parcelas desse
ano, em assinatura no cartão encerrada aos 12 meses.

## Como ficou
- Anual, semestral e trimestral valem **12, 6 e 3 meses**, cada um pago **de
  uma vez** por Pix ou cartão, sem assinatura e sem renovação automática.
- O aceite vence ao fim do período e abre a `Vigencia`
  (`contratacao/vigencias.py`). Trinta dias antes, faixa para o responsável e
  e-mails de 30 e 15 dias; **Organização → Plano e renovação** gera o checkout.
- Renovar pede **novo "li e aceito"** e declaração de poderes, gravados no
  pedido (`Pedido.aceite_*`), sem arrependimento na renovação.
- **Quinze dias depois do fim sem pagamento, o Gratuito** (`rebaixar`), com a
  regra dos médicos da degustação; a renovação paga ou o registro no console
  devolvem plano e médicos.
- Clínicas antigas não ganham período por migração.

## Para o ProntDoc avaliar
O ProntDoc já tem `contratacao/vigencias.py` e um contrato próprio (1.x), com
numeração independente: a regra comercial é dele. O que vale conferir é o
mecânico — o rebaixamento no 16º dia (e não no 14º), os avisos uma vez cada e
a devolução dos médicos —, que `check_renovacao` cobra aqui.
