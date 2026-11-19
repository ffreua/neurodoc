# Dispositivo confiável — entrar sem o código do segundo fator (2026-11-18)

**Decisão do titular, autorizada pela Dra. Karina Albuquerque Freua em
2026-11-18.** Código: `accounts/dispositivo_confiavel.py`. Roteiro:
`checks/check_dispositivo_confiavel.py`.

## O que é

O segundo fator continua obrigatório para dono e médico, e continua
ativado para todo mundo que já o tem. O que muda: ao digitar o código, a
pessoa pode marcar que **confia naquele dispositivo**. Nele, o código deixa
de ser pedido ao entrar — **sem prazo**, até ser revogado. A senha continua
sendo pedida, e o código continua pedido:

- em qualquer outro navegador;
- para as ações sensíveis, que exigem o código **recente**: sessão de
  assinatura, certificados, exportação do acervo, área do TISS e console.
  O login por dispositivo confiável não carimba o código recente.

## Quem decide

A clínica, que é a controladora (o contrato já põe "o MFA dos usuários" sob
controle do CONTRATANTE, Anexo I, 6.3). Em **Equipe → Dispositivo
confiável**, o responsável permite ou proíbe.

- **Nasce proibido** em toda clínica, nova ou existente (padrão no banco).
- Permitir pede a caixa de ciência e o código do segundo fator recente, e
  fica na trilha (`tenancy.dispositivo_confiavel_permitido`).
- Proibir é um clique, revoga na hora os dispositivos da equipe e fica na
  trilha com o total (`tenancy.dispositivo_confiavel_proibido`). Permitir de
  novo não reativa nenhum: cada pessoa aceita o termo de novo.
- Quem atende em várias clínicas só usa se **todas** permitirem.
- Superadministrador e equipe técnica nunca usam.

## O termo

Versão 1.0, em `accounts/dispositivo_confiavel.py` (`TERMO_TEXTO`). Aparece
à vista na tela do código, só para quem pode usar a opção, com a caixa
"Li e aceito o termo acima, e confio neste dispositivo". Cada dispositivo
guarda o **texto inteiro aceito**, a versão e o SHA-256, o navegador e o IP
protegido. Texto novo é versão nova, como no contrato.

O termo diz: uso pessoal e não compartilhado; sem prazo, até revogar; o que
continua pedindo o código; o risco (quem tiver o dispositivo e a senha vê o
que a pessoa vê); como e quando a confiança é revogada; e que tudo fica na
trilha.

## O que derruba a confiança

| Motivo | Como |
| --- | --- |
| A pessoa revoga um ou todos | Minha conta |
| A senha mudou (qualquer caminho) | conferido a cada entrada (`senha_marca`) |
| O segundo fator foi refeito | conferido a cada entrada (`totp_device_id`) |
| O responsável resetou o segundo fator | Equipe |
| A clínica proibiu | Equipe |

O cookie é renovado a cada entrada; o navegador limita a vida de um cookie
a cerca de 400 dias, então só um dispositivo sem uso por mais de um ano
perde a marca — e aí volta a pedir o código.

## Trilha de auditoria

`accounts.dispositivo_confiado` (versão e hash do termo, navegador),
`auth.login` com `mfa: dispositivo_confiavel` a cada entrada sem o código,
`accounts.dispositivo_revogado` com o motivo, e as duas decisões da
clínica. Nenhum token, senha ou texto clínico.

## LGPD, em resumo

A LGPD não exige MFA pelo nome; exige medidas adequadas ao risco (art. 46),
e o dado é de saúde. A opção é defensável porque o segundo fator continua
na conta e em qualquer outro aparelho, a decisão é da controladora, a
pessoa aceita um termo auditável, e as ações de maior dano continuam
pedindo o código. O termo **não** afasta o dever de segurança da PRONTDOC
nem os direitos dos pacientes, que não são parte dele; é prova de que a
pessoa foi informada e escolheu.

**Texto do termo aprovado pela Dra. Karina em 2026-11-18** (versão 1.0,
como está em `accounts/dispositivo_confiavel.py`). Ajuste de redação é
versão nova do termo, e os dispositivos já confiados guardam o texto que
aceitaram.
