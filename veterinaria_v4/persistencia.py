# -*- coding: utf-8 -*-
"""
PERSISTENCIA: BaseDatos (Singleton) y DAO (Template Method).

  PATRÓN: SINGLETON ........ BaseDatos
  PATRÓN: TEMPLATE METHOD .. PropietarioDAO, AnimalDAO, CitaDAO e HistorialDAO heredan de
                             patrones.PlantillaDAO y solo definen procesarConsulta()
Las entidades se arman desde las filas con las funciones *_desde_fila del final.
"""
import os
import sqlite3
import threading
from datetime import date, timedelta

from configuracion import DB_ARCHIVO
from modelo import Animal, Cita, HistorialClinico, Propietario
from patrones import PlantillaDAO
from utilidades import hash_password


# ====================== BASE DE DATOS ======================

class BaseDatos:
    """PATRÓN: SINGLETON (creacional).
    Existe una sola BaseDatos (y una sola conexión) por proceso y todos los DAO la comparten:
    no se agotan recursos ni hay conexiones compitiendo entre sí.
      - instancia: la única BaseDatos; getInstancia() es el acceso global controlado (con
        candado, porque el portal web atiende en otros hilos).
      - Constructor reservado: se obtiene con getInstancia(); BaseDatos(\":memory:\") crea una
        base privada que no es la instancia compartida (pruebas).
      - conectar() / desconectar() llevan la cuenta de usuarios: la conexión solo se cierra
        cuando ya nadie la usa.
    El escritorio y el portal son procesos distintos, así que cada uno tiene su propia
    instancia; SQLite (modo WAL) coordina el acceso entre ambos."""
    _instancia = None
    _candado_clase = threading.Lock()

    @classmethod
    def getInstancia(cls, ruta=DB_ARCHIVO):
        clave = ruta if ruta == ":memory:" else os.path.abspath(ruta)
        with cls._candado_clase:
            if cls._instancia is None or cls._instancia.ruta != clave:
                cls._instancia = cls(ruta)
            return cls._instancia

    def __init__(self, ruta=DB_ARCHIVO):
        self.ruta = ruta if ruta == ":memory:" else os.path.abspath(ruta)
        self.conn = None
        self._usuarios = 0
        self._candado = threading.RLock()

    def conectar(self):
        with self._candado:
            if self.conn is None:
                # check_same_thread=False: el servidor web atiende en un hilo distinto al que abrió la conexión
                self.conn = sqlite3.connect(self.ruta, check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
                self.conn.execute("PRAGMA foreign_keys = ON")
                if self.ruta != ":memory:":
                    self.conn.execute("PRAGMA journal_mode = WAL")   # el portal (otro proceso) lee sin bloquear al escritorio
                self._crear_tablas()
                self._datos_prueba()
                self._cuenta_web_prueba()
            self._usuarios += 1
            return self.conn

    def desconectar(self):
        with self._candado:
            self._usuarios = max(0, self._usuarios - 1)
            if self._usuarios == 0 and self.conn:
                self.conn.close()
                self.conn = None

    def _crear_tablas(self):
        with self.conn:
            for sql in (
                """CREATE TABLE IF NOT EXISTS Usuario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_usuario TEXT UNIQUE NOT NULL,
                    nombre TEXT NOT NULL,
                    password TEXT NOT NULL,
                    rol TEXT NOT NULL CHECK (rol IN ('Administrador','Recepcionista','Veterinario')),
                    estado INTEGER NOT NULL DEFAULT 1)""",
                """CREATE TABLE IF NOT EXISTS Veterinario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER UNIQUE NOT NULL REFERENCES Usuario(id),
                    especialidad TEXT)""",
                """CREATE TABLE IF NOT EXISTS Propietario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    telefono TEXT NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS Animal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    especie TEXT NOT NULL,
                    raza TEXT,
                    edad INTEGER NOT NULL,
                    peso REAL NOT NULL,
                    propietario_id INTEGER REFERENCES Propietario(id))""",
                """CREATE TABLE IF NOT EXISTS Servicio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT UNIQUE NOT NULL,
                    precio REAL NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS Cita (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    motivo TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente','confirmada','finalizada','cancelada')),
                    animal_id INTEGER NOT NULL REFERENCES Animal(id),
                    veterinario_id INTEGER NOT NULL REFERENCES Veterinario(id),
                    servicio_id INTEGER REFERENCES Servicio(id))""",
                """CREATE TABLE IF NOT EXISTS Pago (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    monto REAL NOT NULL,
                    fecha TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'completado',
                    metodo TEXT NOT NULL DEFAULT 'mostrador',
                    referencia TEXT,
                    cita_id INTEGER UNIQUE NOT NULL REFERENCES Cita(id))""",
                """CREATE TABLE IF NOT EXISTS HistorialClinico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    diagnostico TEXT NOT NULL,
                    tratamiento TEXT NOT NULL,
                    vacunas TEXT,
                    alergias TEXT,
                    proxima_vacuna TEXT,
                    animal_id INTEGER NOT NULL REFERENCES Animal(id),
                    veterinario_id INTEGER NOT NULL REFERENCES Veterinario(id))""",
                # Cuenta de acceso al portal web (un propietario = una cuenta)
                """CREATE TABLE IF NOT EXISTS CuentaWeb (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    propietario_id INTEGER UNIQUE NOT NULL REFERENCES Propietario(id),
                    nombre_usuario TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    estado INTEGER NOT NULL DEFAULT 1)""",
            ):
                self.conn.execute(sql)
        self._migrar_estados_cita()
        self._crear_indice_horario()

    def _datos_prueba(self):
        if self.conn.execute("SELECT COUNT(*) FROM Usuario").fetchone()[0]:
            return
        with self.conn:
            for nu, nombre, pw, rol in (
                ("admin", "Admin Principal", "admin123", "Administrador"),
                ("recepcion", "Ana Recepción", "recepcion123", "Recepcionista"),
                ("vet", "Dr. Pérez", "vet12345", "Veterinario"),
            ):
                cur = self.conn.execute(
                    "INSERT INTO Usuario (nombre_usuario, nombre, password, rol) VALUES (?,?,?,?)",
                    (nu, nombre, hash_password(pw), rol))
                if rol == "Veterinario":
                    self.conn.execute(
                        "INSERT INTO Veterinario (usuario_id, especialidad) VALUES (?,?)",
                        (cur.lastrowid, "Medicina general"))
            cur = self.conn.execute(
                "INSERT INTO Propietario (nombre, telefono) VALUES ('Juan Pérez','5551234567')")
            self.conn.execute(
                "INSERT INTO Animal (nombre, especie, raza, edad, peso, propietario_id) "
                "VALUES ('Firulais','Perro','Labrador',5,25.0,?)", (cur.lastrowid,))
            self.conn.execute("INSERT INTO Servicio (nombre, precio) VALUES ('Consulta general', 300)")

    def _cuenta_web_prueba(self):
        """Cuenta de prueba del portal para el primer propietario (cámbiela en producción)."""
        if self.conn.execute("SELECT COUNT(*) FROM CuentaWeb").fetchone()[0]:
            return
        prop = self.conn.execute("SELECT id FROM Propietario ORDER BY id LIMIT 1").fetchone()
        if prop is None:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO CuentaWeb (propietario_id, nombre_usuario, password) VALUES (?,?,?)",
                (prop["id"], "propietario", hash_password("propietario123")))



    def _crear_indice_horario(self):
        with self.conn:
            # Impide dos citas activas del mismo veterinario en el mismo horario
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_cita_horario "
                "ON Cita (veterinario_id, fecha, hora) WHERE estado <> 'cancelada'")

    def _migrar_estados_cita(self):
        """Bases creadas con los estados anteriores (pendiente / realizada / cancelada): se
        reconstruye la tabla Cita con la restricción nueva y 'realizada' pasa a 'finalizada'."""
        sql = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='Cita'").fetchone()
        if sql is None or "'finalizada'" in sql[0]:
            return
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")        # exigido por SQLite para reconstruir una tabla
        try:
            with self.conn:
                self.conn.execute("""CREATE TABLE Cita_nueva (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    motivo TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente','confirmada','finalizada','cancelada')),
                    animal_id INTEGER NOT NULL REFERENCES Animal(id),
                    veterinario_id INTEGER NOT NULL REFERENCES Veterinario(id),
                    servicio_id INTEGER REFERENCES Servicio(id))""")
                self.conn.execute(
                    "INSERT INTO Cita_nueva (id, fecha, hora, motivo, estado, animal_id, veterinario_id, servicio_id) "
                    "SELECT id, fecha, hora, motivo, CASE estado WHEN 'realizada' THEN 'finalizada' ELSE estado END, "
                    "animal_id, veterinario_id, servicio_id FROM Cita")
                self.conn.execute("DROP TABLE Cita")
                self.conn.execute("ALTER TABLE Cita_nueva RENAME TO Cita")
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")


# ====================== DAO ======================

class UsuarioDAO:
    def __init__(self, db):
        self.db = db

    def buscar_por_nombre_usuario(self, nombre_usuario):
        return self.db.conn.execute(
            "SELECT * FROM Usuario WHERE nombre_usuario = ?", (nombre_usuario,)).fetchone()

    def obtener_veterinario(self, usuario_id):
        return self.db.conn.execute(
            "SELECT id, especialidad FROM Veterinario WHERE usuario_id = ?", (usuario_id,)).fetchone()

    def listar_gestionables(self):
        return self.db.conn.execute(
            """SELECT u.id, u.nombre_usuario, u.nombre, u.rol, u.estado, v.especialidad
               FROM Usuario u LEFT JOIN Veterinario v ON v.usuario_id = u.id
               WHERE u.rol IN ('Veterinario','Recepcionista') ORDER BY u.nombre""").fetchall()

    def guardar(self, nombre_usuario, nombre, password_hash, rol, especialidad):
        with self.db.conn:
            cur = self.db.conn.execute(
                "INSERT INTO Usuario (nombre_usuario, nombre, password, rol) VALUES (?,?,?,?)",
                (nombre_usuario, nombre, password_hash, rol))
            if rol == "Veterinario":
                self.db.conn.execute(
                    "INSERT INTO Veterinario (usuario_id, especialidad) VALUES (?,?)",
                    (cur.lastrowid, especialidad))
            return cur.lastrowid

    def actualizar(self, id, nombre, rol, estado, password_hash, especialidad):
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE Usuario SET nombre = ?, rol = ?, estado = ? WHERE id = ?",
                (nombre, rol, int(estado), id))
            if password_hash:
                self.db.conn.execute("UPDATE Usuario SET password = ? WHERE id = ?",
                                     (password_hash, id))
            if rol == "Veterinario":
                existe = self.db.conn.execute(
                    "SELECT id FROM Veterinario WHERE usuario_id = ?", (id,)).fetchone()
                if existe:
                    self.db.conn.execute(
                        "UPDATE Veterinario SET especialidad = ? WHERE usuario_id = ?",
                        (especialidad, id))
                else:
                    self.db.conn.execute(
                        "INSERT INTO Veterinario (usuario_id, especialidad) VALUES (?,?)",
                        (id, especialidad))

    def existe(self, id):
        return self.db.conn.execute(
            "SELECT 1 FROM Usuario WHERE id = ? AND rol IN ('Veterinario','Recepcionista')",
            (id,)).fetchone() is not None


class PropietarioDAO(PlantillaDAO):
    """PATRÓN: TEMPLATE METHOD - define el SQL de sus operaciones; ejecutarOperacion() (de
    PlantillaDAO) pone el orden y la transacción."""
    _CONSULTAS = {
        "guardar": ("INSERT INTO Propietario (nombre, telefono) VALUES (?,?)", "id"),
        "listar": ("SELECT id, nombre, telefono FROM Propietario ORDER BY nombre", "todas"),
        "obtener": ("SELECT id, nombre, telefono FROM Propietario WHERE id = ?", "una"),
        "existe": ("SELECT 1 FROM Propietario WHERE id = ?", "existe"),
        "actualizar": ("UPDATE Propietario SET nombre = ?, telefono = ? WHERE id = ?", "filas"),
    }

    def procesarConsulta(self, operacion, *parametros):
        return self._ejecutarSQL(self._CONSULTAS[operacion], parametros)

    def guardar(self, p):
        return self.ejecutarOperacion("guardar", p.nombre, p.telefono)

    def listar(self):
        return self.ejecutarOperacion("listar")

    def obtener(self, id):
        return self.ejecutarOperacion("obtener", id)

    def existe(self, id):
        return self.ejecutarOperacion("existe", id)

    def actualizar(self, p):
        self.ejecutarOperacion("actualizar", p.nombre, p.telefono, p.id)


class AnimalDAO(PlantillaDAO):
    """PATRÓN: TEMPLATE METHOD (ver PropietarioDAO)."""
    _BASE_BUSQUEDA = ("SELECT a.id, a.nombre, a.especie, COALESCE(p.nombre,'—') AS propietario "
                      "FROM Animal a LEFT JOIN Propietario p ON p.id = a.propietario_id")
    _CONSULTAS = {
        "guardarAnimal": ("INSERT INTO Animal (nombre, especie, raza, edad, peso, propietario_id) "
                          "VALUES (?,?,?,?,?,?)", "id"),
        "actualizarAnimal": ("UPDATE Animal SET nombre=?, especie=?, raza=?, edad=?, peso=?, "
                             "propietario_id=? WHERE id=?", "filas"),
        "obtener": ("""SELECT a.*, p.nombre AS propietario, p.telefono AS telefono
                       FROM Animal a LEFT JOIN Propietario p ON p.id = a.propietario_id
                       WHERE a.id = ?""", "una"),
        "buscarPorId": (_BASE_BUSQUEDA + " WHERE a.id = ?", "todas"),
        "buscarPorNombre": (_BASE_BUSQUEDA + " WHERE a.nombre LIKE ? ORDER BY a.nombre", "todas"),
        "listar": ("SELECT id, nombre FROM Animal ORDER BY nombre", "todas"),
        "listar_completo": ("SELECT * FROM Animal ORDER BY nombre, id", "todas"),
        "listar_por_propietario": ("SELECT id, nombre FROM Animal WHERE propietario_id = ? "
                                   "ORDER BY nombre", "todas"),
    }

    def procesarConsulta(self, operacion, *parametros):
        return self._ejecutarSQL(self._CONSULTAS[operacion], parametros)

    def guardarAnimal(self, a):
        return self.ejecutarOperacion("guardarAnimal", a.nombre, a.especie, a.raza, a.edad,
                                      a.peso, a.propietario_id)

    def actualizarAnimal(self, a):
        self.ejecutarOperacion("actualizarAnimal", a.nombre, a.especie, a.raza, a.edad, a.peso,
                               a.propietario_id, a.id)

    def buscarAnimal(self, texto):
        if texto.isdigit():
            return self.ejecutarOperacion("buscarPorId", int(texto))
        patron = "%" + texto.replace("%", "").replace("_", "") + "%"
        return self.ejecutarOperacion("buscarPorNombre", patron)

    def obtener(self, id):
        return self.ejecutarOperacion("obtener", id)

    def listar(self):
        return self.ejecutarOperacion("listar")

    def listar_completo(self):
        return self.ejecutarOperacion("listar_completo")

    def listar_por_propietario(self, propietario_id):
        return self.ejecutarOperacion("listar_por_propietario", propietario_id)


class CitaDAO(PlantillaDAO):
    """PATRÓN: TEMPLATE METHOD (ver PropietarioDAO)."""
    SELECT = """SELECT c.id, c.fecha, c.hora, a.nombre AS animal, u.nombre AS veterinario,
                       COALESCE(s.nombre,'—') AS servicio, c.estado, c.motivo, c.veterinario_id,
                       EXISTS(SELECT 1 FROM Pago pg WHERE pg.cita_id = c.id) AS pagada
                FROM Cita c
                JOIN Animal a ON a.id = c.animal_id
                JOIN Veterinario v ON v.id = c.veterinario_id
                JOIN Usuario u ON u.id = v.usuario_id
                LEFT JOIN Servicio s ON s.id = c.servicio_id"""
    _ORDEN = " ORDER BY c.fecha DESC, c.hora DESC"
    _CONSULTAS = {
        "hay_conflicto": ("SELECT 1 FROM Cita WHERE veterinario_id=? AND fecha=? AND hora=? "
                          "AND estado <> 'cancelada'", "existe"),
        "guardarCita": ("INSERT INTO Cita (fecha, hora, motivo, estado, animal_id, veterinario_id, "
                        "servicio_id) VALUES (?,?,?,?,?,?,?)", "id"),
        "obtener": (SELECT + " WHERE c.id = ?", "una"),
        "obtener_entidad": ("SELECT id, fecha, hora, motivo, estado, animal_id, veterinario_id, "
                            "servicio_id FROM Cita WHERE id = ?", "una"),
        # Nunca borra una cita que ya tenga pago
        "eliminar_reserva": ("DELETE FROM Cita WHERE id = ? AND id NOT IN (SELECT cita_id FROM Pago)",
                             "filas"),
        "consultarCitas": (SELECT + _ORDEN, "todas"),
        "consultarCitasVeterinario": (SELECT + " WHERE c.veterinario_id = ?" + _ORDEN, "todas"),
        "listar_por_animal": (SELECT + " WHERE c.animal_id = ?" + _ORDEN, "todas"),
        "listar_por_propietario": (SELECT + " WHERE a.propietario_id = ?" + _ORDEN, "todas"),
        "cambiar_estado": ("UPDATE Cita SET estado = ? WHERE id = ?", "filas"),
        "detalle_aviso": ("""SELECT c.id AS cita_id, c.fecha, c.hora, a.nombre AS animal,
                                    a.propietario_id, c.veterinario_id, u.nombre AS veterinario,
                                    p.telefono
                             FROM Cita c JOIN Animal a ON a.id = c.animal_id
                             JOIN Veterinario v ON v.id = c.veterinario_id
                             JOIN Usuario u ON u.id = v.usuario_id
                             LEFT JOIN Propietario p ON p.id = a.propietario_id
                             WHERE c.id = ?""", "una"),
        "sin_pago": ("""SELECT c.id, a.nombre AS animal, c.fecha, c.hora,
                               COALESCE(s.nombre,'Sin servicio') AS servicio,
                               COALESCE(s.precio,0) AS precio
                        FROM Cita c JOIN Animal a ON a.id = c.animal_id
                        LEFT JOIN Servicio s ON s.id = c.servicio_id
                        WHERE c.estado <> 'cancelada' AND c.id NOT IN (SELECT cita_id FROM Pago)
                        ORDER BY c.fecha DESC""", "todas"),
        "para_recordatorio": ("""SELECT c.id, a.nombre AS animal, c.fecha, c.hora, p.telefono
                                 FROM Cita c JOIN Animal a ON a.id = c.animal_id
                                 JOIN Propietario p ON p.id = a.propietario_id
                                 WHERE c.estado IN ('pendiente','confirmada') AND c.fecha = ?
                                 ORDER BY c.hora""", "todas"),
        "veterinarios": ("""SELECT v.id, u.nombre, COALESCE(v.especialidad,'') AS especialidad
                            FROM Veterinario v JOIN Usuario u ON u.id = v.usuario_id
                            WHERE u.rol = 'Veterinario' AND u.estado = 1 ORDER BY u.nombre""",
                         "todas"),
    }

    def procesarConsulta(self, operacion, *parametros):
        return self._ejecutarSQL(self._CONSULTAS[operacion], parametros)

    def hay_conflicto(self, veterinario_id, fecha, hora):
        return self.ejecutarOperacion("hay_conflicto", veterinario_id, fecha, hora)

    def guardarCita(self, c):
        return self.ejecutarOperacion("guardarCita", c.fecha, c.hora, c.motivo, c.estado,
                                      c.animal_id, c.veterinario_id, c.servicio_id)

    def obtener(self, id):
        return self.ejecutarOperacion("obtener", id)

    def obtener_entidad(self, id):
        """La cita como objeto Cita (con animal_id y servicio_id): es el prototipo a clonar."""
        r = self.ejecutarOperacion("obtener_entidad", id)
        return None if r is None else Cita(**dict(r))

    def eliminar_reserva(self, id):
        """Libera una reserva cuyo cobro falló. Nunca borra una cita que ya tenga pago."""
        self.ejecutarOperacion("eliminar_reserva", id)

    def consultarCitas(self, veterinario_id=None):
        if veterinario_id is None:
            return self.ejecutarOperacion("consultarCitas")
        return self.ejecutarOperacion("consultarCitasVeterinario", veterinario_id)

    def listar_por_animal(self, animal_id):
        return self.ejecutarOperacion("listar_por_animal", animal_id)

    def listar_por_propietario(self, propietario_id):
        return self.ejecutarOperacion("listar_por_propietario", propietario_id)

    def cambiar_estado(self, id, estado):
        self.ejecutarOperacion("cambiar_estado", estado, id)

    def detalle_aviso(self, id):
        """Datos para avisar del cambio de una cita (teléfono nulo si el animal no tiene dueño)."""
        r = self.ejecutarOperacion("detalle_aviso", id)
        return None if r is None else dict(r)

    def sin_pago(self):
        return self.ejecutarOperacion("sin_pago")

    def para_recordatorio(self, fecha):
        return self.ejecutarOperacion("para_recordatorio", fecha)

    def veterinarios(self):
        return self.ejecutarOperacion("veterinarios")


class HistorialDAO(PlantillaDAO):
    """PATRÓN: TEMPLATE METHOD (ver PropietarioDAO)."""
    _CONSULTAS = {
        "guardarHistorial": ("INSERT INTO HistorialClinico (fecha, diagnostico, tratamiento, vacunas, "
                             "alergias, proxima_vacuna, animal_id, veterinario_id) "
                             "VALUES (?,?,?,?,?,?,?,?)", "id"),
        "actualizarHistorial": ("UPDATE HistorialClinico SET fecha=?, diagnostico=?, tratamiento=?, "
                                "vacunas=?, alergias=?, proxima_vacuna=? WHERE id=?", "filas"),
        "obtener": ("""SELECT h.*, u.nombre AS veterinario FROM HistorialClinico h
                       JOIN Veterinario v ON v.id = h.veterinario_id
                       JOIN Usuario u ON u.id = v.usuario_id WHERE h.id = ?""", "una"),
        "consultarHistorial": ("""SELECT h.*, u.nombre AS veterinario FROM HistorialClinico h
                                  JOIN Veterinario v ON v.id = h.veterinario_id
                                  JOIN Usuario u ON u.id = v.usuario_id
                                  WHERE h.animal_id = ? ORDER BY h.fecha DESC, h.id DESC""", "todas"),
        "alertas_vacunas": ("""SELECT a.id AS animal_id, a.nombre AS animal, h.vacunas, h.proxima_vacuna
                               FROM HistorialClinico h JOIN Animal a ON a.id = h.animal_id
                               WHERE h.proxima_vacuna IS NOT NULL AND h.proxima_vacuna <= ?
                                 AND NOT EXISTS (SELECT 1 FROM HistorialClinico h2
                                                 WHERE h2.animal_id = h.animal_id AND h2.vacunas = h.vacunas
                                                   AND h2.id > h.id)
                               ORDER BY h.proxima_vacuna""", "todas"),
    }

    def procesarConsulta(self, operacion, *parametros):
        return self._ejecutarSQL(self._CONSULTAS[operacion], parametros)

    def guardarHistorial(self, h):
        return self.ejecutarOperacion("guardarHistorial", h.fecha, h.diagnostico, h.tratamiento,
                                      h.vacunas, h.alergias, h.proxima_vacuna, h.animal_id,
                                      h.veterinario_id)

    def actualizarHistorial(self, h):
        """Reescribe el contenido de un registro existente (corrección o deshacer)."""
        self.ejecutarOperacion("actualizarHistorial", h.fecha, h.diagnostico, h.tratamiento,
                               h.vacunas, h.alergias, h.proxima_vacuna, h.id)

    def obtener(self, id):
        return self.ejecutarOperacion("obtener", id)

    def consultarHistorial(self, animal_id):
        return self.ejecutarOperacion("consultarHistorial", animal_id)

    def alertas_vacunas(self, dias=7):
        limite = (date.today() + timedelta(days=dias)).isoformat()
        return self.ejecutarOperacion("alertas_vacunas", limite)


class ServicioDAO:
    def __init__(self, db):
        self.db = db

    def listar(self):
        return self.db.conn.execute("SELECT id, nombre, precio FROM Servicio ORDER BY nombre").fetchall()

    def guardar(self, nombre, precio):
        with self.db.conn:
            self.db.conn.execute("INSERT INTO Servicio (nombre, precio) VALUES (?,?)", (nombre, precio))

    def actualizar_precio(self, nombre, precio):
        with self.db.conn:
            cur = self.db.conn.execute("UPDATE Servicio SET precio = ? WHERE nombre = ?", (precio, nombre))
        return cur.rowcount


class PagoDAO:
    def __init__(self, db):
        self.db = db

    def guardar(self, cita_id, monto, referencia=None, metodo="mostrador"):
        with self.db.conn:
            self.db.conn.execute(
                "INSERT INTO Pago (monto, fecha, estado, metodo, referencia, cita_id) "
                "VALUES (?, date('now'), 'completado', ?, ?, ?)",
                (monto, metodo, referencia, cita_id))


class CuentaWebDAO:
    def __init__(self, db):
        self.db = db

    def buscar(self, nombre_usuario):
        return self.db.conn.execute(
            """SELECT c.propietario_id, c.password, c.estado, p.nombre
               FROM CuentaWeb c JOIN Propietario p ON p.id = c.propietario_id
               WHERE c.nombre_usuario = ?""", (nombre_usuario,)).fetchone()

    def guardar(self, propietario_id, nombre_usuario, password_hash):
        with self.db.conn:
            cur = self.db.conn.execute(
                "INSERT INTO CuentaWeb (propietario_id, nombre_usuario, password) VALUES (?,?,?)",
                (propietario_id, nombre_usuario, password_hash))
        return cur.lastrowid


class ReporteDAO:
    def __init__(self, db):
        self.db = db

    def animales_por_especie(self):
        return self.db.conn.execute(
            "SELECT a.especie, a.nombre, a.id FROM Animal a ORDER BY a.especie, a.nombre").fetchall()

    def citas_periodo(self, inicio, fin):
        """Todas las citas del periodo, sin importar su estado (insumo del Visitor de auditoría)."""
        return self.db.conn.execute(
            CitaDAO.SELECT + " WHERE c.fecha BETWEEN ? AND ? ORDER BY c.fecha, c.hora",
            (inicio, fin)).fetchall()

    def citas_finalizadas(self, inicio, fin):
        return self.db.conn.execute(
            CitaDAO.SELECT + " WHERE c.estado = 'finalizada' AND c.fecha BETWEEN ? AND ? "
                             "ORDER BY c.fecha, c.hora", (inicio, fin)).fetchall()

    def pacientes_por_veterinario(self, inicio, fin):
        return self.db.conn.execute(
            """SELECT u.nombre AS veterinario, a.nombre AS animal, COUNT(*) AS atenciones
               FROM Cita c JOIN Animal a ON a.id = c.animal_id
               JOIN Veterinario v ON v.id = c.veterinario_id JOIN Usuario u ON u.id = v.usuario_id
               WHERE c.estado = 'finalizada' AND c.fecha BETWEEN ? AND ?
               GROUP BY u.id, a.id ORDER BY u.nombre, a.nombre""", (inicio, fin)).fetchall()

    def ingresos_por_mes(self):
        return self.db.conn.execute(
            """SELECT strftime('%Y-%m', fecha) AS mes, SUM(monto) AS ingresos, COUNT(*) AS pagos
               FROM Pago GROUP BY mes ORDER BY mes""").fetchall()


# ====================== ENTIDADES A PARTIR DE FILAS ======================

def propietario_desde_fila(r, buzon=None):
    return Propietario(r["id"], r["nombre"], r["telefono"], buzon=buzon)


def animal_desde_fila(r):
    return Animal(r["id"], r["nombre"], r["especie"], r["raza"], r["edad"], r["peso"], r["propietario_id"])


def cita_desde_fila(r):
    c = Cita(id=r["id"], fecha=r["fecha"], hora=r["hora"], motivo=r["motivo"], estado=r["estado"],
             veterinario_id=r["veterinario_id"])
    c.animal_nombre, c.veterinario_nombre, c.pagada = r["animal"], r["veterinario"], bool(r["pagada"])
    return c


def historial_desde_fila(r):
    h = HistorialClinico(id=r["id"], fecha=r["fecha"], diagnostico=r["diagnostico"],
                         tratamiento=r["tratamiento"], vacunas=r["vacunas"], alergias=r["alergias"],
                         proxima_vacuna=r["proxima_vacuna"], animal_id=r["animal_id"],
                         veterinario_id=r["veterinario_id"])
    h.veterinario_nombre = r["veterinario"]
    return h
