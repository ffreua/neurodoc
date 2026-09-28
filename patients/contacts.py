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
