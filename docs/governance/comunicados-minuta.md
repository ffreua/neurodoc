# Comunicados da instalação com propaganda — minuta para o contrato 2.5

> **Situação:** aprovada pela advogada em 2026-11-27; **redação da cláusula pendente**. Para a Dra. Karina Albuquerque
> Freua (OAB/SP 450.476), autora da redação do contrato. A propaganda está
> travada no código até `tenancy.contract.VERSAO` chegar a
> `tenancy.plans.CONTRATO_COM_PROPAGANDA` (**2.5**); depois disso, cada
> clínica passa a receber quando aceitar a redação nova. Aviso do sistema
> não depende desta minuta (cláusula 18.1 da 2.4).

## Parecer (2026-11-27)

**A Dra. Karina aprovou** os comunicados com propaganda e entende que a
**ausência de opção de recusa não fere a LGPD**, porque o recebimento faz
parte da contratação do sistema. Fica pendente só a **redação** da cláusula
na versão 2.5 do contrato (e o ajuste do Aviso de Privacidade); publicada a
2.5 em `tenancy/contrato/`, a propaganda libera sozinha para cada clínica que
aceitá-la.

## O que o sistema passou a fazer (2026-11-27)

O console do superadministrador escreve um **comunicado** (título, texto,
link opcional para uma página do próprio sistema) e o manda a todas as
clínicas, às de um plano, a uma clínica ou a um papel (médicos,
secretárias...). Cada pessoa recebe:

- uma linha no **centro de notificações** (o sino) do aplicativo;
- uma **notificação no celular** ou no computador, se ela ligou os avisos
  naquele aparelho (Web Push, NeuroDoc 1.64).

Dois tipos, identificados na tela como tal: **aviso do sistema**
(manutenção, versão nova, mudança de funcionamento) e **propaganda**
(oferta de plano, recurso, condição comercial da PRONTDOC).

**Decisão do titular:** os dois tipos, **sem opção de o usuário recusar**.

## Por que a propaganda espera a redação nova

1. A 2.4, cláusula 18.1, prevê "comunicações contratuais" ao centro de
   notificações — cobre o aviso do sistema, não a oferta comercial.
2. O Aviso de Privacidade lista as finalidades do tratamento e não inclui
   marketing; e diz que "qualquer uso de analytics, **publicidade**,
   rastreamento não essencial (...) deverá ser inventariado e informado em
   versão complementar **antes de sua ativação**". A inscrição de push é um
   identificador do aparelho, e usá-la para publicidade cai nessa frase.

## O que a redação precisaria cobrir (sugestão de pontos, não de texto)

- **Cláusula de comunicações:** a PRONTDOC poderá enviar aos usuários da
  CONTRATANTE, pelo centro de notificações e pelos avisos no aparelho,
  comunicados do sistema **e comunicações comerciais sobre os próprios
  produtos e serviços**; a frequência, se a senhora entender que convém um
  limite.
- **Aviso de Privacidade:** a finalidade "comunicação comercial da
  PRONTDOC aos usuários das clínicas contratantes", a base legal escolhida
  e os dados usados (nome do usuário não entra; usa-se o vínculo, o papel,
  o plano e a inscrição do aparelho). **Nenhum dado de paciente** é usado
  nem pode ser escrito no comunicado.
- **Identificação da publicidade:** o comunicado de propaganda já aparece
  com a etiqueta "Propaganda" na página que se abre ao tocar.

## Pontos para a senhora avaliar sobre "sem recusa"

- **LGPD, art. 18, § 2º** (oposição ao tratamento fundado em hipótese que
  dispensa consentimento) e **art. 7º, IX** (legítimo interesse, com o
  teste de balanceamento do art. 10): se a base for o legítimo interesse, a
  ausência de qualquer meio de oposição pode ser questionada.
- Destinatários são **profissionais e funcionários** da clínica
  contratante, não consumidores finais, e o canal só alcança quem ligou os
  avisos no aparelho — mas a pessoa não ligou para receber oferta.
- Se a senhora entender necessário um meio de oposição, o sistema já está
  preparado para uma chave "receber comunicados comerciais" por pessoa, só
  para a propaganda (o aviso do sistema continuaria sem recusa).

## Onde está no código

`notifications/comunicados.py` (regras e a trava), `ops/superadmin.py`
(`ComunicadosView`, tela `/instalacao/comunicados/`),
`tenancy/plans.py::CONTRATO_COM_PROPAGANDA`, roteiro
`checks/check_comunicados.py`.
