"""Laudos de exame enviados pelo paciente no portal.

O portal recebia só pedidos -- receita, relatório, pedido de exame --, e o
resultado do exame chegava pelo WhatsApp da recepção ou no papel, na
consulta. Aqui o paciente anexa o PDF e ele vai direto para o prontuário.

**Direto, e não para uma fila.** O pedido de receita passa pela fila
porque é ato médico: o médico decide se emite. Laudo de exame é fato que o
paciente já tem na mão; uma fila de aprovação só atrasaria o médico de ler
o que chegou. O que impede o laudo de entrar calado é o aviso: o envio fica
"novo" no prontuário até alguém com acesso clínico marcar que viu.

**Só PDF, até cinco por envio, até 3 MB cada.** Os limites são do produto,
não do anexo comum (25 MB, sete formatos): o portal é público, e um
formulário público que aceita qualquer coisa vira depósito. Laudo de
laboratório e de imagem sai em PDF; foto de tela e documento de Word são
justamente o que a tela pede para não mandar.

**Tudo ou nada.** Ou os cinco entram, ou nenhum: o paciente que vê "deu
erro no terceiro" não sabe se os dois primeiros chegaram, e manda de novo
-- e o médico recebe os dois primeiros em dobro.

**Não passa pela janela de retorno** (`portal_retorno`). A barreira dos
180 dias existe porque prescrever sem exame direto é vedado (CEM, art.
37); mandar o resultado de um exame não é pedir ato médico. Quem está
voltando depois de dois anos é exatamente quem mais traz exame novo.
"""

import datetime
from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from audit.services import protect_ip
from base.net import client_ip

from . import portal
from .models import AttachmentClassification, PortalExamType, PortalExamUpload

MAX_ARQUIVOS = 5
MAX_BYTES = 3 * 1024 * 1024

#: Envios por IP, por hora. Cada envio carrega até cinco arquivos; seis por
#: hora são trinta laudos, folga de sobra para uma família inteira e pouco
#: para quem quisesse encher o disco da clínica.
ENVIOS_POR_HORA = 6

#: O mais antigo que se aceita. Não é regra clínica -- exame antigo vale --,
#: é o que separa uma data digitada errado (0202, 1026) de uma data velha.
DATA_MINIMA = datetime.date(1950, 1, 1)


class EnvioRecusado(Exception):
    """O envio inteiro foi recusado; a mensagem é para o paciente."""


@dataclass
class Linha:
    """Um exame do formulário, já conferido."""

    numero: int
    conteudo: bytes
    nome_original: str
    tipo: str
    outro: str
    data: datetime.date
    local: str
    nome_gravado: str = field(default='')

    @property
    def rotulo(self):
        if self.tipo == PortalExamType.OUTRO and self.outro:
            return self.outro
        return PortalExamType(self.tipo).label


def _data(texto):
    try:
        return datetime.date.fromisoformat((texto or '').strip())
    except ValueError:
        return None


def ler_formulario(post, files):
    """As linhas preenchidas do formulário, conferidas.

    Devolve a lista de `Linha` ou levanta `EnvioRecusado` com a primeira
    coisa a corrigir. A conferência é toda feita **antes** de gravar
    qualquer arquivo, que é o que permite o tudo ou nada.
    """
    from .validators import UploadRejected, validate_upload

    # Conta o que chegou, e não só as cinco linhas que a tela desenha: um
    # formulário montado à mão pode mandar `arquivo_7`.
    enviados = [k for k in files if files.get(k)]
    if len(enviados) > MAX_ARQUIVOS:
        raise EnvioRecusado(f'Envie no máximo {MAX_ARQUIVOS} arquivos de cada vez.')

    hoje = timezone.localdate()
    linhas = []
    for i in range(1, MAX_ARQUIVOS + 1):
        arquivo = files.get(f'arquivo_{i}')
        tipo = (post.get(f'tipo_{i}') or '').strip()
        outro = (post.get(f'outro_{i}') or '').strip()
        data_texto = (post.get(f'data_{i}') or '').strip()
        local = (post.get(f'local_{i}') or '').strip()

        if arquivo is None:
            if any([tipo, outro, data_texto, local]):
                raise EnvioRecusado(
                    f'No exame {i}, falta escolher o arquivo PDF. '
                    f'Se não for enviar esse exame, deixe a linha em branco.'
                )
            continue

        if not arquivo.name.lower().endswith('.pdf'):
            raise EnvioRecusado(
                f'O arquivo do exame {i} não é PDF. Este canal aceita apenas arquivos PDF.'
            )
        if arquivo.size > MAX_BYTES:
            raise EnvioRecusado(
                f'O arquivo do exame {i} tem {arquivo.size / (1024 * 1024):.1f} MB. '
                f'O limite é de 3 MB por arquivo.'
            )
        if tipo not in PortalExamType.values:
            raise EnvioRecusado(f'No exame {i}, escolha qual é o exame.')
        if tipo == PortalExamType.OUTRO and not outro:
            raise EnvioRecusado(f'No exame {i}, escreva o nome do exame.')
        data = _data(data_texto)
        if data is None:
            raise EnvioRecusado(f'No exame {i}, informe a data em que o exame foi realizado.')
        if data > hoje:
            raise EnvioRecusado(f'No exame {i}, a data de realização está no futuro.')
        if data < DATA_MINIMA:
            raise EnvioRecusado(f'No exame {i}, confira a data de realização.')
        if not local:
            raise EnvioRecusado(
                f'No exame {i}, informe onde o exame foi feito (laboratório, clínica ou profissional).'
            )

        conteudo = arquivo.read()
        linha = Linha(
            numero=i, conteudo=conteudo, nome_original=Path(arquivo.name).name[:255],
            tipo=tipo, outro=outro[:120], data=data, local=local[:160],
        )
        # O nome gravado é gerado, e não o do paciente: o validador de nome
        # recusa acento e parêntese, que é o que "Ressonância (1).pdf" tem.
        # Tipo e data no nome também são o que o médico lê na lista.
        base = slugify(linha.rotulo)[:60] or 'exame'
        linha.nome_gravado = f'{base}_{data.isoformat()}_{i}.pdf'
        try:
            validate_upload(conteudo, linha.nome_gravado)
        except UploadRejected:
            # O conteúdo não é PDF (renomeado, corrompido). A mensagem do
            # validador fala de extensão, que o paciente não escolheu.
            raise EnvioRecusado(
                f'O arquivo do exame {i} não é um PDF válido. Confira se ele abre no '
                f'seu computador ou celular e tente de novo.'
            ) from None
        linhas.append(linha)

    if not linhas:
        raise EnvioRecusado('Escolha ao menos um arquivo PDF para enviar.')
    return linhas


def limite_excedido(request):
    return portal._rate_limit(request, 'exames', ENVIOS_POR_HORA, 3600)


def receber(request, tenant, patient, linhas, requester_name, requester_is_patient):
    """Grava os laudos no prontuário, todos ou nenhum.

    Os arquivos entram em quarentena e só ficam disponíveis depois do
    antivírus, como qualquer anexo. Se algo falhar no meio, os arquivos já
    escritos são apagados junto com o rollback -- o disco não tem
    transação, e sem isso sobraria arquivo sem linha no banco.
    """
    from audit.services import record_audit_event
    from notifications.services import notify_capability, patient_context
    from tenancy.permissions import Capability

    from .storage import QuotaExceeded, receive_upload
    from .tasks import scan_attachment

    dados = request.session.get(portal.SESSION_KEY) or {}
    ciencia = (
        timezone.datetime.fromisoformat(dados['privacy_at'])
        if dados.get('privacy_at') else timezone.now()
    )
    ip = protect_ip(client_ip(request))

    escritos = []
    try:
        with transaction.atomic():
            envios = []
            for linha in linhas:
                # Contexto e autor nulos: quem envia não tem conta, e
                # fabricar um `AccessContext` ou um usuário para isso poria
                # na trilha alguém que nunca tocou no arquivo.
                # `receive_upload` não usa o contexto.
                anexo = receive_upload(
                    None, tenant, patient, None, linha.conteudo,
                    linha.nome_gravado, AttachmentClassification.CLINICAL,
                    document_date=linha.data,
                )
                escritos.append(anexo.storage_key)
                envios.append(PortalExamUpload.objects.create(
                    tenant=tenant, patient=patient, attachment=anexo,
                    exam_type=linha.tipo,
                    exam_other=linha.outro if linha.tipo == PortalExamType.OUTRO else '',
                    performed_on=linha.data, performed_at_place=linha.local,
                    original_filename=linha.nome_original,
                    requester_name=requester_name[:255],
                    requester_is_patient=requester_is_patient,
                    privacy_ack_at=ciencia,
                    privacy_notice_version=portal.PRIVACY_NOTICE_VERSION,
                    origin_ip_protected=ip,
                ))
                transaction.on_commit(
                    lambda anexo_id=str(anexo.id): scan_attachment.delay(anexo_id)
                )
            for envio in envios:
                record_audit_event(
                    None, tenant.id, 'documents.portal_exam_uploaded',
                    object_type='attachment', object_id=envio.attachment_id, outcome='success',
                    integrity_metadata={'exam_type': envio.exam_type},
                )
            quantos = len(envios)
            notify_capability(
                tenant, Capability.READ_CLINICAL, kind='portal_exam',
                sanitized_title=(
                    'Exame enviado pelo paciente no portal' if quantos == 1
                    else f'{quantos} exames enviados pelo paciente no portal'
                ),
                target_type='portal_exam', target_id=patient.id,
                context=patient_context(
                    patient, requester=('' if requester_is_patient else requester_name),
                ),
            )
    except QuotaExceeded:
        _apagar(escritos)
        # O motivo real (espaço da clínica) não é do paciente, e dizer
        # quanto a clínica usa seria informação dela.
        raise EnvioRecusado(
            'Não foi possível receber os arquivos agora. Entre em contato com a clínica.'
        ) from None
    except BaseException:
        _apagar(escritos)
        raise

    portal.clear(request)
    return envios


def _apagar(caminhos):
    for caminho in caminhos:
        try:
            Path(caminho).unlink(missing_ok=True)
        except OSError:
            pass


def pendentes(patient):
    """Envios do portal que nenhum médico marcou como vistos."""
    return (
        PortalExamUpload.objects
        .filter(tenant_id=patient.tenant_id, patient=patient, acknowledged_at=None)
        .select_related('attachment')
        .order_by('-created_at')
    )


def marcar_vistos(context, patient, membership_id):
    """Marca como vistos todos os envios pendentes do paciente."""
    from audit.services import record_audit_event

    quantos = (
        PortalExamUpload.objects
        .filter(tenant_id=context.tenant_id, patient=patient, acknowledged_at=None)
        .update(acknowledged_at=timezone.now(), acknowledged_by_id=membership_id)
    )
    if quantos:
        record_audit_event(
            context.user_id, context.tenant_id, 'documents.portal_exam_acknowledged',
            object_type='patient', object_id=patient.id, outcome='success',
            integrity_metadata={'quantos': quantos},
        )
    return quantos
