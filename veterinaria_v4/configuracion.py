# -*- coding: utf-8 -*-
"""
Configuración y constantes compartidas por el escritorio y el portal web.
"""
import os

# Ruta absoluta junto a este archivo: el escritorio y el portal web (procesos distintos)
# comparten siempre la misma base, sin importar desde dónde se ejecuten.
DB_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veterinaria_v4.db")

ROLES_GESTIONABLES = ("Veterinario", "Recepcionista")
ESTADOS_CITA = ("pendiente", "confirmada", "finalizada", "cancelada")
ESPECIES = ("Perro", "Gato", "Ave", "Conejo", "Reptil", "Otro")
SIN_PROPIETARIO = "(sin propietario)"

# Reglas de las citas agendadas en línea (ajústelas a la clínica)
HORARIO_ATENCION = ("08:00", "20:00")   # inicio inclusivo, fin exclusivo
INTERVALO_CITA_MIN = 30
