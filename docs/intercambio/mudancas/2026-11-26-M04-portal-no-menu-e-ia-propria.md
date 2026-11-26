# MD-2026-11-26-04 — Portal no menu, e a IA própria com liga e desliga

**Data:** 2026-11-26. **Tipo:** mudança (pedidos do titular). **Feito nos dois na mesma rodada** (PD-M-2026-11-26-04).

## Portal fora do sino

- `documents/portal.py` e `documents/portal_exames.py` deixam de chamar `notify_capability`:
  pedido e envio de exame do portal não avisam mais no sino. Os avisos antigos ficam onde estão.
- Menu: o item "Solicitações" virou o grupo **Portal**, com **Solicitações** (a fila de sempre)
  e **Exames enviados** (`documents:portal-exams`, `PortalExamListView`): paciente, quem enviou,
  quando, o exame, o laudo, o prontuário e o "Ciente"; aguardando ciente ou todos; paginada.
  Contadores amarelos em cada item e a soma no grupo (`_portal_badge`, uma contagem a mais).
- O alerta vermelho do prontuário continua até o "Ciente".
- `check_exames_do_portal` §7 trocou "o médico foi avisado no sino" por "nenhum aviso no
  sino; contador e lista" — a regra que mudou por pedido, não um teste afrouxado.

## IA própria da clínica

- O relato: apagar a chave e salvar não apagava. Por desenho, campo em branco mantém a chave,
  e não havia como apagá-la. Agora: liga/desliga verde (`data-nd-revela`, comportamento novo
  em `nd-inline.js`, sem script inline), campos só com ele ligado, e **Remover chave e
  configuração** (`AISettingsRemoveView`, POST, `MANAGE_INTEGRATIONS`, trilha
  `ai.provider_settings_removed` sem a chave) que apaga a linha.
- O navegador punha o e-mail de login no "Endereço da API": `autocomplete="off"` nele e
  `new-password` na chave.

## Pendência anotada

SMS e e-mail (SMTP) da clínica e do médico têm o mesmo "em branco mantém" e também não têm
como apagar a senha; o WhatsApp pela Twilio já tem "Remover". Fica para a próxima rodada.

## Verificação

`check_portal_no_menu` e `check_ia_propria_liga` (novos), `check_exames_do_portal`,
`check_notificacoes`, `check_servicos_do_inquilino`, `check_ia_plano`, `check_csp`,
`check_rotulos`, `check_idioma`, `check_mobile`, `check_paginacao`, nos dois.
