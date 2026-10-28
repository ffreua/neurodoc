"""Emitir documentos a partir de um modelo, de dentro do atendimento.

O caminho, de ponta a ponta:

1. na Conduta, o médico escolhe um modelo (`opcoes_para_conduta`);
2. a tela de emissão abre **uma seção por documento** — o conjunto "Queixa
   cognitiva" abre o pedido de imagem e o de laboratório separados —, já
   preenchida, para editar;
3. ao emitir, numa transação só:
   - cada seção vira um `MedicalDocument` pelo caminho de sempre
     (`documents.issuance.create_draft`), e daí **em papel** (número e PDF
     sem tarja, já nos Anexos) ou **pronto para assinar** digitalmente;
   - o texto de cada documento entra **na conduta** do atendimento — o
     prontuário diz o que foi pedido, e o anexo é o papel que saiu.

**Por que o texto vai para `plan_text`, e não para uma tabela ao lado.** É
o campo que o prontuário já tem para "o que se fez com o caso": entra no
`content_hash` ao finalizar, sai na exportação do acervo, aparece no resumo
e é oferecido na consulta seguinte. Uma tabela nova seria um segundo lugar
onde a conduta mora, e cada um desses caminhos teria de aprender a lê-la.

**Atendimento finalizado não se reescreve.** Emitir depois de finalizar é
legítimo (o pedido que ficou para depois), e o texto vai como **adendo**
(`ClinicalAmendment`), o único registro que o finalizado aceita — o corpo
e o `content_hash` não mudam.

**Tudo ou nada.** Uma seção recusada (receita de controle especial sem
endereço, conduta que passaria do limite) desfaz as outras: o médico não
fica com metade dos pedidos emitidos e a conduta sem o texto deles.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from . import estrutura
from .estrutura import CARATER, REGIME, ConteudoInvalido

#: O limite do campo de conduta (`Encounter.plan_text`).
LIMITE_DA_CONDUTA = 20000

PAPEL = 'papel'
ASSINATURA = 'assinatura'


class EmissaoRecusada(Exception):
    """A emissão não pode acontecer; nada foi gravado. A mensagem vai para a tela."""


@dataclass
class Secao:
    """Um documento a sair, já validado."""

    tipo: str
    kind: str
    titulo: str
    conteudo: dict
    texto_da_conduta: str


# ------------------------------------------------- do modelo para a tela


def secoes_iniciais(modelo):
    """As seções da tela de emissão, preenchidas pelo modelo.

    Pedido de exames: uma seção por categoria do modelo. O resto: uma só.
    """
    conteudo = modelo.conteudo
    if modelo.tipo == estrutura.EXAMES:
        secoes = []
        for cat in modelo.categorias:
            secoes.append({
                'tipo': estrutura.EXAMES,
                'titulo': f'Pedido de exames — {cat.rotulo}',
                'inicial': {
                    'categoria': cat.codigo, 'emitir': True,
                    'itens': estrutura.texto_dos_exames(conteudo['grupos'].get(cat.codigo)),
                    'indicacao': conteudo.get('indicacao', ''),
                    'observacoes': conteudo.get('observacoes', ''),
                },
            })
        return secoes
    if modelo.tipo == estrutura.CIRURGIA:
        inicial = {k: v for k, v in conteudo.items() if k not in ('procedimentos', 'materiais')}
        inicial.update(
            emitir=True,
            procedimentos=estrutura.texto_dos_procedimentos(conteudo.get('procedimentos')),
            materiais=estrutura.texto_dos_materiais(conteudo.get('materiais')),
            dias_internacao=conteudo.get('dias_internacao') or None,
        )
        return [{'tipo': modelo.tipo, 'titulo': 'Solicitação de cirurgia', 'inicial': inicial}]
    if modelo.tipo == estrutura.RELATORIO:
        return [{'tipo': modelo.tipo, 'titulo': 'Relatório',
                 'inicial': {'emitir': True, 'texto': conteudo.get('texto', '')}}]
    return [{'tipo': modelo.tipo, 'titulo': 'Receita',
             'inicial': {'emitir': True, 'texto': conteudo.get('texto', ''),
                         'instrucoes': conteudo.get('instrucoes', '')}}]


def diagnosticos_do_atendimento(encounter):
    """As hipóteses que podem ir para o documento, como "código — descrição".

    A refutada fica de fora: é a hipótese que o médico afastou, e imprimi-la
    num pedido seria afirmar o contrário.
    """
    from clinical.models import DiagnosisCertainty

    saida = []
    for d in encounter.diagnoses.exclude(certainty=DiagnosisCertainty.REFUTED).order_by('rank'):
        texto = ' — '.join(p for p in (d.code_snapshot, d.description_snapshot) if p)
        if texto and texto not in saida:
            saida.append(texto[:300])
    return saida


# ------------------------------------------------- da tela para o documento


def _linha(itens, com_quantidade=False):
    linhas = []
    for i in itens:
        texto = f"{i['codigo']} {i['descricao']}" if i.get('codigo') else i['descricao']
        if com_quantidade and int(i.get('quantidade') or 1) > 1:
            texto += f" (x{int(i['quantidade'])})"
        linhas.append(f'- {texto}')
    return '\n'.join(linhas)


def secao_validada(tipo, dados, chave_do_modelo):
    """O `cleaned_data` de uma seção como documento a emitir."""
    from documents.models import MedicalDocumentKind

    cid = (dados.get('cid') or '').strip()
    if tipo == estrutura.EXAMES:
        cat = estrutura.categoria(dados['categoria'])
        conteudo = {
            'categoria': cat.codigo, 'categoria_rotulo': cat.rotulo,
            'itens': dados['itens'], 'indicacao': (dados.get('indicacao') or '').strip(),
            'cid': cid, 'observacoes': (dados.get('observacoes') or '').strip(),
            'modelo': chave_do_modelo,
        }
        titulo = f'Pedido de exames — {cat.rotulo}'
        partes = []
        if conteudo['indicacao']:
            partes.append(f"Indicação: {conteudo['indicacao']}")
        if cid:
            partes.append(f'CID-10: {cid}')
        partes.append(_linha(conteudo['itens']))
        if conteudo['observacoes']:
            partes.append(f"Observações: {conteudo['observacoes']}")
        return Secao(tipo, MedicalDocumentKind.EXAM_REQUEST, titulo, conteudo, '\n'.join(partes))

    if tipo == estrutura.CIRURGIA:
        try:
            conteudo = estrutura.normalizar(estrutura.CIRURGIA, {
                **dados, 'dias_internacao': '' if dados.get('dias_internacao') is None
                else str(dados['dias_internacao']),
            })
        except ConteudoInvalido as exc:
            raise EmissaoRecusada(str(exc)) from exc
        conteudo.update(cid=cid, modelo=chave_do_modelo)
        partes = [f"Indicação: {conteudo['indicacao']}"] if conteudo['indicacao'] else []
        if cid:
            partes.append(f'CID-10: {cid}')
        partes.append('Procedimentos:\n' + _linha(conteudo['procedimentos'], com_quantidade=True))
        if conteudo['materiais']:
            partes.append('Materiais e OPME:\n' + '\n'.join(
                f"- {m['quantidade']} x {m['descricao']}" for m in conteudo['materiais']
            ))
        condicoes = [dict(CARATER)[conteudo['carater']], dict(REGIME)[conteudo['regime']]]
        if conteudo['dias_internacao']:
            condicoes.append(f"{conteudo['dias_internacao']} dia(s) de internação")
        if conteudo['uti']:
            condicoes.append('UTI no pós-operatório')
        if conteudo['reserva_sangue']:
            condicoes.append('reserva de hemoderivados')
        partes.append('Condições: ' + ' · '.join(condicoes))
        if conteudo['local']:
            partes.append(f"Local: {conteudo['local']}")
        if conteudo['observacoes']:
            partes.append(f"Observações: {conteudo['observacoes']}")
        return Secao(tipo, MedicalDocumentKind.SURGERY_REQUEST, 'Solicitação de cirurgia',
                     conteudo, '\n'.join(partes))

    if tipo == estrutura.RELATORIO:
        texto = dados['texto'].strip()
        return Secao(tipo, MedicalDocumentKind.REPORT, 'Relatório',
                     {'report_text': texto, 'modelo': chave_do_modelo}, texto)

    formato = dados.get('formato')
    titulo = {'simple': 'Receita simples', 'special_control': 'Receita de controle especial'}.get(
        formato, 'Receita',
    )
    texto = dados['texto'].strip()
    instrucoes = (dados.get('instrucoes') or '').strip()
    conteudo = {'prescription_text': texto, 'special_instructions': instrucoes,
                'prescription_format': formato, 'modelo': chave_do_modelo}
    corpo = texto + (f'\nInstruções: {instrucoes}' if instrucoes else '')
    return Secao(tipo, MedicalDocumentKind.PRESCRIPTION, titulo, conteudo, corpo)


# ------------------------------------------------------------ a emissão


def _bloco(secao, modo, hoje):
    como = 'emitido em papel' if modo == PAPEL else 'para assinatura digital'
    return f'[{secao.titulo} · {como} · {hoje:%d/%m/%Y}]\n{secao.texto_da_conduta}'.rstrip()


def emitir(context, encounter, membership, usuario, secoes, modo, chave_do_modelo):
    """Emite as seções e registra o texto no prontuário. Devolve os documentos.

    `modo` é `PAPEL` (número, PDF sem tarja, pronto para imprimir e assinar
    à caneta) ou `ASSINATURA` (pronto para a assinatura digital, que segue
    pela tela do documento, uma por vez, como sempre).
    """
    from clinical.finalization import add_amendment
    from clinical.models import Encounter, EncounterStatus
    from documents import issuance
    from documents.retention import soft_delete_attachment

    if modo not in (PAPEL, ASSINATURA):
        raise EmissaoRecusada('Escolha emitir em papel ou preparar para assinatura digital.')
    if not secoes:
        raise EmissaoRecusada('Marque ao menos um documento para emitir.')

    hoje = timezone.localdate()
    texto = '\n\n'.join(_bloco(s, modo, hoje) for s in secoes)

    with transaction.atomic():
        enc = Encounter.objects.select_for_update().select_related('patient', 'tenant').get(pk=encounter.pk)
        editavel = enc.is_editable()
        if editavel:
            atual = (enc.plan_text or '').rstrip()
            nova_conduta = f'{atual}\n\n{texto}' if atual else texto
            if len(nova_conduta) > LIMITE_DA_CONDUTA:
                raise EmissaoRecusada(
                    f'A conduta passaria de {LIMITE_DA_CONDUTA:,} caracteres com estes documentos. '
                    'Emita menos documentos de uma vez ou resuma a conduta já escrita.'.replace(',', '.')
                )
        elif len(texto) > LIMITE_DA_CONDUTA:
            raise EmissaoRecusada('O texto destes documentos passa do limite de um adendo. '
                                  'Emita menos documentos de uma vez.')

        documentos = []
        for secao in secoes:
            try:
                doc = issuance.create_draft(
                    enc.tenant, enc.patient, enc, membership, usuario.id, secao.kind, secao.conteudo,
                )
            except ValueError as exc:
                # Receita de controle especial sem endereço, perfil sem CRM:
                # a recusa de `create_draft` já vem em português, para a tela.
                raise EmissaoRecusada(f'{secao.titulo}: {exc}') from exc
            if modo == PAPEL:
                rascunho = doc.pdf_attachment
                doc = issuance.issue_on_paper(doc, usuario.id)
                # A via em papel substitui o PDF do rascunho como o arquivo do
                # documento. Sem isto os Anexos mostrariam os dois — um deles
                # com a tarja "RASCUNHO SEM VALIDADE" — para cada pedido.
                if rascunho is not None and rascunho.id != doc.pdf_attachment_id:
                    soft_delete_attachment(rascunho, usuario.id,
                                           'Rascunho substituído pela via emitida em papel')
            else:
                doc = issuance.mark_reviewed(doc, usuario.id)
            documentos.append(doc)

        if editavel:
            enc.plan_text = nova_conduta
            campos = ['plan_text', 'row_version', 'updated_at']
            # O mesmo passo do salvamento do atendimento: o primeiro registro
            # tira o rascunho do estado "não iniciado".
            if enc.status == EncounterStatus.DRAFT:
                enc.status = EncounterStatus.IN_PROGRESS
                campos.append('status')
            enc.row_version = (enc.row_version or 0) + 1
            enc.save(update_fields=campos)
            destino = 'conduta'
        else:
            add_amendment(
                context, enc, membership,
                reason='Documento emitido por modelo depois da finalização', text=texto,
            )
            destino = 'adendo'

        record_audit_event(
            usuario, enc.tenant_id, 'modelos.documentos_emitidos',
            object_type='encounter', object_id=enc.id, outcome='success',
            # Identificadores e contagem, nunca o texto (CLAUDE.md, trilha).
            integrity_metadata={
                'modelo': chave_do_modelo, 'modo': modo, 'registro': destino,
                'documentos': [str(d.id) for d in documentos],
            },
        )
    return documentos, destino
