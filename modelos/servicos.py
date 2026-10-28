"""Os modelos que um médico enxerga: os do sistema e os seus.

Uma forma só para os dois (`Modelo`), para que a tela de emissão e a lista
não precisem saber de onde o modelo veio. A **chave** diz:

- `s:<slug>` — do sistema (`modelos/padrao.py`);
- `u:<uuid>` — do médico (`ModeloDocumento`), e só do **próprio** médico;
- `b:<tipo>` ou `b:exames:<categoria>` — em branco, para emitir sem modelo
  pela mesma tela.

A chave de modelo alheio, ou que não existe, devolve `None`, e quem chama
responde 404: não se confirma que o modelo de outro médico existe.
"""

import logging
import uuid
from dataclasses import dataclass, field

from . import estrutura, padrao
from .estrutura import CATEGORIAS, EXAMES, ROTULO_DO_TIPO, TIPOS

logger = logging.getLogger(__name__)


@dataclass
class Modelo:
    chave: str
    tipo: str
    nome: str
    conteudo: dict
    do_sistema: bool = False
    em_branco: bool = False
    #: O registro do médico, quando o modelo é dele.
    registro: object = None
    categorias: list = field(default_factory=list)

    @property
    def rotulo_do_tipo(self):
        return ROTULO_DO_TIPO.get(self.tipo, self.tipo)

    @property
    def conjunto(self):
        return len(self.categorias) > 1

    @property
    def quantidade_de_itens(self):
        if self.tipo == EXAMES:
            return sum(len(v) for v in (self.conteudo.get('grupos') or {}).values())
        if self.tipo == estrutura.CIRURGIA:
            return len(self.conteudo.get('procedimentos') or [])
        return 0


def _montar(chave, tipo, nome, conteudo, **extra):
    conteudo = estrutura.normalizar(tipo, conteudo)
    return Modelo(
        chave=chave, tipo=tipo, nome=nome, conteudo=conteudo,
        categorias=estrutura.categorias_do_modelo(tipo, conteudo), **extra,
    )


def do_sistema():
    """Os modelos do sistema, na forma canônica.

    Um modelo do sistema fora da forma (edição errada de `padrao.py`) fica
    de fora com registro no log, em vez de derrubar a Conduta de todos os
    médicos — esta lista é montada a cada abertura de atendimento.
    `check_modelos` reprova antes do deploy; isto é a rede embaixo.
    """
    saida = []
    for m in padrao.MODELOS:
        try:
            saida.append(_montar(f"s:{m['slug']}", m['tipo'], m['nome'], m['conteudo'], do_sistema=True))
        except estrutura.ConteudoInvalido:
            logger.error('modelos: modelo do sistema fora da forma (slug=%s)', m.get('slug'))
    return saida


def do_medico(usuario, tipo=None):
    from .models import ModeloDocumento

    consulta = ModeloDocumento.objects.filter(autor=usuario)
    if tipo:
        consulta = consulta.filter(tipo=tipo)
    saida = []
    for registro in consulta.order_by('nome'):
        try:
            saida.append(_montar(f'u:{registro.id}', registro.tipo, registro.nome,
                                 registro.conteudo, registro=registro))
        except estrutura.ConteudoInvalido:
            # Gravado sempre normalizado; um registro fora da forma só pode
            # ser de edição manual no banco. Fica fora da lista em vez de
            # derrubar a tela de todos os modelos do médico.
            continue
    return saida


def em_branco(tipo, categoria=None):
    if tipo == EXAMES:
        # Montado à mão, e não por `_montar`: a normalização tira grupo
        # vazio, e o em branco é justamente um grupo vazio da categoria.
        cat = estrutura.categoria(categoria) or CATEGORIAS[0]
        return Modelo(
            chave=f'b:exames:{cat.codigo}', tipo=EXAMES,
            nome=f'Pedido em branco — {cat.rotulo}',
            conteudo={'grupos': {cat.codigo: []}, 'indicacao': '', 'observacoes': ''},
            em_branco=True, categorias=[cat],
        )
    if tipo not in ROTULO_DO_TIPO:
        return None
    return _montar(f'b:{tipo}', tipo, f'{ROTULO_DO_TIPO[tipo]} em branco', {}, em_branco=True)


def por_chave(chave, usuario):
    chave = (chave or '').strip()
    origem, _, resto = chave.partition(':')
    if origem == 's':
        m = padrao.POR_SLUG.get(resto)
        if m is None:
            return None
        try:
            return _montar(chave, m['tipo'], m['nome'], m['conteudo'], do_sistema=True)
        except estrutura.ConteudoInvalido:
            return None
    if origem == 'u':
        from .models import ModeloDocumento

        try:
            ident = uuid.UUID(resto)
        except ValueError:
            return None
        registro = ModeloDocumento.objects.filter(id=ident, autor=usuario).first()
        if registro is None:
            return None
        try:
            return _montar(chave, registro.tipo, registro.nome, registro.conteudo, registro=registro)
        except estrutura.ConteudoInvalido:
            return None
    if origem == 'b':
        tipo, _, categoria = resto.partition(':')
        if tipo == EXAMES and categoria and estrutura.categoria(categoria) is None:
            return None
        return em_branco(tipo, categoria or None)
    return None


def opcoes_para_conduta(usuario):
    """Os grupos do seletor da Conduta, na ordem em que o médico procura.

    Primeiro os conjuntos (a síndrome inteira de uma vez), depois uma
    categoria de exame por grupo, e por fim os outros tipos. Em cada grupo,
    os do médico antes dos do sistema, e o "em branco" por último.
    """
    todos = do_medico(usuario) + do_sistema()
    grupos = []

    conjuntos = [m for m in todos if m.tipo == EXAMES and m.conjunto]
    if conjuntos:
        grupos.append(('Conjuntos de exames (um pedido por categoria)', conjuntos))
    for cat in CATEGORIAS:
        doscat = [m for m in todos if m.tipo == EXAMES and not m.conjunto
                  and m.categorias and m.categorias[0].codigo == cat.codigo]
        grupos.append((f'Pedido de exames — {cat.rotulo}', doscat + [em_branco(EXAMES, cat.codigo)]))
    for tipo, rotulo in TIPOS:
        if tipo == EXAMES:
            continue
        grupos.append((rotulo, [m for m in todos if m.tipo == tipo] + [em_branco(tipo)]))
    return grupos
