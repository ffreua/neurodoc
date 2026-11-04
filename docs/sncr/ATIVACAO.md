# SNCR — plano de ativação e de reversão

Como a receita eletrônica com numeração do SNCR passa de "pronta no
código" a "em uso", e como voltar atrás. **Implementado não é homologado,
e homologado não é autorizado:** cada passo abaixo depende de autorização
expressa do proprietário.

## Antes de publicar

1. **Gate 3 aprovado** pelo proprietário (Sprints 1 a 3 na branch
   `sncr/sprint-1`, ver [ESTADO_EXECUCAO.md](ESTADO_EXECUCAO.md)).
2. Bateria completa verde **com a imagem reconstruída** e num banco
   zerado e semeado (`docker compose down -v`, `seed_demo`, `import_cmed`).
3. **Backup conferido** do dia, e a cópia externa em dia.
4. As migrações são **só de expansão** (`catalogs/0009`, `sncr/0001`):
   tabelas novas, nada alterado nem apagado. A versão anterior roda sobre
   o banco migrado.

## Publicar desligada

5. Merge em `main`, versão nova em `base/version.py`, nota em
   `docs/releases/`, deploy (`scripts/deploy.sh`).
6. **A integração sobe desligada** (`sncr.Configuracao.ativo = False`, o
   padrão da migração). Nada muda para as clínicas: o formulário continua
   oferecendo só as receitas impressas, e a trava de 31/10 (1.21.1)
   continua valendo.
7. **No worker**, importar a lista oficial das controladas:
   `python manage.py import_portaria344` (sem ela, a classificação não acha
   nada e toda receita eletrônica pede confirmação). Se o Anvisalegis
   estiver fora do ar, use a cópia do ato guardada no repositório:
   `--arquivo catalogs/data/portaria344-rdc1036-2026.html`.
8. Smoke test não destrutivo: `/health/`, rodapé com a versão, console
   `/instalacao/operacao/` mostrando o cartão do SNCR **desligado**.

## Ligar (depois do CNPJ) — feito em 2026-10-29

> **Executado.** Passos 9 a 11 concluídos em 2026-10-29 (1.29): ligada em
> Produção, primeiro bloco real recebido, primeira RCE conferida no portal da
> Anvisa, artigo da ajuda publicado. Detalhe em
> [ESTADO_EXECUCAO.md](ESTADO_EXECUCAO.md).

9. Console `/instalacao/operacao/` → cartão do SNCR:
   - **CNPJ da mantenedora** ([PENDENCIA-CNPJ.md](PENDENCIA-CNPJ.md));
   - **Ambiente: Produção** (só muda com a integração desligada);
   - **Ligar**: digitar `LIGAR` e escrever o motivo — vai à trilha
     (`ops.sncr_enabled`).
10. **Teste real (D8):** o proprietário, em "Numeração SNCR", pede **um**
    bloco de RCE com o Gov.br dele. Consome 1 dos 3 pedidos do mês.
    - **Concluído:** o painel mostra 1.000 números livres. Emitir uma RCE
      de verdade, de um medicamento, assinar, e conferir o número no
      portal do SNCR e o PDF contra o modelo da Anvisa.
    - **Recusado:** a mensagem da Anvisa aparece no painel; o ajuste é em
      `sncr/cliente.py` (o formato da resposta, o `Origin`, o token — os
      pontos que eram suposição).
    - **Incerto:** **não pedir de novo.** Conferir no portal do SNCR e
      registrar no painel ("Nenhum bloco foi gerado" ou a faixa que a
      Anvisa mostra) — decisão I14.
11. Só com o teste real bem-sucedido: avisar as clínicas (os médicos de
    cada uma pedem o próprio bloco) e publicar o artigo da central de
    ajuda (texto pronto em [AJUDA.md](AJUDA.md)).
12. **Notificação de Receita A, B e B2 (1.34, decisões D9 e D10).** Não há
    chave própria: com a integração ligada, os três formatos aparecem. O
    primeiro uso real é o teste — sem cota da Vigilância Sanitária, o
    pedido volta **recusado** ("Prescritor não possui saldo disponível"),
    sem custo. Com a cota liberada, pedir **um lote de 10** em "Numeração
    SNCR":
    - **Concluído:** o painel mostra os 10 números e o saldo da cota.
      Emitir uma Notificação de um medicamento, assinar, abrir o QR da
      folha (consulta do número no SNCR) e conferir o PDF contra o modelo.
    - **Incerto:** a resposta não chegou ou veio num formato que o NeuroDoc
      não reconhece. Dar os números por perdidos no painel (decisão I18) e,
      se for formato, ajustar `sncr/cliente.py::_lista_de_numeros` antes de
      pedir de novo.

## Reverter

São três coisas diferentes, e não se confundem:

| O quê | Como | O que acontece |
| --- | --- | --- |
| **Parar de oferecer** (o freio) | Console → **Desligar agora** (um clique) | O formulário deixa de oferecer a eletrônica; rascunhos eletrônicos podem ser refeitos como impressos (I15); as receitas já emitidas **continuam valendo**; os números livres ficam guardados para quando ligar de novo |
| **Voltar a versão da aplicação** | Deploy da versão anterior (`scripts/deploy.sh` no commit anterior, ver `docs/operations/rollback.md`) | As tabelas novas ficam no banco, sem uso; nada se perde |
| **Estado na Anvisa** | Não há reversão | Número usado numa receita não se cancela (FAQ P35–36). **Nunca apagar** bloco, número ou receita para "voltar" — é a única prova de qual número foi para qual paciente |

## Monitorar

- Console: **pedidos incertos** (em vermelho quando houver), números
  livres e usados, médicos com bloco.
- Trilha: `sncr.pedido_*`, `ops.sncr_*`,
  `documents.medicaldocument_sign_failed` com motivo `sncr_sem_numero` ou
  `sncr_desligado`, e `documents.medicaldocument_converted_to_paper`.
- Log `neurodoc.sncr`: pedido incerto e pedido parado (sem token nem dado
  de paciente).
