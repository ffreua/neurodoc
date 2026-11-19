---
id: MD-2026-11-18-04
data: 2026-11-18
origem: sessao-unica
tipo: funcionalidade + segurança
sigiloso: nao
estado_aqui: implementado e verificado no ambiente local (NeuroDoc 1.50); não publicado
commit_aqui: ver `git log --grep "Dispositivo confiavel"`
roteiro_aqui: checks/check_dispositivo_confiavel.py
no_outro: feito na mesma rodada — PD-M-2026-11-18-05
---

# Dispositivo confiável e a chave do segundo fator

**Por quê.** O código do segundo fator a cada entrada torna o acesso ao
prontuário mais lento. Decisão do titular, autorizada pela Dra. Karina:
confiar no próprio dispositivo e entrar nele só com a senha, sem prazo, até
revogar; a clínica decide, e nasce proibido. Registro completo em
`docs/governance/dispositivo-confiavel.md`.

**O que entrou.**

- `accounts/dispositivo_confiavel.py` e `DispositivoConfiavel`
  (`accounts.0005`): termo 1.0 guardado inteiro com hash, cookie só em
  `/accounts/`, conferência a cada entrada (token, pessoa, senha, segundo
  fator), revogação com motivo e trilha.
- `Tenant.dispositivo_confiavel_permitido` (`tenancy.0024`, padrão no banco
  `False`) e o cartão em Equipe: permitir com ciência e código recente,
  proibir num clique revogando a equipe.
- O login pelo dispositivo não carimba o código recente: assinatura,
  certificados, exportação, TISS e console continuam pedindo.
- A tela de configurar o segundo fator mostrava a URL `otpauth://` como
  "chave"; agora mostra só a chave, em grupos de quatro, e o QR traz o
  emissor (`OTP_TOTP_ISSUER`).

**Verificado.** `check_dispositivo_confiavel` (catorze seções) e os vizinhos
`check_mfa_reconfirmacao`, `check_revisao_grupo2`, `check_rotulos`,
`check_csp`, `check_idioma`, `check_confirmacao_unica`, `check_isolation`,
`check_revisao_2026_11_17` e `check_super`, todos sem falha;
`makemigrations --check` limpo.

**Igual nos dois.** Os arquivos alterados eram idênticos nos dois sistemas
(tirando os nomes), e a igualdade foi conferida no original antes de levar a
mudança; só a numeração da migração do `tenancy` difere.
