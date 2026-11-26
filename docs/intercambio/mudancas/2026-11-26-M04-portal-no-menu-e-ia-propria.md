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

## SMS e e-mail (resolvido na mesma rodada)

O mesmo "em branco mantém, e não há como apagar" valia para a chave do SMS, o servidor de
e-mail da clínica e o remetente por médico. Os três ganharam o liga/desliga
(`partials/switch.html`, reaproveitável) e um botão de remover
(`SmsSettingsRemoveView`, `ClinicEmailRemoveView`, `DoctorEmailRemoveView`). A regra do
SMS ficou: desligado **com** chave guardada é recusa de mandar SMS; remover a chave volta ao
SMS padrão da instalação, se o plano incluir. O nome da mensagem não é credencial e fica.

## Verificação

`check_portal_no_menu`, `check_ia_propria_liga` e `check_integracoes_liga` (novos), `check_exames_do_portal`,
`check_notificacoes`, `check_servicos_do_inquilino`, `check_ia_plano`, `check_csp`,
`check_rotulos`, `check_idioma`, `check_mobile`, `check_paginacao`, nos dois.
