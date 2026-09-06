from .models import PatientContact


def create_contact(context, patient, **fields):
    contact = PatientContact(tenant_id=context.tenant_id, patient=patient, **fields)
    contact.full_clean()
    contact.save()
    return contact


def authorized_document_contacts(patient):
    """Contacts eligible to receive documents — distinct from the general list."""
    return patient.contacts.filter(authorized_for_documents=True)
