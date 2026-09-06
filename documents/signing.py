import io

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext


class InvalidPfxPassword(Exception):
    pass


class SigningFailed(Exception):
    pass


def _load_signer(pfx_bytes, password):
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(
            pfx_bytes, other_certs=set(), passphrase=password.encode(),
        )
    except ValueError as exc:
        raise InvalidPfxPassword('Could not unlock the certificate with the given password') from exc
    if signer is None:
        raise InvalidPfxPassword('Could not unlock the certificate with the given password')
    return signer


def verify_pfx_password(pfx_bytes, password):
    """Raises InvalidPfxPassword without signing anything -- used to check a
    password at signing-session start time, before any tmpfs material exists.
    """
    _load_signer(pfx_bytes, password)


def sign_pdf(pdf_bytes, pfx_bytes, password, *, signer_name, reason='Documento médico assinado digitalmente'):
    """Produces a PAdES-compliant signature over the whole document. Never
    recompresses or otherwise mutates the source bytes beyond appending the
    signature (pyHanko's incremental-update model): the original content
    stream is untouched, satisfying "não recriar páginas ou comprimir PDF
    depois de assinado".
    """
    try:
        signer = _load_signer(pfx_bytes, password)
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
        meta = signers.PdfSignatureMetadata(
            field_name='Signature1', subfilter=fields.SigSeedSubFilter.PADES,
            reason=reason, name=signer_name,
        )
        out = signers.sign_pdf(writer, meta, signer=signer)
        return out.getvalue() if hasattr(out, 'getvalue') else out.read()
    except InvalidPfxPassword:
        raise
    except Exception as exc:
        raise SigningFailed(str(exc)) from exc


def validate_signed_pdf(signed_pdf_bytes, trust_root_certificate):
    """Independent verification step (H-08): re-opens the signed bytes fresh
    and validates integrity + trust against the given root, mirroring what
    an external verifier would check. `trust_root_certificate` is the
    signer's own certificate for a self-signed test credential (no real
    ICP-Brasil chain is available, P-05); production would supply the ICP-
    Brasil root/intermediate chain instead.
    """
    reader = PdfFileReader(io.BytesIO(signed_pdf_bytes))
    if not reader.embedded_signatures:
        raise SigningFailed('No embedded signature found')
    signature = reader.embedded_signatures[0]
    vc = ValidationContext(trust_roots=[trust_root_certificate], allow_fetching=False)
    return validate_pdf_signature(signature, vc)
