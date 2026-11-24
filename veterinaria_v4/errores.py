# -*- coding: utf-8 -*-
"""
Veterinaria V4 - ERRORES COMPARTIDOS.
Viven aparte para que todas las capas (patrones, modelo, persistencia, controles, interfaz y
portal) los usen sin depender unas de otras.
"""


class ErrorNegocio(Exception):
    """Error de validación o de regla de negocio, apto para mostrarse al usuario."""


class ErrorSesion(ErrorNegocio):
    """Credenciales o sesión inválidas (el portal responde 401)."""


class ErrorPago(ErrorNegocio):
    """El cobro no se completó: rechazo o pasarela no disponible (el portal responde 402)."""
