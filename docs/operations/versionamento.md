# Versionamento do produto

O NeuroDoc exibe a versão do produto no próprio programa. A fonte única é
`base/version.py`; o rodapé e as superfícies de suporte leem esse valor, sem
copiar o número para templates.

Há dois identificadores, com finalidades diferentes:

- **Versão do produto** (`VERSION`): número compreensível para a clínica.
- **Release ID** (`RELEASE_ID`): SHA do commit efetivamente publicado, usado
  por operação, cache de arquivos estáticos e diagnóstico de uma instalação.

A versão vigente é a que está em `base/version.py` no commit publicado — em
2026-10-22, a **1.24**. Este documento não repete o número a cada versão:
ele dizia "1.12" quando a produção já estava na 1.24, e número copiado é
número que envelhece.

## Onde cada um aparece

| Onde | Versão | SHA |
| --- | --- | --- |
| Rodapé do aplicativo e da página pública | sim | não |
| `/instalacao/` | sim | sim, ao lado |
| Retorno de `base.tasks.operational_ping` (`ops/queue_probe.py`) | sim | sim |
| Fim do deploy (`NeuroDoc 1.24 publicado.` / `Release <sha> deployed`) | sim | sim |
| `.runtime/last-successful.json` (`PRODUCT_VERSION`, `RELEASE_ID`) | sim | sim |
| Caminho dos estáticos (`/static/<sha>/`) | não | sim |

## Regra de incremento

A consolidação anterior à primeira atualização — retirada da captura
local, campo narrativo do exame neurológico e agenda mensal visual —
pertence à **v1.0**, conforme a decisão de produto tomada antes da
entrega.

- funcionalidade compatível avança a casa menor: 1.1, 1.2, 1.3;
- mudança relevante e incompatível avança a casa maior: 2.0, 3.0;
- correção que não acrescenta funcionalidade conserva as duas casas; o
  novo SHA já distingue o build corrigido. A **terceira casa** (1.8.1,
  1.8.2…) aparece só quando é preciso distinguir, num chamado de suporte,
  quem já tem a correção de quem ainda vê o defeito — e a correção que
  não precisa disso segue sem mudar a versão, como a `CLICADA` depois da
  1.7.1.

A alteração do número é feita no mesmo commit da atualização e registrada
na nota de release, em `docs/releases/<versão>-<nome>.md` (por exemplo,
`1.24-o-pedido-pronto.md`). A nota é nomeada pela versão e não pelo SHA: o
commit que cria o arquivo mudaria o SHA que o arquivo nomeia. Os quatro
registros nomeados por SHA em `docs/releases/` são builds da 1.0.

Não se deriva versão de data, quantidade de deploys ou número de migration.
