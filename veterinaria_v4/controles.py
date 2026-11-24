# -*- coding: utf-8 -*-
"""
CONTROL: reglas de negocio y permisos. Es la capa entre la interfaz (Tkinter) y los DAO.
Cada operación exige el rol correspondiente aquí (en el servidor), no solo en la pantalla.

Patrones que se aplican en esta capa (los participantes están en patrones.py):
  Factory Method ......... ControlLogin y ControlUsuario crean usuarios con CreadorUsuario
  Chain of Responsibility  ControlCita valida cada cita con una cadena de manejadores
  Command ................ ControlCita es el receptor de los comandos de InterfazCita
  Observer ............... ControlCita suscribe observadores a cada Cita y los notifica
  State .................. los cambios de estado los decide la propia Cita
  Prototype .............. ControlCita.agendarCitaSeguimiento clona una cita
  Builder ................ ControlHistorial arma los historiales con DirectorHistorial
  Memento ................ ControlHistorial guarda las instantáneas de los cambios
  Iterator + Visitor ..... ControlReporte arma los reportes médico y de auditoría
  Adapter ................ ControlCita.procesarPagoCita cobra a través de IPagador
"""
import re
import sqlite3
from datetime import date, datetime, timedelta

from errores import ErrorNegocio
from configuracion import ROLES_GESTIONABLES
from modelo import (Animal, BuzonNotificaciones, Cita, Propietario, Veterinario)
from patrones import (APIStripeSDK, CreadorUsuario, DirectorHistorial, HistorialClinicoBuilder,
                      InterfazCita, IPagador, ListaHistoriales, ManejadorAutenticacion,
                      ManejadorDisponibilidadCita, ManejadorExistenciaCita, ManejadorPermisosRol,
                      ManejadorValidacionCita, PasarelaPagoAdapter, Solicitud,
                      VisitanteAuditoriaCitas, VisitanteReporteMedico)
from persistencia import (AnimalDAO, CitaDAO, CuentaWebDAO, HistorialDAO, PagoDAO, PropietarioDAO,
                          ReporteDAO, ServicioDAO, UsuarioDAO, animal_desde_fila,
                          cita_desde_fila, historial_desde_fila)
from utilidades import (decimal, escribir_pdf, exigir, fecha_valida, hash_password,
                        texto_opcional, texto_requerido, verificar_password)


class ControlLogin:
    def __init__(self, db):
        self.dao = UsuarioDAO(db)

    def validarCredenciales(self, nombre_usuario, password):
        nombre_usuario = (nombre_usuario or "").strip()
        if not nombre_usuario or not password:
            raise ErrorNegocio("Ingrese su nombre de usuario y contraseña")
        try:
            fila = self.dao.buscar_por_nombre_usuario(nombre_usuario)
            if fila is None:
                raise ErrorNegocio("No existe una cuenta asociada a ese usuario")
            if not verificar_password(password, fila["password"]):
                raise ErrorNegocio("Credenciales incorrectas")
            if not fila["estado"]:
                raise ErrorNegocio("La cuenta está inactiva")
            # PATRÓN: FACTORY METHOD - el creador del rol decide qué clase de Usuario se instancia;
            # este código no conoce Administrador, Recepcionista ni Veterinario.
            creador = CreadorUsuario.paraRol(fila["rol"])
            datos = dict(id=fila["id"], nombre_usuario=fila["nombre_usuario"], estado=True)
            if fila["rol"] == "Veterinario":
                vet = self.dao.obtener_veterinario(fila["id"])
                datos.update(especialidad=vet["especialidad"], veterinario_id=vet["id"])
            usuario = creador.crear(fila["nombre"], **datos)
            creador.registrarAcceso()
            return usuario
        except sqlite3.Error:
            raise ErrorNegocio("No fue posible realizar la autenticación")

    def cerrarSesion(self):
        return None


class ControlUsuario:
    def __init__(self, db):
        self.dao = UsuarioDAO(db)

    def _validar(self, nombre, rol, especialidad):
        nombre = texto_requerido(nombre, "El nombre")
        if rol not in ROLES_GESTIONABLES:
            raise ErrorNegocio("El rol debe ser Veterinario o Recepcionista")
        esp = texto_opcional(especialidad, 80) if rol == "Veterinario" else None
        return nombre, esp

    def consultar(self, usuario):
        exigir(usuario, "Administrador")
        return self.dao.listar_gestionables()

    def registrar(self, usuario, nombre_usuario, nombre, password, rol, especialidad):
        exigir(usuario, "Administrador")
        nombre_usuario = texto_requerido(nombre_usuario, "El nombre de usuario", 30)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,30}", nombre_usuario):
            raise ErrorNegocio("El usuario solo admite letras, números, . _ - (mínimo 3)")
        nombre, esp = self._validar(nombre, rol, especialidad)
        if len(password or "") < 8:
            raise ErrorNegocio("La contraseña debe tener al menos 8 caracteres")
        if self.dao.buscar_por_nombre_usuario(nombre_usuario):
            raise ErrorNegocio("El nombre de usuario ya está registrado")
        # PATRÓN: FACTORY METHOD - el creador del rol arma el usuario con el rol correcto
        nuevo = CreadorUsuario.paraRol(rol).crear(nombre, nombre_usuario=nombre_usuario, especialidad=esp)
        try:
            return self.dao.guardar(nuevo.nombre_usuario, nuevo.nombre, hash_password(password),
                                    nuevo.getRol(), getattr(nuevo, "especialidad", None))
        except sqlite3.IntegrityError:
            raise ErrorNegocio("El nombre de usuario ya está registrado")

    def modificar(self, usuario, id, nombre, rol, estado, password, especialidad):
        exigir(usuario, "Administrador")
        if not self.dao.existe(id):
            raise ErrorNegocio("No se encontró la cuenta que desea modificar")
        nombre, esp = self._validar(nombre, rol, especialidad)
        pw_hash = None
        if password:
            if len(password) < 8:
                raise ErrorNegocio("La contraseña debe tener al menos 8 caracteres")
            pw_hash = hash_password(password)
        self.dao.actualizar(id, nombre, rol, estado, pw_hash, esp)


class ControlPropietario:
    def __init__(self, db):
        self.dao = PropietarioDAO(db)
        self.cuentas = CuentaWebDAO(db)

    def _validar_cuenta(self, nombre_usuario, password):
        nombre_usuario = texto_requerido(nombre_usuario, "El usuario web", 30)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,30}", nombre_usuario):
            raise ErrorNegocio("El usuario web solo admite letras, números, . _ - (mínimo 3)")
        if len(password or "") < 8:
            raise ErrorNegocio("La contraseña web debe tener al menos 8 caracteres")
        if self.cuentas.buscar(nombre_usuario):
            raise ErrorNegocio("Ese usuario web ya está registrado")
        return nombre_usuario

    def registrar(self, usuario, nombre, telefono, usuario_web=None, password_web=None):
        """Registra al propietario y, si se indica usuario/contraseña web, su cuenta del portal."""
        exigir(usuario, "Recepcionista", "Administrador")
        p = Propietario(nombre=nombre, telefono=telefono)
        p.validar()
        quiere_cuenta = bool((usuario_web or "").strip() or password_web)
        if quiere_cuenta:
            usuario_web = self._validar_cuenta(usuario_web, password_web)   # antes de guardar nada
        nuevo = self.dao.guardar(p)
        if quiere_cuenta:
            self.cuentas.guardar(nuevo, usuario_web, hash_password(password_web))
        return nuevo

    def crear_cuenta_web(self, usuario, propietario_id, usuario_web, password_web):
        exigir(usuario, "Recepcionista", "Administrador")
        if not self.dao.existe(propietario_id):
            raise ErrorNegocio("El propietario no existe")
        usuario_web = self._validar_cuenta(usuario_web, password_web)
        try:
            return self.cuentas.guardar(propietario_id, usuario_web, hash_password(password_web))
        except sqlite3.IntegrityError:
            raise ErrorNegocio("El propietario ya tiene una cuenta web")

    def listar(self, usuario):
        exigir(usuario, "Recepcionista", "Administrador")
        return self.dao.listar()

    def modificar(self, usuario, id, nombre, telefono):
        """CU12: solo el Administrador. El permiso se exige aquí (servidor), no solo en la interfaz."""
        exigir(usuario, "Administrador")
        if not self.dao.existe(id):
            raise ErrorNegocio("El propietario no existe")
        p = Propietario(id, nombre, telefono)
        p.validar()
        self.dao.actualizar(p)


class ControlAnimal:
    def __init__(self, db):
        self.dao = AnimalDAO(db)
        self.propietarios = PropietarioDAO(db)
        self.historial = HistorialDAO(db)
        self.citas = CitaDAO(db)

    def _armar(self, id, nombre, especie, raza, edad, peso, propietario_id):
        a = Animal(id, nombre, especie, raza, edad, peso, propietario_id)
        a.validar()
        if a.propietario_id is not None and not self.propietarios.existe(a.propietario_id):
            raise ErrorNegocio("El propietario seleccionado no existe")
        return a

    def registrar(self, usuario, nombre, especie, raza, edad, peso, propietario_id=None):
        exigir(usuario, "Recepcionista", "Administrador")
        return self.dao.guardarAnimal(self._armar(None, nombre, especie, raza, edad, peso, propietario_id))

    def actualizar(self, usuario, id, nombre, especie, raza, edad, peso, propietario_id=None):
        exigir(usuario, "Recepcionista", "Administrador")
        if self.dao.obtener(id) is None:
            raise ErrorNegocio(f"No existe un animal con ID {id}")
        self.dao.actualizarAnimal(self._armar(id, nombre, especie, raza, edad, peso, propietario_id))

    def obtener(self, usuario, id):
        exigir(usuario, "Recepcionista", "Administrador", "Veterinario")
        fila = self.dao.obtener(id)
        if fila is None:
            raise ErrorNegocio(f"No existe un animal con ID {id}")
        return fila

    def listar(self, usuario):
        exigir(usuario, "Recepcionista", "Administrador", "Veterinario")
        return self.dao.listar()

    def buscar(self, usuario, texto):
        exigir(usuario, "Administrador", "Veterinario")
        texto = (texto or "").strip()
        if not texto:
            raise ErrorNegocio("Ingrese un ID o nombre para buscar")
        resultados = self.dao.buscarAnimal(texto)
        if not resultados:
            raise ErrorNegocio("No se encontraron resultados")
        return resultados

    def consultar(self, usuario, id):
        exigir(usuario, "Administrador", "Veterinario")
        return {"animal": self.obtener(usuario, id),
                "historial": self.historial.consultarHistorial(id),
                "citas": self.citas.listar_por_animal(id)}


class ControlCita:
    """Receptor de los comandos de cita (Command). Cada cita que maneja se arma con sus
    observadores (Observer): la interfaz, el propietario del animal y el veterinario."""
    def __init__(self, db, buzon=None, pagador: IPagador = None):
        self.dao = CitaDAO(db)
        self.animales = AnimalDAO(db)
        self.propietarios = PropietarioDAO(db)
        self.servicios = ServicioDAO(db)
        self.pagos = PagoDAO(db)
        self.buzon = buzon if buzon is not None else BuzonNotificaciones()
        self.interfaz = None                    # InterfazCita: la asigna Controles
        self.pagador = pagador if pagador is not None else PasarelaPagoAdapter(APIStripeSDK())
        self.fallos = []                        # (hora, observador, error)
        # PATRÓN: CHAIN OF RESPONSIBILITY - validaciones de una cita, en orden, como eslabones
        # independientes (sesión -> permisos -> datos -> existencia -> disponibilidad).
        self.cadena = ManejadorAutenticacion()
        (self.cadena
         .setSiguiente(ManejadorPermisosRol("Recepcionista", "Administrador"))
         .setSiguiente(ManejadorValidacionCita())
         .setSiguiente(ManejadorExistenciaCita(self.animales, self.dao))
         .setSiguiente(ManejadorDisponibilidadCita(self.dao)))

    def veterinarios(self, usuario):
        exigir(usuario, "Recepcionista", "Administrador")
        return self.dao.veterinarios()

    # ----- PATRÓN: OBSERVER: armado y aviso a los observadores -----
    def _preparar(self, cita):
        """Completa los datos de la cita y le suscribe sus observadores."""
        detalle = self.dao.detalle_aviso(cita.id) or {}
        cita.animal_nombre = detalle.get("animal")
        cita.veterinario_nombre = detalle.get("veterinario")
        if self.interfaz is not None:
            cita.suscribir(self.interfaz)
        if detalle.get("propietario_id") is not None:
            cita.suscribir(Propietario(detalle["propietario_id"], telefono=detalle.get("telefono"),
                                       buzon=self.buzon))
        if detalle.get("veterinario_id") is not None:
            cita.suscribir(Veterinario(nombre=detalle.get("veterinario"),
                                       veterinario_id=detalle["veterinario_id"], buzon=self.buzon))
        return cita

    def _publicar(self, cita, evento):
        cita.evento = evento
        cita.notificarObservadores()
        self.fallos.extend(cita.fallos)
        del self.fallos[:-50]
        cita.fallos.clear()

    # ----- Command: operaciones que invocan los comandos -----
    def agendarCita(self, usuario, cita):
        self.cadena.manejar(Solicitud(usuario=usuario, cita=cita))      # CHAIN OF RESPONSIBILITY
        try:
            cita.id = self.dao.guardarCita(cita)                        # TEMPLATE METHOD (CitaDAO)
        except sqlite3.IntegrityError:
            raise ErrorNegocio("El veterinario ya tiene una cita en ese horario; elija otro")
        self._publicar(self._preparar(cita), "agendada")                # OBSERVER
        return cita.id

    def agendarCitaSeguimiento(self, usuario, citaBase, fecha, hora, motivo=None):
        """PATRÓN: PROTOTYPE - la cita nueva es una COPIA de la existente (mismo animal,
        veterinario y servicio); solo cambian fecha, hora, estado y motivo. 'citaBase' es la Cita
        o su id."""
        exigir(usuario, "Recepcionista", "Administrador")
        base = citaBase if isinstance(citaBase, Cita) else self.dao.obtener_entidad(citaBase)
        if base is None:
            raise ErrorNegocio("No se encontró la cita")
        if not base.admite_seguimiento():                               # STATE decide
            raise ErrorNegocio("No se puede dar seguimiento a una cita cancelada")
        motivo = texto_opcional(motivo, 200) or f"Seguimiento: {base.motivo}"[:200]
        return self.agendarCita(usuario, base.clonar_seguimiento(fecha, hora, motivo))

    def consultarCitas(self, usuario):
        exigir(usuario, "Recepcionista", "Administrador")
        return self.dao.consultarCitas()

    def citas_del_veterinario(self, usuario):
        exigir(usuario, "Veterinario")
        return self.dao.consultarCitas(usuario.veterinario_id)

    def _cita(self, id):
        cita = self.dao.obtener_entidad(id)
        if cita is None:
            raise ErrorNegocio("No se encontró la cita")
        return self._preparar(cita)

    def _cambiar(self, cita, transicion, evento):
        """Aplica una transición del STATE, la guarda y avisa a los observadores. Devuelve el
        estado anterior."""
        anterior = cita.estado
        transicion()                                                    # STATE (rechaza si no procede)
        self.dao.cambiar_estado(cita.id, cita.estado)
        self._publicar(cita, evento)                                    # OBSERVER
        return anterior

    def confirmarCita(self, usuario, id):
        exigir(usuario, "Recepcionista", "Administrador")
        cita = self._cita(id)
        return self._cambiar(cita, cita.confirmar, "confirmada")

    def cancelarCita(self, usuario, id):
        exigir(usuario, "Recepcionista", "Administrador")
        cita = self._cita(id)
        return self._cambiar(cita, cita.cancelar, "cancelada")

    def finalizarCita(self, usuario, id):
        exigir(usuario, "Veterinario")
        cita = self._cita(id)
        if cita.veterinario_id != usuario.veterinario_id:
            raise ErrorNegocio("Solo puede atender sus propias citas")
        return self._cambiar(cita, cita.finalizar, "finalizada")

    # ----- deshacer (lo invocan los comandos a través de InterfazCita) -----
    def deshacer_cambio_estado(self, usuario, cita_id, estado_anterior, esperado):
        """Devuelve la cita a su estado anterior, solo si sigue como la dejó la acción."""
        if esperado == "finalizada":
            exigir(usuario, "Veterinario")
        else:
            exigir(usuario, "Recepcionista", "Administrador")
        cita = self._cita(cita_id)
        if esperado == "finalizada" and cita.veterinario_id != usuario.veterinario_id:
            raise ErrorNegocio("Solo puede atender sus propias citas")
        if cita.estado != esperado:
            raise ErrorNegocio(f"No se puede deshacer: la cita ya no está {esperado}")
        cita.cambiarEstado(estado_anterior)
        try:
            self.dao.cambiar_estado(cita.id, cita.estado)
        except sqlite3.IntegrityError:                                  # el horario lo ocupó otra cita
            raise ErrorNegocio("No se puede deshacer: el veterinario ya tiene otra cita en ese horario")
        self._publicar(cita, "restaurada")                              # OBSERVER

    def deshacer_agenda(self, usuario, cita_id):
        """Deshace un agendado o un seguimiento: elimina la cita recién creada. Nunca borra una
        cita que ya cambió de estado o que ya tiene un pago."""
        exigir(usuario, "Recepcionista", "Administrador")
        fila = self.dao.obtener(cita_id)
        if fila is None:
            raise ErrorNegocio("No se encontró la cita")
        if fila["estado"] != "pendiente":
            raise ErrorNegocio("No se puede deshacer: la cita ya no está pendiente")
        if fila["pagada"]:
            raise ErrorNegocio("No se puede deshacer: la cita ya tiene un pago registrado")
        cita = self._cita(cita_id)                                      # se arma antes de borrar
        self.dao.eliminar_reserva(cita_id)
        self._publicar(cita, "agenda_deshecha")                         # OBSERVER

    def recordatorios_manana(self, usuario):
        exigir(usuario, "Recepcionista", "Administrador")
        manana = (date.today() + timedelta(days=1)).isoformat()
        return self.dao.para_recordatorio(manana)

    def procesarPagoCita(self, usuario, cita_id, token):
        """Cobra la cita con tarjeta a través de IPagador (PATRÓN: ADAPTER) y registra el pago."""
        exigir(usuario, "Recepcionista")
        pendiente = next((r for r in self.dao.sin_pago() if r["id"] == cita_id), None)
        if pendiente is None:
            raise ErrorNegocio("La cita no existe, está cancelada o ya tiene un pago registrado")
        monto = float(pendiente["precio"])
        if monto <= 0:
            raise ErrorNegocio("La cita no tiene un servicio con precio")
        self.pagador.procesarPago(monto, f"Cita #{cita_id}", token)
        referencia = self.pagador.referencia
        try:
            self.pagos.guardar(cita_id, monto, referencia, metodo="tarjeta")
        except sqlite3.Error:
            self.pagador.reembolsar(referencia)
            raise ErrorNegocio("No fue posible registrar el pago; el cargo se revirtió")
        return referencia


class ControlHistorial:
    """Arma los historiales con el Builder y guarda las instantáneas de sus cambios (Memento)."""
    LIMITE_CAMBIOS = 20

    def __init__(self, db):
        self.dao = HistorialDAO(db)
        self.animales = AnimalDAO(db)
        # PATRÓN: BUILDER - el Director conoce las «recetas» y el Builder arma y valida el expediente
        self.director = DirectorHistorial(HistorialClinicoBuilder())
        # PATRÓN: MEMENTO - este control es el cuidador: (id del historial, MementoHistorial)
        self.historialCambios = []

    def _paciente(self, animal_id):
        if self.animales.obtener(animal_id) is None:
            raise ErrorNegocio("No se encontró el paciente")

    def actualizarHistorial(self, usuario, animal_id, diagnostico, tratamiento, vacunas, alergias,
                            proxima_vacuna):
        """Agrega una consulta al historial clínico del animal."""
        exigir(usuario, "Veterinario")
        self._paciente(animal_id)
        h = self.director.construirConsultaGeneral(diagnostico, tratamiento, vacunas, alergias,
                                                   proxima_vacuna)
        h.animal_id, h.veterinario_id = animal_id, usuario.veterinario_id
        return self.dao.guardarHistorial(h)

    def registrar_vacunacion(self, usuario, animal_id, vacunas, proxima_vacuna=None):
        """Visita solo de vacunación (BUILDER: otra receta del Director)."""
        exigir(usuario, "Veterinario")
        self._paciente(animal_id)
        if not (vacunas or "").strip():
            raise ErrorNegocio("Indique la vacuna aplicada")
        h = self.director.construirControlVacunas(vacunas, proxima_vacuna)
        h.animal_id, h.veterinario_id = animal_id, usuario.veterinario_id
        return self.dao.guardarHistorial(h)

    def consultarHistorial(self, usuario, animal_id):
        exigir(usuario, "Administrador", "Veterinario")
        self._paciente(animal_id)
        return self.dao.consultarHistorial(animal_id)

    def corregir_ultimo_registro(self, usuario, animal_id, diagnostico, tratamiento, vacunas,
                                 alergias, proxima_vacuna):
        """Corrige el registro más reciente del animal. Antes de modificarlo guarda su
        instantánea (MEMENTO) para poder deshacer el cambio."""
        exigir(usuario, "Veterinario")
        self._paciente(animal_id)
        filas = self.dao.consultarHistorial(animal_id)
        if not filas:
            raise ErrorNegocio("El animal aún no tiene registros que corregir")
        h = historial_desde_fila(filas[0])
        if h.veterinario_id != usuario.veterinario_id:
            raise ErrorNegocio("Solo puede corregir sus propios registros")
        nuevo = self.director.construirConsultaGeneral(diagnostico, tratamiento, vacunas, alergias,
                                                       proxima_vacuna)    # valida el contenido
        self.historialCambios.append((h.id, h.guardarEstado()))           # MEMENTO
        del self.historialCambios[:-self.LIMITE_CAMBIOS]
        h.diagnostico, h.tratamiento, h.vacunas = nuevo.diagnostico, nuevo.tratamiento, nuevo.vacunas
        h.alergias, h.proxima_vacuna = nuevo.alergias, nuevo.proxima_vacuna
        self.dao.actualizarHistorial(h)
        return h.id

    def hay_cambios_para_deshacer(self):
        return bool(self.historialCambios)

    def deshacerUltimoCambio(self, usuario, h=None):
        """Devuelve el historial a su instantánea anterior (MEMENTO). 'h' es el HistorialClinico
        modificado; si no se indica se carga desde la base de datos."""
        exigir(usuario, "Veterinario")
        if not self.historialCambios:
            raise ErrorNegocio("No hay cambios para deshacer")
        historial_id, memento = self.historialCambios.pop()
        if h is None:
            fila = self.dao.obtener(historial_id)
            if fila is None:
                raise ErrorNegocio("El registro ya no existe")
            h = historial_desde_fila(fila)
        if h.id != historial_id:
            raise ErrorNegocio("El último cambio corresponde a otro registro")
        h.restaurar(memento)                                              # MEMENTO
        self.dao.actualizarHistorial(h)
        return h.id

    def limpiar_cambios(self):
        """Al cerrar sesión: los cambios de un usuario no se deshacen desde otra sesión."""
        self.historialCambios.clear()

    def alertas_vacunas(self, usuario):
        exigir(usuario, "Veterinario")
        return self.dao.alertas_vacunas()


class ControlServicio:
    def __init__(self, db):
        self.dao = ServicioDAO(db)

    def listar(self, usuario):
        exigir(usuario, "Administrador", "Recepcionista")
        return self.dao.listar()

    def agregar(self, usuario, nombre, precio):
        exigir(usuario, "Administrador")
        nombre = texto_requerido(nombre, "El nombre del servicio", 80)
        precio = decimal(precio, "El precio")
        try:
            self.dao.guardar(nombre, precio)
        except sqlite3.IntegrityError:
            raise ErrorNegocio("Ya existe un servicio con ese nombre")

    def actualizar_precio(self, usuario, nombre, precio):
        exigir(usuario, "Administrador")
        nombre = texto_requerido(nombre, "El nombre del servicio", 80)
        if self.dao.actualizar_precio(nombre, decimal(precio, "El precio")) == 0:
            raise ErrorNegocio("No existe un servicio con ese nombre")


class ControlPago:
    def __init__(self, db):
        self.dao = PagoDAO(db)
        self.citas = CitaDAO(db)

    def citas_sin_pago(self, usuario):
        exigir(usuario, "Recepcionista")
        return self.citas.sin_pago()

    def registrar(self, usuario, cita_id, monto):
        exigir(usuario, "Recepcionista")
        monto = decimal(monto, "El monto")
        cita = self.citas.obtener(cita_id)
        if cita is None:
            raise ErrorNegocio("No se encontró la cita")
        if cita["estado"] == "cancelada":
            raise ErrorNegocio("No se puede cobrar una cita cancelada")
        try:
            self.dao.guardar(cita_id, monto)
        except sqlite3.IntegrityError:
            raise ErrorNegocio("Esa cita ya tiene un pago registrado")


class ControlReporte:
    TIPOS = ("Animales por especie", "Citas realizadas por periodo",
             "Pacientes atendidos por veterinario", "Ingresos por mes",
             "Resumen médico por animal", "Auditoría de citas por periodo")
    CON_PERIODO = (TIPOS[1], TIPOS[2], TIPOS[5])

    def __init__(self, db):
        self.dao = ReporteDAO(db)
        self.animales = AnimalDAO(db)
        self.historial = HistorialDAO(db)

    def generarReporte(self, usuario, tipo, inicio=None, fin=None):
        """Devuelve la lista de líneas del reporte."""
        exigir(usuario, "Administrador")
        if tipo not in self.TIPOS:
            raise ErrorNegocio("Seleccione un tipo de reporte")
        periodo = ""
        if tipo in self.CON_PERIODO:
            inicio, fin = fecha_valida(inicio, "La fecha inicial"), fecha_valida(fin, "La fecha final")
            if inicio > fin:
                raise ErrorNegocio("La fecha inicial no puede ser posterior a la final")
            periodo = f"Periodo: {inicio} a {fin}"
        lineas = [f"REPORTE: {tipo.upper()}"]
        if periodo:
            lineas.append(periodo)
        lineas += [f"Generado: {datetime.now():%Y-%m-%d %H:%M}", ""]
        cuerpo = []
        if tipo == self.TIPOS[0]:
            actual = None
            for r in self.dao.animales_por_especie():
                if r["especie"] != actual:
                    actual = r["especie"]
                    cuerpo.append(f"{actual}:")
                cuerpo.append(f"   #{r['id']} {r['nombre']}")
        elif tipo == self.TIPOS[1]:
            for r in self.dao.citas_finalizadas(inicio, fin):
                cuerpo.append(f"{r['fecha']} {r['hora']} | {r['animal']} | {r['veterinario']} | {r['motivo']}")
        elif tipo == self.TIPOS[2]:
            actual = None
            for r in self.dao.pacientes_por_veterinario(inicio, fin):
                if r["veterinario"] != actual:
                    actual = r["veterinario"]
                    cuerpo.append(f"{actual}:")
                cuerpo.append(f"   {r['animal']} ({r['atenciones']} atención/es)")
        elif tipo == self.TIPOS[3]:
            for r in self.dao.ingresos_por_mes():
                cuerpo.append(f"{r['mes']}   ${r['ingresos']:.2f}   ({r['pagos']} pagos)")
        elif tipo == self.TIPOS[4]:
            # PATRONES VISITOR + ITERATOR: el visitante arma el reporte; el iterador recorre los
            # registros de cada animal (del más antiguo al más reciente).
            visitante = VisitanteReporteMedico()
            for fila in self.animales.listar_completo():
                animal = animal_desde_fila(fila)
                animal.aceptar(visitante)
                registros = ListaHistoriales(
                    historial_desde_fila(h) for h in self.historial.consultarHistorial(animal.id))
                if not len(registros):
                    visitante.lineas.append("   Sin registros médicos")
                iterador = registros.crearIterador()
                while iterador.haySiguiente():
                    iterador.siguiente().aceptar(visitante)
            cuerpo = visitante.lineas
        else:
            # PATRÓN VISITOR: la auditoría es un visitante que recorre las citas del periodo
            visitante = VisitanteAuditoriaCitas()
            for fila in self.dao.citas_periodo(inicio, fin):
                cita_desde_fila(fila).aceptar(visitante)
            if visitante.detalle:
                cuerpo = visitante.lineas
        if not cuerpo:
            raise ErrorNegocio("No hay registros para generar el reporte")
        return lineas + cuerpo

    def exportar_pdf(self, usuario, lineas, ruta):
        exigir(usuario, "Administrador")
        if not lineas:
            raise ErrorNegocio("Genere un reporte antes de exportarlo")
        try:
            escribir_pdf(ruta, lineas)
        except OSError:
            raise ErrorNegocio("No fue posible generar el archivo PDF")


class Controles:
    """Agrupa los controles de la aplicación de escritorio y los objetos de la sesión."""
    def __init__(self, db):
        self.buzon = BuzonNotificaciones()          # avisos de los observadores (Propietario, Veterinario)
        self.login = ControlLogin(db)
        self.usuario = ControlUsuario(db)
        self.propietario = ControlPropietario(db)
        self.animal = ControlAnimal(db)
        self.cita = ControlCita(db, self.buzon)
        self.historial = ControlHistorial(db)
        self.servicio = ControlServicio(db)
        self.pago = ControlPago(db)
        self.reporte = ControlReporte(db)
        # PATRÓN: COMMAND (invocador) + OBSERVER (observador): ejecuta y registra los comandos
        # de cita y se entera de los cambios de cada cita.
        self.interfazCita = InterfazCita(self.cita)
        self.cita.interfaz = self.interfazCita
