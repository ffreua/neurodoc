# Relação de suboperadores

É a relação que o contrato de adesão promete "em local acessível à
CONTRATANTE" (cláusula 8.2), com os campos que a cláusula 8.3 pede:
identidade do prestador, finalidade, categorias gerais de informação,
localização relevante e existência de transferência internacional.

**Atualizada em 2026-10-22** (inclusão da OpenRouter). Conferida contra a
instalação em produção nesse dia — não é a lista do que *poderia* ser usado, é a do que **está**
em uso. Mudança aqui é inclusão ou substituição de suboperador, e a
cláusula 8.4 manda comunicar às clínicas **antes**.

| Prestador | Finalidade | O que trata | Onde | Transferência internacional |
| --- | --- | --- | --- | --- |
| **Leaseweb USA**, contratada pela **Integrator** (hospedagem) | Servidor onde o sistema roda: banco de dados, anexos, documentos e o backup local cifrado | Todos os dados do sistema, inclusive prontuário e dados sensíveis de saúde | San Jose, Califórnia, **EUA** | **Sim**, desde o início da operação (2026-09-25) |
| **Cloudflare** (proxy e proteção da borda) | Proteger o servidor contra ataque de derrubada e esconder o endereço dele; desde 2026-10-19 todo acesso passa por ela | Todo o tráfego entre o navegador e o servidor, em trânsito — inclusive conteúdo clínico, que ela processa para filtrar e não guarda como serviço | Rede global; para quem acessa do Brasil, em geral o nó de São Paulo | **Sim** |
| **Hostinger** (e-mail da instalação) | Enviar e-mail de conta (confirmação, senha), aviso de horário e o link de entrega de documento | Nome e e-mail do destinatário, assunto neutro e um link opaco — **nunca diagnóstico nem o documento** | A confirmar com o provedor | A confirmar |
| **SMSDEV** (SMS) | Enviar aviso de horário, lembrete e o link de entrega de documento | Telefone e mensagem neutra com o link | Brasil | Não |
| **NVIDIA** (IA padrão da instalação) | Apoio clínico por IA, só nos planos que o contratam e só quando a clínica liga o recurso | Texto clínico **desidentificado** localmente antes de sair (nome, CPF, telefone e e-mail removidos); a resposta volta como rascunho que o médico revisa | **EUA** | **Sim** |
| **OpenRouter, Inc.** (IA **reserva** da instalação, desde 2026-10-22) | Responder no lugar da NVIDIA **só quando a chamada a ela falha** (fora do ar, tempo esgotado, limite de uso, modelo aposentado), só para clínica que usa o padrão da instalação e só no plano que contrata IA | O mesmo texto clínico **desidentificado** que iria à NVIDIA; a resposta volta como rascunho que o médico revisa. Cada uso fica na trilha de auditoria e no artefato, com qual provedor respondeu | **EUA**. A OpenRouter repassa o pedido a um provedor de infraestrutura que serve o modelo, escolhido a cada pedido; a instalação **exige** só provedor de **retenção zero**, que **não usa o dado para treino**, e exclui os sediados na China | **Sim** |

**Sobre a OpenRouter.** Ela não roda o modelo: é um intermediário que
repassa o pedido a um dos provedores de infraestrutura que servem aquele
modelo — em 2026-10-22, 37 para o `deepseek/deepseek-v4.1-flash`, alguns
deles na China. Por isso a instalação manda, em todo pedido que **ela**
paga, a exigência de roteamento (`zdr`, `data_collection: deny` e a lista
de exclusão), conferida em produção no mesmo dia. A reserva **nasce
desligada** e é ligada no console; desligá-la é um clique. Trocar o
provedor reserva por outro é **inclusão de suboperador**: esta tabela muda
antes, e as clínicas são comunicadas.

**O que não está na tabela, e por quê.**

- **O servidor de e-mail ou de SMS que a própria clínica configura** e o
  **provedor de IA que a clínica contrata com a chave dela** (hoje, uma
  clínica usa a OpenRouter) não são suboperadores do NeuroDoc: são
  contratos da clínica, que ela escolheu e que ela informa aos pacientes.
- **O destino da cópia externa do backup** recebe só arquivos cifrados
  com `age`, cuja chave privada não sai da custódia do responsável — o
  destino não consegue ler o conteúdo.

O detalhe de cada tratamento, com a base legal e a medida técnica que o
protege, está em [`lgpd.md`](lgpd.md) §3 e §4.
