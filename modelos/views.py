"""As telas de Modelos: a lista, o editor do modelo do médico e a emissão.

**Quem abre.** A lista e o editor pedem `READ_CLINICAL` — o papel médico,
o único que escreve documento clínico. A emissão pede `ISSUE_DOCUMENT`, a
mesma capacidade do botão "Emitir documento" e da assinatura: quem não
pode emitir não chega à tela que emite. A secretária e o gestor não abrem
nenhuma das duas (404).

**De quem é o modelo.** Do médico (`modelos/models.py`): toda consulta
filtra por `autor=request.user`, e o modelo de outro médico responde 404,
como o que não existe.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from audit.services import record_audit_event
from clinical import selectors as clinical_selectors
from clinical.models import EncounterKind
from tenancy.permissions import Capability, CapabilityRequiredView

from . import emissao, estrutura, servicos
from .estrutura import CATEGORIAS, EXAMES, ROTULO_DO_TIPO, TIPOS
from .forms import FORM_DA_SECAO, ModeloForm, valores_iniciais_do_editor
from .models import ModeloDocumento

ABA_CONJUNTOS = 'conjuntos'


class ModelosView(CapabilityRequiredView):
    required_capability = Capability.READ_CLINICAL


def _registro_do_medico_or_404(request, modelo_id):
    registro = ModeloDocumento.objects.filter(id=modelo_id, autor=request.user).first()
    if registro is None:
        raise Http404
    return registro


def _auditar(request, acao, registro):
    record_audit_event(
        request.user, request.access_context.tenant_id, acao,
        object_type='modelo_documento', object_id=registro.id, outcome='success',
        integrity_metadata={'tipo': registro.tipo},
    )


# ------------------------------------------------------------------ lista


class ListaView(ModelosView):
    def get(self, request):
        tipo = request.GET.get('tipo') or EXAMES
        if tipo not in ROTULO_DO_TIPO:
            tipo = EXAMES
        aba = request.GET.get('aba') or ''
        todos = servicos.do_medico(request.user, tipo) + [
            m for m in servicos.do_sistema() if m.tipo == tipo
        ]
        abas = []
        if tipo == EXAMES:
            abas = [(c.codigo, c.rotulo) for c in CATEGORIAS] + [(ABA_CONJUNTOS, 'Conjuntos')]
            if aba not in dict(abas):
                aba = CATEGORIAS[0].codigo
            if aba == ABA_CONJUNTOS:
                todos = [m for m in todos if m.conjunto]
            else:
                todos = [m for m in todos if not m.conjunto and m.categorias
                         and m.categorias[0].codigo == aba]
        return render(request, 'modelos/lista.html', {
            'tipos': TIPOS, 'tipo': tipo, 'rotulo_do_tipo': ROTULO_DO_TIPO[tipo],
            'abas': abas, 'aba': aba, 'aba_conjuntos': ABA_CONJUNTOS,
            'meus': [m for m in todos if not m.do_sistema],
            'do_sistema': [m for m in todos if m.do_sistema],
        })


class VerView(ModelosView):
    def get(self, request, chave):
        modelo = servicos.por_chave(chave, request.user)
        if modelo is None or modelo.em_branco:
            raise Http404
        return render(request, 'modelos/ver.html', {
            'modelo': modelo, 'grupos': [
                (cat, modelo.conteudo['grupos'][cat.codigo]) for cat in modelo.categorias
            ] if modelo.tipo == EXAMES else [],
        })


# ----------------------------------------------------------------- editor


def _destino_da_lista(tipo, conteudo):
    url = f"{reverse('modelos:lista')}?tipo={tipo}"
    if tipo == EXAMES:
        cats = estrutura.categorias_do_modelo(tipo, conteudo)
        aba = ABA_CONJUNTOS if len(cats) > 1 else (cats[0].codigo if cats else '')
        url += f'&aba={aba}'
    return url


class NovoView(ModelosView):
    def get(self, request, tipo):
        if tipo not in ROTULO_DO_TIPO:
            raise Http404
        return render(request, 'modelos/editar.html', {
            'form': ModeloForm(tipo=tipo), 'tipo': tipo, 'rotulo_do_tipo': ROTULO_DO_TIPO[tipo],
            'categoria_aberta': request.GET.get('aba') or '',
        })

    def post(self, request, tipo):
        if tipo not in ROTULO_DO_TIPO:
            raise Http404
        form = ModeloForm(request.POST, tipo=tipo)
        if not form.is_valid():
            return render(request, 'modelos/editar.html', {
                'form': form, 'tipo': tipo, 'rotulo_do_tipo': ROTULO_DO_TIPO[tipo],
            }, status=400)
        registro = ModeloDocumento.objects.create(
            autor=request.user, tipo=tipo, nome=form.cleaned_data['nome'].strip(),
            conteudo=form.conteudo,
        )
        _auditar(request, 'modelos.modelo_criado', registro)
        messages.success(request, 'Modelo salvo.')
        return redirect(_destino_da_lista(tipo, registro.conteudo))


class EditarView(ModelosView):
    def get(self, request, modelo_id):
        registro = _registro_do_medico_or_404(request, modelo_id)
        form = ModeloForm(
            initial=valores_iniciais_do_editor(registro.tipo, registro.conteudo, registro.nome),
            tipo=registro.tipo,
        )
        return render(request, 'modelos/editar.html', {
            'form': form, 'registro': registro, 'tipo': registro.tipo,
            'rotulo_do_tipo': ROTULO_DO_TIPO[registro.tipo],
        })

    def post(self, request, modelo_id):
        registro = _registro_do_medico_or_404(request, modelo_id)
        form = ModeloForm(request.POST, tipo=registro.tipo)
        if not form.is_valid():
            return render(request, 'modelos/editar.html', {
                'form': form, 'registro': registro, 'tipo': registro.tipo,
                'rotulo_do_tipo': ROTULO_DO_TIPO[registro.tipo],
            }, status=400)
        registro.nome = form.cleaned_data['nome'].strip()
        registro.conteudo = form.conteudo
        registro.row_version += 1
        registro.save(update_fields=['nome', 'conteudo', 'row_version', 'updated_at'])
        _auditar(request, 'modelos.modelo_alterado', registro)
        messages.success(request, 'Modelo atualizado.')
        return redirect(_destino_da_lista(registro.tipo, registro.conteudo))


class CopiarView(ModelosView):
    """Copia um modelo (do sistema ou do próprio médico) para os do médico.

    É o caminho para mudar um modelo do sistema: ele é o mesmo para todas
    as clínicas e não se edita; a cópia é do médico, e abre no editor.
    """

    def post(self, request):
        modelo = servicos.por_chave(request.POST.get('chave'), request.user)
        if modelo is None or modelo.em_branco:
            raise Http404
        registro = ModeloDocumento.objects.create(
            autor=request.user, tipo=modelo.tipo, nome=f'{modelo.nome} (cópia)'[:120],
            conteudo=modelo.conteudo,
            origem=modelo.chave[2:] if modelo.do_sistema else '',
        )
        _auditar(request, 'modelos.modelo_criado', registro)
        messages.success(request, 'Cópia criada nos seus modelos. Ajuste e salve.')
        return redirect('modelos:editar', modelo_id=registro.id)


class ExcluirView(ModelosView):
    def post(self, request, modelo_id):
        registro = _registro_do_medico_or_404(request, modelo_id)
        destino = _destino_da_lista(registro.tipo, registro.conteudo)
        _auditar(request, 'modelos.modelo_excluido', registro)
        registro.delete()
        messages.success(request, 'Modelo excluído. Os documentos já emitidos com ele não mudam.')
        return redirect(destino)


# ---------------------------------------------------------------- emissão


def _membro_medico(request):
    from tenancy.models import Membership

    if not request.access_context.has_role('doctor'):
        return None
    return Membership.objects.filter(
        id=request.access_context.membership_id,
    ).select_related('user').first()


def _volta_ao_atendimento(encounter):
    ancora = '#nd-modelos' if encounter.kind == EncounterKind.FREE_TEXT else '#tab-conduta'
    return reverse('clinical:detail', args=[encounter.id]) + ancora


class EmitirView(CapabilityRequiredView):
    """A tela de emissão por modelo, aberta da Conduta.

    GET abre o modelo em seções editáveis; POST emite. A estrutura das
    seções (quantas, de que tipo, de qual categoria) sai **sempre do
    modelo**, nunca do que o navegador mandou: o envio só preenche os
    campos. É o que impede um POST forjado de emitir um pedido de categoria
    que o modelo não tem, ou de pular a indicação obrigatória da imagem.
    """

    required_capability = Capability.ISSUE_DOCUMENT

    def _contexto(self, request, encounter_id, chave):
        encounter = clinical_selectors.get_encounter_or_404(request.access_context, encounter_id)
        membership = _membro_medico(request)
        if membership is None:
            raise Http404
        modelo = servicos.por_chave(chave, request.user)
        return encounter, membership, modelo

    def _secoes(self, modelo, encounter, data=None):
        diagnosticos = emissao.diagnosticos_do_atendimento(encounter)
        secoes = []
        for indice, secao in enumerate(emissao.secoes_iniciais(modelo)):
            Form = FORM_DA_SECAO[secao['tipo']]
            form = Form(data, prefix=f's{indice}', initial=secao['inicial'], diagnosticos=diagnosticos)
            secoes.append({**secao, 'form': form})
        return secoes

    def _tela(self, request, encounter, modelo, secoes, status=200, erro=''):
        return render(request, 'modelos/emitir.html', {
            'encounter': encounter, 'patient': encounter.patient, 'modelo': modelo,
            'secoes': secoes, 'varias': len(secoes) > 1, 'erro': erro,
            'volta': _volta_ao_atendimento(encounter),
            'finalizado': not encounter.is_editable(),
        }, status=status)

    def get(self, request, encounter_id):
        encounter, membership, modelo = self._contexto(request, encounter_id, request.GET.get('modelo'))
        if modelo is None:
            messages.error(request, 'Escolha um modelo da lista para emitir.')
            return redirect(_volta_ao_atendimento(encounter))
        return self._tela(request, encounter, modelo, self._secoes(modelo, encounter))

    def post(self, request, encounter_id):
        encounter, membership, modelo = self._contexto(request, encounter_id, request.POST.get('modelo'))
        if modelo is None:
            raise Http404
        secoes = self._secoes(modelo, encounter, data=request.POST)
        validas, invalida = [], False
        for secao in secoes:
            form = secao['form']
            # Seção desmarcada não é validada nem emitida. Com uma seção só, a
            # caixa nem aparece e o valor chega por campo oculto.
            if not form.data.get(form.add_prefix('emitir')):
                continue
            if not form.is_valid():
                invalida = True
                continue
            dados = dict(form.cleaned_data)
            if secao['tipo'] == EXAMES:
                dados['categoria'] = secao['inicial']['categoria']
            try:
                validas.append(emissao.secao_validada(secao['tipo'], dados, modelo.chave))
            except emissao.EmissaoRecusada as exc:
                form.add_error(None, str(exc))
                invalida = True
        if invalida:
            return self._tela(request, encounter, modelo, secoes, status=400,
                              erro='Confira os campos marcados. Nada foi emitido.')
        try:
            documentos, destino = emissao.emitir(
                request.access_context, encounter, membership, request.user, validas,
                request.POST.get('acao'), modelo.chave,
            )
        except emissao.EmissaoRecusada as exc:
            return self._tela(request, encounter, modelo, secoes, status=400, erro=str(exc))

        quantos = len(documentos)
        documentos_txt = 'documento' if quantos == 1 else 'documentos'
        onde = 'na conduta' if destino == 'conduta' else 'em adendo ao atendimento'
        if request.POST.get('acao') == emissao.PAPEL:
            messages.success(
                request, f'{quantos} {documentos_txt} emitido(s) em papel, com número, e anexado(s) '
                         f'à ficha do paciente. O texto foi registrado {onde}.',
            )
        else:
            messages.success(
                request, f'{quantos} {documentos_txt} pronto(s) para assinar — abra cada um na lista '
                         f'abaixo para assinar digitalmente. O texto foi registrado {onde}.',
            )
        return redirect(_volta_ao_atendimento(encounter))
