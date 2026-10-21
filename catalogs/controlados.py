"""Importar a lista da Portaria 344 e classificar a substância de um medicamento.

O parser mora em `catalogs/portaria344.py`, sem Django; aqui ficam o
banco e a pergunta que a receita vai fazer: "esta substância é controlada,
em que lista, e que receituário ela pede?".

**A classificação compara palavras inteiras**, e não trechos: a substância
da CMED vem com o sal ("CLORIDRATO DE SERTRALINA"), e o adendo de cada
lista diz que os sais estão sob o mesmo controle — então "SERTRALINA"
dentro dela conta. Mas "TESTOSTERONA" (C5) não pode achar
"METILTESTOSTERONA" por acaso, nem "CETAMINA" (B1) achar "ESCETAMINA": a
fronteira de palavra é o que separa uma coisa da outra.

**O resultado é sugestão, nunca decisão silenciosa.** Uma substância pode
estar em mais de uma lista, e os adendos mudam o receituário por dose ou
forma farmacêutica. Quem usa `classificar` mostra as listas e o adendo ao
médico; o receituário escolhido continua sendo dele.
"""

import hashlib
import re

from django.db import transaction
from django.utils import timezone

from . import portaria344
from .models import (
    CatalogRelease, CatalogReleaseStatus, CatalogSystem, ControlledList, ControlledSubstance,
)


class VersaoRepetida(Exception):
    pass


def release_ativa():
    return CatalogRelease.objects.filter(
        system=CatalogSystem.PORTARIA_344, status=CatalogReleaseStatus.ACTIVE,
    ).first()


@transaction.atomic
def importar(conteudo_html, url='', versao='', ativar=True):
    """Lê o ato, grava as listas numa release nova e (por padrão) a ativa.

    Tudo ou nada: o parser recusa o texto que não reconhece antes de
    qualquer gravação, e a gravação é uma transação só. A release antiga
    não é apagada — fica `superseded`, como nos outros catálogos.
    """
    texto = portaria344.texto_do_html(conteudo_html)
    listas = portaria344.ler(texto)
    nome_ato, atualizacao = portaria344.versao_do_ato(texto)
    versao = versao or nome_ato or timezone.localdate().isoformat()
    if CatalogRelease.objects.filter(system=CatalogSystem.PORTARIA_344, version=versao).exists():
        raise VersaoRepetida(versao)
    bruto = conteudo_html if isinstance(conteudo_html, bytes) else conteudo_html.encode('utf-8')
    release = CatalogRelease.objects.create(
        system=CatalogSystem.PORTARIA_344, version=versao, source_url=url,
        imported_at=timezone.now(), content_sha256=hashlib.sha256(bruto).hexdigest(),
        license_note=(f'Anexo I da Portaria SVS/MS 344/1998, atualização n. {atualizacao}'
                      if atualizacao else 'Anexo I da Portaria SVS/MS 344/1998'),
        status=CatalogReleaseStatus.DRAFT,
    )
    total = 0
    for posicao, lista in enumerate(listas):
        registro = ControlledList.objects.create(
            release=release, code=lista.codigo, title=lista.titulo[:300],
            receituario=portaria344.RECEITUARIO_POR_LISTA[lista.codigo],
            receituario_texto=lista.receituario_texto[:300], adendo=lista.adendo, position=posicao,
        )
        ControlledSubstance.objects.bulk_create([
            ControlledSubstance(
                release=release, controlled_list=registro, number=s.numero, name=s.nome[:500],
                synonyms='\n'.join(s.sinonimos),
                search_text=portaria344.normalizar(' '.join([s.nome, *s.sinonimos])),
            )
            for s in lista.substancias
        ])
        total += len(lista.substancias)
    if ativar:
        CatalogRelease.objects.filter(
            system=CatalogSystem.PORTARIA_344, status=CatalogReleaseStatus.ACTIVE,
        ).exclude(pk=release.pk).update(status=CatalogReleaseStatus.SUPERSEDED)
        release.status = CatalogReleaseStatus.ACTIVE
        release.save(update_fields=['status'])
    return release, len(listas), total


#: Adjetivos de sal na redação do anexo. A lista diz "Valproato sódico", a
#: CMED diz "VALPROATO DE SÓDIO": sem tirar o adjetivo, a busca não acha um
#: pelo outro. O adendo de cada lista põe os sais sob o mesmo controle,
#: então procurar o nome sem o adjetivo não alarga nada.
#:
#: **Só o adjetivo, nunca "de sódio".** A primeira versão tirava também
#: "de sódio", e "Sulfato de sódio" (lista D2) virou "SULFATO" — que casava
#: com todo sulfato da CMED. Na forma "X de sódio" o X é o ânion, e o nome
#: completo já casa com a redação da CMED.
_ADJETIVOS_DE_SAL = frozenset({'SODICO', 'POTASSICO', 'CALCICO', 'MAGNESICO'})

#: Listas fora da classificação da receita: a D2 é de insumos químicos
#: (controle do Ministério da Justiça), não de medicamento, e a receita não
#: tem o que fazer com ela — só traria falso positivo ("Acetona",
#: "Sulfato de sódio").
_RECEITUARIOS_FORA = frozenset({'nao_medicamento'})


def _nomes(substancia):
    """O nome e os sinônimos, cada um como palavra(s) a procurar."""
    nomes = [substancia.name, *[s for s in substancia.synonyms.splitlines() if s.strip()]]
    saida = []
    for nome in nomes:
        # O parêntese explica ("Somatropina (hormônio do crescimento
        # humano)"): o que se procura é o nome antes dele.
        base = portaria344.normalizar(re.split(r'\s*\(', nome)[0]).strip()
        if len(base) >= 4:
            saida.append(base)
        palavras = base.split()
        if len(palavras) == 2 and palavras[1] in _ADJETIVOS_DE_SAL and len(palavras[0]) >= 4:
            saida.append(palavras[0])
    return saida


_PADROES = {}


def _padroes(release):
    """As expressões de cada substância da release, compiladas uma vez.

    A lista tem ~780 substâncias e muda poucas vezes por ano; compilar a
    cada pergunta custava ~80 ms por medicamento. O cache é por release:
    importar outra troca a chave, e a antiga sai.
    """
    if release.pk not in _PADROES:
        _PADROES.clear()
        _PADROES[release.pk] = [
            (substancia, [
                re.compile(r'(?<![A-Z0-9])' + re.escape(nome) + r'(?![A-Z0-9])') for nome in _nomes(substancia)
            ])
            for substancia in (
                ControlledSubstance.objects.filter(release=release)
                .exclude(controlled_list__receituario__in=_RECEITUARIOS_FORA)
                .select_related('controlled_list').order_by('controlled_list__position', 'number')
            )
        ]
    return _PADROES[release.pk]


def classificar(texto_da_substancia, release=None):
    """As substâncias controladas que aparecem no texto, com a lista de cada.

    Devolve uma lista de `(ControlledSubstance, ControlledList)`, sem
    repetição, na ordem do anexo. Vazia quando nada casa — o que **não**
    prova que o medicamento é livre: o texto pode vir com grafia que a
    lista não usa. A tela diz isso.
    """
    release = release or release_ativa()
    alvo = portaria344.normalizar(texto_da_substancia or '')
    if release is None or not alvo.strip():
        return []
    return [
        (substancia, substancia.controlled_list)
        for substancia, padroes in _padroes(release)
        if any(p.search(alvo) for p in padroes)
    ]
