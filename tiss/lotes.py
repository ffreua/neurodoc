"""Lotes de guias: montar, gerar o arquivo, registrar envio e retorno.

## As quatro coisas que este módulo não confunde

**Gerar** o arquivo não é **enviar**; enviar não é ter **protocolo**; e
nenhuma das três é **receber**. A tela registra cada etapa à mão — o
NeuroDoc não fala com portal de operadora —, e **nenhuma toca no
financeiro**: o recebível da consulta continua sendo baixado pelo
pagamento, como sempre. Recusa do arquivo não apaga dívida nem pagamento.

## Montar é decidir; gerar é escrever

`criar_lotes` decide tudo o que vai no arquivo — guias, número, data e
hora da transação — numa transação com trava nas guias, e o banco recusa a
guia em dois lotes ativos (`tiss_lote_guia_ativa_uniq`). O arquivo é
escrito depois, no worker (`gerar_arquivo`), a partir do **snapshot** de
cada guia: os bytes não dependem de quando a tarefa roda. Repetir a tarefa
— o worker caiu, a mensagem chegou duas vezes — não emite lote novo nem
numeração nova; regenera o mesmo arquivo, ou não faz nada se ele já está
pronto.

## O que decide se a guia entra

Fechada, sem lote ativo, credenciamento que exporta para cobrança, e
**fechada na versão que o credenciamento usa hoje** — guia de 4.00.00 com
o credenciamento já em 4.03.00 precisa de revisão, para os campos serem
conferidos de novo na versão nova. Uma seleção nunca perde guia em
silêncio: o plano lista as recusadas com o motivo antes da confirmação.

## Ciclo

A guia pertence ao ciclo da sua `data_referencia` — o dia do último
procedimento, gravado no fechamento. Dois ciclos por credenciamento
(1º ao último dia; 15 a 14) e o período manual.
"""

import calendar
import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import record_audit_event

from . import versoes
from .models import (
    CicloFechamento, Configuracao, EstadoGuia, EstadoLote, Guia, Lote, LoteGuia, ResultadoLote,
    Sequencia,
)

log = logging.getLogger(__name__)

LIMITE_ANS = 100
MAX_ERROS_GRAVADOS = 30


class LoteRecusado(Exception):
    """Mensagem em português, para a tela."""


class ArquivoCorrompido(Exception):
    """O arquivo no disco não bate com o SHA-256 gravado. Para quem opera."""


# ------------------------------------------------------------------ ciclo

def periodo_do_ciclo(ciclo, referencia):
    """O período de faturamento que contém `referencia`: `(inicio, fim)`."""
    if ciclo == CicloFechamento.QUINZE:
        if referencia.day >= 15:
            inicio = referencia.replace(day=15)
        else:
            anterior = referencia.replace(day=1) - timedelta(days=1)
            inicio = anterior.replace(day=15)
        proximo = (inicio.replace(day=1) + timedelta(days=32)).replace(day=1)
        return inicio, proximo.replace(day=14)
    ultimo = calendar.monthrange(referencia.year, referencia.month)[1]
    return referencia.replace(day=1), referencia.replace(day=ultimo)


def periodo_anterior(ciclo, referencia):
    inicio, _ = periodo_do_ciclo(ciclo, referencia)
    return periodo_do_ciclo(ciclo, inicio - timedelta(days=1))


# ------------------------------------------------------------------ fila e plano

def elegiveis(tenant_id):
    """Guias fechadas que não estão em lote ativo."""
    return (
        Guia.objects.filter(tenant_id=tenant_id, estado=EstadoGuia.FECHADA)
        .exclude(participacoes__ativo=True)
        .select_related('paciente', 'credenciamento__operadora', 'credenciamento__prestador')
    )


def motivo_de_recusa(guia, checar_lote=True):
    """Por que a guia não entra em lote agora; `''` se entra.

    A fila já vem de `elegiveis`, sem guia em lote: ela passa
    `checar_lote=False` e economiza uma consulta por linha.
    """
    if guia.estado != EstadoGuia.FECHADA:
        return f'está {guia.get_estado_display().lower()}'
    if checar_lote and LoteGuia.objects.filter(guia=guia, ativo=True).exists():
        return 'já está em outro lote'
    cred = guia.credenciamento
    if cred is None or not cred.ativo:
        return 'credenciamento inativo'
    if not cred.exporta_para_cobranca:
        return f'a versão {cred.versao} é histórica e o aceite da operadora não foi registrado'
    if guia.versao != cred.versao:
        return (f'fechada na versão {guia.versao}, e o credenciamento usa a {cred.versao} '
                'hoje: abra uma revisão para conferir os campos na versão nova')
    if not guia.snapshot.get('guia'):
        return 'fechada antes da geração de XML: abra uma revisão para fechá-la de novo'
    return ''


@dataclass
class Grupo:
    credenciamento: object
    tipo: str
    versao: str
    guias: list = field(default_factory=list)

    @property
    def total(self):
        return sum((Decimal(g.snapshot['total']) for g in self.guias), Decimal('0.00'))

    @property
    def quantidade(self):
        return len(self.guias)


@dataclass
class Plano:
    grupos: list
    recusadas: list

    @property
    def assinatura(self):
        """Muda se qualquer guia mudar de lote planejado: a confirmação compara."""
        partes = []
        for g in self.grupos:
            partes.append(f'{g.credenciamento.id}|{g.tipo}|{g.versao}|' + ','.join(str(x.id) for x in g.guias))
        return hashlib.sha256('\n'.join(partes).encode()).hexdigest()[:32]


def _ordem(guia):
    n = guia.numero_prestador
    return (guia.data_referencia or date.min, len(n), n)


def planejar(tenant_id, guia_ids):
    """Divide a seleção em lotes: credenciamento × tipo × versão, até o limite."""
    guias = list(
        Guia.objects.filter(tenant_id=tenant_id, id__in=list(guia_ids))
        .select_related('credenciamento__operadora', 'credenciamento__prestador', 'paciente')
    )
    recusadas, aceitas = [], []
    for g in guias:
        motivo = motivo_de_recusa(g)
        (recusadas.append((g, motivo)) if motivo else aceitas.append(g))
    chaves = {}
    for g in sorted(aceitas, key=_ordem):
        chaves.setdefault((g.credenciamento_id, g.tipo, g.versao), []).append(g)
    grupos = []
    for (_, tipo, versao), lista in sorted(
        chaves.items(), key=lambda kv: (kv[1][0].credenciamento.operadora.name, kv[0][1]),
    ):
        cred = lista[0].credenciamento
        limite = min(cred.limite_guias_por_lote or LIMITE_ANS, LIMITE_ANS)
        for i in range(0, len(lista), limite):
            grupos.append(Grupo(cred, tipo, versao, lista[i:i + limite]))
    return Plano(grupos, sorted(recusadas, key=lambda r: _ordem(r[0])))


def _proximo_lote(tenant_id):
    seq, _ = Sequencia.objects.select_for_update().get_or_create(tenant_id=tenant_id, nome='lote')
    seq = Sequencia.objects.select_for_update().get(id=seq.id)
    numero = seq.proximo
    seq.proximo = numero + 1
    seq.save(update_fields=['proximo', 'updated_at'])
    return str(numero)


def _exige_exportar(context):
    from tenancy.permissions import Capability

    if not context.can(Capability.TISS_EXPORT):
        raise LoteRecusado('Você não tem permissão para gerar lotes.')
    if not Configuracao.objects.filter(ativo=True).exists():
        raise LoteRecusado('O faturamento TISS está desligado nesta instalação.')


def criar_lotes(context, user, guia_ids, assinatura, periodo=(None, None)):
    """Cria os lotes do plano confirmado e põe a geração na fila do worker.

    `assinatura` é a do plano que a pessoa viu: se a seleção mudou entre
    ver e confirmar (outra pessoa montou lote com uma das guias, uma guia
    foi revisada), nada é criado e a tela mostra o plano de novo.
    """
    _exige_exportar(context)
    with transaction.atomic():
        # Trava as guias em ordem de id — a mesma ordem para todo mundo,
        # sem espera circular entre dois operadores.
        travadas = list(
            Guia.objects.select_for_update().filter(tenant_id=context.tenant_id, id__in=list(guia_ids))
            .order_by('id').values_list('id', flat=True)
        )
        plano = planejar(context.tenant_id, travadas)
        if plano.assinatura != assinatura:
            raise LoteRecusado('A seleção mudou desde que o plano foi montado. Confira o plano de novo.')
        if not plano.grupos:
            raise LoteRecusado('Nenhuma guia da seleção pode entrar em lote.')
        agora = timezone.localtime().replace(microsecond=0)
        criados = []
        for grupo in plano.grupos:
            lote = Lote.objects.create(
                tenant_id=context.tenant_id, numero=_proximo_lote(context.tenant_id),
                credenciamento=grupo.credenciamento, tipo=grupo.tipo, versao=grupo.versao,
                periodo_inicio=periodo[0], periodo_fim=periodo[1], transacao_em=agora,
                quantidade=grupo.quantidade, total=grupo.total, solicitado_por=user,
            )
            try:
                with transaction.atomic():
                    LoteGuia.objects.bulk_create([
                        LoteGuia(tenant_id=context.tenant_id, lote=lote, guia=g) for g in grupo.guias
                    ])
            except IntegrityError:
                raise LoteRecusado('Uma das guias acabou de entrar em outro lote. Confira o plano de novo.') from None
            record_audit_event(
                user, context.tenant_id, 'tiss.lote_criado', object_type='lote_tiss', object_id=lote.id,
                outcome='success', integrity_metadata={
                    'numero': lote.numero, 'guias': lote.quantidade, 'total': str(lote.total),
                    'versao': lote.versao, 'tipo': lote.tipo,
                },
            )
            criados.append(lote)
        for lote in criados:
            transaction.on_commit(lambda i=lote.id: _enfileirar(i))
    return criados


def _enfileirar(lote_id):
    from .tasks import gerar_lote

    gerar_lote.delay(str(lote_id))


# ------------------------------------------------------------------ geração

def _pasta(tenant_id):
    pasta = Path(settings.MEDIA_ROOT) / str(tenant_id) / 'tiss'
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _ainda_autorizado(lote):
    """As três chaves e quem pediu, conferidos de novo antes de escrever."""
    from tenancy.models import Membership, MembershipStatus, TenantStatus
    from tenancy.permissions import Capability, capabilities_for
    from tenancy.plans import has_tiss

    if not Configuracao.objects.filter(ativo=True).exists():
        return 'O faturamento TISS foi desligado na instalação.'
    tenant = lote.tenant
    if tenant.status != TenantStatus.ACTIVE:
        return 'A clínica não está ativa.'
    if not (has_tiss(tenant.plan) and tenant.tiss_liberado):
        return 'O TISS não está liberado para esta clínica (plano ou liberação).'
    vinculo = (
        Membership.objects.filter(tenant_id=tenant.id, user_id=lote.solicitado_por_id,
                                  status=MembershipStatus.ACTIVE).first()
        if lote.solicitado_por_id else None
    )
    if vinculo is None:
        return 'Quem pediu o lote não tem mais vínculo ativo com a clínica.'
    caps = capabilities_for(vinculo.roles, clinically_enabled=vinculo.can_practice_clinically(),
                            ai_contracted=False, tiss_contracted=True)
    if Capability.TISS_EXPORT not in caps:
        return 'Quem pediu o lote não tem mais permissão para gerar lotes.'
    if not lote.credenciamento.exporta_para_cobranca:
        return 'O credenciamento não exporta mais para cobrança (versão histórica sem aceite).'
    return ''


def snapshots_do_lote(lote):
    participacoes = (
        LoteGuia.objects.filter(lote=lote, ativo=True).select_related('guia').order_by('created_at', 'id')
    )
    guias = sorted((p.guia for p in participacoes), key=_ordem)
    return guias


def _falha(lote, erros):
    lote.estado = EstadoLote.FALHA
    lote.erros = list(erros)[:MAX_ERROS_GRAVADOS]
    lote.tentativas += 1
    lote.save(update_fields=['estado', 'erros', 'tentativas', 'updated_at'])
    record_audit_event(
        None, lote.tenant_id, 'tiss.lote_falhou', object_type='lote_tiss', object_id=lote.id,
        outcome='failure', integrity_metadata={'numero': lote.numero, 'erros': len(lote.erros)},
    )
    return lote


def gerar_arquivo(lote_id):
    """Escreve o arquivo do lote. Idempotente — ver o topo do módulo."""
    from .xml import GERADOR, XmlInvalido, mensagem_lote

    with transaction.atomic():
        lote = (
            Lote.objects.select_for_update(of=('self',))
            .select_related('tenant', 'credenciamento__operadora', 'credenciamento__prestador')
            .filter(id=lote_id).first()
        )
        if lote is None or lote.estado != EstadoLote.GERANDO:
            return lote
        motivo = _ainda_autorizado(lote)
        if motivo:
            return _falha(lote, [motivo])
        guias = snapshots_do_lote(lote)
        fora = [g.numero_prestador for g in guias if g.estado != EstadoGuia.FECHADA]
        if fora:
            return _falha(lote, [
                f'A guia {n} foi cancelada ou substituída depois de entrar no lote. '
                'Cancele este lote e monte outro.' for n in fora
            ])
        cred = lote.credenciamento
        identificacao = cred.identificacao
        documento = cred.codigo_na_operadora if identificacao == 'codigo' else cred.prestador.documento
        try:
            dados, valor_hash = mensagem_lote(
                versao=lote.versao, tipo=lote.tipo, numero_lote=lote.numero,
                transacao_em=timezone.localtime(lote.transacao_em),
                prestador_id=(identificacao, documento),
                registro_ans=cred.operadora.ans_registration,
                snapshots=[g.snapshot for g in guias],
            )
        except XmlInvalido as exc:
            return _falha(lote, [str(exc)])
        erros = versoes.validar(lote.versao, dados)
        if erros:
            return _falha(lote, ['O arquivo não passou no XSD oficial da versão ' + lote.versao + ':', *erros])

        destino = _pasta(lote.tenant_id) / f'lote-{lote.numero}-{lote.id}.xml'
        temporario = destino.with_suffix('.parcial')
        fd = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as fh:
            fh.write(dados)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporario, destino)

        lote.arquivo = str(destino)
        lote.sha256 = hashlib.sha256(dados).hexdigest()
        lote.tamanho = len(dados)
        lote.hash_tiss = valor_hash
        lote.gerador = GERADOR
        lote.gerado_em = timezone.now()
        lote.tentativas += 1
        lote.erros = []
        lote.estado = EstadoLote.PRONTO
        lote.save()
        record_audit_event(
            None, lote.tenant_id, 'tiss.lote_gerado', object_type='lote_tiss', object_id=lote.id,
            outcome='success', integrity_metadata={
                'numero': lote.numero, 'sha256': lote.sha256, 'versao': lote.versao, 'guias': len(guias),
            },
        )
        return lote


def ler_arquivo(lote):
    """Os bytes do arquivo pronto, conferidos contra o SHA-256 gravado."""
    if lote.estado == EstadoLote.GERANDO or not lote.arquivo:
        raise LoteRecusado('O arquivo deste lote ainda não está pronto.')
    dados = Path(lote.arquivo).read_bytes()
    if hashlib.sha256(dados).hexdigest() != lote.sha256:
        raise ArquivoCorrompido(f'lote {lote.id}: arquivo diferente do SHA-256 gravado')
    return dados


# ------------------------------------------------------------------ transições

def _travar(context, lote):
    lote = Lote.objects.select_for_update().get(id=lote.id)
    if lote.tenant_id != context.tenant_id:
        raise LoteRecusado('Lote de outra clínica.')
    return lote


@transaction.atomic
def tentar_de_novo(context, user, lote):
    _exige_exportar(context)
    lote = _travar(context, lote)
    if lote.estado != EstadoLote.FALHA:
        raise LoteRecusado('Só lote com falha é gerado de novo.')
    lote.estado = EstadoLote.GERANDO
    lote.save(update_fields=['estado', 'updated_at'])
    record_audit_event(user, context.tenant_id, 'tiss.lote_regerado', object_type='lote_tiss',
                       object_id=lote.id, outcome='success', integrity_metadata={'numero': lote.numero})
    transaction.on_commit(lambda: _enfileirar(lote.id))
    return lote


@transaction.atomic
def registrar_envio(context, user, lote, data_envio, protocolo):
    """Registra que o arquivo foi enviado. Não toca no financeiro."""
    _exige_exportar(context)
    lote = _travar(context, lote)
    if lote.estado != EstadoLote.PRONTO:
        raise LoteRecusado('Só lote com arquivo pronto é enviado.')
    if data_envio is None:
        raise LoteRecusado('Informe a data do envio.')
    if data_envio > timezone.localdate():
        raise LoteRecusado('A data do envio não pode ser no futuro.')
    if lote.gerado_em and data_envio < timezone.localtime(lote.gerado_em).date():
        raise LoteRecusado('A data do envio não pode ser anterior à geração do arquivo.')
    anterior = (lote.enviado_em, lote.protocolo)
    lote.enviado_em = data_envio
    lote.protocolo = (protocolo or '').strip()[:30]
    lote.envio_registrado_por, lote.envio_registrado_em = user, timezone.now()
    lote.save()
    record_audit_event(
        user, context.tenant_id, 'tiss.lote_enviado', object_type='lote_tiss', object_id=lote.id,
        outcome='success', integrity_metadata={
            'numero': lote.numero, 'protocolo': lote.protocolo,
            'retificacao': anterior[0] is not None,
        },
    )
    return lote


@transaction.atomic
def registrar_resultado(context, user, lote, resultado, observacao):
    """O retorno da operadora. Recusa não apaga cobrança nem pagamento."""
    _exige_exportar(context)
    lote = _travar(context, lote)
    if not lote.enviado:
        raise LoteRecusado('Registre o envio antes do retorno.')
    if resultado not in ResultadoLote.values:
        raise LoteRecusado('Resultado inválido.')
    observacao = (observacao or '').strip()[:500]
    if resultado in (ResultadoLote.RECUSADO, ResultadoLote.PARCIAL) and not observacao:
        raise LoteRecusado('Escreva o que a operadora informou (motivo da recusa ou das glosas).')
    lote.resultado, lote.resultado_obs = resultado, observacao
    lote.resultado_por, lote.resultado_em = user, timezone.now()
    lote.save()
    record_audit_event(
        user, context.tenant_id, 'tiss.lote_retorno', object_type='lote_tiss', object_id=lote.id,
        outcome='success', integrity_metadata={'numero': lote.numero, 'resultado': resultado},
    )
    return lote


@transaction.atomic
def cancelar_lote(context, user, lote, motivo):
    """Cancela e solta as guias. Enviado, só se a operadora recusou o arquivo.

    O arquivo gerado continua no disco e no registro: é a prova do que foi
    (ou não foi) mandado.
    """
    _exige_exportar(context)
    lote = _travar(context, lote)
    motivo = (motivo or '').strip()
    if not motivo:
        raise LoteRecusado('Escreva o motivo do cancelamento.')
    if lote.estado == EstadoLote.CANCELADO:
        raise LoteRecusado('Este lote já está cancelado.')
    if lote.enviado and lote.resultado != ResultadoLote.RECUSADO:
        raise LoteRecusado(
            'Lote já enviado só é cancelado depois de registrada a recusa da operadora. '
            'Para reapresentar guias glosadas, libere cada uma com o motivo.'
        )
    lote.estado = EstadoLote.CANCELADO
    lote.cancelado_em, lote.cancelado_por, lote.motivo_cancelamento = timezone.now(), user, motivo[:255]
    lote.save()
    LoteGuia.objects.filter(lote=lote, ativo=True).update(
        ativo=False, liberada_motivo=f'Lote cancelado: {motivo}'[:255], updated_at=timezone.now(),
    )
    record_audit_event(
        user, context.tenant_id, 'tiss.lote_cancelado', object_type='lote_tiss', object_id=lote.id,
        outcome='success', integrity_metadata={'numero': lote.numero, 'motivo': motivo[:255]},
    )
    return lote


@transaction.atomic
def liberar_guia(context, user, lote, guia, motivo):
    """Reapresentação: a guia sai do lote enviado e pode entrar em outro.

    Ação distinta e justificada — o lote enviado continua como foi, com o
    arquivo, e a participação antiga fica no histórico com o motivo.
    """
    _exige_exportar(context)
    lote = _travar(context, lote)
    motivo = (motivo or '').strip()
    if not motivo:
        raise LoteRecusado('Escreva o motivo da reapresentação (a glosa, o erro a corrigir).')
    if not lote.enviado:
        raise LoteRecusado('Antes do envio, cancele o lote em vez de liberar guias.')
    participacao = LoteGuia.objects.filter(lote=lote, guia=guia, ativo=True).first()
    if participacao is None:
        raise LoteRecusado('Esta guia não está ativa neste lote.')
    participacao.ativo = False
    participacao.liberada_motivo = motivo[:255]
    participacao.save(update_fields=['ativo', 'liberada_motivo', 'updated_at'])
    record_audit_event(
        user, context.tenant_id, 'tiss.guia_liberada_do_lote', object_type='lote_tiss', object_id=lote.id,
        outcome='success', integrity_metadata={'numero': lote.numero, 'guia': guia.numero_prestador},
    )
    return participacao


def lote_ativo_da_guia(guia):
    p = LoteGuia.objects.filter(guia=guia, ativo=True).select_related('lote').first()
    return p.lote if p else None
