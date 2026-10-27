from .models import PatientContact

#: Relação que marca o contato do **próprio** paciente, e não de um
#: parente ou responsável.
#:
#: Estava escrita à mão em `patients/forms.py` e em
#: `scheduling/services.py`. Duas cópias de uma string que outro código
#: compara: quem ajustasse a acentuação de uma delas deixaria de casar com
#: a outra, e o contato do paciente passaria a ser tratado como o de um
#: terceiro — sem erro nenhum, só deixando de sincronizar.
SELF_RELATIONSHIP = 'Próprio paciente'


def confirm_contact_channels(contact, confirmed_at=None):
    """Registra os canais que a equipe conferiu ao salvar o contato.

    Habilitar SMS/e-mail na ficha é um ato explícito da equipe, não uma
    inferência a partir da mera existência do dado. Só o canal habilitado e
    preenchido recebe a data; o outro continua inelegível para entrega.
    """
    from django.utils import timezone

    confirmed_at = confirmed_at or timezone.now()
    fields = []
    if contact.sms_enabled and contact.phone and contact.verified_phone_at is None:
        contact.verified_phone_at = confirmed_at
        fields.append('verified_phone_at')
    if contact.email_enabled and contact.email and contact.verified_email_at is None:
        contact.verified_email_at = confirmed_at
        fields.append('verified_email_at')
    if fields:
        contact.save(update_fields=[*fields, 'updated_at'])
    return fields


def confirm_self_contact_channels(patient, confirmed_at=None):
    """Confirma o contato do próprio paciente ao concluir o pré-cadastro."""
    confirmed = 0
    for contact in patient.contacts.filter(relationship=SELF_RELATIONSHIP):
        confirmed += len(confirm_contact_channels(contact, confirmed_at=confirmed_at))
    return confirmed


def sync_self_contact_name(patient):
    """Renomeia o contato do próprio paciente quando o paciente é renomeado.

    O contato guarda uma **cópia** do nome, e a cópia não acompanhava a
    ficha: renomear um paciente deixava a lista de Contatos mostrando o
    nome antigo ao lado do telefone novo. Apareceu em uso real, num
    cadastro de teste que virou cadastro de verdade — que é justamente o
    caminho em que o nome muda.

    Não é cosmético. O nome do contato é o que aparece no comprovante de
    entrega de documento (`documents/medical_detail.html`), e ali ele
    responde "para quem esta receita foi enviada". Um nome errado nessa
    linha é um registro de entrega que aponta para a pessoa errada.

    **Só os contatos do próprio paciente.** O de um parente tem nome
    próprio e não se deduz do da ficha — sincronizá-lo apagaria o nome de
    quem cuida do paciente.

    Devolve quantas linhas mudaram, para quem chama poder registrar.
    """
    return patient.contacts.filter(
        relationship=SELF_RELATIONSHIP,
    ).exclude(name=patient.full_name).update(name=patient.full_name)


def create_contact(context, patient, **fields):
    contact = PatientContact(tenant_id=context.tenant_id, patient=patient, **fields)
    contact.full_clean()
    contact.save()
    return contact


def authorized_document_contacts(patient):
    """Contacts eligible to receive documents — distinct from the general list."""
    return patient.contacts.filter(authorized_for_documents=True)


def contato_vigente(contact, agora=None):
    """Se o contato ainda vale: sem validade, ou validade no futuro.

    A mesma regra de `communications.services._still_valid`, que é quem
    decide se uma mensagem sai. É também o que a tela usa para esconder o
    contato excluído — ver `remove_contact`.
    """
    from django.utils import timezone

    agora = agora or timezone.now()
    return contact.valid_until is None or contact.valid_until > agora


def remove_contact(contact):
    """Exclui o contato. Devolve `'apagado'` ou `'encerrado'`.

    **Apaga quando nada aponta para ele.** O contato digitado errado, que
    nunca recebeu mensagem, sai do banco.

    **Encerra quando há histórico.** A entrega de documento, o link enviado
    e o destinatário de campanha apontam para o contato com `PROTECT`, e
    apontam de propósito: são o registro de **para quem** uma receita foi
    enviada. Apagá-los para conseguir apagar o contato trocaria um contato
    indesejado por um buraco no comprovante de entrega.

    Encerrar é vencer a validade (`valid_until`) agora — e não uma marca
    nova. A escolha é pelo que já existe: todo caminho que **envia**
    (documento, confirmação, lembrete, aviso de horário, campanha) já
    recusa contato vencido, então o encerrado deixa de receber sem que
    nenhum desses caminhos precise saber que exclusão existe. Uma coluna
    nova "excluído" teria de ser lembrada em cada um, e o primeiro
    esquecido mandaria SMS para quem a clínica tirou da ficha.

    Junto, desliga as autorizações e revoga os links de documento ainda
    abertos: quem exclui um contato está dizendo que aquela pessoa não
    recebe mais nada daqui — inclusive o link que já está no celular dela.
    """
    from django.db import transaction
    from django.utils import timezone

    from communications.models import Delivery, DocumentAccessToken, MarketingRecipient

    with transaction.atomic():
        com_historico = (
            Delivery.objects.filter(contact=contact).exists()
            or DocumentAccessToken.objects.filter(contact=contact).exists()
            or MarketingRecipient.objects.filter(contact=contact).exists()
        )
        if not com_historico:
            contact.delete()
            return 'apagado'
        agora = timezone.now()
        DocumentAccessToken.objects.filter(
            contact=contact, revoked_at__isnull=True,
        ).update(revoked_at=agora)
        contact.valid_until = agora
        contact.sms_enabled = False
        contact.email_enabled = False
        contact.authorized_for_documents = False
        contact.legal_authority = False
        campos = ['valid_until', 'sms_enabled', 'email_enabled', 'authorized_for_documents',
                  'legal_authority', 'updated_at']
        if contact.marketing_opt_in_at and not contact.marketing_opt_out_at:
            contact.marketing_opt_out_at = agora
            campos.append('marketing_opt_out_at')
        contact.save(update_fields=campos)
        return 'encerrado'
