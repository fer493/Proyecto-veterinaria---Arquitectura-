# -*- coding: utf-8 -*-
"""
ENTIDADES DEL DOMINIO (sin base de datos, interfaz ni servidor web).

Aquí las entidades participan en los patrones definidos en patrones.py:
  Factory Method ... Usuario y sus productos: Administrador, Recepcionista, Veterinario, Propietario
  Observer ......... Cita es el sujeto; Propietario y Veterinario son observadores
  State ............ Cita es el contexto; delega en su estadoActual
  Prototype ........ Cita implementa PrototipoCita (clonar)
  Memento .......... HistorialClinico es el originador (guardarEstado / restaurar)
  Visitor .......... Animal, Cita e HistorialClinico implementan aceptar()
"""
import re
from datetime import date, datetime

from errores import ErrorNegocio
from patrones import (ElementoClinica, MementoHistorial, ObservadorCita, PrototipoCita,
                      estadoDe)
from utilidades import (decimal, entero, fecha_valida, hora_valida, texto_opcional,
                        texto_requerido)


class BuzonNotificaciones:
    """Destino de los avisos que las entidades observadoras generan (simulan SMS y avisos
    internos; no hay una pasarela real de mensajes)."""
    MAXIMO = 200

    def __init__(self):
        self.mensajes = []              # (hora, teléfono, texto) enviados a propietarios
        self.avisos = []                # (hora, veterinario, texto) avisos a veterinarios

    def _agregar(self, lista, registro):
        lista.append(registro)
        del lista[:-self.MAXIMO]

    def sms(self, telefono, texto):
        self._agregar(self.mensajes, (datetime.now(), telefono, texto))

    def aviso(self, veterinario, texto):
        self._agregar(self.avisos, (datetime.now(), veterinario, texto))


# ====================== USUARIOS (productos del Factory Method) ======================

class Usuario:
    """Interfaz Usuario del patrón Factory Method: getRol()."""
    ROL = None

    def __init__(self, id=None, nombre_usuario=None, nombre=None, rol=None, estado=True):
        self.id = id
        self.nombre_usuario = nombre_usuario
        self.nombre = nombre
        self.rol = rol or self.ROL
        self.estado = bool(estado)

    def getRol(self):
        return self.rol


class Administrador(Usuario):
    ROL = "Administrador"

    @property
    def idAdministrador(self):
        return self.id


class Recepcionista(Usuario):
    ROL = "Recepcionista"

    @property
    def idRecepcionista(self):
        return self.id


class Veterinario(Usuario, ObservadorCita):
    """Producto del Factory Method y OBSERVADOR de las citas (recibe el aviso interno)."""
    ROL = "Veterinario"
    AVISOS = {
        "agendada": "Nueva cita #{cita_id}: {animal}, {fecha} {hora}.",
        "confirmada": "Se confirmó la cita #{cita_id}: {animal}, {fecha} {hora}.",
        "cancelada": "Se canceló la cita #{cita_id}: {animal}, {fecha} {hora}.",
        "restaurada": "La cita #{cita_id} ({animal}, {fecha} {hora}) volvió a su estado anterior.",
        "agenda_deshecha": "Se anuló la cita #{cita_id}: {animal}, {fecha} {hora}.",
    }                                   # 'finalizada' no se avisa: la marca el propio veterinario

    def __init__(self, *args, especialidad=None, veterinario_id=None, buzon=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.especialidad = especialidad
        self.veterinario_id = veterinario_id
        self.buzon = buzon

    @property
    def idVeterinario(self):
        return self.veterinario_id

    def actualizar(self, cita):                     # PATRÓN: OBSERVER (observador)
        plantilla = self.AVISOS.get(cita.evento)
        if plantilla is None or self.buzon is None:
            return
        self.buzon.aviso(self.nombre, plantilla.format(
            cita_id=cita.id, animal=cita.animal_nombre, fecha=cita.fecha, hora=cita.hora))


class Propietario(Usuario, ObservadorCita):
    """Dueño de uno o más animales. Es un Usuario más del Factory Method (rol «Propietario») y
    OBSERVADOR de las citas de sus animales (recibe el SMS simulado)."""
    ROL = "Propietario"
    SMS = {
        "agendada": "Su cita #{cita_id} de {animal} quedó agendada para el {fecha} a las {hora}.",
        "confirmada": "Su cita #{cita_id} de {animal} quedó confirmada ({fecha} {hora}).",
        "cancelada": "Su cita #{cita_id} de {animal} ({fecha} {hora}) fue cancelada.",
        "finalizada": "Gracias por visitarnos: la cita #{cita_id} de {animal} fue atendida.",
        "restaurada": "Su cita #{cita_id} de {animal} volvió a su estado anterior ({fecha} {hora}).",
        "agenda_deshecha": "Su cita #{cita_id} de {animal} ({fecha} {hora}) fue anulada por un "
                           "error de captura.",
    }

    def __init__(self, id=None, nombre=None, telefono=None, nombre_usuario=None, estado=True,
                 buzon=None):
        super().__init__(id=id, nombre_usuario=nombre_usuario, nombre=nombre, estado=estado)
        self.telefono = telefono
        self.buzon = buzon

    @property
    def idPropietario(self):
        return self.id

    def validar(self):
        self.nombre = texto_requerido(self.nombre, "El nombre completo")
        tel = re.sub(r"[\s\-]", "", self.telefono or "")
        if not re.fullmatch(r"\d{10}", tel):
            raise ErrorNegocio("El teléfono debe tener 10 dígitos")
        self.telefono = tel

    def actualizar(self, cita):                     # PATRÓN: OBSERVER (observador)
        plantilla = self.SMS.get(cita.evento)
        if plantilla is None or not self.telefono or self.buzon is None:
            return                                  # sin teléfono no hay a quién avisar
        self.buzon.sms(self.telefono, plantilla.format(
            cita_id=cita.id, animal=cita.animal_nombre, fecha=cita.fecha, hora=cita.hora))


# ====================== ANIMAL ======================

class Animal(ElementoClinica):
    def __init__(self, id=None, nombre=None, especie=None, raza=None,
                 edad=None, peso=None, propietario_id=None):
        self.id = id
        self.nombre = nombre
        self.especie = especie
        self.raza = raza
        self.edad = edad
        self.peso = peso
        self.propietario_id = propietario_id

    @property
    def idAnimal(self):
        return self.id

    def validar(self):
        self.nombre = texto_requerido(self.nombre, "El nombre del animal")
        self.especie = texto_requerido(self.especie, "La especie", 50)
        self.raza = texto_opcional(self.raza, 50)
        self.edad = entero(self.edad, "La edad", 0, 60)
        self.peso = decimal(self.peso, "El peso", 0, 1500)

    def aceptar(self, v):                           # PATRÓN: VISITOR (elemento)
        return v.visitarAnimal(self)


# ====================== CITA ======================

class Cita(PrototipoCita, ElementoClinica):
    """Cita veterinaria. Participa en cuatro patrones:
      STATE ....... contexto: delega confirmar / cancelar / finalizar en su estadoActual
      OBSERVER .... sujeto: avisa a sus observadores (InterfazCita, Propietario, Veterinario)
      PROTOTYPE ... prototipo concreto: clonar()
      VISITOR ..... elemento: aceptar()"""
    _CAMPOS = ("id", "fecha", "hora", "motivo", "animal_id", "veterinario_id", "servicio_id")
    # Datos de solo lectura que llenan los reportes y los avisos al armar la cita desde SQL
    animal_nombre = None
    veterinario_nombre = None
    pagada = False

    def __init__(self, id=None, fecha=None, hora=None, motivo=None, estado="pendiente",
                 animal_id=None, veterinario_id=None, servicio_id=None,
                 estadoInicial=None, prototipo=None):
        if prototipo is not None:                   # PATRÓN: PROTOTYPE (constructor de copia)
            for campo in self._CAMPOS:
                setattr(self, campo, getattr(prototipo, campo))
            estado = prototipo.estado
            self.animal_nombre = prototipo.animal_nombre
            self.veterinario_nombre = prototipo.veterinario_nombre
        else:
            self.id, self.fecha, self.hora, self.motivo = id, fecha, hora, motivo
            self.animal_id, self.veterinario_id, self.servicio_id = animal_id, veterinario_id, servicio_id
        self._observadores = []                     # PATRÓN: OBSERVER
        self.fallos = []                            # (hora, observador, error)
        self.evento = None                          # lo que cambió: lo leen los observadores
        self._estadoActual = None
        self.cambiarEstado(estadoInicial if estadoInicial is not None else estado)

    @property
    def idCita(self):
        return self.id

    # ----- PATRÓN: STATE (contexto) -----
    @property
    def estado(self):
        return self._estadoActual.nombre

    @estado.setter
    def estado(self, nombre):
        self.cambiarEstado(nombre)

    def cambiarEstado(self, nuevoEstado, notificar=False):
        """Fija el estado actual (un EstadoCita o su nombre). Con notificar=True avisa además a
        los observadores."""
        if isinstance(nuevoEstado, str):
            nuevoEstado = estadoDe(nuevoEstado)
        nuevoEstado.setContexto(self)
        self._estadoActual = nuevoEstado
        self.evento = nuevoEstado.nombre
        if notificar:
            self.notificarObservadores()

    def confirmar(self):
        self._estadoActual.confirmar()

    def cancelar(self):
        self._estadoActual.cancelar()

    def finalizar(self):
        self._estadoActual.finalizar()

    def admite_seguimiento(self):
        return self._estadoActual.admiteSeguimiento()

    # ----- PATRÓN: OBSERVER (sujeto) -----
    def suscribir(self, o):
        if o not in self._observadores:
            self._observadores.append(o)

    def desuscribir(self, o):
        if o in self._observadores:
            self._observadores.remove(o)

    def notificarObservadores(self):
        for o in list(self._observadores):
            try:
                o.actualizar(self)
            except Exception as e:                  # un observador defectuoso no deshace la operación
                self.fallos.append((datetime.now(), type(o).__name__, f"{type(e).__name__}: {e}"))

    # ----- PATRÓN: PROTOTYPE (prototipo concreto) -----
    def clonar(self):
        return Cita(prototipo=self)

    def clonar_seguimiento(self, fecha, hora, motivo=None):
        """Cita de seguimiento: conserva animal, veterinario y servicio; cambia lo que no se
        hereda (sin id, estado «pendiente», nueva fecha y hora)."""
        nueva = self.clonar()
        nueva.id = None
        nueva.cambiarEstado("pendiente")
        nueva.fecha, nueva.hora = fecha, hora
        if motivo:
            nueva.motivo = motivo
        return nueva

    def validar(self):
        self.fecha = fecha_valida(self.fecha)
        self.hora = hora_valida(self.hora)
        self.motivo = texto_requerido(self.motivo, "El motivo", 200)
        if self.animal_id is None:
            raise ErrorNegocio("Seleccione un animal")
        if self.veterinario_id is None:
            raise ErrorNegocio("Seleccione un veterinario")

    def aceptar(self, v):                           # PATRÓN: VISITOR (elemento)
        return v.visitarCita(self)


# ====================== HISTORIAL CLÍNICO ======================

class HistorialClinico(ElementoClinica):
    veterinario_nombre = None

    def __init__(self, id=None, fecha=None, diagnostico=None, tratamiento=None,
                 vacunas=None, alergias=None, proxima_vacuna=None,
                 animal_id=None, veterinario_id=None):
        self.id = id
        self.fecha = fecha or date.today().isoformat()
        self.diagnostico = diagnostico
        self.tratamiento = tratamiento
        self.vacunas = vacunas
        self.alergias = alergias
        self.proxima_vacuna = proxima_vacuna
        self.animal_id = animal_id
        self.veterinario_id = veterinario_id

    @property
    def idHistorial(self):
        return self.id

    def validar(self):
        self.diagnostico = texto_requerido(self.diagnostico, "El diagnóstico", 500)
        self.tratamiento = texto_requerido(self.tratamiento, "El tratamiento", 500)
        self.vacunas = texto_opcional(self.vacunas)
        self.alergias = texto_opcional(self.alergias)
        prox = (self.proxima_vacuna or "").strip()
        self.proxima_vacuna = fecha_valida(prox, "La próxima aplicación") if prox else None
        if self.proxima_vacuna and not self.vacunas:
            raise ErrorNegocio("Indique la vacuna a la que corresponde la próxima aplicación")

    # ----- PATRÓN: MEMENTO (originador) -----
    def guardarEstado(self):
        return MementoHistorial(self.fecha, self.diagnostico, self.tratamiento, self.vacunas,
                                self.alergias, self.proxima_vacuna)

    def restaurar(self, m):
        (self.fecha, self.diagnostico, self.tratamiento, self.vacunas, self.alergias,
         self.proxima_vacuna) = m._getEstado()

    def aceptar(self, v):                           # PATRÓN: VISITOR (elemento)
        return v.visitarHistorial(self)
