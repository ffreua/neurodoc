---
id: MD-2026-11-17-01
data: 2026-11-17
origem: sessao-unica
tipo: seguranca + funcionalidade + decisao-comercial
sigiloso: nao                 # corrigido nos dois na mesma rodada antes de publicar
estado_aqui: corrigido
commit_aqui: ver `git log --grep "2026-11-17"` (commits desta rodada)
roteiro_aqui: checks/check_revisao_2026_11_17.py
no_outro: corrigido-na-mesma-rodada
---

# Rodada de 2026-11-17: segurança, IA por tarefa, parcelamento e TISS

**Feita numa sessão só, com os dois repositórios** (guia em `CLAUDE.md` da
pasta raiz). A partir desta rodada o intercâmbio é o registro do que cada
lado recebeu, e não mais a conversa entre duas sessões.

## Segurança — achados de @meirakalile-ship-it

O desenvolvedor @meirakalile-ship-it leu o código (versão de 14/11) e
relatou os pontos abaixo. **Todos procediam, e o código era o mesmo nos dois
sistemas**; a correção é a mesma, adaptada só nos nomes.

| # | Achado | Correção |
| --- | --- | --- |
| 1 | O superusuário lia o prontuário pelo `/admin/` sem trilha (somente-leitura bloqueava escrever, não ler) | `base.admin.SemConteudoClinicoAdmin`: a lista aparece, o registro aberto é recusado — atendimento, achados, diagnósticos, adendos, IA (job, rascunho, chat), documento médico, OCR, observações e mensagens da equipe |
| 2 | Certificado A1 revogado continuava guardado (e no backup) | revogar apaga o `.pfx.enc` e descarta a chave embrulhada (*crypto-shredding*), encerra a sessão aberta; `descartar_certificados_revogados` para os antigos |
| 3 | Senha do PFX na sessão de assinatura por até 12 h | sessões de 2 ou 4 h, e o teto vale também para as abertas antes (a chave efêmera já ficava em tmpfs, conferido pelo deploy) |
| 4 | Rodapé afirmava "certificado ICP-Brasil" sem a cadeia ser conferida | o documento diz "certificado digital"; validar a cadeia contra as raízes do ITI fica pendente |
| 5 | Código de recuperação do 2FA sem limite (carga de CPU) | forma conferida antes de derivar senha; teto de 10 erros por conta em 15 min |
| 6a | `--old-key` na linha de comando | `--old-key-stdin`; `--old-key` avisa |
| 6b | `.env.example` com segundo fator desligado e CSP só relatando | molde com segundo fator exigido e CSP aplicada; o local continua relaxado. **Atenção:** o deploy completa o `.env` da VPS com o molde |
| §25 | Trilha sem proteção contra `TRUNCATE`; texto livre do médico na trilha | gatilho `BEFORE TRUNCATE`; motivo da retificação em `MedicalDocument.motivo_retificacao`, da recusa da IA em `AIArtifact.motivo_recusa` |

Pendente: hash encadeado da trilha (para detectar `DISABLE TRIGGER`), cadeia
ICP-Brasil no envio do certificado. As linhas antigas da trilha com texto
livre continuam lá — a trilha é imutável por desenho.

## IA por tarefa

`InstallationSettings.ai_model_pesado` (console, mesmo provedor e chave):
apoio diagnóstico (prazo 150 s) e relatório do paciente vão a ele; chat e
resumo ficam no principal. Vazio = como antes. A verificação horária
confere os dois. 

## Parcelamento no cartão, sem juros

Até 12x no anual, 6x no semestral, trimestral e Pix à vista; o valor cobrado
é o do período. `tenancy.plans.parcelas_no_cartao` decide pela redação do
contrato (`CONTRATO_COM_PARCELAMENTO`). **Aqui espera o contrato 2.3**: a 2.2 diz "pago integralmente de uma vez" e versão aceita não se edita. Minuta em `docs/governance/contrato-2.3-minuta.md`; publicada, o parcelamento liga sozinho. Vem do ProntDoc 1.1.0.

## TISS liberado ao contratar

`tenancy.services.liberar_tiss_pelo_plano`, no cadastro pelo convite e na
troca de plano do console — inclusive na **conversão da degustação**, que a
1.2.0 do ProntDoc não cobria — e com trilha (`tenancy.tiss_liberado_pelo_plano`).
Clínicas que já estavam no Completo não foram liberadas retroativamente. É a adoção da mudança PD-M-2026-11-15-01 do ProntDoc, por decisão do titular. Atenção: a **agenda de exames** não tem chave de instalação, então abre de imediato para o Completo contratado; o menu do TISS continua atrás de `tiss.Configuracao.ativo`.
