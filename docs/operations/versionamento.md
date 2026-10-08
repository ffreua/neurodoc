# Versionamento do produto

O NeuroDoc exibe a versão do produto no próprio programa. A fonte única é
`base/version.py`; o rodapé e as superfícies de suporte leem esse valor, sem
copiar o número para templates.

Há dois identificadores, com finalidades diferentes:

- **Versão do produto** (`VERSION`): número compreensível para a clínica.
- **Release ID** (`RELEASE_ID`): SHA do commit efetivamente publicado, usado
  por operação, cache de arquivos estáticos e diagnóstico de uma instalação.

## Regra de incremento

A consolidação anterior à primeira atualização — retirada da captura
local, campo narrativo do exame neurológico e agenda mensal visual —
pertence à **v1.0**, conforme a decisão de produto tomada antes da
entrega. A versão atual é a **1.8.3**.

- funcionalidade compatível avança a casa menor: 1.1, 1.2, 1.3;
- mudança relevante e incompatível avança a casa maior: 2.0, 3.0;
- correção que não acrescenta funcionalidade conserva as duas casas; o
  novo SHA já distingue o build corrigido. A **terceira casa** (1.8.1,
  1.8.2…) aparece só quando é preciso distinguir, num chamado de suporte,
  quem já tem a correção de quem ainda vê o defeito — e a correção que
  não precisa disso segue sem mudar a versão, como a `CLICADA` depois da
  1.7.1.

A alteração do número é feita no mesmo commit da atualização e registrada
na nota de release. Não se deriva versão de data, quantidade de deploys ou
número de migration.
