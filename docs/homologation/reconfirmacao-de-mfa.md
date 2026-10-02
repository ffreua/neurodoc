# Reconfirmar o segundo fator, sem derrubar a sessão

**Roteiro:** `checks/check_mfa_reconfirmacao.py` ·
**Módulos:** `accounts/views.py`, `accounts/mfa.py`, `documents/views.py`,
`static/duralux/app.js` ·
**Tela:** `/accounts/mfa/confirmar/`

---

## 1. Os dois becos sem saída

Encontrados no mesmo uso: o médico emitiu um laudo, foi assinar, e bateu
nos dois seguidos.

### A página em branco

Abrir sessão de assinatura exige MFA confirmada nos últimos **trinta
minutos**. A do login envelhece. Quando envelhecia, a view devolvia `403`
com a frase solta em fundo branco:

> Confirme o código do seu aplicativo de autenticação para liberar a assinatura.

Dizia o que fazer e não oferecia onde — porque **a tela de reconfirmação
não existia**. A única tela de MFA do sistema (`MFAChallengeView`) atende
quem ainda *não entrou*: depende de um usuário pendente na sessão, e o
sucesso dela faz o login.

No envio de certificado a saída era pior ainda: uma mensagem pedindo para
**sair e entrar de novo** — derrubar a sessão inteira para reconfirmar seis
dígitos.

### O botão que gira para sempre

`data-nd-confirm` cancela o envio com `preventDefault()`. Mas
`preventDefault` **não impede que os outros ouvintes de `submit` rodem** —
e `initBusyButtons` rodava: punha o spinner e desabilitava o botão. Quem
respondia "cancelar" ficava com um botão morto numa tela que não ia a lugar
nenhum. A única saída era recarregar a página.

A correção é uma linha, e é deliberadamente genérica:
`if (event.defaultPrevented) return;`. Cobre qualquer cancelamento, não só
o da confirmação — o próximo motivo para cancelar um envio não precisa
lembrar deste arquivo.

## 2. A tela nova

`MFAConfirmView` atende quem **já está dentro**. O sucesso não faz login:
só carimba a hora (`mark_recent_mfa`) e devolve a pessoa a onde estava.

**Não dá para unir com `MFAChallengeView`.** Juntar as duas produziria uma
view onde o estado de autenticação do visitante é condicional — exatamente
o lugar onde um erro vira falha de autenticação.

**O `next` é validado contra o próprio host.** Um destino solto aqui
transformaria a confirmação de MFA em trampolim para fora do domínio, que é
o formato clássico do phishing de redirecionamento. O roteiro testa três
formas de destino externo, inclusive o `//host` sem esquema.

**Quem não tem segundo fator é mandado configurar**, não recusado. Dizer
"confirme o código" a quem não tem código nenhum seria o mesmo beco.

## 3. A ordem das perguntas

Antes, a sequência era: escolher certificado → digitar a senha → clicar em
habilitar → **descobrir que faltava o código**. E a senha se perdia, porque
ela não é guardada.

**E não vai ser.** A senha abre a chave privada do certificado; nada que a
guarde — sessão, cache, campo oculto — vale a comodidade de não redigitá-la.

Então a ordem mudou em dois lugares:

| Onde | O que mudou |
| --- | --- |
| Tela de certificados | Sem MFA recente, o formulário de senha **não aparece**: aparece o aviso e o botão que leva ao código |
| `SigningSessionStartView` | A MFA é conferida **antes** do formulário e do certificado |

A segunda é rede de segurança da primeira. `start_session` continua
conferindo por conta própria: a ordem da view é a da tela, não a trava.

## 4. O que o roteiro cobra

`rodar_roteiros mfa_reconfirmacao`

| Seção | Asserções |
| --- | --- |
| 1 | a tela existe e manda o visitante sem sessão ao login |
| 2 | com MFA configurada abre e diz por quantos minutos vale; sem ela, manda configurar |
| 3 | três formas de destino externo são recusadas; caminho interno é aceito |
| 4 | código errado volta com erro e **não** carimba a hora |
| 4-B | código certo carimba e volta para onde se estava |
| 5 | abrir sessão sem MFA recente **redireciona**, não devolve 403 em branco |
| 6 | a tela de certificados não oferece o campo de senha sem MFA recente |
| 7 | o travamento do botão respeita o cancelamento, e a guarda vem antes de desabilitar |
| 8 | `require_recent_mfa` não devolve mais 403 cru |
| 9 | a saída "saia e entre novamente" não existe mais |

O roteiro monta o próprio dispositivo TOTP em vez de contar com o do seed
— sem segundo fator confirmado, as seções que importam nem chegariam a
rodar — e o remove no fim. Entre o código errado e o certo ele zera o
contador de tentativas do django-otp: sem isso, acusaria o produto por uma
proteção que funcionou.
