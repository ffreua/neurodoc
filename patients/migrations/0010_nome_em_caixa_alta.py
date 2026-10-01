"""Grava os nomes já cadastrados na forma canônica: caixa alta, sem espaço sobrando.

**Esta migração não tem volta, e a irreversibilidade é a decisão.** A
grafia original é sobrescrita: "Nakagawa" vira "NAKAGAWA", e nome próprio
não se reconstrói por regra — não há como saber se "DA" era "da" ou "Da",
nem se "MCDONALD" era "McDonald".

A escolha foi do responsável pelo produto em 30/09/2026, com a alternativa
(guardar a grafia original e aplicar caixa alta só na exibição)
apresentada e recusada. A rede de segurança é o backup cifrado tomado
imediatamente antes de publicar — `docs/operations/backup.md`.

O `reverse` existe e é um **no-op declarado**, e não uma restauração
fingida: `migrate` precisa de algo para rodar ao desfazer, e escrever ali
um `.lower()` ou um `.title()` devolveria "maria da silva" ou "Maria Da
Silva" — formas que o banco nunca teve, com a aparência de terem sido
recuperadas. Errado em silêncio é pior que ausente.

O contato do **próprio paciente** acompanha, porque ele guarda uma cópia
do nome e aparece no comprovante de entrega de documento. O contato de um
parente **não** acompanha: tem nome próprio, não se deduz da ficha, e
padronizar a aparência não autoriza reescrever o nome de quem cuida do
paciente — foi a mesma linha que `sync_self_contact_name` já traçava.
"""
from django.db import migrations

#: Repetido aqui, e não importado de `patients.contacts`: migração lê o
#: banco como ele era na data em que foi escrita. Importar do código vivo
#: faz a migração mudar de comportamento quando a constante mudar, e aí
#: ela deixa de descrever o que de fato aconteceu naquele dia.
RELACAO_PROPRIO_PACIENTE = 'Próprio paciente'


def _canonico(valor):
    return ' '.join((valor or '').split()).upper()


def para_caixa_alta(apps, schema_editor):
    Patient = apps.get_model('patients', 'Patient')
    PatientContact = apps.get_model('patients', 'PatientContact')

    # Em lotes, e com `bulk_update`: uma clínica grande tem milhares de
    # fichas, e uma gravação por linha faria a publicação esperar o banco
    # linha a linha, com o serviço já parado para migrar.
    alterados = []
    for paciente in Patient.objects.all().iterator(chunk_size=500):
        novo_nome = _canonico(paciente.full_name)
        nova_mae = _canonico(paciente.mother_name)
        if (novo_nome, nova_mae) == (paciente.full_name, paciente.mother_name):
            continue
        paciente.full_name = novo_nome
        paciente.mother_name = nova_mae
        alterados.append(paciente)
        if len(alterados) >= 500:
            Patient.objects.bulk_update(alterados, ['full_name', 'mother_name'])
            alterados = []
    if alterados:
        Patient.objects.bulk_update(alterados, ['full_name', 'mother_name'])

    contatos = []
    for contato in PatientContact.objects.filter(
        relationship=RELACAO_PROPRIO_PACIENTE,
    ).iterator(chunk_size=500):
        novo = _canonico(contato.name)
        if novo == contato.name:
            continue
        contato.name = novo
        contatos.append(contato)
        if len(contatos) >= 500:
            PatientContact.objects.bulk_update(contatos, ['name'])
            contatos = []
    if contatos:
        PatientContact.objects.bulk_update(contatos, ['name'])


def nao_ha_volta(apps, schema_editor):
    """Desfazer a migração não devolve a grafia original — ela foi perdida.

    Deixar isto vazio é o comportamento honesto. Quem precisar da grafia
    anterior restaura o backup cifrado anterior à publicação; não há
    informação neste banco que permita reconstruí-la.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0009_repair_confirmed_patients_and_contacts'),
    ]

    operations = [
        migrations.RunPython(para_caixa_alta, nao_ha_volta),
    ]
