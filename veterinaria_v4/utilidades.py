# -*- coding: utf-8 -*-
"""
Utilidades sin dependencias del dominio: contraseñas, validación de datos de entrada,
control de permisos por rol y exportación de reportes a PDF.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import date, datetime

from errores import ErrorNegocio, ErrorSesion


def hash_password(password, salt=None):
    """PBKDF2-SHA256 con sal aleatoria. Devuelve 'sal$hash'."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${digest}"


def verificar_password(password, almacenado):
    try:
        salt, _ = almacenado.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_password(password, salt), almacenado)


def texto_requerido(valor, campo, maximo=100):
    valor = (valor or "").strip()
    if not valor:
        raise ErrorNegocio(f"{campo} es obligatorio")
    if len(valor) > maximo:
        raise ErrorNegocio(f"{campo} no puede superar {maximo} caracteres")
    return valor


def texto_opcional(valor, maximo=300):
    valor = (valor or "").strip()
    if len(valor) > maximo:
        raise ErrorNegocio(f"El texto no puede superar {maximo} caracteres")
    return valor or None


def entero(valor, campo, minimo=None, maximo=None):
    try:
        n = int(str(valor).strip())
    except (ValueError, TypeError):
        raise ErrorNegocio(f"{campo} debe ser un número entero")
    if (minimo is not None and n < minimo) or (maximo is not None and n > maximo):
        raise ErrorNegocio(f"{campo} debe estar entre {minimo} y {maximo}")
    return n


def decimal(valor, campo, minimo_exclusivo=0, maximo=None):
    try:
        x = float(str(valor).strip().replace(",", "."))
    except (ValueError, TypeError):
        raise ErrorNegocio(f"{campo} debe ser un número")
    if x <= minimo_exclusivo or (maximo is not None and x > maximo):
        raise ErrorNegocio(f"{campo} no es válido")
    return x


def fecha_valida(valor, campo="La fecha"):
    try:
        return datetime.strptime((valor or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ErrorNegocio(f"{campo} no es válida (use AAAA-MM-DD)")


def hora_valida(valor, campo="La hora"):
    try:
        return datetime.strptime((valor or "").strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ErrorNegocio(f"{campo} no es válida (use HH:MM)")


def id_de_opcion(texto, campo):
    """Extrae el id de una opción de combobox con formato 'id - descripción'."""
    if not texto:
        raise ErrorNegocio(f"Seleccione {campo}")
    return entero(texto.split(" - ")[0], campo)


def exigir(usuario, *roles):
    if usuario is None or usuario.rol not in roles:
        raise ErrorNegocio("No tiene permisos para realizar esta acción")


def escribir_pdf(ruta, lineas):
    """Genera un PDF de texto simple (sin dependencias externas)."""
    por_pagina = 48
    paginas = [lineas[i:i + por_pagina] for i in range(0, len(lineas), por_pagina)] or [[]]
    n = len(paginas)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, pagina in enumerate(paginas):
        partes = ["BT", "/F1 11 Tf", "15 TL", "50 800 Td"]
        for linea in pagina:
            t = linea.encode("cp1252", "replace").decode("latin-1")
            t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            partes.append(f"({t}) '")
        partes.append("ET")
        flujo = "\n".join(partes).encode("latin-1")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(flujo)).encode() + b" >>\nstream\n"
                    + flujo + b"\nendstream")
    salida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, cuerpo in enumerate(objs, start=1):
        offsets.append(len(salida))
        salida += f"{num} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        salida += f"{off:010d} 00000 n \n".encode()
    salida += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
               f"startxref\n{inicio_xref}\n%%EOF\n").encode()
    with open(ruta, "wb") as f:
        f.write(bytes(salida))


