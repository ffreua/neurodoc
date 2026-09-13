# Verificações de regressão

Roteiros que exercitam o sistema contra o banco de demonstração
(`seed_demo`), pela camada HTTP, com o cliente de teste do Django.

Não são testes unitários e não substituem uma suíte automatizada — a
DEC-20 registra que nenhuma foi criada nesta fase. São o que existe hoje
para responder "isto continua funcionando?", e cada um tenta **quebrar**
o que verifica, em vez de confirmá-lo.

Estavam num diretório temporário, fora do repositório, até 09/09/2026.
Um diretório temporário some, e com ele sumiria a única regressão que
existe sobre permissões, isolamento entre inquilinos e o portal.

## Como rodar

Um:

```sh
docker compose exec -T app python manage.py shell < checks/check_matrix.py
```

Todos:

```sh
for f in checks/check_*.py; do
  echo "--- $f"
  docker compose exec -T app python manage.py shell < "$f" 2>&1 | tail -3
done
```

Cada roteiro imprime o que observou, termina em `OK: …` quando passa e
sai com código 1 listando as falhas quando não passa.

## O que cada um cobre

| Roteiro | Assunto |
| --- | --- |
| `check_admin` | Convênios, planos e tabela de honorários — quem pode o quê |
| `check_chave` | Chave-mestra de segredos separada da do PFX, e a rotação |
| `check_agenda` | Tipo de atendimento no modal de marcação |
| `check_bookerr` | Aviso de erro nomeando o campo que falhou |
| `check_cf` | Itens trazidos do atendimento anterior |
| `check_docform` | Formulário de documento por tipo, e retificação |
| `check_g3` | Equipe, papéis, registro profissional, identidade da clínica |
| `check_g45` | Provedor de IA e SMTP por clínica, com os botões de teste |
| `check_g6` | QR, assinatura no PDF, verificação pública, receita em duas vias |
| `check_g7` | Entrega ao paciente: link, segundo fator, revogação |
| `check_g8` | Compactação de anexo e relatório de retenção |
| `check_g9` | Campanhas: consentimento, lista congelada, descadastro |
| `check_foto` | Fotografia do paciente: formatos, papéis, isolamento e remoção |
| `check_g10` | Portal de solicitações e a fila do médico |
| `check_hint` | Máscara de segredo com largura fixa |
| `check_ia_padrao` | Provedor de IA padrão da instalação, e a precedência da clínica |
| `check_isolation` | Documento no prontuário do paciente certo |
| `check_links` | Nenhum perfil vê link que não consegue abrir |
| `check_matrix` | A matriz de acesso confere com o PRD seção 4 |
| `check_notificacoes` | Aviso nomeia o paciente, leva à resolução, e alcança só quem pode agir |
| `check_convite` | Entrada do superadministrador: link, senha, MFA, console |
| `check_landing` | Página de vendas, formulário de contato e a tela de leads |
| `check_chatbot` | O que o chat manda ao provedor, e o que ele nunca manda |
| `check_codigos` | Busca de CID-10 e TUSS, incluindo a abreviação da tabela |
| `check_convite_plano` | Convite carregando o plano, e o console que emite e troca |
| `check_planos` | Limites de plano nas seis portas, e o que acontece ao rebaixar |
| `check_prontuario` | Número do prontuário e documentos por paciente |
| `check_roles` | Resposta de cada papel nas telas principais |
| `check_resto` | Hábitos, confirmação por e-mail, pedido editável, receita, console |
| `check_secretary` | A secretária trabalha, e não passa do que lhe compete |
| `check_super` | O console da instalação por dentro, e o que ele não mostra |
| `check_tenantb` | A segunda clínica não vê dado da primeira |

## Cuidados

Rodam contra o banco de **demonstração**, não contra um banco de teste
descartável: alguns criam registro e apagam no fim. Um roteiro
interrompido no meio pode deixar sobra — `check_secretary` deixa um
paciente por rodada, porque apaga o horário e não o cadastro (paciente com
atendimento é protegido por `PROTECT`, e apagá-lo apagaria o registro de
que aquele atendimento existiu; o caminho é arquivar).

Nunca rodar contra dado real.
