"""Serviços da guia TISS: criar com o que já se sabe, conferir, fechar.

**O caminho curto é preencher sozinho; o caminho certo é dizer o que falta.**
A guia nasce com cobertura, credenciamento, profissionais, datas e — na de
Consulta — o procedimento e o preço da consulta já cobrada. O que não dá
para saber (senha de autorização, tipo de atendimento do exame, a
indicação clínica que só o médico escreve) vira **pendência** legível, e a
guia não fecha com pendência que impede. Nada é inventado: sem dado, o
campo fica vazio e a pendência diz quem o preenche.

**Quem decide se um código vale é o XSD da versão** (`versoes.dominio`);
o XML é da Sprint 3, mas a conferência dos domínios já é feita aqui, para a
guia não fechar com um código que a versão do credenciamento recusaria.

Transições (criar, fechar, cancelar, revisar) moram aqui, com trava e
trilha. A tela só chama.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from . import versoes
from .models import (
    Credenciamento, EstadoGuia, Guia, ItemGuia, ProfissionalTiss, Sequencia,
    TipoContratadoSolicitante, TipoGuia,
)

CENTAVO = Decimal('0.01')
#: A ANS manda usar 9999999 quando o prestador não tem CNES.
CNES_INEXISTENTE = '9999999'


class GuiaRecusada(Exception):
    """Mensagem em português, para a tela."""


@dataclass(frozen=True)
class Pendencia:
    campo: str
    mensagem: str
    impede: bool = True
    #: Quem resolve: 'recepcao', 'medico', 'gestor'. Diz à tela a quem apontar.
    quem: str = 'recepcao'


# ------------------------------------------------------------------ números

def _proximo_numero(tenant_id):
    """Reserva o próximo número sob trava, na transação de quem chama."""
    seq, _ = Sequencia.objects.select_for_update().get_or_create(tenant_id=tenant_id, nome='guia')
    seq = Sequencia.objects.select_for_update().get(id=seq.id)
    numero = seq.proximo
    seq.proximo = numero + 1
    seq.save(update_fields=['proximo', 'updated_at'])
    return str(numero)


# ------------------------------------------------------------------ preço e código

def total_do_item(quantidade, valor_unitario, fator):
    """Quantidade × unitário × fator, arredondado ao centavo — uma vez só."""
    bruto = Decimal(quantidade) * Decimal(valor_unitario) * Decimal(fator)
    return bruto.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def preco_contratado(guia, codigo, data, executante=None):
    """O honorário do contrato para o procedimento, e de onde veio.

    Procura a regra de convênio do plano da cobertura com o procedimento de
    mesmo **código** (as releases TUSS trocam; o código fica), vigente na
    data, a do médico executante antes da geral. Devolve `(valor, origem)`
    ou `(None, motivo)`.
    """
    from finance.models import FeeSchedule, PaymentCategory

    if guia.cobertura_id is None:
        return None, 'sem convênio na guia'
    qs = (
        FeeSchedule.objects
        .filter(tenant_id=guia.tenant_id, payment_category=PaymentCategory.INSURANCE,
                plan_id=guia.cobertura.plan_id, procedure__code=codigo, effective_from__lte=data)
        .exclude(effective_to__lt=data)
        .select_related('physician__user')
    )
    membro = executante.membership_id if executante and executante.membership_id else None
    # Só a regra geral do plano ou a do médico executante; a dele primeiro,
    # e em cada uma a vigência mais recente.
    candidatas = sorted(
        (f for f in qs if f.physician_id is None or (membro and f.physician_id == membro)),
        key=lambda f: (f.physician_id is None, -f.effective_from.toordinal()),
    )
    if not candidatas:
        return None, 'sem honorário de convênio cadastrado para este código e plano'
    regra = candidatas[0]
    quem = (regra.physician.user.get_full_name() or 'médico') if regra.physician_id else 'geral do plano'
    return regra.gross_amount, f'Tabela de honorários ({quem}), vigente desde {regra.effective_from:%d/%m/%Y}'


def conferir_codigo(tabela, codigo, data):
    """O termo TUSS na data do serviço: `(descricao, release, aviso)`.

    Procura na release ativa e, se não estiver lá, nas anteriores — o código
    retirado hoje pode ter valido no dia do atendimento (A3 §207). Levanta
    `GuiaRecusada` se o código não existe, ou se não valia naquela data.
    Tabela própria da operadora (`00`) não passa pelo catálogo.
    """
    from catalogs.models import CatalogReleaseStatus, CatalogSystem, ProcedureCode

    codigo = (codigo or '').strip()
    if not codigo:
        raise GuiaRecusada('Informe o código do procedimento.')
    if tabela != '22':
        return None, '', 'Código fora da tabela 22: conferido só pela operadora.'
    linhas = list(
        ProcedureCode.objects.filter(release__system=CatalogSystem.TUSS, code=codigo)
        .select_related('release').order_by('-release__imported_at')
    )
    if not linhas:
        raise GuiaRecusada(f'O código {codigo} não está na tabela TUSS de procedimentos.')
    ativa = next((p for p in linhas if p.release.status == CatalogReleaseStatus.ACTIVE), linhas[0])
    for termo in [ativa, *[p for p in linhas if p is not ativa]]:
        if termo.starts_on is None and termo.ends_on is None:
            continue
        if termo.starts_on and termo.starts_on > data:
            continue
        if termo.ends_on and termo.ends_on < data:
            continue
        return termo.description[:150], termo.release.version, ''
    if all(p.starts_on is None and p.ends_on is None for p in linhas):
        return ativa.description[:150], ativa.release.version, (
            'A tabela sincronizada não traz a vigência deste código; confira no portal da operadora.'
        )
    raise GuiaRecusada(f'O código {codigo} não estava vigente na TUSS em {data:%d/%m/%Y}.')


# ------------------------------------------------------------------ criar

def _cobertura_sugerida(paciente, appointment, dia):
    from scheduling.models import BillingMode

    if appointment is not None and appointment.billing_mode == BillingMode.INSURANCE:
        return appointment.coverage
    from finance.receivables import _active_coverage

    return _active_coverage(paciente, dia)


def _credenciamento_para(tenant_id, cobertura, dia):
    if cobertura is None:
        return None
    candidatos = [
        c for c in Credenciamento.objects.filter(
            tenant_id=tenant_id, ativo=True, operadora_id=cobertura.plan.insurer_id,
        ).select_related('prestador')
        if (c.vigencia_inicio is None or c.vigencia_inicio <= dia)
        and (c.vigencia_fim is None or c.vigencia_fim >= dia)
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _profissional_de(tenant_id, membership_id):
    if not membership_id:
        return None
    achados = list(ProfissionalTiss.objects.filter(tenant_id=tenant_id, membership_id=membership_id, ativo=True)[:2])
    return achados[0] if len(achados) == 1 else None


_TIPO_CONSULTA = {'first_visit': '1', 'follow_up': '2', 'return_visit': '2'}


@transaction.atomic
def criar_guia(context, user, paciente, tipo, appointment=None):
    """Cria a guia em preenchimento, com o que já se sabe.

    `appointment`, quando vem, tem de ser deste paciente e desta clínica.
    Na guia de Consulta, se o horário já teve chegada e cobrança, o item da
    consulta nasce com o código do honorário que cobrou e **o recebível
    vinculado** — a guia fatura a cobrança existente, não cria outra.
    """
    if tipo not in TipoGuia.values:
        raise GuiaRecusada('Tipo de guia inválido.')
    if paciente.tenant_id != context.tenant_id:
        raise GuiaRecusada('Paciente de outra clínica.')
    if appointment is not None:
        # Relido do banco: a forma de cobrança e o convênio decidem a guia,
        # e uma instância carregada antes de alguém trocá-los levaria o
        # convênio errado para a cobrança.
        appointment = type(appointment).objects.get(id=appointment.id)
    if appointment is not None and (
        appointment.tenant_id != context.tenant_id or appointment.patient_id != paciente.id
    ):
        raise GuiaRecusada('Este horário não é deste paciente.')

    hoje = timezone.localdate()
    dia = timezone.localtime(appointment.starts_at).date() if appointment else hoje
    cobertura = _cobertura_sugerida(paciente, appointment, dia)
    credenciamento = _credenciamento_para(context.tenant_id, cobertura, dia)
    medico = _profissional_de(context.tenant_id, appointment.physician_membership_id if appointment else None)

    guia = Guia(
        tenant_id=context.tenant_id, tipo=tipo, paciente=paciente, cobertura=cobertura,
        credenciamento=credenciamento, numero_prestador=_proximo_numero(context.tenant_id),
        data_emissao=hoje, carteira=(cobertura.member_number if cobertura else '')[:20],
        validade_carteira=cobertura.ends_on if cobertura else None,
        executante=medico, appointment=appointment, criada_por=user,
    )
    if tipo == TipoGuia.CONSULTA:
        guia.tipo_consulta = _TIPO_CONSULTA.get(appointment.type, '') if appointment else ''
    else:
        guia.solicitante = medico
        guia.data_solicitacao = dia
    guia.full_clean(exclude=['tenant'])
    guia.save()

    if tipo == TipoGuia.CONSULTA and appointment is not None:
        _item_da_consulta_cobrada(guia, appointment, dia)

    record_audit_event(
        user, context.tenant_id, 'tiss.guia_criada', object_type='guia_tiss', object_id=guia.id,
        outcome='success', integrity_metadata={
            'tipo': tipo, 'numero': guia.numero_prestador,
            'origem': 'agenda' if appointment else 'ficha',
        },
    )
    return guia


def _item_da_consulta_cobrada(guia, appointment, dia):
    """O item da consulta, se ela já foi cobrada no check-in.

    Sem cobrança, não há item: agendamento não prova que a consulta
    aconteceu. Com cobrança, o código vem do procedimento da regra que
    cobrou; sem procedimento na regra, o item espera o código (pendência).
    """
    from catalogs.models import ProcedureCode
    from finance.models import ChargeKind, Receivable, ReceivableStatus

    recebivel = (
        Receivable.objects.filter(
            tenant_id=guia.tenant_id, appointment=appointment, charge_kind=ChargeKind.CONSULTATION,
        ).exclude(status=ReceivableStatus.CANCELLED).first()
    )
    if recebivel is None or ItemGuia.objects.filter(recebivel=recebivel).exists():
        return None
    procedimento_id = (recebivel.fee_snapshot or {}).get('procedure_id')
    termo = ProcedureCode.objects.filter(id=procedimento_id).first() if procedimento_id else None
    codigo = termo.code if termo else ''
    descricao = termo.description[:150] if termo else ''
    valor, origem = (None, '')
    if codigo:
        valor, origem = preco_contratado(guia, codigo, dia, guia.executante)
    if valor is None:
        valor, origem = recebivel.charged_amount, 'Valor da cobrança do check-in'
    return ItemGuia.objects.create(
        tenant_id=guia.tenant_id, guia=guia, sequencial=1, data_execucao=dia,
        codigo=codigo, descricao=descricao, release_tuss=termo.release.version if termo else '',
        quantidade=1, valor_unitario=valor, valor_total=total_do_item(1, valor, 1),
        preco_origem=origem, recebivel=recebivel,
    )


# ------------------------------------------------------------------ itens

def _travar_rascunho(guia):
    guia = Guia.objects.select_for_update().get(id=guia.id)
    if not guia.editavel:
        raise GuiaRecusada('Guia fechada não muda. Para corrigir, abra uma revisão.')
    return guia


@transaction.atomic
def gravar_item(context, user, guia, dados, item=None):
    """Inclui ou altera um procedimento realizado. `dados` vem do formulário."""
    guia = _travar_rascunho(guia)
    if guia.tenant_id != context.tenant_id:
        raise GuiaRecusada('Guia de outra clínica.')
    if item is not None and item.guia_id != guia.id:
        raise GuiaRecusada('Este procedimento é de outra guia.')
    if guia.tipo == TipoGuia.CONSULTA and item is None:
        existente = guia.itens.first()
        if existente is not None and not existente.codigo:
            # A consulta veio da cobrança do check-in sem código (a regra de
            # honorário não tinha procedimento): completar o item mantém o
            # vínculo com a cobrança, que remover e incluir perderia.
            item = existente
        elif existente is not None:
            raise GuiaRecusada('A guia de Consulta tem um procedimento só. Remova o atual para trocar.')

    tabela = dados.get('tabela') or '22'
    data = dados['data_execucao']
    descricao, release, _aviso = conferir_codigo(tabela, dados['codigo'], data)
    descricao = descricao or (dados.get('descricao') or '').strip()[:150]
    if not descricao:
        raise GuiaRecusada('Informe a descrição do procedimento.')
    quantidade = int(dados.get('quantidade') or 1)
    fator = Decimal(dados.get('fator') or '1.00')
    valor_informado = dados.get('valor_unitario')
    contrato, origem = preco_contratado(guia, dados['codigo'], data, guia.executante)
    motivo = (dados.get('preco_motivo') or '').strip()
    if valor_informado in (None, ''):
        if contrato is None:
            raise GuiaRecusada(f'Sem preço para este procedimento ({origem}). Informe o valor e o motivo.')
        valor = contrato
    else:
        valor = Decimal(valor_informado).quantize(CENTAVO)
        if contrato is None or valor != contrato:
            if not motivo:
                raise GuiaRecusada(
                    'O valor difere do honorário do contrato'
                    + (f' (R$ {contrato})' if contrato is not None else '')
                    + '. Escreva o motivo.'
                )
            origem = f'Informado por {user.get_full_name() or user.email}'
    if valor <= 0:
        raise GuiaRecusada('O valor do procedimento precisa ser maior que zero.')

    alvo = item or ItemGuia(
        tenant_id=guia.tenant_id, guia=guia,
        sequencial=(max([i.sequencial for i in guia.itens.all()] or [0]) + 1),
    )
    alvo.data_execucao = data
    alvo.hora_inicial = dados.get('hora_inicial')
    alvo.hora_final = dados.get('hora_final')
    alvo.tabela = tabela
    alvo.codigo = dados['codigo'].strip()
    alvo.descricao = descricao
    alvo.release_tuss = release
    alvo.quantidade = quantidade
    alvo.via_acesso = dados.get('via_acesso') or ''
    alvo.tecnica = dados.get('tecnica') or ''
    alvo.fator = fator
    alvo.valor_unitario = valor
    alvo.valor_total = total_do_item(quantidade, valor, fator)
    alvo.preco_origem = origem[:255]
    alvo.preco_motivo = motivo[:255] if motivo else ''
    alvo.full_clean(exclude=['tenant', 'guia', 'recebivel'])
    alvo.save()
    record_audit_event(
        user, context.tenant_id, 'tiss.item_gravado', object_type='guia_tiss', object_id=guia.id,
        outcome='success', integrity_metadata={
            'item': alvo.sequencial, 'codigo': alvo.codigo, 'preco_manual': bool(motivo),
        },
    )
    return alvo


@transaction.atomic
def remover_item(context, user, guia, item):
    guia = _travar_rascunho(guia)
    if item.guia_id != guia.id or guia.tenant_id != context.tenant_id:
        raise GuiaRecusada('Este procedimento é de outra guia.')
    sequencial = item.sequencial
    item.delete()
    # Renumera para o XML sair 1, 2, 3 — `sequencialItem` sem buraco.
    for n, restante in enumerate(guia.itens.order_by('sequencial'), start=1):
        if restante.sequencial != n:
            ItemGuia.objects.filter(id=restante.id).update(sequencial=n)
    record_audit_event(
        user, context.tenant_id, 'tiss.item_removido', object_type='guia_tiss', object_id=guia.id,
        outcome='success', integrity_metadata={'item': sequencial},
    )


# ------------------------------------------------------------------ pendências

def _no_dominio(versao, tipo, valor):
    dominio = versoes.dominio(versao, tipo)
    return not dominio or valor in dominio


def pendencias(guia):
    """O que falta para fechar, dito a quem resolve. Lista vazia = pode fechar."""
    from .validators import registro_ans_valido

    p = []
    v = guia.versao_efetiva
    cred = guia.credenciamento
    cob = guia.cobertura

    if cob is None:
        p.append(Pendencia('cobertura', 'Escolha o convênio do paciente (cobertura) da guia.'))
    if cred is None:
        p.append(Pendencia('credenciamento', 'Escolha o credenciamento: com que prestador e operadora esta guia é cobrada.'))
    else:
        if not cred.ativo:
            p.append(Pendencia('credenciamento', 'O credenciamento escolhido está inativo.', quem='gestor'))
        if cob is not None and cred.operadora_id != cob.plan.insurer_id:
            p.append(Pendencia('credenciamento', 'O credenciamento é de outra operadora que não a do convênio do paciente.'))
        if not registro_ans_valido(cred.operadora.ans_registration):
            p.append(Pendencia('credenciamento', 'A operadora está sem o registro ANS de seis dígitos.', quem='gestor'))
        if not cred.exporta_para_cobranca:
            p.append(Pendencia(
                'credenciamento',
                f'A versão {cred.versao} é histórica e o aceite da operadora não foi registrado: '
                'a guia só serve para conferência.', impede=False, quem='gestor',
            ))
    if not guia.carteira:
        p.append(Pendencia('carteira', 'Informe o número da carteira do beneficiário.'))
    if guia.validade_carteira and guia.validade_carteira < guia.data_emissao:
        p.append(Pendencia('validade_carteira', 'A carteira estava vencida na emissão.', impede=False))

    if guia.executante is None:
        p.append(Pendencia('executante', 'Informe o profissional executante (cadastro em Faturamento TISS).'))
    elif not _no_dominio(v, 'dm_CBOS', guia.executante.cbo):
        p.append(Pendencia('executante', f'O CBO {guia.executante.cbo} do executante não existe na versão {v}.', quem='gestor'))

    if not _no_dominio(v, 'dm_indicadorAcidente', guia.indicacao_acidente):
        p.append(Pendencia('indicacao_acidente', 'Indicação de acidente fora do domínio da versão.'))
    if v.startswith('4') and not _no_dominio(v, 'dm_regimeAtendimento', guia.regime_atendimento):
        p.append(Pendencia('regime_atendimento', 'Regime de atendimento fora do domínio da versão.'))
    for campo, tipo_dm, rotulo in (
        ('ausencia_cod_validacao', 'dm_ausenciaCodValidacao', 'Motivo da ausência do código de validação'),
        ('cobertura_especial', 'dm_cobEsp', 'Indicador de cobertura especial'),
        ('saude_ocupacional', 'dm_saudeOcupacional', 'Saúde ocupacional'),
    ):
        valor = getattr(guia, campo)
        if valor and not _no_dominio(v, tipo_dm, valor):
            p.append(Pendencia(campo, f'{rotulo}: o código {valor} não existe na versão {v}.'))

    itens = list(guia.itens.all())
    if guia.tipo == TipoGuia.CONSULTA:
        if not guia.tipo_consulta:
            p.append(Pendencia('tipo_consulta', 'Informe o tipo de consulta (primeira, retorno...).'))
        elif not _no_dominio(v, 'dm_tipoConsulta', guia.tipo_consulta):
            p.append(Pendencia('tipo_consulta', 'Tipo de consulta fora do domínio da versão.'))
        if len(itens) != 1:
            p.append(Pendencia('itens', 'A guia de Consulta tem exatamente um procedimento: a consulta realizada.'))
    else:
        if guia.solicitante is None:
            p.append(Pendencia('solicitante', 'Informe o profissional solicitante (pode ser de fora da clínica).'))
        elif not _no_dominio(v, 'dm_CBOS', guia.solicitante.cbo):
            p.append(Pendencia('solicitante', f'O CBO {guia.solicitante.cbo} do solicitante não existe na versão {v}.', quem='gestor'))
        if guia.contratado_solicitante_tipo != TipoContratadoSolicitante.PROPRIO and not (
            guia.contratado_solicitante_codigo and guia.contratado_solicitante_nome
        ):
            p.append(Pendencia('contratado_solicitante_codigo', 'Informe o código e o nome do contratado solicitante.'))
        if not _no_dominio(v, 'dm_caraterAtendimento', guia.carater_atendimento):
            p.append(Pendencia('carater_atendimento', 'Caráter do atendimento fora do domínio da versão.'))
        if not guia.tipo_atendimento:
            p.append(Pendencia('tipo_atendimento', 'Informe o tipo de atendimento.'))
        elif not _no_dominio(v, 'dm_tipoAtendimento', guia.tipo_atendimento):
            p.append(Pendencia(
                'tipo_atendimento',
                f'O tipo de atendimento {guia.tipo_atendimento} não existe na versão {v} '
                '(exame é 05 até a 4.00.01 e 23 a partir da 4.01.00).',
            ))
        if guia.tipo_consulta and not _no_dominio(v, 'dm_tipoConsulta', guia.tipo_consulta):
            p.append(Pendencia('tipo_consulta', 'Tipo de consulta fora do domínio da versão.'))
        if guia.motivo_encerramento and not _no_dominio(v, 'dm_motivoSaidaObito', guia.motivo_encerramento):
            p.append(Pendencia('motivo_encerramento', 'Motivo de encerramento fora do domínio da versão.'))
        if (guia.senha or guia.numero_operadora or guia.validade_senha) and not guia.data_autorizacao:
            p.append(Pendencia('data_autorizacao', 'Com senha ou número da operadora, informe a data da autorização.'))
        if not guia.indicacao_clinica:
            p.append(Pendencia(
                'indicacao_clinica', 'Indicação clínica em branco: muitas operadoras a exigem. Só o médico a preenche.',
                impede=False, quem='medico',
            ))
        if not itens:
            p.append(Pendencia('itens', 'Inclua os procedimentos realizados.'))

    for item in itens:
        if not item.codigo:
            p.append(Pendencia('itens', f'Procedimento {item.sequencial}: falta o código.'))
        if item.valor_total <= 0:
            p.append(Pendencia('itens', f'Procedimento {item.sequencial}: valor zerado.'))
        for campo, tipo_dm in (('via_acesso', 'dm_viaDeAcesso'), ('tecnica', 'dm_tecnicaUtilizada')):
            valor = getattr(item, campo)
            if valor and not _no_dominio(v, tipo_dm, valor):
                p.append(Pendencia('itens', f'Procedimento {item.sequencial}: {campo.replace("_", " ")} fora da versão.'))
        if item.recebivel_id and item.recebivel.charged_amount != item.valor_total:
            p.append(Pendencia(
                'itens',
                f'Procedimento {item.sequencial}: a guia cobra R$ {item.valor_total} e a cobrança do '
                f'check-in é de R$ {item.recebivel.charged_amount}. Se a diferença for real, ajuste no '
                'financeiro (com motivo).', impede=False, quem='gestor',
            ))
    return p


def pode_fechar(guia):
    return not [x for x in pendencias(guia) if x.impede]


# ------------------------------------------------------------------ fechar, cancelar, revisar

def _snapshot(guia):
    """O que foi faturado, congelado: a guia não muda quando o cadastro muda."""
    cred, cob = guia.credenciamento, guia.cobertura

    def prof(pr):
        if pr is None:
            return None
        return {'nome': pr.nome, 'conselho': pr.conselho, 'numero': pr.numero_conselho,
                'uf': pr.uf, 'cbo': pr.cbo, 'cpf': pr.cpf}

    def dia(d):
        return d.isoformat() if d else None

    # O que o XML escreve sai daqui, e não da linha da guia: o arquivo gerado
    # um ano depois tem de ser o mesmo que seria gerado no dia do fechamento.
    campos_da_guia = {
        'numero_prestador': guia.numero_prestador, 'numero_operadora': guia.numero_operadora,
        'guia_principal': guia.guia_principal, 'data_emissao': dia(guia.data_emissao),
        'data_autorizacao': dia(guia.data_autorizacao), 'senha': guia.senha,
        'validade_senha': dia(guia.validade_senha), 'cod_validacao': guia.cod_validacao,
        'ausencia_cod_validacao': guia.ausencia_cod_validacao,
        'contratado_solicitante_tipo': guia.contratado_solicitante_tipo,
        'contratado_solicitante_codigo': guia.contratado_solicitante_codigo,
        'contratado_solicitante_nome': guia.contratado_solicitante_nome,
        'data_solicitacao': dia(guia.data_solicitacao), 'carater_atendimento': guia.carater_atendimento,
        'indicacao_clinica': guia.indicacao_clinica, 'cobertura_especial': guia.cobertura_especial,
        'tipo_atendimento': guia.tipo_atendimento, 'indicacao_acidente': guia.indicacao_acidente,
        'tipo_consulta': guia.tipo_consulta, 'motivo_encerramento': guia.motivo_encerramento,
        'regime_atendimento': guia.regime_atendimento, 'saude_ocupacional': guia.saude_ocupacional,
        'observacao': guia.observacao,
    }

    return {
        'tipo': guia.tipo,
        'guia': campos_da_guia,
        'versao': cred.versao,
        'operadora': {'nome': cred.operadora.name, 'registro_ans': cred.operadora.ans_registration},
        'prestador': {
            'nome': cred.prestador.nome, 'tipo_pessoa': cred.prestador.tipo_pessoa,
            'documento': cred.prestador.documento, 'cnes': cred.prestador.cnes or CNES_INEXISTENTE,
        },
        'credenciamento': {'identificacao': cred.identificacao, 'codigo': cred.codigo_na_operadora},
        'beneficiario': {
            'nome': guia.paciente.full_name, 'carteira': guia.carteira,
            'validade_carteira': guia.validade_carteira.isoformat() if guia.validade_carteira else None,
            'plano': cob.plan.name, 'atendimento_rn': guia.atendimento_rn,
        },
        'executante': prof(guia.executante),
        'solicitante': prof(guia.solicitante),
        'itens': [
            {'sequencial': i.sequencial, 'data': i.data_execucao.isoformat(),
             'hora_inicial': i.hora_inicial.isoformat() if i.hora_inicial else None,
             'hora_final': i.hora_final.isoformat() if i.hora_final else None,
             'tabela': i.tabela, 'codigo': i.codigo, 'descricao': i.descricao,
             'release_tuss': i.release_tuss, 'quantidade': i.quantidade,
             'via_acesso': i.via_acesso, 'tecnica': i.tecnica, 'fator': str(i.fator),
             'valor_unitario': str(i.valor_unitario), 'valor_total': str(i.valor_total),
             'preco_origem': i.preco_origem, 'preco_motivo': i.preco_motivo,
             'recebivel': str(i.recebivel_id) if i.recebivel_id else None}
            for i in guia.itens.order_by('sequencial')
        ],
        'total': str(sum((i.valor_total for i in guia.itens.all()), Decimal('0.00'))),
    }


@transaction.atomic
def fechar(context, user, guia):
    guia = _travar_rascunho(guia)
    if guia.tenant_id != context.tenant_id:
        raise GuiaRecusada('Guia de outra clínica.')
    impedem = [x for x in pendencias(guia) if x.impede]
    if impedem:
        raise GuiaRecusada('Ainda há pendências: ' + '; '.join(x.mensagem for x in impedem))
    guia.snapshot = _snapshot(guia)
    guia.versao = guia.credenciamento.versao
    guia.data_referencia = max(i.data_execucao for i in guia.itens.all())
    guia.estado = EstadoGuia.FECHADA
    guia.fechada_em = timezone.now()
    guia.fechada_por = user
    guia.save()
    if guia.revisa_id:
        Guia.objects.filter(id=guia.revisa_id, estado=EstadoGuia.FECHADA).update(
            estado=EstadoGuia.SUBSTITUIDA, updated_at=timezone.now(),
        )
    record_audit_event(
        user, context.tenant_id, 'tiss.guia_fechada', object_type='guia_tiss', object_id=guia.id,
        outcome='success', integrity_metadata={
            'numero': guia.numero_prestador, 'versao': guia.versao, 'total': guia.snapshot['total'],
            'revisa': str(guia.revisa_id) if guia.revisa_id else None,
        },
    )
    return guia


@transaction.atomic
def cancelar(context, user, guia, motivo):
    guia = Guia.objects.select_for_update().get(id=guia.id)
    if guia.tenant_id != context.tenant_id:
        raise GuiaRecusada('Guia de outra clínica.')
    motivo = (motivo or '').strip()
    if not motivo:
        raise GuiaRecusada('Escreva o motivo do cancelamento.')
    if guia.estado not in (EstadoGuia.RASCUNHO, EstadoGuia.FECHADA):
        raise GuiaRecusada('Esta guia já está cancelada ou substituída.')
    from .models import LoteGuia

    no_lote = LoteGuia.objects.filter(guia=guia, ativo=True).select_related('lote').first()
    if no_lote is not None:
        # O arquivo do lote leva esta guia: cancelá-la por fora faria o lote
        # cobrar uma guia que o NeuroDoc diz cancelada.
        raise GuiaRecusada(
            f'Esta guia está no lote {no_lote.lote.numero}. Cancele o lote (ou, se já enviado, '
            'libere a guia para reapresentação) antes de cancelá-la.'
        )
    guia.estado = EstadoGuia.CANCELADA
    guia.cancelada_em, guia.cancelada_por, guia.motivo_cancelamento = timezone.now(), user, motivo[:255]
    guia.save()
    # Solta a cobrança: o mesmo serviço pode ser faturado de novo noutra
    # guia. A guia cancelada guarda no snapshot qual era.
    guia.itens.exclude(recebivel=None).update(recebivel=None)
    record_audit_event(
        user, context.tenant_id, 'tiss.guia_cancelada', object_type='guia_tiss', object_id=guia.id,
        outcome='success', integrity_metadata={'numero': guia.numero_prestador, 'motivo': motivo[:255]},
    )
    return guia


@transaction.atomic
def abrir_revisao(context, user, guia):
    """Corrigir guia fechada: uma guia nova, em preenchimento, que a revisa.

    A original continua fechada — e com o snapshot de quando foi fechada —
    até a revisão ser fechada; aí vira "substituída". As cobranças passam
    para a revisão já agora, porque um recebível só cabe num item.
    """
    original = Guia.objects.select_for_update().get(id=guia.id)
    if original.tenant_id != context.tenant_id:
        raise GuiaRecusada('Guia de outra clínica.')
    if original.estado != EstadoGuia.FECHADA:
        raise GuiaRecusada('Só guia fechada se corrige por revisão; em preenchimento, edite.')
    if Guia.objects.filter(revisa=original).exclude(estado=EstadoGuia.CANCELADA).exists():
        raise GuiaRecusada('Esta guia já tem uma revisão em andamento.')
    campos = [f.name for f in Guia._meta.concrete_fields if f.name not in {
        'id', 'created_at', 'updated_at', 'row_version', 'estado', 'numero_prestador', 'versao',
        'snapshot', 'fechada_em', 'fechada_por', 'cancelada_em', 'cancelada_por',
        'motivo_cancelamento', 'revisa', 'criada_por', 'data_emissao',
    }]
    nova = Guia(**{c: getattr(original, c) for c in campos})
    nova.numero_prestador = _proximo_numero(context.tenant_id)
    nova.data_emissao = timezone.localdate()
    nova.revisa = original
    nova.criada_por = user
    nova.save()
    for item in original.itens.order_by('sequencial'):
        recebivel = item.recebivel_id
        if recebivel:
            ItemGuia.objects.filter(id=item.id).update(recebivel=None)
        ItemGuia.objects.create(**{
            f.name: getattr(item, f.name) for f in ItemGuia._meta.concrete_fields
            if f.name not in {'id', 'created_at', 'updated_at', 'row_version', 'guia', 'recebivel'}
        }, guia=nova, recebivel_id=recebivel)
    record_audit_event(
        user, context.tenant_id, 'tiss.guia_revisao_aberta', object_type='guia_tiss', object_id=nova.id,
        outcome='success', integrity_metadata={'revisa': str(original.id), 'numero': nova.numero_prestador},
    )
    return nova


def registrar_indicacao(context, user, guia, texto):
    """A indicação clínica é do médico: quem escreveu e quando ficam na guia."""
    from tenancy.permissions import Capability

    if not context.can(Capability.READ_CLINICAL):
        raise GuiaRecusada('A indicação clínica é preenchida pelo médico.')
    texto = (texto or '').strip()[:500]
    guia.indicacao_clinica = texto
    guia.indicacao_por = user if texto else None
    guia.indicacao_em = timezone.now() if texto else None
