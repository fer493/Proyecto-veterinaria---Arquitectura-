# -*- coding: utf-8 -*-
"""
PATRONES DE DISEÑO de la clínica veterinaria (un solo archivo).

Cada sección agrupa los participantes de un patrón con los nombres de clases, atributos y
operaciones de su diagrama de clases. Las entidades que también participan en un patrón
(Cita, Animal, HistorialClinico, Propietario, Veterinario, Usuario) viven en modelo.py, y los
DAO / BaseDatos en persistencia.py; allí cada punto de aplicación lleva el comentario
«PATRÓN: <nombre>».

  Creacionales ..... Singleton (BaseDatos), Factory Method, Builder, Prototype
  Estructurales .... Adapter, Decorator, Facade, Proxy
  Comportamiento ... Template Method, State, Observer, Chain of Responsibility, Command,
                     Iterator, Memento, Visitor

Dependencias: este módulo solo importa errores, configuración y utilidades. Las entidades se
importan dentro de los métodos que las instancian (modelo.py importa este módulo).
"""
import re
import secrets
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import date, datetime

from configuracion import HORARIO_ATENCION, INTERVALO_CITA_MIN
from errores import ErrorNegocio, ErrorPago, ErrorSesion
from utilidades import entero, exigir, hash_password, verificar_password


def _modelo():
    """Módulo de entidades, cargado al usarse para no crear una importación circular."""
    import modelo
    return modelo


# =====================================================================================
#  PATRÓN: FACTORY METHOD (creacional)
#  CreadorUsuario define el método fábrica crearUsuario(); cada creador concreto decide qué
#  clase de Usuario instancia. ControlLogin y ControlUsuario trabajan con CreadorUsuario y con
#  la interfaz Usuario (getRol), sin conocer las clases concretas.
# =====================================================================================

class CreadorUsuario(ABC):
    ROL = None
    ACCESOS = []                # (hora, nombre, rol) de los ingresos de la sesión de la aplicación
    MAX_ACCESOS = 200

    def __init__(self):
        self._usuario = None

    @abstractmethod
    def crearUsuario(self, nombre, **datos):
        """Método fábrica: devuelve el producto concreto (Usuario)."""

    def crear(self, nombre, **datos):
        """Crea el usuario con el método fábrica y comprueba que su rol sea el del creador."""
        usuario = self.crearUsuario(nombre, **datos)
        if usuario.getRol() != self.ROL:
            raise ErrorNegocio("Rol de usuario no válido")
        self._usuario = usuario
        return usuario

    def registrarAcceso(self):
        """Anota el ingreso del último usuario creado por este creador."""
        u = self._usuario
        CreadorUsuario.ACCESOS.append((datetime.now(), u.nombre_usuario or u.nombre, u.getRol()))
        del CreadorUsuario.ACCESOS[:-self.MAX_ACCESOS]

    @staticmethod
    def paraRol(rol):
        """Creador que corresponde al rol (una instancia nueva por llamada)."""
        try:
            return {c.ROL: c for c in (CreadorAdministrador, CreadorRecepcionista,
                                       CreadorVeterinario, CreadorPropietario)}[rol]()
        except KeyError:
            raise ErrorNegocio("Rol de usuario no válido")


class CreadorVeterinario(CreadorUsuario):
    ROL = "Veterinario"

    def crearUsuario(self, nombre, **datos):
        return _modelo().Veterinario(nombre=nombre, **datos)


class CreadorPropietario(CreadorUsuario):
    ROL = "Propietario"

    def crearUsuario(self, nombre, **datos):
        datos.pop("especialidad", None)
        return _modelo().Propietario(nombre=nombre, **datos)


class CreadorAdministrador(CreadorUsuario):
    ROL = "Administrador"

    def crearUsuario(self, nombre, **datos):
        datos.pop("especialidad", None)
        return _modelo().Administrador(nombre=nombre, **datos)


class CreadorRecepcionista(CreadorUsuario):
    ROL = "Recepcionista"

    def crearUsuario(self, nombre, **datos):
        datos.pop("especialidad", None)
        return _modelo().Recepcionista(nombre=nombre, **datos)


# =====================================================================================
#  PATRÓN: BUILDER + DIRECTOR (creacional)
#  HistorialBuilder arma un HistorialClinico paso a paso; DirectorHistorial conoce las
#  secuencias de construcción (consulta general, control de vacunas). ControlHistorial usa
#  solo al Director.
# =====================================================================================

class HistorialBuilder(ABC):
    @abstractmethod
    def reiniciar(self): ...

    @abstractmethod
    def setFecha(self, fecha): ...

    @abstractmethod
    def setDiagnostico(self, diagnostico): ...

    @abstractmethod
    def setTratamiento(self, tratamiento): ...

    @abstractmethod
    def setVacunas(self, vacunas, proxima_vacuna=None): ...

    @abstractmethod
    def setAlergias(self, alergias): ...

    @abstractmethod
    def obtenerResultado(self): ...


class HistorialClinicoBuilder(HistorialBuilder):
    def __init__(self):
        self._historial = None
        self.reiniciar()

    def reiniciar(self):
        self._historial = _modelo().HistorialClinico()

    def setFecha(self, fecha):
        self._historial.fecha = fecha
        return self

    def setDiagnostico(self, diagnostico):
        self._historial.diagnostico = diagnostico
        return self

    def setTratamiento(self, tratamiento):
        self._historial.tratamiento = tratamiento
        return self

    def setVacunas(self, vacunas, proxima_vacuna=None):
        self._historial.vacunas = vacunas
        self._historial.proxima_vacuna = proxima_vacuna
        return self

    def setAlergias(self, alergias):
        self._historial.alergias = alergias
        return self

    def obtenerResultado(self):
        """Entrega el historial ya validado y deja el constructor listo para otro expediente."""
        try:
            self._historial.validar()
            return self._historial
        finally:
            self.reiniciar()


class DirectorHistorial:
    def __init__(self, builder: HistorialBuilder):
        self._builder = builder

    def construirConsultaGeneral(self, diagnostico, tratamiento, vacunas=None, alergias=None,
                                 proxima_vacuna=None):
        b = self._builder
        b.reiniciar()
        return (b.setFecha(date.today().isoformat())
                .setDiagnostico(diagnostico).setTratamiento(tratamiento)
                .setVacunas(vacunas, proxima_vacuna).setAlergias(alergias)
                .obtenerResultado())

    def construirControlVacunas(self, vacunas, proxima_vacuna=None):
        """Visita solo de vacunación: el Director fija el diagnóstico y el tratamiento."""
        b = self._builder
        b.reiniciar()
        return (b.setFecha(date.today().isoformat())
                .setDiagnostico("Control de vacunación (sin hallazgos)")
                .setTratamiento("Aplicación de vacuna")
                .setVacunas(vacunas, proxima_vacuna)
                .obtenerResultado())


# =====================================================================================
#  PATRÓN: PROTOTYPE (creacional)
#  PrototipoCita es la interfaz; Cita (modelo.py) es el prototipo concreto.
#  ControlCita.agendarCitaSeguimiento clona una cita existente.
# =====================================================================================

class PrototipoCita(ABC):
    @abstractmethod
    def clonar(self): ...


# =====================================================================================
#  PATRÓN: STATE (comportamiento)
#  Cita (contexto) delega en su estadoActual. Pendiente -> Confirmada | Cancelada | Finalizada;
#  Confirmada -> Cancelada | Finalizada; Cancelada y Finalizada ya no cambian.
# =====================================================================================

class EstadoCita(ABC):
    nombre = None

    def __init__(self):
        self._cita = None

    def setContexto(self, cita):
        self._cita = cita

    def confirmar(self):
        raise ErrorNegocio(self._rechazo("confirmar"))

    def cancelar(self):
        raise ErrorNegocio(self._rechazo("cancelar"))

    def finalizar(self):
        raise ErrorNegocio(self._rechazo("finalizar"))

    def admiteSeguimiento(self):
        return True

    # Qué acciones admite el estado: la interfaz las usa para habilitar o no sus botones
    def puedeConfirmar(self):
        return False

    def puedeCancelar(self):
        return False

    def puedeFinalizar(self):
        return False

    def _rechazo(self, accion):
        return f"No se puede {accion} una cita {self.nombre}"


class EstadoPendiente(EstadoCita):
    nombre = "pendiente"

    def confirmar(self):
        self._cita.cambiarEstado(EstadoConfirmada())

    def cancelar(self):
        self._cita.cambiarEstado(EstadoCancelada())

    def finalizar(self):
        self._cita.cambiarEstado(EstadoFinalizada())

    def puedeConfirmar(self):
        return True

    def puedeCancelar(self):
        return True

    def puedeFinalizar(self):
        return True


class EstadoConfirmada(EstadoCita):
    nombre = "confirmada"

    def cancelar(self):
        self._cita.cambiarEstado(EstadoCancelada())

    def finalizar(self):
        self._cita.cambiarEstado(EstadoFinalizada())

    def puedeCancelar(self):
        return True

    def puedeFinalizar(self):
        return True

    def _rechazo(self, accion):
        return "La cita ya está confirmada"


class EstadoCancelada(EstadoCita):
    nombre = "cancelada"

    def admiteSeguimiento(self):
        return False


class EstadoFinalizada(EstadoCita):
    nombre = "finalizada"


ESTADOS_CONCRETOS = {e.nombre: e for e in (EstadoPendiente, EstadoConfirmada,
                                           EstadoCancelada, EstadoFinalizada)}


def estadoDe(nombre):
    """Objeto de estado a partir del nombre guardado en la base de datos."""
    try:
        return ESTADOS_CONCRETOS[nombre]()
    except KeyError:
        raise ErrorNegocio(f"Estado de cita desconocido: {nombre}")


# =====================================================================================
#  PATRÓN: OBSERVER (comportamiento)
#  La Cita es el sujeto (suscribir / desuscribir / notificarObservadores). Observadores:
#  InterfazCita, Propietario y Veterinario (estos dos en modelo.py).
# =====================================================================================

class ObservadorCita(ABC):
    @abstractmethod
    def actualizar(self, cita): ...


# =====================================================================================
#  PATRÓN: CHAIN OF RESPONSIBILITY (comportamiento)
#  Antes de agendar una cita se comprueba, en orden: sesión, permisos, datos válidos,
#  existencia de animal y veterinario, y horario libre. Cada comprobación es un eslabón
#  que detiene la solicitud (ErrorNegocio) o la pasa al siguiente. ControlCita arma la cadena.
# =====================================================================================

class Solicitud:
    """Mensaje que viaja por la cadena."""
    def __init__(self, usuario=None, cita=None):
        self.usuario = usuario
        self.cita = cita


class ManejadorSolicitud(ABC):
    @abstractmethod
    def setSiguiente(self, h): ...

    @abstractmethod
    def manejar(self, solicitud) -> bool: ...


class ManejadorBase(ManejadorSolicitud):
    def __init__(self):
        self._siguiente = None

    def setSiguiente(self, h):
        self._siguiente = h
        return h                        # permite encadenar: a.setSiguiente(b).setSiguiente(c)

    def manejar(self, solicitud):
        """Entrega la solicitud al siguiente eslabón; True si toda la cadena la aprobó."""
        if self._siguiente is not None:
            return self._siguiente.manejar(solicitud)
        return True


class ManejadorAutenticacion(ManejadorBase):
    def manejar(self, solicitud):
        if solicitud.usuario is None:
            raise ErrorNegocio("Debe iniciar sesión para realizar esta acción")
        return super().manejar(solicitud)


class ManejadorPermisosRol(ManejadorBase):
    def __init__(self, *roles):
        super().__init__()
        self._roles = roles

    def manejar(self, solicitud):
        exigir(solicitud.usuario, *self._roles)
        return super().manejar(solicitud)


class ManejadorValidacionCita(ManejadorBase):
    def manejar(self, solicitud):
        solicitud.cita.validar()
        return super().manejar(solicitud)


class ManejadorExistenciaCita(ManejadorBase):
    def __init__(self, animal_dao, cita_dao):
        super().__init__()
        self._animales, self._citas = animal_dao, cita_dao

    def manejar(self, solicitud):
        c = solicitud.cita
        if self._animales.obtener(c.animal_id) is None:
            raise ErrorNegocio("El animal debe estar registrado previamente")
        if c.veterinario_id not in [v["id"] for v in self._citas.veterinarios()]:
            raise ErrorNegocio("No se encontró el veterinario")
        return super().manejar(solicitud)


class ManejadorDisponibilidadCita(ManejadorBase):
    def __init__(self, cita_dao):
        super().__init__()
        self._citas = cita_dao

    def manejar(self, solicitud):
        c = solicitud.cita
        if self._citas.hay_conflicto(c.veterinario_id, c.fecha, c.hora):
            raise ErrorNegocio("El veterinario ya tiene una cita en ese horario; elija otro")
        return super().manejar(solicitud)


# =====================================================================================
#  PATRÓN: COMMAND (comportamiento)
#  Cada acción sobre las citas es un Comando; el RECEPTOR es ControlCita y el INVOCADOR es
#  InterfazCita, que conserva la bitácora y la pila de «Deshacer».
# =====================================================================================

class Comando(ABC):
    usuario = None
    deshacible = False                  # los comandos que modifican datos lo ponen en True

    @abstractmethod
    def ejecutar(self): ...

    @abstractmethod
    def descripcion(self): ...

    def deshacer(self):
        raise ErrorNegocio("Esta acción no se puede deshacer")


class ComandoAgendarCita(Comando):
    deshacible = True

    def __init__(self, receptor, datos, usuario=None):
        self._receptor, self._datosCita, self.usuario = receptor, datos, usuario
        self.cita_id = None

    def ejecutar(self):
        self.cita_id = self._receptor.agendarCita(self.usuario, self._datosCita)
        return self.cita_id

    def deshacer(self):
        self._receptor.deshacer_agenda(self.usuario, self.cita_id)

    def descripcion(self):
        c = self._datosCita
        return f"Agendar cita (animal {c.animal_id}, vet {c.veterinario_id}, {c.fecha} {c.hora})"


class ComandoConsultarCitas(Comando):
    def __init__(self, receptor, usuario=None):
        self._receptor, self.usuario = receptor, usuario

    def ejecutar(self):
        return self._receptor.consultarCitas(self.usuario)

    def descripcion(self):
        return "Consultar citas programadas"


class ComandoConfirmarCita(Comando):
    deshacible = True

    def __init__(self, receptor, usuario, cita_id):
        self._receptor, self.usuario, self.cita_id = receptor, usuario, cita_id
        self._estadoAnterior = None

    def ejecutar(self):
        self._estadoAnterior = self._receptor.confirmarCita(self.usuario, self.cita_id)

    def deshacer(self):
        self._receptor.deshacer_cambio_estado(self.usuario, self.cita_id, self._estadoAnterior,
                                              "confirmada")

    def descripcion(self):
        return f"Confirmar cita #{self.cita_id}"


class ComandoCancelarCita(Comando):
    deshacible = True

    def __init__(self, receptor, usuario, cita_id):
        self._receptor, self.usuario, self.cita_id = receptor, usuario, cita_id
        self._estadoAnterior = None

    def ejecutar(self):
        self._estadoAnterior = self._receptor.cancelarCita(self.usuario, self.cita_id)

    def deshacer(self):
        self._receptor.deshacer_cambio_estado(self.usuario, self.cita_id, self._estadoAnterior,
                                              "cancelada")

    def descripcion(self):
        return f"Cancelar cita #{self.cita_id}"


class ComandoFinalizarCita(Comando):
    deshacible = True

    def __init__(self, receptor, usuario, cita_id):
        self._receptor, self.usuario, self.cita_id = receptor, usuario, cita_id
        self._estadoAnterior = None

    def ejecutar(self):
        self._estadoAnterior = self._receptor.finalizarCita(self.usuario, self.cita_id)

    def deshacer(self):
        self._receptor.deshacer_cambio_estado(self.usuario, self.cita_id, self._estadoAnterior,
                                              "finalizada")

    def descripcion(self):
        return f"Finalizar la cita #{self.cita_id}"


class ComandoCrearSeguimiento(Comando):
    deshacible = True

    def __init__(self, receptor, usuario, cita_id, fecha, hora):
        self._receptor, self.usuario = receptor, usuario
        self.cita_id, self._fecha, self._hora = cita_id, fecha, hora
        self.nueva_id = None

    def ejecutar(self):
        self.nueva_id = self._receptor.agendarCitaSeguimiento(self.usuario, self.cita_id,
                                                              self._fecha, self._hora)
        return self.nueva_id

    def deshacer(self):
        self._receptor.deshacer_agenda(self.usuario, self.nueva_id)

    def descripcion(self):
        return f"Cita de seguimiento de la #{self.cita_id} ({self._fecha} {self._hora})"


class InterfazCita(ObservadorCita):
    """INVOCADOR del patrón Command (comandoActual / setComando / ejecutarAccion) y
    OBSERVADOR del patrón Observer (actualizar). Registra la bitácora de acciones y la pila de
    «Deshacer» de la sesión."""
    MAXIMO = 500
    LIMITE_DESHACER = 20

    def __init__(self, control=None):
        self._control = control                 # ControlCita: receptor de los comandos
        self._comandoActual = None
        self.bitacora = []                      # (hora, usuario, acción, resultado)
        self.eventos = []                       # (hora, cita_id, evento) recibidos como observador
        self._pilaDeshacer = []
        self._candado = threading.Lock()

    # ----- Command: invocador -----
    def setComando(self, c):
        self._comandoActual = c

    def ejecutarAccion(self):
        comando = self._comandoActual
        if comando is None:
            raise ErrorNegocio("No hay una acción seleccionada")
        try:
            resultado = comando.ejecutar()
        except ErrorNegocio as e:
            self._anotar(comando, f"RECHAZADO: {e}")
            raise
        except Exception as e:
            self._anotar(comando, f"ERROR: {type(e).__name__}")
            raise
        self._anotar(comando, "OK")
        if comando.deshacible:
            with self._candado:
                self._pilaDeshacer.append(comando)
                del self._pilaDeshacer[:-self.LIMITE_DESHACER]
        return resultado

    def agendarCita(self, usuario, cita):
        self.setComando(ComandoAgendarCita(self._control, cita, usuario))
        return self.ejecutarAccion()

    def consultarCitas(self, usuario):
        self.setComando(ComandoConsultarCitas(self._control, usuario))
        return self.ejecutarAccion()

    def _propio(self, comando, usuario):
        return (usuario is not None and comando.usuario is not None
                and getattr(comando.usuario, "id", None) == getattr(usuario, "id", object()))

    def proxima_a_deshacer(self, usuario):
        """Descripción de la acción que se deshará (la última del usuario), o None."""
        with self._candado:
            if self._pilaDeshacer and self._propio(self._pilaDeshacer[-1], usuario):
                return self._pilaDeshacer[-1].descripcion()
        return None

    def deshacer(self, usuario):
        """Revierte la última acción deshacible del usuario y devuelve su descripción."""
        with self._candado:
            if not self._pilaDeshacer or not self._propio(self._pilaDeshacer[-1], usuario):
                raise ErrorNegocio("No hay acciones suyas para deshacer")
            comando = self._pilaDeshacer.pop()      # si falla no se reintenta: la pila no se atasca
        try:
            comando.deshacer()
        except ErrorNegocio as e:
            self._anotar(comando, f"DESHACER RECHAZADO: {e}")
            raise
        except Exception as e:
            self._anotar(comando, f"DESHACER ERROR: {type(e).__name__}")
            raise
        self._anotar(comando, "DESHECHO")
        return comando.descripcion()

    def limpiar_deshacer(self):
        """Al cerrar sesión: lo hecho por un usuario no se deshace desde otra sesión."""
        with self._candado:
            self._pilaDeshacer.clear()

    def _anotar(self, comando, resultado):
        usuario = getattr(comando.usuario, "nombre_usuario", "—")
        with self._candado:
            self.bitacora.append((datetime.now(), usuario, comando.descripcion(), resultado))
            del self.bitacora[:-self.MAXIMO]

    # ----- Observer: observador -----
    def actualizar(self, cita):
        with self._candado:
            self.eventos.append((datetime.now(), cita.id, cita.evento))
            del self.eventos[:-self.MAXIMO]


# =====================================================================================
#  PATRÓN: ITERATOR (comportamiento)
#  ListaHistoriales es la colección; crearIterador() entrega un IteradorHistorial que recorre
#  los registros del más antiguo al más reciente (IteradorHistorialReciente hace lo contrario).
#  Lo usan ControlReporte y la ficha del animal.
# =====================================================================================

class IteradorHistorial(ABC):
    @abstractmethod
    def siguiente(self): ...

    @abstractmethod
    def haySiguiente(self) -> bool: ...

    def __iter__(self):                     # también funciona con «for h in iterador»
        return self

    def __next__(self):
        if not self.haySiguiente():
            raise StopIteration
        return self.siguiente()


class ColeccionHistoriales(ABC):
    @abstractmethod
    def crearIterador(self): ...


class ListaHistoriales(ColeccionHistoriales):
    def __init__(self, historiales=()):
        self._registros = list(historiales)

    def agregarHistorial(self, h):
        self._registros.append(h)

    def __len__(self):
        return len(self._registros)

    def crearIterador(self):
        return IteradorHistorialCronologico(self)

    def crearIteradorReciente(self):
        return IteradorHistorialReciente(self)


class IteradorHistorialCronologico(IteradorHistorial):
    _reciente_primero = False

    def __init__(self, c: ListaHistoriales):
        self._coleccion = c
        self._posicionActual = 0
        # copia ordenada: el recorrido no se altera si la colección cambia mientras se recorre
        self._orden = sorted(c._registros, key=lambda h: (h.fecha, h.id or 0),
                             reverse=self._reciente_primero)

    def siguiente(self):
        if not self.haySiguiente():
            raise StopIteration
        h = self._orden[self._posicionActual]
        self._posicionActual += 1
        return h

    def haySiguiente(self):
        return self._posicionActual < len(self._orden)


class IteradorHistorialReciente(IteradorHistorialCronologico):
    """Del registro más reciente al más antiguo."""
    _reciente_primero = True


# =====================================================================================
#  PATRÓN: MEMENTO (comportamiento)
#  HistorialClinico (originador, modelo.py) crea un MementoHistorial con guardarEstado() y se
#  restaura con restaurar(m). ControlHistorial es el cuidador: guarda los mementos en
#  historialCambios y los usa en deshacerUltimoCambio().
# =====================================================================================

class MementoHistorial:
    """Instantánea inmutable del contenido de un historial clínico."""
    __slots__ = ("_fecha", "_diagnostico", "_tratamiento", "_vacunas", "_alergias",
                 "_proxima_vacuna")

    def __init__(self, fecha, diag, trat, vac, aler, proxima_vacuna=None):
        self._fecha, self._diagnostico, self._tratamiento = fecha, diag, trat
        self._vacunas, self._alergias, self._proxima_vacuna = vac, aler, proxima_vacuna

    def _getEstado(self):
        """Solo el originador (HistorialClinico) lee el contenido."""
        return (self._fecha, self._diagnostico, self._tratamiento, self._vacunas,
                self._alergias, self._proxima_vacuna)


# =====================================================================================
#  PATRÓN: VISITOR (comportamiento)
#  ElementoClinica (Animal, Cita, HistorialClinico) acepta un VisitanteClinica; un reporte
#  nuevo es un visitante nuevo, sin tocar las entidades. Lo usa ControlReporte.
# =====================================================================================

class ElementoClinica(ABC):
    @abstractmethod
    def aceptar(self, v): ...


class VisitanteClinica(ABC):
    @abstractmethod
    def visitarAnimal(self, a): ...

    @abstractmethod
    def visitarCita(self, c): ...

    @abstractmethod
    def visitarHistorial(self, h): ...


class VisitanteReporteMedico(VisitanteClinica):
    """Resumen médico: ficha de cada animal seguida de sus registros clínicos."""
    def __init__(self):
        self.lineas = []

    def visitarAnimal(self, a):
        if self.lineas:
            self.lineas.append("")
        self.lineas.append(f"ANIMAL #{a.id}: {a.nombre} ({a.especie}, {a.edad} años, {a.peso} kg)")

    def visitarHistorial(self, h):
        self.lineas.append(f"   {h.fecha} | Dx: {h.diagnostico} | Tx: {h.tratamiento} | "
                           f"Vacunas: {h.vacunas or '—'} | Alergias: {h.alergias or '—'}")

    def visitarCita(self, c):
        pass                                # este reporte no usa citas


class VisitanteAuditoriaCitas(VisitanteClinica):
    """Auditoría de citas: totales por estado y por veterinario, y cuántas están pagadas."""
    def __init__(self):
        self.por_estado, self.por_veterinario = {}, {}
        self.pagadas = 0
        self.detalle = []

    def visitarCita(self, c):
        self.por_estado[c.estado] = self.por_estado.get(c.estado, 0) + 1
        self.por_veterinario[c.veterinario_nombre] = self.por_veterinario.get(c.veterinario_nombre, 0) + 1
        self.pagadas += 1 if c.pagada else 0
        self.detalle.append(f"{c.fecha} {c.hora} | {c.animal_nombre} | {c.veterinario_nombre} | "
                            f"{c.estado} | {'Pagada' if c.pagada else 'Sin pago'}")

    def visitarAnimal(self, a):
        pass

    def visitarHistorial(self, h):
        pass

    @property
    def lineas(self):
        total = len(self.detalle)
        resumen = [f"Total de citas: {total}   (pagadas: {self.pagadas}, sin pago: {total - self.pagadas})",
                   "Por estado: " + ", ".join(f"{k}={v}" for k, v in sorted(self.por_estado.items())),
                   "Por veterinario: " + ", ".join(f"{k}={v}" for k, v in sorted(self.por_veterinario.items())),
                   ""]
        return resumen + self.detalle


# =====================================================================================
#  PATRÓN: TEMPLATE METHOD (comportamiento)
#  PlantillaDAO.ejecutarOperacion() fija el orden de toda operación (conectarBD ->
#  transacción con procesarConsulta -> desconectarBD); cada DAO solo define procesarConsulta()
#  con el SQL de sus operaciones. La transacción se escribe una vez y ningún DAO la olvida.
# =====================================================================================

class PlantillaDAO(ABC):
    def __init__(self, bd):
        self._bd = bd

    def ejecutarOperacion(self, operacion, *parametros):       # método plantilla
        self.conectarBD()                                      # 1. paso fijo
        try:
            with self._bd.conn:                                # 2. paso fijo: commit o rollback
                return self.procesarConsulta(operacion, *parametros)   # 3. paso variable
        finally:
            self.desconectarBD()                               # 4. paso fijo

    def conectarBD(self):
        """Toma la conexión compartida (Singleton): la abre solo si nadie la tenía abierta."""
        self._bd.conectar()

    def desconectarBD(self):
        """Libera la conexión; se cierra solo cuando ya nadie la usa."""
        self._bd.desconectar()

    @abstractmethod
    def procesarConsulta(self, operacion, *parametros):
        """Paso variable: ejecuta la consulta de la operación y devuelve su resultado."""

    def _ejecutarSQL(self, consulta, parametros):
        """Ejecuta (sql, modo) y entrega el resultado según el modo de la consulta."""
        sql, modo = consulta
        cursor = self._bd.conn.execute(sql, parametros)
        if modo == "id":
            return cursor.lastrowid
        if modo == "una":
            return cursor.fetchone()
        if modo == "todas":
            return cursor.fetchall()
        if modo == "existe":
            return cursor.fetchone() is not None
        return cursor.rowcount                                 # modo "filas"


# =====================================================================================
#  PATRÓN: ADAPTER (estructural)
#  El sistema solo conoce IPagador. PasarelaPagoAdapter lo implementa y traduce hacia el SDK
#  del proveedor (APIStripeSDK, aquí simulado). Cambiar de proveedor = otro adaptador.
#  Lo usa ControlCita.procesarPagoCita y PagosSubsistema.procesarAnticipo.
# =====================================================================================

class ErrorPasarela(Exception):
    """Falla de comunicación con el proveedor (la lanza el SDK externo)."""


class TarjetaRechazada(ErrorPasarela):
    """El proveedor rechazó el cargo; 'codigo' es su código de falla."""
    def __init__(self, codigo):
        super().__init__(codigo)
        self.codigo = codigo


class IPagador(ABC):
    """Interfaz objetivo (Target) que espera el sistema de la clínica."""
    referencia = None                   # referencia del último cargo aprobado

    @abstractmethod
    def procesarPago(self, monto: float, descripcion="", token=None) -> bool:
        """Cobra 'monto' (pesos). True si se aprobó; lanza ErrorPago si falla."""

    @abstractmethod
    def reembolsar(self, referencia):
        """Revierte un cargo ya realizado. Lanza ErrorPago si no se pudo."""


class APIStripeSDK:
    """ADAPTADO (Adaptee): simula el SDK de un proveedor real, con interfaz propia e
    incompatible (montos en centavos, tokens, excepciones del proveedor). Se sustituye por el SDK
    real sin cambiar el resto del sistema.

    Tokens de prueba: tok_test_ok, tok_test_declined, tok_test_nofunds, tok_test_timeout.
    En una pasarela real el SDK convierte la tarjeta en un token desde el navegador: este
    servidor nunca recibe ni guarda el número de tarjeta."""
    FALLAS = {"tok_test_declined": "card_declined", "tok_test_nofunds": "insufficient_funds"}
    TOKENS_VALIDOS = ("tok_test_ok", "tok_test_declined", "tok_test_nofunds", "tok_test_timeout")

    def __init__(self):
        self._cargos = {}
        self._candado = threading.Lock()

    def chargeInCents(self, amount: int, token="tok_test_ok") -> str:
        if token == "tok_test_timeout":
            raise ErrorPasarela("timeout")
        if token in self.FALLAS:
            raise TarjetaRechazada(self.FALLAS[token])
        if token != "tok_test_ok":
            raise TarjetaRechazada("invalid_source")
        cargo = "ch_" + secrets.token_hex(8)
        with self._candado:
            self._cargos[cargo] = amount
        return cargo

    def verifyTransaction(self, token) -> bool:
        return token in self.TOKENS_VALIDOS

    def refund(self, charge_id):
        with self._candado:
            if self._cargos.pop(charge_id, None) is None:
                raise ErrorPasarela("cargo desconocido")


class PasarelaPagoAdapter(IPagador):
    MENSAJES = {"card_declined": "La tarjeta fue rechazada",
                "insufficient_funds": "Fondos insuficientes"}

    def __init__(self, apiExterna: APIStripeSDK):
        self._apiExterna = apiExterna
        self._local = threading.local()         # la referencia es propia de cada hilo

    @property
    def referencia(self):
        return getattr(self._local, "referencia", None)

    def procesarPago(self, monto, descripcion="", token=None):
        if not self._apiExterna.verifyTransaction(token):
            raise ErrorPago("Medio de pago no válido")
        try:
            self._local.referencia = self._apiExterna.chargeInCents(
                self._convertToServiceFormat(monto), token)
        except TarjetaRechazada as e:
            raise ErrorPago(self.MENSAJES.get(e.codigo, "No fue posible procesar el pago"))
        except ErrorPasarela:
            raise ErrorPago("El servicio de pagos no respondió. No se realizó ningún cargo; "
                            "intente de nuevo en unos minutos")
        return True

    def reembolsar(self, referencia):
        try:
            self._apiExterna.refund(referencia)
        except ErrorPasarela:
            raise ErrorPago("No fue posible revertir el cargo")

    def _convertToServiceFormat(self, monto):
        """Pesos (float) -> centavos (int), que es lo que entiende el SDK."""
        return int(round(monto * 100))


# =====================================================================================
#  PATRÓN: DECORATOR (estructural)
#  Responsabilidades añadidas a un servicio sin modificarlo: el servicio base de consulta se
#  envuelve con servicios extra (examen médico) y con la auditoría de seguridad. Se apilan en
#  ClienteClinica.procesarPeticion():
#      DecoradorAuditoriaLog( DecoradorServicioExtra( ServicioConsultaBase ) )
# =====================================================================================

class IComponenteServicio(ABC):
    @abstractmethod
    def ejecutar(self):
        """Devuelve el detalle del cobro: {'conceptos': [(nombre, precio)], 'total': float}."""


class ServicioConsultaBase(IComponenteServicio):
    def __init__(self, nombre, precio):
        self._nombre, self._precio = nombre, float(precio)

    def ejecutar(self):
        return {"conceptos": [(self._nombre, self._precio)], "total": self._precio}


class BaseDecorator(IComponenteServicio):
    def __init__(self, c: IComponenteServicio):
        self._wrappee = c

    def ejecutar(self):
        return self._wrappee.ejecutar()


class DecoradorServicioExtra(BaseDecorator):
    """Suma un servicio adicional (p. ej. un examen médico) al cobro del servicio envuelto."""
    def __init__(self, c, nombre_extra, precio_extra):
        super().__init__(c)
        self._extra = (nombre_extra, float(precio_extra))
        self._detalle = None

    def ejecutar(self):
        self._detalle = super().ejecutar()
        self.agregarExamenMedico()
        return self._detalle

    def agregarExamenMedico(self):
        nombre, precio = self._extra
        self._detalle["conceptos"].append((nombre, precio))
        self._detalle["total"] += precio


class DecoradorAuditoriaLog(BaseDecorator):
    """Deja constancia de cada cobro calculado. Nunca guarda datos de pago."""
    MAXIMO = 500

    def __init__(self, c, bitacora=None):
        super().__init__(c)
        self._bitacora = bitacora if bitacora is not None else []
        self._detalle = None

    def ejecutar(self):
        self._detalle = super().ejecutar()
        self.registrarLogSeguridad()
        return self._detalle

    def registrarLogSeguridad(self):
        conceptos = ", ".join(n for n, _ in self._detalle["conceptos"])
        self._bitacora.append((datetime.now(), conceptos, self._detalle["total"]))
        del self._bitacora[:-self.MAXIMO]


class ClienteClinica:
    """Cliente del Decorator: arma la pila de decoradores y ejecuta el servicio."""
    def __init__(self, bitacora=None):
        self._bitacora = bitacora

    def procesarPeticion(self, servicio, extra=None):
        componente = ServicioConsultaBase(servicio["nombre"], servicio["precio"])
        if extra is not None:
            componente = DecoradorServicioExtra(componente, extra["nombre"], extra["precio"])
        return DecoradorAuditoriaLog(componente, self._bitacora).ejecutar()


# =====================================================================================
#  PATRÓN: FACADE (estructural)
#  FachadaVeterinaria ofrece pocas operaciones al sitio web (agendarCitaCompleta,
#  consultarExpedienteGeneral) y coordina los subsistemas de citas, historial y pagos, que el
#  cliente no conoce. El portal la usa a través del Proxy.
# =====================================================================================

class CitasSubsistema:
    CAMPOS_CITA = ("id", "fecha", "hora", "animal", "veterinario", "servicio", "estado")

    def __init__(self, cita_dao, animal_dao, servicio_dao):
        self._citas, self._animales, self._servicios = cita_dao, animal_dao, servicio_dao

    def verificarDisponibilidad(self, propietario_id, datos):
        """Reglas del agendado en línea. Devuelve (cita, servicio, servicio_extra). El precio sale
        siempre de la base de datos, nunca de la petición."""
        Cita = _modelo().Cita
        animal_id = entero(datos.get("animal_id"), "La mascota", 1)
        veterinario_id = entero(datos.get("veterinario_id"), "El veterinario", 1)
        servicio_id = entero(datos.get("servicio_id"), "El servicio", 1)
        cita = Cita(fecha=_texto(datos, "fecha"), hora=_texto(datos, "hora"),
                    motivo=_texto(datos, "motivo"), animal_id=animal_id,
                    veterinario_id=veterinario_id, servicio_id=servicio_id)
        cita.validar()
        animal = self._animales.obtener(animal_id)
        if animal is None or animal["propietario_id"] != propietario_id:
            raise ErrorNegocio("La mascota seleccionada no es válida")
        if veterinario_id not in [v["id"] for v in self._citas.veterinarios()]:
            raise ErrorNegocio("No se encontró el veterinario")
        catalogo = self._servicios.listar()
        servicio = next((s for s in catalogo if s["id"] == servicio_id), None)
        if servicio is None or servicio["precio"] <= 0:
            raise ErrorNegocio("Seleccione un servicio disponible")
        extra = None
        if datos.get("extra_servicio_id") not in (None, "", 0, "0"):
            extra_id = entero(datos.get("extra_servicio_id"), "El servicio adicional", 1)
            extra = next((s for s in catalogo if s["id"] == extra_id), None)
            if extra is None or extra["precio"] <= 0 or extra_id == servicio_id:
                raise ErrorNegocio("Seleccione un servicio adicional válido")
        if datetime.strptime(f"{cita.fecha} {cita.hora}", "%Y-%m-%d %H:%M") <= datetime.now():
            raise ErrorNegocio("La cita debe ser en una fecha y hora futuras")
        if not (HORARIO_ATENCION[0] <= cita.hora < HORARIO_ATENCION[1]):
            raise ErrorNegocio(f"Atendemos de {HORARIO_ATENCION[0]} a {HORARIO_ATENCION[1]}")
        if int(cita.hora[3:]) % INTERVALO_CITA_MIN:
            raise ErrorNegocio(f"Las citas en línea se agendan cada {INTERVALO_CITA_MIN} minutos")
        if self._citas.hay_conflicto(cita.veterinario_id, cita.fecha, cita.hora):
            raise ErrorNegocio("Ese horario ya no está disponible; elija otro")
        return cita, servicio, extra

    def guardarCita(self, cita):
        """Reserva el horario (el índice único de la base evita carreras entre solicitudes)."""
        try:
            return self._citas.guardarCita(cita)
        except sqlite3.IntegrityError:
            raise ErrorNegocio("Ese horario ya no está disponible; elija otro")

    def liberarReserva(self, cita_id):
        self._citas.eliminar_reserva(cita_id)

    def catalogo(self, propietario_id):
        """Datos del formulario: solo SUS mascotas, veterinarios activos y servicios con precio."""
        return {
            "mascotas": [{"id": a["id"], "nombre": a["nombre"]}
                         for a in self._animales.listar_por_propietario(propietario_id)],
            "veterinarios": [{"id": v["id"], "nombre": v["nombre"], "especialidad": v["especialidad"]}
                             for v in self._citas.veterinarios()],
            "servicios": [{"id": s["id"], "nombre": s["nombre"], "precio": s["precio"]}
                          for s in self._servicios.listar() if s["precio"] > 0],
            "horario": {"inicio": HORARIO_ATENCION[0], "fin": HORARIO_ATENCION[1],
                        "intervalo": INTERVALO_CITA_MIN},
        }

    def citasDe(self, propietario_id):
        resultado = []
        for r in self._citas.listar_por_propietario(propietario_id):
            fila = {k: r[k] for k in self.CAMPOS_CITA}
            fila["pago"] = "Pagado" if r["pagada"] else "Por pagar"
            resultado.append(fila)
        return resultado


class HistorialSubsistema:
    def __init__(self, historial_dao):
        self._historial = historial_dao
        self._director = DirectorHistorial(HistorialClinicoBuilder())

    def crearExpedienteInicial(self, animal_id, veterinario_id):
        """Si el animal aún no tiene expediente, abre uno con un registro de alta."""
        if self._historial.consultarHistorial(animal_id):
            return None
        h = self._director.construirConsultaGeneral(
            "Expediente inicial (aún sin consulta)", "Pendiente de la primera consulta")
        h.animal_id, h.veterinario_id = animal_id, veterinario_id
        return self._historial.guardarHistorial(h)

    def actualizarNotas(self, animal_id, veterinario_id, notas):
        """Agrega al expediente una nota informativa del propietario (no es un dato clínico)."""
        h = self._director.construirConsultaGeneral("Nota del propietario (portal web)", notas)
        h.animal_id, h.veterinario_id = animal_id, veterinario_id
        return self._historial.guardarHistorial(h)


class PagosSubsistema:
    PAGO_EN_CLINICA = "efectivo"        # medio de pago sin pasarela: se cobra en recepción

    def __init__(self, pago_dao, pagador: IPagador, reintentos=3, espera=0.3):
        self._pagos, self._pagador = pago_dao, pagador
        self._reintentos, self._espera = reintentos, espera
        self.por_conciliar = []         # cargos que no pudieron revertirse: revisión manual

    def validarMedioPago(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_]{3,64}", token):
            raise ErrorNegocio("Seleccione un medio de pago")
        return token

    def procesarAnticipo(self, cita_id, total, descripcion, token):
        """Cobra por la pasarela y registra el pago. Devuelve la referencia del cargo (None si el
        pago es en la clínica). Si el pago no se puede registrar, reembolsa el cargo."""
        if token == self.PAGO_EN_CLINICA:
            return None
        try:
            self._pagador.procesarPago(total, descripcion, token)
        except ErrorNegocio:
            raise
        except Exception:
            raise ErrorPago("No fue posible procesar el pago")
        referencia = self._pagador.referencia
        try:
            self._pagos.guardar(cita_id, total, referencia, metodo="web")
        except sqlite3.Error:
            self._reembolsar(cita_id, referencia)
            raise ErrorPago("No pudimos confirmar su pago. Si ve un cargo, será reembolsado")
        return referencia

    def _reembolsar(self, cita_id, referencia):
        """Reintenta el reembolso; el cobro nunca se reintenta (podría cobrar dos veces)."""
        for n in range(1, self._reintentos + 1):
            try:
                self._pagador.reembolsar(referencia)
                return
            except ErrorPago:
                if n < self._reintentos:
                    time.sleep(self._espera * n)
        self.por_conciliar.append((cita_id, referencia))


_HASH_FALSO = []


def _hash_falso():
    if not _HASH_FALSO:
        _HASH_FALSO.append(hash_password("contraseña-inexistente"))
    return _HASH_FALSO[0]


def _texto(datos, clave):
    """Valor de texto del JSON recibido (cualquier otro tipo se trata como vacío)."""
    valor = datos.get(clave)
    return valor if isinstance(valor, str) else ""


# =====================================================================================
#  PATRÓN: PROXY (estructural, de protección)
#  Subject es la interfaz común; RealSubject (la fachada) hace el trabajo; Proxy exige sesión
#  vigente (checkAccess) y toma el propietario de la SESIÓN, nunca de la petición. Client es
#  quien pide el expediente. El servidor HTTP solo ve al Proxy.
# =====================================================================================

class Subject(ABC):
    @abstractmethod
    def request(self, operacion, contexto, datos=None):
        """'contexto' es el id del propietario en el sujeto real y el token en el Proxy."""


class RealSubject(Subject):
    OPERACIONES = ()                    # operaciones que el Proxy puede pedir

    def request(self, operacion, contexto, datos=None):
        if operacion not in self.OPERACIONES:
            raise ErrorNegocio("Operación no disponible")
        metodo = getattr(self, operacion)
        return metodo(contexto) if datos is None else metodo(contexto, datos)


class FachadaVeterinaria(RealSubject):
    OPERACIONES = ("agendarCitaCompleta", "consultarExpedienteGeneral", "catalogo")

    def __init__(self, citas: CitasSubsistema, historial: HistorialSubsistema,
                 pagos: PagosSubsistema, cuenta_dao):
        self._subsistemaCitas = citas
        self._subsistemaHistorial = historial
        self._subsistemaPagos = pagos
        self._cuentas = cuenta_dao
        self.bitacoraServicios = []     # auditoría de los cobros calculados (Decorator)

    def autenticar(self, nombre_usuario, password):
        """Devuelve (propietario_id, nombre). El mensaje de error es genérico a propósito
        (no revela si el usuario existe)."""
        nombre_usuario = (nombre_usuario or "").strip() if isinstance(nombre_usuario, str) else ""
        password = password if isinstance(password, str) else ""
        fila = self._cuentas.buscar(nombre_usuario) if nombre_usuario else None
        valido = verificar_password(password, fila["password"] if fila else _hash_falso())
        if fila is None or not valido or not fila["estado"]:
            raise ErrorSesion("Usuario o contraseña incorrectos")
        return fila["propietario_id"], fila["nombre"]

    def catalogo(self, propietario_id):
        return self._subsistemaCitas.catalogo(propietario_id)

    def consultarExpedienteGeneral(self, propietario_id):
        """Las citas del propietario con el estado de su pago."""
        return self._subsistemaCitas.citasDe(propietario_id)

    def agendarCitaCompleta(self, propietario_id, datos):
        """Valida -> reserva el horario -> calcula el cobro -> cobra -> abre el expediente.
        Si el cobro falla se libera la reserva."""
        pagos = self._subsistemaPagos
        token = pagos.validarMedioPago(datos.get("token_pago"))
        cita, servicio, extra = self._subsistemaCitas.verificarDisponibilidad(propietario_id, datos)
        cita_id = self._subsistemaCitas.guardarCita(cita)
        try:
            detalle = ClienteClinica(self.bitacoraServicios).procesarPeticion(servicio, extra)
            referencia = pagos.procesarAnticipo(
                cita_id, detalle["total"], f"Cita #{cita_id} - {servicio['nombre']}", token)
        except Exception:
            self._subsistemaCitas.liberarReserva(cita_id)
            raise
        try:
            self._subsistemaHistorial.crearExpedienteInicial(cita.animal_id, cita.veterinario_id)
            notas = _texto(datos, "notas").strip()
            if notas:
                self._subsistemaHistorial.actualizarNotas(cita.animal_id, cita.veterinario_id,
                                                          notas[:300])
        except (ErrorNegocio, sqlite3.Error):
            pass                        # el expediente es secundario: la cita ya quedó agendada
        resultado = {"cita_id": cita_id, "referencia": referencia, "monto": detalle["total"],
                     "conceptos": [n for n, _ in detalle["conceptos"]]}
        if referencia is None:
            resultado["pago"] = "efectivo"
        return resultado


class Proxy(Subject):
    DURACION = 2 * 3600                 # segundos

    def __init__(self, realSubject: FachadaVeterinaria):
        self._realSubject = realSubject
        self._sesiones = {}             # token -> (propietario_id, nombre, expira)
        self._candado = threading.Lock()
        self.auditoria = []

    def iniciarSesion(self, nombre_usuario, password):
        propietario_id, nombre = self._realSubject.autenticar(nombre_usuario, password)
        token = secrets.token_urlsafe(32)
        with self._candado:
            self._sesiones[token] = (propietario_id, nombre, time.time() + self.DURACION)
        self.auditoria.append((datetime.now(), propietario_id, "login"))
        return token, nombre

    def cerrarSesion(self, token):
        with self._candado:
            self._sesiones.pop(token or "", None)

    def request(self, operacion, token, datos=None):
        propietario_id = self._checkAccess(token)
        try:
            resultado = self._realSubject.request(operacion, propietario_id, datos)
        except ErrorNegocio as e:
            self.auditoria.append((datetime.now(), propietario_id, f"{operacion}:rechazada:{e}"))
            raise
        detalle = f":{resultado['cita_id']}" if isinstance(resultado, dict) and "cita_id" in resultado else ""
        self.auditoria.append((datetime.now(), propietario_id, f"{operacion}{detalle}"))
        return resultado

    def _checkAccess(self, token):
        """Id del propietario de la sesión vigente; ErrorSesion si no la hay."""
        with self._candado:
            dato = self._sesiones.get(token or "")
            if dato and time.time() > dato[2]:
                del self._sesiones[token]
                dato = None
        if dato is None:
            raise ErrorSesion("Sesión inválida o vencida")
        return dato[0]


class Client:
    """Cliente del Proxy: pide el expediente del propietario de la sesión."""
    def __init__(self, sujeto: Subject):
        self._sujeto = sujeto

    def solicitarExpediente(self, token):
        return self._sujeto.request("consultarExpedienteGeneral", token)


class ClienteApp:
    """Cliente del Facade: traduce las peticiones web a operaciones de la fachada (vía Proxy)."""
    def __init__(self, proxy: Proxy):
        self._proxy = proxy

    def enviarPeticionWeb(self, operacion, token, datos=None):
        return self._proxy.request(operacion, token, datos)

    def iniciarSesion(self, nombre_usuario, password):
        return self._proxy.iniciarSesion(nombre_usuario, password)

    def cerrarSesion(self, token):
        self._proxy.cerrarSesion(token)
