# -*- coding: utf-8 -*-
"""
Sistema de gestión de clínica veterinaria - V4 (APLICACIÓN DE ESCRITORIO, Tkinter)
Personal interno: Administrador, Recepcionista y Veterinario.

Este archivo contiene SOLO la interfaz. El resto del sistema está separado por responsabilidad:
    errores.py ........ excepciones compartidas
    configuracion.py .. rutas y constantes
    utilidades.py ..... validaciones, contraseñas y PDF
    modelo.py ......... entidades del dominio
    patrones.py ....... todos los patrones de diseño
    persistencia.py ... BaseDatos y DAO
    controles.py ...... reglas de negocio y permisos
    Veterinaria_V4.py . interfaz de escritorio (este archivo)
    portal_web.py ..... portal web de propietarios (proceso independiente)
Capas: Interfaz (Tkinter) -> Control -> DAO -> BaseDatos.

Portal web de propietarios: es un proceso INDEPENDIENTE (portal_web.py) que comparte la base de
datos. Al abrir esta aplicación se lanza solo y se abre en el navegador (LanzadorPortal); si ya
estaba corriendo, se reutiliza; al cerrar la aplicación se detiene. También puede ejecutarlo a mano:
python portal_web.py. Para no abrir el navegador automáticamente ponga ABRIR_NAVEGADOR = False.

Usuarios de prueba (cámbialos en producción):
    admin / admin123      recepcion / recepcion123      vet / vet12345

PATRONES DE DISEÑO: cada pantalla donde se aplica uno muestra una franja con letras de color
(violeta = creacional, azul = estructural, naranja = comportamiento). Se ocultan desde el menú
Ver > "Mostrar etiquetas de patrones"; el listado completo está en Ayuda > "Patrones aplicados".
Todos los patrones están en patrones.py; la interfaz usa Command (InterfazCita), State (estados
de la cita), Memento (corregir y deshacer el historial), Observer (pestaña «Notificaciones»),
Builder (historial), Prototype (cita de seguimiento), Iterator (ficha) y Factory Method (login).
"""
import atexit
import math
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, simpledialog, ttk
from errores import ErrorNegocio
from configuracion import DB_ARCHIVO, ESPECIES, ROLES_GESTIONABLES, SIN_PROPIETARIO
from controles import ControlReporte, Controles
from modelo import Cita
from patrones import (ComandoCancelarCita, ComandoConfirmarCita, ComandoCrearSeguimiento,
                      ComandoFinalizarCita, CreadorUsuario, ListaHistoriales, estadoDe)
from persistencia import BaseDatos, historial_desde_fila
from utilidades import entero, id_de_opcion


# ====================== INTERFAZ (Tkinter) ======================

FALLO = object()


# ====================== TEMA VISUAL (mismo diseño que el portal web) ======================
FAMILIA = "Segoe UI"        # si no existe, Tk usa la fuente por defecto del sistema
C_VERDE, C_VERDE_OSC, C_VERDE_CLARO = "#167653", "#0f5a3f", "#e6f4ec"
C_FONDO, C_TEXTO, C_SUAVE, C_BORDE = "#f6fbf8", "#1d3328", "#62766b", "#d6e3da"
C_ETIQUETA, C_FOCO = "#355344", "#3fa475"

# ====================== ETIQUETAS DE PATRONES (letras de color) ======================
COLOR_CATEGORIA = {"Creacional": "#7b3fb5", "Estructural": "#1f5fbf", "Comportamiento": "#c2570c"}
FONDO_INSIGNIA = "#eaf4ee"
VISTA = {"patrones": True}      # ¿mostrar las franjas? (menú Ver)

# patrón: (categoría, dónde se aplica, ¿ya existía antes de esta versión?)
PATRONES = {
    "Singleton": ("Creacional", "persistencia.py: BaseDatos.getInstancia() (una sola conexión compartida por todos los DAO)", False),
    "Factory Method": ("Creacional", "patrones.py: CreadorUsuario y sus creadores por rol (login y alta de usuarios)", False),
    "Builder": ("Creacional", "patrones.py: HistorialClinicoBuilder + DirectorHistorial (Historial Clínico)", False),
    "Prototype": ("Creacional", "patrones.py: PrototipoCita + modelo.py: Cita.clonar() (cita de seguimiento)", False),
    "Adapter": ("Estructural", "patrones.py: PasarelaPagoAdapter sobre APIStripeSDK (pago con tarjeta)", True),
    "Facade": ("Estructural", "patrones.py: FachadaVeterinaria con sus subsistemas (sitio web)", True),
    "Proxy": ("Estructural", "patrones.py: Proxy (sesión y control de acceso del portal)", True),
    "Decorator": ("Estructural", "patrones.py: DecoradorServicioExtra y DecoradorAuditoriaLog sobre ServicioConsultaBase", False),
    "Chain of Responsibility": ("Comportamiento", "patrones.py: cadena de manejadores que arma ControlCita al agendar una cita", False),
    "Command": ("Comportamiento", "patrones.py: comandos de cita + InterfazCita como invocador (bitácora y deshacer)", False),
    "Iterator": ("Comportamiento", "patrones.py: ListaHistoriales e IteradorHistorialCronologico (ficha del animal y reportes)", False),
    "Template Method": ("Comportamiento", "patrones.py: PlantillaDAO.ejecutarOperacion() (Animal, Propietario, Cita, Historial)", False),
    "Visitor": ("Comportamiento", "patrones.py: VisitanteReporteMedico y VisitanteAuditoriaCitas (Reportes)", False),
    "State": ("Comportamiento", "patrones.py: EstadoCita (Pendiente / Confirmada / Cancelada / Finalizada) en la Cita", False),
    "Memento": ("Comportamiento", "patrones.py: MementoHistorial + ControlHistorial (corregir y deshacer el historial)", False),
    "Observer": ("Comportamiento", "modelo.py: Cita (sujeto) con InterfazCita, Propietario y Veterinario como observadores", False),
}

# pestaña -> [(patrón, qué hace en esa pantalla)]
TAB_PATRONES = {
    "__login__": [("Singleton", "una sola conexión a la base de datos"),
                  ("Factory Method", "el login crea el usuario según su rol")],
    "Consultar Animales": [("Iterator", "la ficha recorre el historial con un IteradorHistorial (más reciente primero)")],
    "Registrar Animal": [("Template Method", "AnimalDAO.guardarAnimal() sigue el esqueleto de PlantillaDAO")],
    "Registrar Propietario": [("Template Method", "PropietarioDAO.guardar() sigue el esqueleto de PlantillaDAO")],
    "Agendar Cita": [("Chain of Responsibility", "sesión → permisos → datos → existencia → disponibilidad"),
                     ("Command", "«Agendar» se ejecuta como ComandoAgendarCita y queda en la Bitácora"),
                     ("Template Method", "CitaDAO.guardarCita() sigue el esqueleto de PlantillaDAO"),
                     ("Observer", "al agendar se avisa a la interfaz, al propietario y al veterinario (pestaña Notificaciones)")],
    "Consultar Citas": [("Command", "consultar, confirmar y cancelar son comandos registrados en la Bitácora"),
                        ("Prototype", "«Crear cita de seguimiento» clona la cita seleccionada"),
                        ("State", "el estado de la cita decide si se puede confirmar, cancelar o dar seguimiento"),
                        ("Observer", "cada cambio de estado notifica a los observadores de la cita")],
    "Mis Citas": [("State", "solo una cita pendiente o confirmada puede finalizarse"),
                  ("Observer", "los avisos de recepción llegan por observador")],
    "Notificaciones": [("Observer", "Propietario y Veterinario reciben cada cambio de la Cita que observan")],
    "Historial Clínico": [("Builder", "el Director arma el expediente paso a paso (consulta general o solo vacunación)"),
                          ("Memento", "«Corregir último registro» guarda un MementoHistorial; «Deshacer último cambio» lo restaura"),
                          ("Template Method", "HistorialDAO.guardarHistorial() sigue el esqueleto de PlantillaDAO")],
    "Pagos": [("Adapter", "«Cobrar con tarjeta de prueba» paga por IPagador (PasarelaPagoAdapter)")],
    "Reportes": [("Visitor", "«Resumen médico» y «Auditoría de citas» son visitantes de las entidades"),
                 ("Iterator", "el resumen médico recorre los registros con un iterador cronológico")],
    "Usuarios": [("Factory Method", "al registrar, CreadorUsuario crea el usuario con el rol correcto")],
    "Bitácora": [("Command", "cada fila es un comando ejecutado por InterfazCita"),
                 ("Factory Method", "los accesos los registra el creador del rol")],
}


def crear_insignia_patrones(master, clave, fondo=FONDO_INSIGNIA, tam=9, ancho=None):
    """Franja con letras de color: qué patrones de diseño se aplican en esta pantalla."""
    marco = tk.Frame(master, bg=fondo, padx=8, pady=4)
    for patron, nota in TAB_PATRONES.get(clave, ()):
        color = COLOR_CATEGORIA[PATRONES[patron][0]]
        if ancho:                                           # versión compacta (tarjeta del login)
            tk.Label(marco, text=f"● {patron}: {nota}", fg=color, bg=fondo, font=(FAMILIA, tam),
                     wraplength=ancho, justify="left").pack(anchor="w")
            continue
        fila = tk.Frame(marco, bg=fondo)
        fila.pack(anchor="w", fill="x")
        tk.Label(fila, text=f"● Patrón {patron}", fg=color, bg=fondo,
                 font=(FAMILIA, tam, "bold")).pack(side="left")
        tk.Label(fila, text=f"  —  {nota}", fg=color, bg=fondo, font=(FAMILIA, tam)).pack(side="left")
    return marco


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _mezcla(c1, c2, t):
    """Color intermedio entre c1 y c2 (t de 0 a 1): sirve para los degradados."""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _elipse(cx, cy, rx, ry, grados):
    """Puntos de una elipse girada (Tk no dibuja óvalos rotados, se dibuja como polígono)."""
    c, s = math.cos(math.radians(grados)), math.sin(math.radians(grados))
    puntos = []
    for k in range(28):
        t = 2 * math.pi * k / 28
        x, y = rx * math.cos(t), ry * math.sin(t)
        puntos += [cx + x * c - y * s, cy + x * s + y * c]
    return puntos


# Huella: almohadilla + 4 deditos, sobre una cuadrícula de 100 x 100 (igual que el portal web)
_HUELLA = ((50, 68, 25, 20, 0), (19, 44, 9, 12, -22), (38, 25, 9.5, 13, -8),
           (62, 25, 9.5, 13, 8), (81, 44, 9, 12, 22))


def dibujar_huella(canvas, cx, cy, tam, rot, color, tag):
    k = tam / 100
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    for ex, ey, rx, ry, ang in _HUELLA:
        dx, dy = (ex - 50) * k, (ey - 50) * k
        canvas.create_polygon(_elipse(cx + dx * c - dy * s, cy + dx * s + dy * c, rx * k, ry * k, ang + rot),
                              fill=color, outline="", tags=tag)


def _rect_redondo(canvas, x1, y1, x2, y2, r, **kw):
    puntos = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(puntos, smooth=True, **kw)


def _degradado(canvas, ancho, alto, c1, c2, horizontal, tag, pasos=48):
    for i in range(pasos):
        color = _mezcla(c1, c2, i / (pasos - 1))
        if horizontal:
            canvas.create_rectangle(ancho * i / pasos, 0, ancho * (i + 1) / pasos + 1, alto,
                                    fill=color, outline="", tags=tag)
        else:
            canvas.create_rectangle(0, alto * i / pasos, ancho, alto * (i + 1) / pasos + 1,
                                    fill=color, outline="", tags=tag)


def aplicar_tema(root):
    """Restila TODA la aplicación (botones, campos, etiquetas, pestañas, tablas, combos...)
    sin tocar cada pantalla: se llama una sola vez, antes de crear los widgets."""
    for nombre in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(nombre).configure(family=FAMILIA, size=10)
        except tk.TclError:
            pass
    root.configure(bg=C_FONDO)
    op = root.option_add
    for clase in ("Frame", "Labelframe", "Toplevel"):
        op(f"*{clase}.background", C_FONDO)
    op("*Label.background", C_FONDO)
    op("*Label.foreground", C_TEXTO)
    op("*Labelframe.foreground", C_VERDE_OSC)
    for clase in ("Checkbutton", "Radiobutton"):
        op(f"*{clase}.background", C_FONDO)
        op(f"*{clase}.activeBackground", C_FONDO)
        op(f"*{clase}.foreground", C_TEXTO)
        op(f"*{clase}.selectColor", "#ffffff")
        op(f"*{clase}.highlightThickness", 0)
    for clase in ("Entry", "Text"):
        op(f"*{clase}.background", "#fbfdfb")
        op(f"*{clase}.foreground", C_TEXTO)
        op(f"*{clase}.relief", "flat")
        op(f"*{clase}.borderWidth", 0)
        op(f"*{clase}.highlightThickness", 1)
        op(f"*{clase}.highlightBackground", C_BORDE)
        op(f"*{clase}.highlightColor", C_FOCO)
        op(f"*{clase}.insertBackground", C_TEXTO)
        op(f"*{clase}.selectBackground", "#bfe3cf")
        op(f"*{clase}.selectForeground", C_TEXTO)
    op("*Button.background", C_VERDE)
    op("*Button.foreground", "#ffffff")
    op("*Button.activeBackground", C_VERDE_OSC)
    op("*Button.activeForeground", "#ffffff")
    op("*Button.disabledForeground", "#cfe3d6")
    op("*Button.relief", "flat")
    op("*Button.borderWidth", 0)
    op("*Button.highlightThickness", 0)
    op("*Button.padX", 18)
    op("*Button.padY", 7)
    op("*Button.cursor", "hand2")
    op("*Button.font", (FAMILIA, 10, "bold"))
    op("*TCombobox*Listbox.background", "#ffffff")
    op("*TCombobox*Listbox.selectBackground", C_VERDE)
    op("*TCombobox*Listbox.selectForeground", "#ffffff")

    est = ttk.Style(root)
    est.theme_use("clam")
    est.configure(".", background=C_FONDO, foreground=C_TEXTO, font=(FAMILIA, 10),
                  bordercolor=C_BORDE, focuscolor=C_FONDO)
    est.configure("TFrame", background=C_FONDO)
    est.configure("TLabel", background=C_FONDO, foreground=C_TEXTO)
    est.configure("TNotebook", background="#e3f0e8", borderwidth=0, tabmargins=(10, 8, 10, 0))
    est.configure("TNotebook.Tab", padding=(12, 8), background="#d3e6da", foreground=C_ETIQUETA,
                  borderwidth=0, font=(FAMILIA, 10))
    est.map("TNotebook.Tab", background=[("selected", C_FONDO), ("active", "#e6f2ea")],
            foreground=[("selected", C_VERDE)])
    est.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=C_TEXTO,
                  rowheight=28, borderwidth=0)
    est.configure("Treeview.Heading", background="#f1f8f3", foreground="#46614f",
                  font=(FAMILIA, 9, "bold"), relief="flat", padding=(8, 7))
    est.map("Treeview", background=[("selected", C_VERDE)], foreground=[("selected", "#ffffff")])
    est.map("Treeview.Heading", background=[("active", C_VERDE_CLARO)])
    est.configure("TCombobox", fieldbackground="#fbfdfb", background=C_VERDE_CLARO, foreground=C_TEXTO,
                  bordercolor=C_BORDE, lightcolor=C_BORDE, darkcolor=C_BORDE,
                  arrowcolor=C_VERDE, padding=5)
    est.map("TCombobox", fieldbackground=[("readonly", "#fbfdfb")],
            selectbackground=[("readonly", "#fbfdfb")], selectforeground=[("readonly", C_TEXTO)],
            bordercolor=[("focus", C_FOCO)], lightcolor=[("focus", C_FOCO)], darkcolor=[("focus", C_FOCO)])
    for orient in ("Vertical", "Horizontal"):
        est.configure(f"{orient}.TScrollbar", background="#cfe3d6", troughcolor="#eef5f0",
                      bordercolor="#eef5f0", arrowcolor=C_VERDE, relief="flat")
        est.map(f"{orient}.TScrollbar", background=[("active", "#a9cdb8")])


class Encabezado(tk.Canvas):
    """Barra superior verde con el logo (igual que la cabecera del portal web)."""
    ALTO = 66

    def __init__(self, master, texto_sesion):
        super().__init__(master, height=self.ALTO, highlightthickness=0, bd=0)
        self.texto_sesion = texto_sesion
        self.bind("<Configure>", self._dibujar)

    def _dibujar(self, evento):
        self.delete("all")
        ancho = evento.width
        _degradado(self, ancho, self.ALTO, "#25a06f", "#0f5a3f", True, "g")
        _rect_redondo(self, 18, 11, 62, 55, 13, fill="#ffffff", outline="")
        dibujar_huella(self, 40, 33, 30, 0, C_VERDE, "p")
        self.create_text(76, 24, text="Veterinaria", anchor="w", fill="#ffffff", font=(FAMILIA, 15, "bold"))
        self.create_text(76, 46, text="Atención veterinaria, más cerca de ti", anchor="w",
                         fill="#cdeedd", font=(FAMILIA, 9))
        texto = self.create_text(ancho - 34, 33, text=self.texto_sesion, anchor="e",
                                 fill="#ffffff", font=(FAMILIA, 10, "bold"))
        x1, y1, x2, y2 = self.bbox(texto)
        pastilla = _rect_redondo(self, x1 - 14, y1 - 6, x2 + 14, y2 + 6, 14, fill="#1b8a5f", outline="")
        self.tag_lower(pastilla, texto)


class PantallaLogin:
    # (x, y, tamaño, giro, color) sobre una cuadrícula de 1200 x 800, igual que el fondo del portal
    HUELLAS = ((85, 105, 90, -25, "#cfe7d9"), (1095, 95, 110, 20, "#f6dfc8"), (215, 365, 70, 15, "#cfe7d9"),
               (940, 340, 80, -15, "#f6dfc8"), (120, 680, 120, -10, "#f6dfc8"), (1050, 650, 100, 25, "#cfe7d9"),
               (555, 715, 70, -30, "#cfe7d9"), (650, 70, 60, 10, "#f6dfc8"), (358, 548, 55, 20, "#cfe7d9"),
               (810, 550, 60, -20, "#f6dfc8"))

    def __init__(self, root, controles, al_ingresar):
        self.root, self.controles, self.al_ingresar = root, controles, al_ingresar
        self.marco = tk.Canvas(root, highlightthickness=0, bd=0, bg=C_FONDO)
        self.marco.pack(expand=True, fill="both")
        tarjeta = tk.Frame(self.marco, bg="#ffffff", highlightthickness=1,
                           highlightbackground="#dcebe0", padx=38, pady=32)
        self._ventana = self.marco.create_window(0, 0, window=tarjeta, anchor="center")

        insignia = tk.Canvas(tarjeta, width=56, height=56, bg="#ffffff", highlightthickness=0)
        _rect_redondo(insignia, 1, 1, 55, 55, 17, fill="#e1f3e9", outline="")
        dibujar_huella(insignia, 28, 28, 30, 0, C_VERDE, "p")
        insignia.pack(anchor="w")

        def etiqueta(texto, **opciones):
            return tk.Label(tarjeta, text=texto, bg="#ffffff", **opciones)

        etiqueta("BIENVENIDO AL SISTEMA", fg=C_VERDE, font=(FAMILIA, 8, "bold")).pack(anchor="w", pady=(14, 2))
        etiqueta("Inicio de Sesión", fg="#163b2a", font=(FAMILIA, 19, "bold")).pack(anchor="w")
        etiqueta("Gestiona las citas, pacientes y pagos de la clínica.", fg=C_SUAVE,
                 wraplength=300, justify="left").pack(anchor="w", pady=(4, 8))
        etiqueta("Usuario", fg=C_ETIQUETA, font=(FAMILIA, 9, "bold")).pack(anchor="w", pady=(12, 5))
        self.entrada_usuario = tk.Entry(tarjeta, width=34, font=(FAMILIA, 11))
        self.entrada_usuario.pack(fill="x", ipady=7)
        etiqueta("Contraseña", fg=C_ETIQUETA, font=(FAMILIA, 9, "bold")).pack(anchor="w", pady=(14, 5))
        self.entrada_password = tk.Entry(tarjeta, width=34, show="*", font=(FAMILIA, 11))
        self.entrada_password.pack(fill="x", ipady=7)
        tk.Button(tarjeta, text="Ingresar", command=self.ingresar,
                  font=(FAMILIA, 11, "bold")).pack(fill="x", pady=(24, 0), ipady=4)
        if VISTA["patrones"]:
            crear_insignia_patrones(tarjeta, "__login__", fondo="#ffffff", tam=8, ancho=300
                                    ).pack(anchor="w", pady=(14, 0))
        self.entrada_usuario.bind("<Return>", lambda e: self.entrada_password.focus_set())
        self.entrada_password.bind("<Return>", lambda e: self.ingresar())
        self.entrada_usuario.focus_set()
        self.marco.bind("<Configure>", self._dibujar_fondo)

    def _dibujar_fondo(self, evento):
        ancho, alto = evento.width, evento.height
        c = self.marco
        c.delete("fondo")
        _degradado(c, ancho, alto, "#f8fcf9", "#e1f1e7", False, "fondo")
        c.create_oval(-170, alto * .18 - 190, 230, alto * .18 + 210, fill="#e9f5ee", outline="", tags="fondo")
        c.create_oval(ancho - 220, alto * .58 - 170, ancho + 120, alto * .58 + 170, fill="#fcf2e6",
                      outline="", tags="fondo")
        escala = (ancho / 1200 + alto / 800) / 2
        for x, y, tam, giro, color in self.HUELLAS:
            dibujar_huella(c, x / 1200 * ancho, y / 800 * alto, tam * escala, giro, color, "fondo")
        c.tag_lower("fondo")
        c.coords(self._ventana, ancho / 2, alto / 2)

    def ingresar(self):
        try:
            usuario = self.controles.login.validarCredenciales(
                self.entrada_usuario.get(), self.entrada_password.get())
        except ErrorNegocio as e:
            messagebox.showerror("Error", str(e))
            return
        self.al_ingresar(usuario)


class PanelPrincipal:
    def __init__(self, root, controles, usuario, al_cerrar_sesion):
        self.root, self.ctl, self.usuario = root, controles, usuario
        self.al_cerrar_sesion = al_cerrar_sesion
        self.constructores = {}
        menu = tk.Menu(root)
        archivo = tk.Menu(menu, tearoff=0)
        archivo.add_command(label="Cerrar sesión", command=self.al_cerrar_sesion)
        archivo.add_separator()
        archivo.add_command(label="Abrir portal web", command=root.abrir_portal)
        archivo.add_command(label="Salir", command=root.salir)
        menu.add_cascade(label="Archivo", menu=archivo)
        self.ver_patrones = tk.BooleanVar(value=VISTA["patrones"])
        ver = tk.Menu(menu, tearoff=0)
        ver.add_checkbutton(label="Mostrar etiquetas de patrones", variable=self.ver_patrones,
                            command=self._alternar_patrones)
        menu.add_cascade(label="Ver", menu=ver)
        ayuda = tk.Menu(menu, tearoff=0)
        ayuda.add_command(label="Patrones aplicados...", command=self._ventana_patrones)
        menu.add_cascade(label="Ayuda", menu=ayuda)
        root.config(menu=menu)
        Encabezado(root, f"Sesión: {usuario.nombre} ({usuario.rol})").pack(fill="x")
        self.cuaderno = ttk.Notebook(root)
        self.cuaderno.pack(expand=True, fill="both")

        recep_admin = [("Registrar Animal", self.t_registrar_animal),
                       ("Modificar Animal", self.t_modificar_animal),
                       ("Registrar Propietario", self.t_registrar_propietario),
                       ("Agendar Cita", self.t_agendar_cita),
                       ("Consultar Citas", self.t_consultar_citas),
                       ("Notificaciones", self.t_notificaciones)]
        if usuario.rol == "Administrador":
            pestanas = [("Consultar Animales", self.t_consultar_animales)] + recep_admin + [
                ("Modificar Propietario", self.t_modificar_propietario),
                ("Reportes", self.t_reportes), ("Usuarios", self.t_usuarios),
                ("Servicios", self.t_servicios), ("Bitácora", self.t_bitacora)]
        elif usuario.rol == "Recepcionista":
            pestanas = recep_admin + [("Registrar Pago", self.t_pagos),
                                      ("Recordatorios", self.t_recordatorios)]
        else:
            pestanas = [("Consultar Animales", self.t_consultar_animales),
                        ("Historial Clínico", self.t_historial),
                        ("Mis Citas", self.t_mis_citas),
                        ("Alertas de Vacunas", self.t_alertas)]
        self.insignias = []          # (franja de patrones, cuerpo de la pestaña)
        for texto, constructor in pestanas:
            marco = ttk.Frame(self.cuaderno)
            self.cuaderno.add(marco, text=texto)
            # La pestaña = franja de patrones (arriba) + cuerpo (el contenido de siempre).
            # Al cambiar de pestaña solo se reconstruye el cuerpo.
            cuerpo = ttk.Frame(marco)
            cuerpo.pack(fill="both", expand=True)
            if texto in TAB_PATRONES:
                franja = crear_insignia_patrones(marco, texto)
                self.insignias.append((franja, cuerpo))
                if self.ver_patrones.get():
                    franja.pack(fill="x", padx=8, pady=(6, 2), before=cuerpo)
            self.constructores[str(marco)] = (cuerpo, constructor)
            constructor(cuerpo)
        # Al cambiar de pestaña se reconstruye para mostrar datos actualizados
        self.cuaderno.bind("<<NotebookTabChanged>>", self._al_cambiar_pestana)

    # ---------- utilidades de interfaz ----------
    def _al_cambiar_pestana(self, _evento):
        seleccion = self.cuaderno.select()
        if not seleccion:
            return
        marco = self.cuaderno.nametowidget(seleccion)
        cuerpo, constructor = self.constructores[str(marco)]
        for w in cuerpo.winfo_children():
            w.destroy()
        constructor(cuerpo)

    def _alternar_patrones(self):
        VISTA["patrones"] = self.ver_patrones.get()
        for franja, cuerpo in self.insignias:
            if VISTA["patrones"]:
                franja.pack(fill="x", padx=8, pady=(6, 2), before=cuerpo)
            else:
                franja.pack_forget()

    def _ventana_patrones(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Patrones de diseño aplicados")
        ventana.geometry("980x500")
        tk.Label(ventana, text="Patrones de diseño del sistema (letras de color = categoría)",
                 font=(FAMILIA, 11, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        leyenda = tk.Frame(ventana)
        leyenda.pack(anchor="w", padx=12)
        for categoria, color in COLOR_CATEGORIA.items():
            tk.Label(leyenda, text=f"● {categoria}", fg=color, font=(FAMILIA, 10, "bold")).pack(side="left", padx=(0, 16))
        tabla = ttk.Treeview(ventana, columns=("Patrón", "Categoría", "Origen", "Dónde se aplica"),
                             show="headings", height=16)
        for col, ancho in (("Patrón", 160), ("Categoría", 110), ("Origen", 90), ("Dónde se aplica", 720)):
            tabla.heading(col, text=col)
            tabla.column(col, width=ancho, anchor="w")
        for categoria, color in COLOR_CATEGORIA.items():
            tabla.tag_configure(categoria, foreground=color)
        for nombre, (categoria, donde, existia) in PATRONES.items():
            tabla.insert("", "end", tags=(categoria,),
                         values=(nombre, categoria, "Ya existía" if existia else "Nuevo", donde))
        tabla.pack(fill="both", expand=True, padx=12, pady=10)

    def _accion(self, comando):
        """PATRÓN: COMMAND - selecciona el comando en InterfazCita (invocador) y lo ejecuta."""
        self.ctl.interfazCita.setComando(comando)
        return self.ctl.interfazCita.ejecutarAccion()

    def _ejecutar(self, funcion, *args):
        try:
            return funcion(*args)
        except ErrorNegocio as e:
            messagebox.showerror("Error", str(e))
        except sqlite3.Error as e:
            messagebox.showerror("Error", f"Error de base de datos: {e}")
        return FALLO

    def _barra_deshacer(self, marco, al_deshacer=None):
        """Botón «Deshacer» + texto de la acción que se revertirá (MEMENTO + COMMAND).
        Devuelve la función que actualiza la barra; las pantallas la llaman tras cada acción."""
        barra = tk.Frame(marco)
        barra.pack(pady=(0, 5))
        boton = tk.Button(barra, text="Deshacer última acción")
        boton.pack(side="left", padx=5)
        etiqueta = tk.Label(barra, fg=C_SUAVE)
        etiqueta.pack(side="left")

        def refrescar():
            descripcion = self.ctl.interfazCita.proxima_a_deshacer(self.usuario)
            boton.config(state="normal" if descripcion else "disabled")
            etiqueta.config(text=f"Se deshará: {descripcion}" if descripcion
                            else "No hay acciones para deshacer")

        def deshacer():
            if self._ejecutar(self.ctl.interfazCita.deshacer, self.usuario) is not FALLO:
                messagebox.showinfo("Deshacer", "La acción se deshizo")
                if al_deshacer:
                    al_deshacer()
            refrescar()

        boton.config(command=deshacer)
        refrescar()
        return refrescar

    @staticmethod
    def _tabla(marco, columnas, anchos, alto=8):
        tabla = ttk.Treeview(marco, columns=columnas, show="headings", height=alto)
        for col, ancho in zip(columnas, anchos):
            tabla.heading(col, text=col)
            tabla.column(col, width=ancho, anchor="w")
        tabla.pack(fill="both", expand=True, padx=5, pady=5)
        return tabla

    @staticmethod
    def _fila_form(marco, fila, etiqueta, widget):
        tk.Label(marco, text=etiqueta).grid(row=fila, column=0, padx=5, pady=4, sticky="e")
        widget.grid(row=fila, column=1, padx=5, pady=4, sticky="w")
        return widget

    @staticmethod
    def _id_seleccion(tabla, campo="un registro"):
        sel = tabla.selection()
        if not sel:
            raise ErrorNegocio(f"Seleccione {campo}")
        return tabla.item(sel[0], "values")

    @staticmethod
    def _opciones_animales(filas):
        return [f"{f['id']} - {f['nombre']}" for f in filas]

    def _buscador_animales(self, marco, al_seleccionar):
        """Búsqueda por ID o nombre (CU03). Llama a al_seleccionar(id_animal)."""
        barra = tk.Frame(marco)
        barra.pack(fill="x", padx=5, pady=5)
        tk.Label(barra, text="ID o nombre del animal:").pack(side="left")
        entrada = tk.Entry(barra, width=25)
        entrada.pack(side="left", padx=5)
        tabla = self._tabla(marco, ("ID", "Nombre", "Especie", "Propietario"), (60, 160, 100, 180), 4)

        def buscar():
            for i in tabla.get_children():
                tabla.delete(i)
            r = self._ejecutar(self.ctl.animal.buscar, self.usuario, entrada.get())
            if r is FALLO:
                return
            for f in r:
                tabla.insert("", "end", values=(f["id"], f["nombre"], f["especie"], f["propietario"]))
            hijos = tabla.get_children()
            if len(hijos) == 1:
                tabla.selection_set(hijos[0])

        def seleccionado(_e):
            sel = tabla.selection()
            if sel:
                al_seleccionar(int(tabla.item(sel[0], "values")[0]))

        tk.Button(barra, text="Buscar", command=buscar).pack(side="left")
        entrada.bind("<Return>", lambda e: buscar())
        tabla.bind("<<TreeviewSelect>>", seleccionado)

    @staticmethod
    def _texto_ficha(datos):
        a = datos["animal"]
        lineas = [f"ANIMAL #{a['id']}: {a['nombre']}",
                  f"Especie: {a['especie']}   Raza: {a['raza'] or '—'}",
                  f"Edad: {a['edad']} años   Peso: {a['peso']} kg",
                  f"Propietario: {a['propietario'] or '—'}  Tel: {a['telefono'] or '—'}",
                  "", "=== HISTORIAL CLÍNICO ==="]
        historial = ListaHistoriales(historial_desde_fila(h) for h in datos["historial"])
        if len(historial):
            iterador = historial.crearIteradorReciente()        # PATRÓN: ITERATOR
            while iterador.haySiguiente():
                h = iterador.siguiente()
                lineas += [f"Fecha: {h.fecha}  (atendió: {h.veterinario_nombre})",
                           f"  Diagnóstico: {h.diagnostico}",
                           f"  Tratamiento: {h.tratamiento}",
                           f"  Vacunas: {h.vacunas or '—'}"
                           + (f"  (próxima: {h.proxima_vacuna})" if h.proxima_vacuna else ""),
                           f"  Alergias: {h.alergias or '—'}", "-" * 50]
        else:
            lineas.append("Sin registros médicos")
        lineas += ["", "=== CITAS ==="]
        if datos["citas"]:
            for c in datos["citas"]:
                lineas.append(f"{c['fecha']} {c['hora']} | {c['veterinario']} | {c['estado']} | {c['motivo']}")
        else:
            lineas.append("Sin citas registradas")
        return "\n".join(lineas)

    @staticmethod
    def _escribir(texto_widget, contenido):
        texto_widget.config(state="normal")
        texto_widget.delete("1.0", tk.END)
        texto_widget.insert(tk.END, contenido)
        texto_widget.config(state="disabled")

    # ---------- CU03: consultar animales ----------
    def t_consultar_animales(self, marco):
        texto = scrolledtext.ScrolledText(marco, wrap=tk.WORD, height=15, state="disabled")

        def mostrar(animal_id):
            datos = self._ejecutar(self.ctl.animal.consultar, self.usuario, animal_id)
            if datos is not FALLO:
                self._escribir(texto, self._texto_ficha(datos))

        self._buscador_animales(marco, mostrar)
        texto.pack(fill="both", expand=True, padx=5, pady=5)

    # ---------- CU02 / modificar animal ----------
    def _form_animal(self, marco, propietarios):
        f = tk.Frame(marco)
        f.pack(padx=10, pady=10, anchor="w")
        w = {"nombre": tk.Entry(f, width=30),
             "especie": ttk.Combobox(f, values=ESPECIES, width=27),
             "raza": tk.Entry(f, width=30), "edad": tk.Entry(f, width=30),
             "peso": tk.Entry(f, width=30),
             "propietario": ttk.Combobox(f, values=[SIN_PROPIETARIO] + [
                 f"{p['id']} - {p['nombre']}" for p in propietarios], state="readonly", width=27)}
        w["propietario"].set(SIN_PROPIETARIO)
        for i, (etq, clave) in enumerate((("Nombre:", "nombre"), ("Especie:", "especie"),
                                          ("Raza (opcional):", "raza"), ("Edad (años):", "edad"),
                                          ("Peso (kg):", "peso"), ("Propietario:", "propietario"))):
            self._fila_form(f, i, etq, w[clave])
        return w

    @staticmethod
    def _leer_form_animal(w):
        prop = w["propietario"].get()
        pid = None if prop in ("", SIN_PROPIETARIO) else id_de_opcion(prop, "un propietario")
        return (w["nombre"].get(), w["especie"].get(), w["raza"].get(),
                w["edad"].get(), w["peso"].get(), pid)

    def t_registrar_animal(self, marco):
        props = self._ejecutar(self.ctl.propietario.listar, self.usuario)
        w = self._form_animal(marco, [] if props is FALLO else props)

        def registrar():
            def accion():
                return self.ctl.animal.registrar(self.usuario, *self._leer_form_animal(w))
            nuevo_id = self._ejecutar(accion)
            if nuevo_id is not FALLO:
                messagebox.showinfo("Éxito", f"Animal registrado con ID {nuevo_id}")
                for clave in ("nombre", "raza", "edad", "peso"):
                    w[clave].delete(0, tk.END)

        tk.Button(marco, text="Registrar", command=registrar).pack(pady=10)

    def t_modificar_animal(self, marco):
        props = self._ejecutar(self.ctl.propietario.listar, self.usuario)
        animales = self._ejecutar(self.ctl.animal.listar, self.usuario)
        sup = tk.Frame(marco)
        sup.pack(padx=10, pady=10, anchor="w")
        tk.Label(sup, text="Animal:").pack(side="left")
        combo = ttk.Combobox(sup, state="readonly", width=30,
                             values=[] if animales is FALLO else self._opciones_animales(animales))
        combo.pack(side="left", padx=5)
        w = self._form_animal(marco, [] if props is FALLO else props)

        def cargar():
            def accion():
                return self.ctl.animal.obtener(self.usuario, id_de_opcion(combo.get(), "un animal"))
            a = self._ejecutar(accion)
            if a is FALLO:
                return
            for clave, valor in (("nombre", a["nombre"]), ("especie", a["especie"]),
                                 ("raza", a["raza"] or ""), ("edad", a["edad"]), ("peso", a["peso"])):
                if isinstance(w[clave], ttk.Combobox):
                    w[clave].set(valor)
                else:
                    w[clave].delete(0, tk.END)
                    w[clave].insert(0, str(valor))
            if a["propietario_id"] is None:
                w["propietario"].set(SIN_PROPIETARIO)
            else:
                w["propietario"].set(f"{a['propietario_id']} - {a['propietario']}")

        def actualizar():
            def accion():
                animal_id = id_de_opcion(combo.get(), "un animal")
                self.ctl.animal.actualizar(self.usuario, animal_id, *self._leer_form_animal(w))
                return True
            if self._ejecutar(accion) is not FALLO:
                messagebox.showinfo("Éxito", "Datos del animal actualizados")

        tk.Button(sup, text="Cargar datos", command=cargar).pack(side="left")
        tk.Button(marco, text="Actualizar", command=actualizar).pack(pady=10)

    # ---------- CU04: registrar propietario ----------
    def t_registrar_propietario(self, marco):
        f = tk.Frame(marco)
        f.pack(padx=10, pady=10, anchor="w")
        nombre = self._fila_form(f, 0, "Nombre completo:", tk.Entry(f, width=35))
        telefono = self._fila_form(f, 1, "Teléfono (10 dígitos):", tk.Entry(f, width=35))
        usuario_web = self._fila_form(f, 2, "Usuario del portal web (opcional):", tk.Entry(f, width=35))
        clave_web = self._fila_form(f, 3, "Contraseña del portal (opcional):", tk.Entry(f, width=35, show="*"))

        def registrar():
            nuevo = self._ejecutar(self.ctl.propietario.registrar, self.usuario,
                                   nombre.get(), telefono.get(), usuario_web.get(), clave_web.get())
            if nuevo is not FALLO:
                messagebox.showinfo("Éxito", f"Propietario registrado con ID {nuevo}")
                for campo in (nombre, telefono, usuario_web, clave_web):
                    campo.delete(0, tk.END)

        tk.Button(marco, text="Registrar", command=registrar).pack(pady=10)

    # ---------- CU12: modificar propietario (solo Administrador) ----------
    def t_modificar_propietario(self, marco):
        props = self._ejecutar(self.ctl.propietario.listar, self.usuario)
        tabla = self._tabla(marco, ("ID", "Nombre", "Teléfono"), (60, 280, 140), 8)
        for p in ([] if props is FALLO else props):
            tabla.insert("", "end", values=(p["id"], p["nombre"], p["telefono"]))
        f = tk.Frame(marco)
        f.pack(padx=10, pady=10, anchor="w")
        nombre = self._fila_form(f, 0, "Nombre completo:", tk.Entry(f, width=35))
        telefono = self._fila_form(f, 1, "Teléfono (10 dígitos):", tk.Entry(f, width=35))

        def al_elegir(_evento):
            sel = tabla.selection()
            if not sel:
                return
            _, nom, tel = tabla.item(sel[0], "values")
            for campo, valor in ((nombre, nom), (telefono, tel)):
                campo.delete(0, tk.END)
                campo.insert(0, str(valor))

        def guardar():
            def accion():
                propietario_id = entero(self._id_seleccion(tabla, "un propietario")[0], "El propietario")
                self.ctl.propietario.modificar(self.usuario, propietario_id, nombre.get(), telefono.get())
                return True
            if self._ejecutar(accion) is True:
                messagebox.showinfo("Éxito", "Propietario actualizado")
                self._al_cambiar_pestana(None)

        tabla.bind("<<TreeviewSelect>>", al_elegir)
        tk.Button(marco, text="Guardar cambios", command=guardar).pack(pady=10)

    # ---------- CU05: agendar cita ----------
    def t_agendar_cita(self, marco):
        animales = self._ejecutar(self.ctl.animal.listar, self.usuario)
        vets = self._ejecutar(self.ctl.cita.veterinarios, self.usuario)
        servicios = self._ejecutar(self.ctl.servicio.listar, self.usuario)
        f = tk.Frame(marco)
        f.pack(padx=10, pady=10, anchor="w")
        c_animal = self._fila_form(f, 0, "Animal:", ttk.Combobox(
            f, state="readonly", width=35,
            values=[] if animales is FALLO else self._opciones_animales(animales)))
        c_vet = self._fila_form(f, 1, "Veterinario:", ttk.Combobox(
            f, state="readonly", width=35,
            values=[] if vets is FALLO else [f"{v['id']} - {v['nombre']} {v['especialidad']}".strip()
                                              for v in vets]))
        c_serv = self._fila_form(f, 2, "Servicio (opcional):", ttk.Combobox(
            f, state="readonly", width=35,
            values=["(sin servicio)"] + ([] if servicios is FALLO else
                                         [f"{s['id']} - {s['nombre']}" for s in servicios])))
        c_serv.set("(sin servicio)")
        e_fecha = self._fila_form(f, 3, "Fecha (AAAA-MM-DD):", tk.Entry(f, width=38))
        e_hora = self._fila_form(f, 4, "Hora (HH:MM):", tk.Entry(f, width=38))
        e_motivo = self._fila_form(f, 5, "Motivo:", tk.Entry(f, width=38))

        def agendar():
            def accion():
                serv = c_serv.get()
                sid = None if serv in ("", "(sin servicio)") else id_de_opcion(serv, "un servicio")
                cita = Cita(animal_id=id_de_opcion(c_animal.get(), "un animal"),
                            veterinario_id=id_de_opcion(c_vet.get(), "un veterinario"),
                            servicio_id=sid, fecha=e_fecha.get(), hora=e_hora.get(),
                            motivo=e_motivo.get())
                return self.ctl.interfazCita.agendarCita(self.usuario, cita)   # PATRÓN: COMMAND
            if self._ejecutar(accion) is not FALLO:
                messagebox.showinfo("Éxito", "Cita agendada con estado pendiente")
                e_motivo.delete(0, tk.END)
                refrescar_deshacer()

        tk.Button(marco, text="Agendar", command=agendar).pack(pady=10)
        refrescar_deshacer = self._barra_deshacer(marco)

    # ---------- CU06: consultar citas ----------
    def t_consultar_citas(self, marco):
        cols = ("ID", "Fecha", "Hora", "Animal", "Veterinario", "Servicio", "Estado")
        tabla = self._tabla(marco, cols, (50, 90, 60, 130, 150, 130, 90), 12)

        def llenar():
            for i in tabla.get_children():
                tabla.delete(i)
            b_confirmar.config(state="normal")
            b_cancelar.config(state="normal")
            b_seguimiento.config(state="normal")
            refrescar_deshacer()
            filas = self._ejecutar(self.ctl.interfazCita.consultarCitas, self.usuario)   # PATRÓN: COMMAND
            if filas is FALLO:
                return
            if not filas:
                messagebox.showinfo("Citas", "No hay citas disponibles")
            for c in filas:
                tabla.insert("", "end", values=(c["id"], c["fecha"], c["hora"], c["animal"],
                                                c["veterinario"], c["servicio"], c["estado"]))

        def al_seleccionar(_evento=None):
            # PATRÓN STATE: el estado de la cita seleccionada dice qué botones tienen sentido
            seleccion = tabla.selection()
            if not seleccion:
                return
            estado = estadoDe(tabla.item(seleccion[0])["values"][6])
            b_confirmar.config(state="normal" if estado.puedeConfirmar() else "disabled")
            b_cancelar.config(state="normal" if estado.puedeCancelar() else "disabled")
            b_seguimiento.config(state="normal" if estado.admiteSeguimiento() else "disabled")

        def confirmar():
            def accion():
                cid = int(self._id_seleccion(tabla, "una cita")[0])
                self._accion(ComandoConfirmarCita(self.ctl.cita, self.usuario, cid))
                return True
            if self._ejecutar(accion) is True:
                llenar()

        def cancelar():
            def accion():
                cid = int(self._id_seleccion(tabla, "una cita")[0])
                if not messagebox.askyesno("Confirmar", f"¿Cancelar la cita {cid}?"):
                    return None
                self._accion(ComandoCancelarCita(self.ctl.cita, self.usuario, cid))
                return True
            if self._ejecutar(accion) is True:
                llenar()

        def seguimiento():
            def accion():
                cid = int(self._id_seleccion(tabla, "una cita")[0])
                fecha = simpledialog.askstring("Cita de seguimiento",
                                               "Fecha de la nueva cita (AAAA-MM-DD):", parent=marco)
                if not fecha:
                    return None
                hora = simpledialog.askstring("Cita de seguimiento", "Hora (HH:MM):", parent=marco)
                if not hora:
                    return None
                self._accion(ComandoCrearSeguimiento(self.ctl.cita, self.usuario, cid, fecha, hora))
                return True
            if self._ejecutar(accion) is True:
                messagebox.showinfo("Éxito", "Cita de seguimiento creada (copia de la seleccionada, "
                                             "con estado pendiente)")
                llenar()

        botones = tk.Frame(marco)
        botones.pack(pady=5)
        b_confirmar = tk.Button(botones, text="Confirmar cita seleccionada", command=confirmar)
        b_confirmar.pack(side="left", padx=5)
        b_cancelar = tk.Button(botones, text="Cancelar cita seleccionada", command=cancelar)
        b_cancelar.pack(side="left", padx=5)
        b_seguimiento = tk.Button(botones, text="Crear cita de seguimiento", command=seguimiento)
        b_seguimiento.pack(side="left", padx=5)
        refrescar_deshacer = self._barra_deshacer(marco, al_deshacer=llenar)
        tabla.bind("<<TreeviewSelect>>", al_seleccionar)
        llenar()

    # ---------- Veterinario: mis citas ----------
    def t_mis_citas(self, marco):
        cols = ("ID", "Fecha", "Hora", "Animal", "Motivo", "Estado")
        tabla = self._tabla(marco, cols, (50, 90, 60, 140, 220, 90), 12)

        def llenar():
            for i in tabla.get_children():
                tabla.delete(i)
            b_atender.config(state="normal")
            refrescar_deshacer()
            filas = self._ejecutar(self.ctl.cita.citas_del_veterinario, self.usuario)
            if filas is FALLO:
                return
            for c in filas:
                tabla.insert("", "end", values=(c["id"], c["fecha"], c["hora"], c["animal"],
                                                c["motivo"], c["estado"]))

        def al_seleccionar(_evento=None):
            seleccion = tabla.selection()                      # PATRÓN STATE
            if seleccion:
                estado = estadoDe(tabla.item(seleccion[0])["values"][5])
                b_atender.config(state="normal" if estado.puedeFinalizar() else "disabled")

        def atender():
            def accion():
                cid = int(self._id_seleccion(tabla, "una cita")[0])
                self._accion(ComandoFinalizarCita(self.ctl.cita, self.usuario, cid))
                return True
            if self._ejecutar(accion) is True:
                llenar()

        b_atender = tk.Button(marco, text="Finalizar cita", command=atender)
        b_atender.pack(pady=5)
        refrescar_deshacer = self._barra_deshacer(marco, al_deshacer=llenar)
        tabla.bind("<<TreeviewSelect>>", al_seleccionar)
        tk.Label(marco, text="Avisos de recepción sobre su agenda (se reinicia al cerrar la aplicación):"
                 ).pack(anchor="w", padx=8)
        avisos = self._tabla(marco, ("Hora", "Aviso"), (80, 700), 4)
        for momento, vet, texto in reversed(self.ctl.buzon.avisos):         # OBSERVER
            if vet == self.usuario.nombre:
                avisos.insert("", "end", values=(f"{momento:%H:%M:%S}", texto))
        llenar()

    # ---------- Notificaciones (Observer) ----------
    def t_notificaciones(self, marco):
        tk.Label(marco, text="SMS simulados al propietario (un observador de las citas; "
                             "se reinicia al cerrar la aplicación):").pack(anchor="w", padx=8, pady=(8, 0))
        sms = self._tabla(marco, ("Hora", "Teléfono", "Mensaje"), (80, 110, 760), 7)
        for momento, telefono, texto in reversed(self.ctl.buzon.mensajes):
            sms.insert("", "end", values=(f"{momento:%H:%M:%S}", telefono, texto))
        tk.Label(marco, text="Avisos internos a los veterinarios:").pack(anchor="w", padx=8, pady=(8, 0))
        avisos = self._tabla(marco, ("Hora", "Veterinario", "Aviso"), (80, 160, 710), 6)
        for momento, vet, texto in reversed(self.ctl.buzon.avisos):
            avisos.insert("", "end", values=(f"{momento:%H:%M:%S}", vet, texto))
        if self.ctl.cita.fallos:
            tk.Label(marco, fg="#b03a3a", text=f"{len(self.ctl.cita.fallos)} observador(es) fallaron; "
                     "las operaciones no se vieron afectadas.").pack(anchor="w", padx=8, pady=4)

    # ---------- CU07: actualizar historial clínico ----------
    def t_historial(self, marco):
        estado = {"animal": None}
        etiqueta = tk.Label(marco, text="Seleccione un animal", font=(FAMILIA, 10, "bold"))
        f = tk.Frame(marco)
        e_diag = self._fila_form(f, 0, "Diagnóstico:", tk.Entry(f, width=50))
        e_trat = self._fila_form(f, 1, "Tratamiento:", tk.Entry(f, width=50))
        e_vac = self._fila_form(f, 2, "Vacunas aplicadas:", tk.Entry(f, width=50))
        e_prox = self._fila_form(f, 3, "Próxima aplicación (AAAA-MM-DD):", tk.Entry(f, width=50))
        e_alerg = self._fila_form(f, 4, "Alergias:", tk.Entry(f, width=50))

        def elegido(animal_id):
            estado["animal"] = animal_id
            etiqueta.config(text=f"Animal seleccionado: ID {animal_id}")

        solo_vacuna = tk.BooleanVar(value=False)

        def guardar():
            def accion():
                if estado["animal"] is None:
                    raise ErrorNegocio("Busque y seleccione un animal")
                if solo_vacuna.get():                       # BUILDER: receta "control de vacunación"
                    return self.ctl.historial.registrar_vacunacion(
                        self.usuario, estado["animal"], e_vac.get(), e_prox.get())
                return self.ctl.historial.actualizarHistorial(
                    self.usuario, estado["animal"], e_diag.get(), e_trat.get(),
                    e_vac.get(), e_alerg.get(), e_prox.get())
            if self._ejecutar(accion) is not FALLO:
                messagebox.showinfo("Éxito", "Historial clínico actualizado")
                for e in (e_diag, e_trat, e_vac, e_prox, e_alerg):
                    e.delete(0, tk.END)

        def corregir():
            def accion():
                if estado["animal"] is None:
                    raise ErrorNegocio("Busque y seleccione un animal")
                return self.ctl.historial.corregir_ultimo_registro(      # PATRÓN: MEMENTO
                    self.usuario, estado["animal"], e_diag.get(), e_trat.get(),
                    e_vac.get(), e_alerg.get(), e_prox.get())
            if self._ejecutar(accion) is not FALLO:
                messagebox.showinfo("Éxito", "El último registro del animal se corrigió")
                refrescar_memento()

        def deshacer_cambio():
            if self._ejecutar(self.ctl.historial.deshacerUltimoCambio, self.usuario) is not FALLO:
                messagebox.showinfo("Deshacer", "El registro volvió a su contenido anterior")
            refrescar_memento()

        def refrescar_memento():
            b_deshacer.config(state="normal" if self.ctl.historial.hay_cambios_para_deshacer()
                              else "disabled")

        self._buscador_animales(marco, elegido)
        etiqueta.pack(pady=5)
        f.pack(padx=10, pady=5)
        tk.Checkbutton(marco, text="Solo control de vacunación (no requiere diagnóstico ni tratamiento)",
                       variable=solo_vacuna).pack()
        botones = tk.Frame(marco)
        botones.pack(pady=8)
        tk.Button(botones, text="Guardar en historial", command=guardar).pack(side="left", padx=5)
        tk.Button(botones, text="Corregir último registro", command=corregir).pack(side="left", padx=5)
        b_deshacer = tk.Button(botones, text="Deshacer último cambio", command=deshacer_cambio)
        b_deshacer.pack(side="left", padx=5)
        refrescar_memento()

    def t_alertas(self, marco):
        filas = self._ejecutar(self.ctl.historial.alertas_vacunas, self.usuario)
        if filas is FALLO:
            return
        if not filas:
            tk.Label(marco, text="No hay vacunas próximas a vencer").pack(pady=20)
            return
        tk.Label(marco, text="Vacunas próximas (7 días) o vencidas:").pack(pady=10)
        tabla = self._tabla(marco, ("Animal ID", "Animal", "Vacuna", "Próxima aplicación"),
                            (80, 150, 200, 140), 12)
        for r in filas:
            tabla.insert("", "end", values=(r["animal_id"], r["animal"], r["vacunas"], r["proxima_vacuna"]))

    # ---------- Pagos y recordatorios (Recepcionista) ----------
    def t_pagos(self, marco):
        citas = self._ejecutar(self.ctl.pago.citas_sin_pago, self.usuario)
        citas = [] if citas is FALLO else citas
        precios = {c["id"]: c["precio"] for c in citas}
        f = tk.Frame(marco)
        f.pack(padx=10, pady=10, anchor="w")
        combo = self._fila_form(f, 0, "Cita:", ttk.Combobox(
            f, state="readonly", width=60,
            values=[f"{c['id']} - {c['animal']} ({c['fecha']} {c['hora']}) - {c['servicio']} - ${c['precio']:.2f}"
                    for c in citas]))
        monto = self._fila_form(f, 1, "Monto:", tk.Entry(f, width=20))

        def al_elegir(_e):
            try:
                monto.delete(0, tk.END)
                monto.insert(0, f"{precios.get(id_de_opcion(combo.get(), 'cita'), 0):.2f}")
            except ErrorNegocio:
                pass

        def registrar():
            def accion():
                self.ctl.pago.registrar(self.usuario, id_de_opcion(combo.get(), "una cita"), monto.get())
                return True
            if self._ejecutar(accion) is True:
                messagebox.showinfo("Éxito", "Pago registrado")
                self._al_cambiar_pestana(None)

        def cobrar_con_tarjeta():
            def accion():
                cid = id_de_opcion(combo.get(), "una cita")
                if not messagebox.askyesno("Tarjeta de prueba", "Se cobrará con la tarjeta de prueba "
                                           "aprobada (modo de prueba, sin tarjeta real). ¿Continuar?"):
                    return None
                return self.ctl.cita.procesarPagoCita(self.usuario, cid, "tok_test_ok")   # PATRÓN: ADAPTER
            referencia = self._ejecutar(accion)
            if referencia not in (FALLO, None):
                messagebox.showinfo("Éxito", f"Pago aprobado. Comprobante: {referencia}")
                self._al_cambiar_pestana(None)

        combo.bind("<<ComboboxSelected>>", al_elegir)
        botones = tk.Frame(marco)
        botones.pack(pady=10)
        tk.Button(botones, text="Registrar pago", command=registrar).pack(side="left", padx=5)
        tk.Button(botones, text="Cobrar con tarjeta de prueba", command=cobrar_con_tarjeta).pack(side="left", padx=5)

    def t_recordatorios(self, marco):
        citas = self._ejecutar(self.ctl.cita.recordatorios_manana, self.usuario)
        if citas is FALLO:
            return
        if not citas:
            tk.Label(marco, text="No hay citas pendientes para mañana").pack(pady=20)
            return
        tk.Label(marco, text="Citas de mañana:").pack(pady=10)
        for c in citas:
            fila = tk.Frame(marco, borderwidth=1, relief="groove", padx=10, pady=5)
            fila.pack(fill="x", padx=5, pady=2)
            tk.Label(fila, text=f"#{c['id']} - {c['animal']} a las {c['hora']}").pack(side="left")
            tk.Button(fila, text="Enviar SMS", command=lambda t=c["telefono"], i=c["id"]: messagebox.showinfo(
                "Recordatorio", f"(Simulado) Recordatorio enviado al {t} para la cita {i}")
            ).pack(side="right")

    # ---------- Administrador ----------
    def t_servicios(self, marco):
        tabla = self._tabla(marco, ("ID", "Nombre", "Precio"), (60, 250, 100), 8)
        f = tk.Frame(marco)
        f.pack(padx=5, pady=5)
        nombre = self._fila_form(f, 0, "Nombre:", tk.Entry(f))
        precio = self._fila_form(f, 1, "Precio:", tk.Entry(f))

        def llenar():
            for i in tabla.get_children():
                tabla.delete(i)
            filas = self._ejecutar(self.ctl.servicio.listar, self.usuario)
            if filas is not FALLO:
                for s in filas:
                    tabla.insert("", "end", values=(s["id"], s["nombre"], f"{s['precio']:.2f}"))

        def operar(metodo):
            def accion():
                metodo(self.usuario, nombre.get(), precio.get())
                return True
            if self._ejecutar(accion) is True:
                llenar()

        tk.Button(f, text="Agregar", command=lambda: operar(self.ctl.servicio.agregar)).grid(row=2, column=0, pady=5)
        tk.Button(f, text="Actualizar precio",
                  command=lambda: operar(self.ctl.servicio.actualizar_precio)).grid(row=2, column=1, pady=5)
        llenar()

    def t_usuarios(self, marco):
        cols = ("ID", "Usuario", "Nombre", "Rol", "Especialidad", "Activo")
        tabla = self._tabla(marco, cols, (50, 110, 160, 110, 140, 60), 7)
        f = tk.Frame(marco)
        f.pack(padx=5, pady=5)
        e_user = self._fila_form(f, 0, "Usuario (solo al registrar):", tk.Entry(f, width=28))
        e_nombre = self._fila_form(f, 1, "Nombre:", tk.Entry(f, width=28))
        e_pass = self._fila_form(f, 2, "Contraseña (vacía = sin cambio):", tk.Entry(f, width=28, show="*"))
        c_rol = self._fila_form(f, 3, "Rol:", ttk.Combobox(f, values=ROLES_GESTIONABLES,
                                                            state="readonly", width=25))
        e_esp = self._fila_form(f, 4, "Especialidad (veterinarios):", tk.Entry(f, width=28))
        activo = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="Cuenta activa", variable=activo).grid(row=5, column=1, sticky="w")

        def llenar():
            for i in tabla.get_children():
                tabla.delete(i)
            filas = self._ejecutar(self.ctl.usuario.consultar, self.usuario)
            if filas is not FALLO:
                for u in filas:
                    tabla.insert("", "end", values=(u["id"], u["nombre_usuario"], u["nombre"], u["rol"],
                                                    u["especialidad"] or "", "Sí" if u["estado"] else "No"))

        def al_seleccionar(_e):
            sel = tabla.selection()
            if not sel:
                return
            v = tabla.item(sel[0], "values")
            for e, val in ((e_user, v[1]), (e_nombre, v[2]), (e_esp, v[4])):
                e.delete(0, tk.END)
                e.insert(0, val)
            e_pass.delete(0, tk.END)
            c_rol.set(v[3])
            activo.set(v[5] == "Sí")

        def registrar():
            def accion():
                self.ctl.usuario.registrar(self.usuario, e_user.get(), e_nombre.get(), e_pass.get(),
                                           c_rol.get(), e_esp.get())
                return True
            if self._ejecutar(accion) is True:
                messagebox.showinfo("Éxito", "Cuenta registrada")
                llenar()

        def modificar():
            def accion():
                uid = int(self._id_seleccion(tabla, "una cuenta")[0])
                self.ctl.usuario.modificar(self.usuario, uid, e_nombre.get(), c_rol.get(),
                                           activo.get(), e_pass.get(), e_esp.get())
                return True
            if self._ejecutar(accion) is True:
                messagebox.showinfo("Éxito", "Cuenta actualizada")
                llenar()

        botones = tk.Frame(marco)
        botones.pack(pady=5)
        tk.Button(botones, text="Registrar nueva", command=registrar).pack(side="left", padx=5)
        tk.Button(botones, text="Modificar seleccionada", command=modificar).pack(side="left", padx=5)
        tabla.bind("<<TreeviewSelect>>", al_seleccionar)
        llenar()

    # ---------- Bitácora (Command + Factory Method) ----------
    def t_bitacora(self, marco):
        tk.Label(marco, text="Acciones de citas ejecutadas como comandos (se reinicia al cerrar la aplicación):"
                 ).pack(anchor="w", padx=8, pady=(8, 0))
        tabla = self._tabla(marco, ("Hora", "Usuario", "Acción", "Resultado"), (90, 110, 420, 360), 9)
        for hora, usuario, accion, resultado in reversed(self.ctl.interfazCita.bitacora):
            tabla.insert("", "end", values=(f"{hora:%H:%M:%S}", usuario, accion, resultado))
        tk.Label(marco, text="Accesos registrados por el creador de usuarios:").pack(anchor="w", padx=8)
        accesos = self._tabla(marco, ("Hora", "Usuario", "Rol"), (90, 160, 160), 5)
        for hora, usuario, rol in reversed(CreadorUsuario.ACCESOS):
            accesos.insert("", "end", values=(f"{hora:%H:%M:%S}", usuario, rol))

    # ---------- CU08: reportes ----------
    def t_reportes(self, marco):
        f = tk.Frame(marco)
        f.pack(padx=10, pady=10, anchor="w")
        combo = self._fila_form(f, 0, "Tipo de reporte:", ttk.Combobox(
            f, values=ControlReporte.TIPOS, state="readonly", width=38))
        e_ini = self._fila_form(f, 1, "Desde (AAAA-MM-DD):", tk.Entry(f, width=40))
        e_fin = self._fila_form(f, 2, "Hasta (AAAA-MM-DD):", tk.Entry(f, width=40))
        texto = scrolledtext.ScrolledText(marco, wrap=tk.WORD, height=15, state="disabled")
        ultimo = {"lineas": []}

        def generar():
            r = self._ejecutar(self.ctl.reporte.generarReporte, self.usuario, combo.get(), e_ini.get(), e_fin.get())
            if r is not FALLO:
                ultimo["lineas"] = r
                self._escribir(texto, "\n".join(r))

        def exportar():
            def accion():
                if not ultimo["lineas"]:
                    raise ErrorNegocio("Genere un reporte antes de exportarlo")
                ruta = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
                if not ruta:
                    return None
                self.ctl.reporte.exportar_pdf(self.usuario, ultimo["lineas"], ruta)
                return ruta
            r = self._ejecutar(accion)
            if r not in (FALLO, None):
                messagebox.showinfo("Éxito", f"Reporte exportado a:\n{r}")

        botones = tk.Frame(marco)
        botones.pack()
        tk.Button(botones, text="Generar", command=generar).pack(side="left", padx=5)
        tk.Button(botones, text="Exportar PDF", command=exportar).pack(side="left", padx=5)
        texto.pack(fill="both", expand=True, padx=5, pady=5)


ABRIR_PORTAL = True        # lanzar el portal web al abrir la aplicación
ABRIR_NAVEGADOR = True     # y abrirlo en el navegador


class LanzadorPortal:
    """Arranca portal_web.py como PROCESO APARTE (la separación se mantiene) y lo detiene al salir."""
    def __init__(self, host="127.0.0.1", puerto=8000):
        self.host, self.puerto = host, puerto
        self.proceso = None            # solo si lo lanzamos nosotros

    @property
    def url(self):
        return f"http://{self.host}:{self.puerto}"

    def _responde(self):
        try:
            with socket.create_connection((self.host, self.puerto), timeout=0.5):
                return True
        except OSError:
            return False

    def _es_el_portal(self):
        try:
            with urllib.request.urlopen(self.url + "/", timeout=1.5) as r:
                return b"Portal del propietario" in r.read(4000)
        except Exception:
            return False

    def iniciar(self, espera=8.0):
        """Lanza el portal (o reutiliza uno ya activo). Lanza OSError si no se logra."""
        if self._responde():
            if self._es_el_portal():
                return                  # ya estaba corriendo: se reutiliza
            raise OSError(f"El puerto {self.puerto} está ocupado por otro programa")
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portal_web.py")
        if not os.path.exists(ruta):
            raise OSError("No se encontró portal_web.py junto a esta aplicación")
        self.proceso = subprocess.Popen(
            [sys.executable, ruta, "--host", self.host, "--puerto", str(self.puerto), "--db", DB_ARCHIVO],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))      # sin ventana negra en Windows
        atexit.register(self.detener)
        limite = time.time() + espera
        while time.time() < limite:
            if self.proceso.poll() is not None:
                detalle = (self.proceso.stderr.read() or b"").decode("utf-8", "replace").strip()
                self.proceso = None
                raise OSError(detalle.splitlines()[-1] if detalle else "el portal terminó al iniciar")
            if self._responde():
                return
            time.sleep(0.15)
        self.detener()
        raise OSError("el portal no respondió a tiempo")

    def abrir_navegador(self):
        webbrowser.open(self.url)

    def detener(self):
        """Detiene solo el portal que lanzó esta aplicación (nunca uno ajeno)."""
        p, self.proceso = self.proceso, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()


class Veterinaria(tk.Tk):
    def __init__(self):
        super().__init__()
        aplicar_tema(self)
        self.title("Veterinaria")
        self.geometry("1200x720")
        self.minsize(1000, 600)
        self.db = BaseDatos.getInstancia()         # PATRÓN: SINGLETON
        try:
            self.db.conectar()
        except sqlite3.Error as e:
            messagebox.showerror("Error", f"No se pudo conectar a la base de datos: {e}")
            self.destroy()
            raise
        self.controles = Controles(self.db)
        self.portal = LanzadorPortal()
        self.portal_activo = False
        if ABRIR_PORTAL:
            try:
                self.portal.iniciar()
                self.portal_activo = True
                self.title(f"Veterinaria — portal web: {self.portal.url}")
                if ABRIR_NAVEGADOR:
                    self.after(400, self.portal.abrir_navegador)
            except OSError as e:
                messagebox.showwarning("Portal web", f"No se pudo iniciar el portal web ({e}).\n"
                                       "La aplicación funcionará sin él; puede iniciarlo con: python portal_web.py")
        self.protocol("WM_DELETE_WINDOW", self.salir)
        self.mostrar_login()

    def _limpiar(self):
        for w in self.winfo_children():
            w.destroy()
        self.config(menu=tk.Menu(self))

    def mostrar_login(self):
        self.controles.interfazCita.limpiar_deshacer()   # lo deshecho no cruza sesiones
        self.controles.historial.limpiar_cambios()
        self._limpiar()
        PantallaLogin(self, self.controles, self.mostrar_panel)

    def mostrar_panel(self, usuario):
        self._limpiar()
        PanelPrincipal(self, self.controles, usuario, self.mostrar_login)

    def abrir_portal(self):
        if not self.portal_activo:
            messagebox.showinfo("Portal web", "El portal web no está en ejecución.")
            return
        self.portal.abrir_navegador()

    def salir(self):
        self.portal.detener()
        self.db.desconectar()
        self.destroy()


if __name__ == "__main__":
    app = Veterinaria()
    try:
        app.mainloop()
    finally:
        app.portal.detener()