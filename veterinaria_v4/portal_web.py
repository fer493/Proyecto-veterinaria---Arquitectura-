# -*- coding: utf-8 -*-
"""
Veterinaria V4 - PORTAL WEB DEL PROPIETARIO (proceso independiente, sin Tkinter).

Ejecutar:   python portal_web.py [--host 127.0.0.1] [--puerto 8000] [--db ruta.db]
Abrir:      http://127.0.0.1:8000        (cuenta de prueba: propietario / propietario123)

Es un cliente más del mismo sistema: comparte con el escritorio la base de datos y las capas
de persistencia y patrones, pero se ejecuta, se inicia y se cae por separado.
  CU10 Agendar cita en línea | CU11 Pago con pasarela (Adapter) | CU13 Consultar mis citas
Estilo: cliente-servidor REST en capas. Los patrones Facade, Proxy, Adapter y Decorator están
en patrones.py; aquí solo se ensamblan. Singleton: BaseDatos (persistencia.py). Las páginas
muestran en azul dónde se aplica cada uno.
"""
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from configuracion import DB_ARCHIVO
from errores import ErrorNegocio, ErrorPago, ErrorSesion
from patrones import (APIStripeSDK, CitasSubsistema, Client, ClienteApp, FachadaVeterinaria,
                      HistorialSubsistema, PagosSubsistema, PasarelaPagoAdapter, Proxy)
from persistencia import (AnimalDAO, BaseDatos, CitaDAO, CuentaWebDAO, HistorialDAO, PagoDAO,
                          ServicioDAO)


PAGINA_PORTAL = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portal del propietario</title>
<style>
 :root{
   --verde:#167653;--verde-oscuro:#0f5a3f;--verde-claro:#e6f4ec;
   --texto:#1d3328;--suave:#62766b;--borde:#e0ebe3;
   --sombra:0 18px 50px rgba(20,70,48,.12),0 2px 6px rgba(20,70,48,.05);
 }
 *{box-sizing:border-box}
 html{scroll-behavior:smooth}
 body{
   margin:0;min-height:100vh;color:var(--texto);
   font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
   background:
     radial-gradient(60rem 40rem at 92% -10%,rgba(255,217,184,.60),transparent 60%),
     radial-gradient(50rem 36rem at -8% 0%,rgba(168,224,190,.65),transparent 60%),
     radial-gradient(50rem 40rem at 50% 112%,rgba(150,215,200,.50),transparent 60%),
     linear-gradient(180deg,#f7fbf8 0%,#e9f4ed 100%);
   background-attachment:fixed;
 }
 /* ---------- Fondo decorativo ---------- */
 #fondo{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
 #fondo>svg{position:absolute;inset:0;width:100%;height:100%}
 .pata{fill:#2f9a6b;opacity:.10}
 .pata.c{fill:#e59a5a;opacity:.12}
 .blob{position:absolute;border-radius:50%;filter:blur(64px);opacity:.55;animation:flota 24s ease-in-out infinite alternate}
 .b1{width:400px;height:400px;left:-110px;top:22%;background:#a9e2c3}
 .b2{width:340px;height:340px;right:-90px;top:52%;background:#ffd9b8;animation-delay:-9s}
 .b3{width:280px;height:280px;left:45%;top:-90px;background:#c8ecdc;animation-delay:-15s}
 @keyframes flota{to{transform:translate(46px,-54px) scale(1.14)}}
 @keyframes sube{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
 main{position:relative;z-index:1;max-width:1120px;margin:0 auto;padding:38px 24px 56px}
 /* ---------- Cabecera ---------- */
 .cabecera{display:flex;align-items:center;gap:18px;margin-bottom:30px;animation:sube .5s both}
 .logo{flex:none;width:64px;height:64px;border-radius:20px;display:grid;place-items:center;
   background:linear-gradient(135deg,#2bab76,#115f44);box-shadow:0 12px 26px rgba(22,118,83,.32)}
 .logo svg{width:36px;height:36px;fill:#fff}
 h1{font-size:clamp(1.7rem,3vw,2.4rem);letter-spacing:-.04em;margin:0;font-weight:800;color:#163b2a;line-height:1.1}
 .sub{margin:6px 0 0;color:var(--suave);font-size:.98rem}
 h2{font-size:1.22rem;letter-spacing:-.02em;margin:0 0 8px;color:#214633}
 p{line-height:1.6}
 /* ---------- Tarjetas (efecto cristal) ---------- */
 .tarjeta{
   background:rgba(255,255,255,.80);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);
   border:1px solid rgba(255,255,255,.9);border-radius:22px;padding:28px;margin-bottom:22px;
   box-shadow:var(--sombra);animation:sube .55s both
 }
 #citas{animation-delay:.08s}
 /* ---------- Login ---------- */
 #login{max-width:450px;margin:26px auto 0;padding:36px 34px;text-align:left}
 .insignia{width:58px;height:58px;border-radius:18px;display:grid;place-items:center;margin-bottom:16px;
   background:linear-gradient(135deg,#e6f4ec,#cfeedd);box-shadow:inset 0 0 0 1px #cfe6d8}
 .insignia svg{width:30px;height:30px;fill:var(--verde)}
 .eyebrow{display:block;color:var(--verde);font-size:.76rem;font-weight:800;letter-spacing:.13em;text-transform:uppercase;margin-bottom:6px}
 .intro{color:var(--suave);font-size:.93rem;line-height:1.5;margin:4px 0 6px}
 label{display:block;margin:17px 0 7px;font-size:.87rem;font-weight:700;color:#355344}
 input,select{
   width:100%;min-height:46px;padding:11px 13px;border:1px solid #d6e3da;border-radius:12px;
   background:rgba(255,255,255,.9);color:var(--texto);font:inherit;transition:border-color .18s,box-shadow .18s,background .18s
 }
 input:hover,select:hover{border-color:#a3c9b1}
 input:focus,select:focus{outline:none;border-color:#3fa475;box-shadow:0 0 0 4px rgba(63,164,117,.15);background:#fff}
 .fila{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}
 button{
   margin-top:18px;padding:13px 22px;border:0;border-radius:12px;
   background:linear-gradient(135deg,#25a06f,#12694a);color:#fff;cursor:pointer;
   font:inherit;font-weight:700;box-shadow:0 8px 18px rgba(22,118,83,.26);
   transition:transform .16s,box-shadow .16s,filter .16s
 }
 button:hover{transform:translateY(-2px);filter:brightness(1.05);box-shadow:0 12px 24px rgba(22,118,83,.30)}
 button:active{transform:translateY(0)}
 button:disabled{opacity:.55;cursor:wait;transform:none}
 button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #8cc9ae;outline-offset:2px}
 #entrar{width:100%}
 #pagar{min-width:190px}
 #salir{background:#edf5ef;color:#286345;box-shadow:none;border:1px solid #d9eadf;padding:10px 16px}
 #salir:hover{background:#e0f0e6;box-shadow:none}
 /* ---------- Panel privado ---------- */
 #agendar>div:first-child{display:flex;align-items:center;justify-content:space-between;gap:12px;
   padding-bottom:19px;margin-bottom:22px;border-bottom:1px solid var(--borde)}
 #hola{font-size:1.1rem;font-weight:800;color:#1f5238}
 #hola::before{content:"👋";margin-right:8px}
 #agendar h2,#citas h2{display:flex;align-items:center;gap:10px}
 #agendar h2::before,#citas h2::before{display:grid;place-items:center;width:32px;height:32px;
   border-radius:10px;background:linear-gradient(135deg,#e6f4ec,#cfeedd);color:var(--verde);font-size:1.1rem}
 #agendar h2::before{content:"＋"}
 #citas h2::before{content:"▤";font-size:1rem}
 small{display:block;color:var(--suave);line-height:1.55;margin-top:10px}
 #total{display:inline-block;margin:20px 0 0;padding:12px 18px;border-radius:14px;
   background:linear-gradient(135deg,#eef9f2,#e1f4e9);color:#156240;font-size:1.1rem;font-weight:800;
   box-shadow:inset 0 0 0 1px #cfe8d9}
 #total:empty{display:none}
 /* ---------- Tabla ---------- */
 .tabla{overflow-x:auto;border:1px solid var(--borde);border-radius:14px;margin-top:17px;background:#fff}
 table{width:100%;border-collapse:collapse;min-width:700px}
 th,td{padding:14px 14px;text-align:left;border-bottom:1px solid #edf2ee;font-size:.9rem}
 th{background:#f1f8f3;color:#46614f;font-size:.74rem;text-transform:uppercase;letter-spacing:.06em}
 tbody tr{transition:background .15s}
 tbody tr:hover{background:#f6fbf8}
 tbody tr:last-child td{border-bottom:0}
 .chip{display:inline-block;padding:4px 12px;border-radius:999px;font-size:.78rem;font-weight:700;
   text-transform:capitalize;background:#eef2ef;color:#4b5f54}
 .chip.pendiente,.chip.porpagar{background:#fff3dc;color:#99600a}
 .chip.realizada,.chip.pagado{background:#dff5e8;color:#1b7a4c}
 .chip.cancelada{background:#fde8e8;color:#b03a3a}
 /* ---------- Mensajes ---------- */
 .error{color:#b42335;min-height:1.2em;font-size:.9rem;font-weight:600}
 .ok{color:#16764e;min-height:1.2em;font-weight:700;background:#e9f7ee;border-radius:12px;padding:10px 14px}
 .ok:empty{display:none}
 .oculto{display:none!important}
 #sinmascotas{padding:15px;border-radius:12px;background:#fff6e2;color:#7d581a}
 #vacio{padding:24px;text-align:center;color:var(--suave);background:rgba(248,251,249,.9);border-radius:12px}
 #act{text-align:right;font-size:.78rem}
 .pie{text-align:center;color:#7d9185;font-size:.8rem;margin-top:8px}
 @media(max-width:700px){
   main{padding:26px 15px 40px}
   .tarjeta{padding:20px;border-radius:18px}
   #login{margin:18px auto 0;padding:26px 22px}
   .fila{grid-template-columns:1fr;gap:0}
   .logo{width:54px;height:54px;border-radius:17px}
   .logo svg{width:30px;height:30px}
   #agendar>div:first-child{align-items:flex-start}
 }
 @media(max-width:430px){
   #agendar>div:first-child{flex-direction:column}
   #salir{margin:0!important;float:none!important}
   button{width:100%}
 }
 @media(prefers-reduced-motion:reduce){
   .blob,.tarjeta,.cabecera{animation:none}
   button,input,select{transition:none}
 }
 .patron{margin:0 0 14px;font-size:.78rem;font-weight:600;line-height:1.55;color:#1f5fbf}
 </style></head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
 <symbol id="pata" viewBox="0 0 100 100">
  <ellipse cx="50" cy="68" rx="25" ry="20"/>
  <ellipse cx="19" cy="44" rx="9" ry="12" transform="rotate(-22 19 44)"/>
  <ellipse cx="38" cy="25" rx="9.5" ry="13" transform="rotate(-8 38 25)"/>
  <ellipse cx="62" cy="25" rx="9.5" ry="13" transform="rotate(8 62 25)"/>
  <ellipse cx="81" cy="44" rx="9" ry="12" transform="rotate(22 81 44)"/>
 </symbol></defs></svg>
<div id="fondo" aria-hidden="true">
 <div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div>
 <svg viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice">
  <use href="#pata" class="pata"   x="40"   y="60"  width="90"  height="90"  transform="rotate(-25 85 105)"/>
  <use href="#pata" class="pata c" x="1040" y="40"  width="110" height="110" transform="rotate(20 1095 95)"/>
  <use href="#pata" class="pata"   x="180"  y="330" width="70"  height="70"  transform="rotate(15 215 365)"/>
  <use href="#pata" class="pata c" x="900"  y="300" width="80"  height="80"  transform="rotate(-15 940 340)"/>
  <use href="#pata" class="pata c" x="60"   y="620" width="120" height="120" transform="rotate(-10 120 680)"/>
  <use href="#pata" class="pata"   x="1000" y="600" width="100" height="100" transform="rotate(25 1050 650)"/>
  <use href="#pata" class="pata"   x="520"  y="680" width="70"  height="70"  transform="rotate(-30 555 715)"/>
  <use href="#pata" class="pata c" x="620"  y="40"  width="60"  height="60"  transform="rotate(10 650 70)"/>
  <use href="#pata" class="pata"   x="330"  y="520" width="55"  height="55"  transform="rotate(20 358 548)"/>
  <use href="#pata" class="pata c" x="780"  y="520" width="60"  height="60"  transform="rotate(-20 810 550)"/>
 </svg>
</div>
<main>
<header class="cabecera">
 <div class="logo"><svg viewBox="0 0 100 100"><use href="#pata"/></svg></div>
 <div><h1>Portal del propietario</h1><p class="sub">Atención veterinaria, más cerca de ti</p></div>
</header>
<section id="login" class="tarjeta">
 <div class="insignia"><svg viewBox="0 0 100 100"><use href="#pata"/></svg></div>
 <span class="eyebrow">Bienvenido al portal</span>
 <h2>Ingresa a tu cuenta</h2>
 <p class="patron">● Patrón Proxy — la sesión se valida en Proxy, nunca en el navegador</p>
 <p class="intro">Administra las citas y servicios de tus mascotas desde un solo lugar.</p>
 <label for="u">Usuario</label><input id="u" autocomplete="username">
 <label for="p">Contraseña</label><input id="p" type="password" autocomplete="current-password">
 <button id="entrar">Ingresar</button><p class="error" id="err" role="alert"></p>
</section>
<div id="privado" class="oculto">
<section id="agendar" class="tarjeta">
 <div><strong id="hola"></strong> <button id="salir" style="float:right;margin:0">Cerrar sesión</button></div>
 <h2>Agendar una cita</h2>
 <p class="patron">● Patrón Facade — FachadaVeterinaria expone una sola operación: agendarCitaCompleta<br>● Patrón Adapter — PasarelaPagoAdapter traduce al SDK de la pasarela (APIStripeSDK)<br>● Patrón Decorator — el cobro del servicio se envuelve con servicio extra y auditoría</p>
 <p id="sinmascotas" class="oculto">Aún no tiene mascotas registradas. Pida a recepción que las registre para poder agendar.</p>
 <div id="form">
  <div class="fila">
   <div><label for="mascota">Mascota</label><select id="mascota"></select></div>
   <div><label for="vet">Veterinario</label><select id="vet"></select></div>
  </div>
  <label for="serv">Servicio</label><select id="serv"></select>
  <label for="extra">Servicio adicional (opcional)</label><select id="extra"></select>
  <div class="fila">
   <div><label for="fecha">Fecha</label><input id="fecha" type="date"></div>
   <div><label for="hora">Hora</label><select id="hora"></select></div>
  </div>
  <label for="motivo">Motivo de la consulta</label><input id="motivo" maxlength="200">
  <label for="notas">Notas para el veterinario (opcional)</label><input id="notas" maxlength="300">
  <label for="tarjeta">Medio de pago</label>
  <select id="tarjeta">
   <option value="tok_test_ok">Tarjeta de prueba: aprobada</option>
   <option value="tok_test_declined">Tarjeta de prueba: rechazada</option>
   <option value="tok_test_nofunds">Tarjeta de prueba: fondos insuficientes</option>
   <option value="tok_test_timeout">Tarjeta de prueba: la pasarela no responde</option>
   <option value="efectivo">Efectivo: pago en la veterinaria</option>
  </select>
  <small>Modo de prueba: no se solicita ninguna tarjeta real. Con una pasarela real, su SDK tokeniza la tarjeta en el navegador y este sitio nunca recibe el número.</small>
  <small id="notaefectivo" class="oculto">Pagará en recepción al llegar a su cita. El horario queda reservado a su nombre; le pedimos llegar unos minutos antes.</small>
  <p id="total"></p>
  <button id="pagar">Pagar y agendar</button>
  <p class="error" id="errcita" role="alert"></p><p class="ok" id="okcita" role="status"></p>
 </div>
</section>
<section id="citas" class="tarjeta">
 <h2>Mis citas</h2>
 <p class="patron">● Patrón Proxy + Facade — el propietario sale de la sesión; solo ve sus citas</p>
 <div class="tabla"><table><thead><tr><th>Fecha</th><th>Hora</th><th>Mascota</th><th>Veterinario</th><th>Servicio</th><th>Estado</th><th>Pago</th></tr></thead>
 <tbody id="filas"></tbody></table></div>
 <p id="vacio" class="oculto">No tiene citas registradas.</p>
 <small id="act"></small>
</section>
</div>
<script>
let token=null, timer=null, precios={};
const $=id=>document.getElementById(id);
async function api(ruta,cuerpo){
  const o={headers:{}};
  if(cuerpo){o.method="POST";o.headers["Content-Type"]="application/json";o.body=JSON.stringify(cuerpo);}
  if(token)o.headers.Authorization="Bearer "+token;
  const r=await fetch(ruta,o); const d=await r.json().catch(()=>({}));
  if(!r.ok){const e=new Error(d.error||"Error del servidor");e.estado=r.status;throw e;}
  return d;
}
function mostrarLogin(msg){token=null;clearInterval(timer);$("privado").classList.add("oculto");
  $("login").classList.remove("oculto");$("err").textContent=msg||"";$("p").value="";}
function llenar(id,items){const s=$(id);s.replaceChildren();for(const [v,t] of items)s.appendChild(new Option(t,v));}
function dosd(n){return String(n).padStart(2,"0");}
async function cargarCatalogo(){
  const c=await api("/api/portal/catalogo");
  llenar("mascota",c.mascotas.map(m=>[m.id,m.nombre]));
  llenar("vet",c.veterinarios.map(v=>[v.id,v.nombre+(v.especialidad?" ("+v.especialidad+")":"")]));
  precios={};for(const s of c.servicios)precios[s.id]=s.precio;
  llenar("serv",c.servicios.map(s=>[s.id,s.nombre+" - $"+s.precio.toFixed(2)]));
  llenar("extra",[["","Ninguno"]].concat(c.servicios.map(s=>[s.id,s.nombre+" - $"+s.precio.toFixed(2)])));
  const h=c.horario,[hi,mi]=h.inicio.split(":").map(Number),[hf,mf]=h.fin.split(":").map(Number),horas=[];
  for(let m=hi*60+mi;m<hf*60+mf;m+=h.intervalo)horas.push([dosd(Math.floor(m/60))+":"+dosd(m%60),dosd(Math.floor(m/60))+":"+dosd(m%60)]);
  llenar("hora",horas);
  const hoy=new Date();$("fecha").min=hoy.getFullYear()+"-"+dosd(hoy.getMonth()+1)+"-"+dosd(hoy.getDate());
  const sin=c.mascotas.length===0;$("sinmascotas").classList.toggle("oculto",!sin);$("form").classList.toggle("oculto",sin);
  total();
}
function total(){const b=precios[$("serv").value],x=precios[$("extra").value]||0,p=b===undefined?undefined:b+x,ef=$("tarjeta").value==="efectivo";
  $("total").textContent=p===undefined?"":(ef?"Total a pagar en la veterinaria: $":"Total a pagar: $")+p.toFixed(2);
  $("pagar").textContent=ef?"Agendar cita":"Pagar y agendar";
  $("notaefectivo").classList.toggle("oculto",!ef);}
async function cargar(){
  try{
    const citas=await api("/api/portal/mis-citas"); const tb=$("filas"); tb.replaceChildren();
    for(const c of citas){const tr=document.createElement("tr");
      for(const k of ["fecha","hora","animal","veterinario","servicio","estado","pago"]){
        const td=document.createElement("td");
        if(k==="estado"||k==="pago"){const s=document.createElement("span");
          s.className="chip "+String(c[k]).toLowerCase().replace(/\s/g,"");s.textContent=c[k];td.appendChild(s);}
        else td.textContent=c[k];
        tr.appendChild(td);}
      tb.appendChild(tr);}
    $("vacio").classList.toggle("oculto",citas.length>0);
    $("act").textContent="Actualizado: "+new Date().toLocaleTimeString();
  }catch(e){if(e.estado===401)mostrarLogin("Su sesión terminó, ingrese de nuevo.");}
}
$("serv").onchange=total;$("extra").onchange=total;$("tarjeta").onchange=total;
$("entrar").onclick=async()=>{
  try{const r=await api("/api/portal/login",{usuario:$("u").value,password:$("p").value});
    token=r.token;$("hola").textContent="Hola, "+r.nombre;$("err").textContent="";
    $("login").classList.add("oculto");$("privado").classList.remove("oculto");
    $("errcita").textContent="";$("okcita").textContent="";
    await cargarCatalogo();await cargar();timer=setInterval(cargar,10000);
  }catch(e){$("err").textContent=e.message;}
};
$("pagar").onclick=async()=>{
  const b=$("pagar");b.disabled=true;$("errcita").textContent="";$("okcita").textContent="";
  try{
    const r=await api("/api/portal/citas",{animal_id:$("mascota").value,veterinario_id:$("vet").value,
      servicio_id:$("serv").value,extra_servicio_id:$("extra").value,notas:$("notas").value,fecha:$("fecha").value,hora:$("hora").value,
      motivo:$("motivo").value,token_pago:$("tarjeta").value});
    $("okcita").textContent=r.pago==="efectivo"
      ?"Cita agendada. Pagará $"+r.monto.toFixed(2)+" en efectivo al llegar a la veterinaria."
      :"Cita agendada y pagada ($"+r.monto.toFixed(2)+"). Comprobante: "+r.referencia;
    $("motivo").value="";$("notas").value="";await cargar();
  }catch(e){if(e.estado===401)mostrarLogin("Su sesión terminó, ingrese de nuevo.");else $("errcita").textContent=e.message;}
  finally{b.disabled=false;}
};
$("p").addEventListener("keydown",e=>{if(e.key==="Enter")$("entrar").click();});
$("salir").onclick=async()=>{try{await api("/api/portal/logout",{});}catch(e){}mostrarLogin("");};
</script>
<p class="pie">Veterinaria V4 · Portal del propietario</p></main></body></html>
"""


class ServidorPortal:
    """Servidor HTTP que corre en un hilo dentro de la aplicación de escritorio.
    Tiene su PROPIA conexión a la base (otro hilo); SQLite coordina el acceso entre ambas."""
    def __init__(self, ruta_bd=DB_ARCHIVO, host="127.0.0.1", puerto=8000, pasarela=None):
        self.db = BaseDatos.getInstancia(ruta_bd)       # PATRÓN: SINGLETON
        self.db.conectar()
        # PATRÓN: ADAPTER - el sistema solo conoce IPagador; el adaptador traduce al SDK del proveedor
        pagador = pasarela or PasarelaPagoAdapter(APIStripeSDK())
        self.pagador = pagador
        # PATRÓN: FACADE - la fachada coordina los subsistemas de citas, historial y pagos
        self.fachada = FachadaVeterinaria(
            CitasSubsistema(CitaDAO(self.db), AnimalDAO(self.db), ServicioDAO(self.db)),
            HistorialSubsistema(HistorialDAO(self.db)),
            PagosSubsistema(PagoDAO(self.db), pagador),
            CuentaWebDAO(self.db))
        # PATRÓN: PROXY - lo único que ve el servidor HTTP: exige sesión antes de llegar a la fachada
        self.portal = Proxy(self.fachada)
        self.clienteApp = ClienteApp(self.portal)       # cliente del Facade
        self.cliente = Client(self.portal)              # cliente del Proxy
        try:
            self.httpd = HTTPServer((host, puerto), self._crear_handler())
        except OSError:
            self.db.desconectar()
            raise
        self.hilo = None

    @property
    def url(self):
        host, puerto = self.httpd.server_address[:2]
        return f"http://{host}:{puerto}"

    def iniciar(self):
        self.hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.hilo.start()

    def detener(self):
        if self.hilo is not None:
            self.httpd.shutdown()
        self.httpd.server_close()
        self.db.desconectar()

    def _crear_handler(self):
        app, cliente = self.clienteApp, self.cliente

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _responder(self, estado, cuerpo, html=False):
                if html:
                    datos, tipo = cuerpo.encode("utf-8"), "text/html; charset=utf-8"
                else:
                    datos, tipo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8"), \
                                  "application/json; charset=utf-8"
                self.send_response(estado)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(datos)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if html:
                    self.send_header("X-Frame-Options", "DENY")
                    self.send_header("Content-Security-Policy",
                                     "default-src 'none'; script-src 'unsafe-inline'; "
                                     "style-src 'unsafe-inline'; connect-src 'self'")
                self.end_headers()
                self.wfile.write(datos)

            def _token(self):
                auth = self.headers.get("Authorization", "")
                return auth[7:] if auth.startswith("Bearer ") else None

            def _json(self):
                largo = int(self.headers.get("Content-Length") or 0)
                if largo > 10_000:
                    raise ErrorNegocio("Petición demasiado grande")
                try:
                    datos = json.loads(self.rfile.read(largo).decode("utf-8")) if largo else {}
                except (ValueError, UnicodeDecodeError):
                    raise ErrorNegocio("JSON inválido")
                if not isinstance(datos, dict):
                    raise ErrorNegocio("JSON inválido")
                return datos

            def _atender(self, accion):
                try:
                    accion()
                except ErrorSesion as e:
                    self._responder(401, {"error": str(e)})
                except ErrorPago as e:
                    self._responder(402, {"error": str(e)})
                except ErrorNegocio as e:
                    self._responder(400, {"error": str(e)})
                except sqlite3.Error:
                    self._responder(503, {"error": "Servicio no disponible, intente de nuevo"})
                except Exception:
                    self._responder(500, {"error": "Error interno del servidor"})

            def do_GET(self):
                def accion():
                    ruta = self.path.split("?")[0]
                    if ruta in ("/", "/index.html"):
                        self._responder(200, PAGINA_PORTAL, html=True)
                    elif ruta == "/api/portal/mis-citas":
                        self._responder(200, cliente.solicitarExpediente(self._token()))
                    elif ruta == "/api/portal/catalogo":
                        self._responder(200, app.enviarPeticionWeb("catalogo", self._token()))
                    else:
                        self._responder(404, {"error": "No encontrado"})
                self._atender(accion)

            def do_POST(self):
                def accion():
                    ruta = self.path.split("?")[0]
                    if ruta == "/api/portal/login":
                        d = self._json()
                        token, nombre = app.iniciarSesion(d.get("usuario"), d.get("password"))
                        self._responder(200, {"token": token, "nombre": nombre})
                    elif ruta == "/api/portal/citas":
                        self._responder(201, app.enviarPeticionWeb("agendarCitaCompleta", self._token(), self._json()))
                    elif ruta == "/api/portal/logout":
                        app.cerrarSesion(self._token())
                        self._responder(200, {"ok": True})
                    else:
                        self._responder(404, {"error": "No encontrado"})
                self._atender(accion)

        return Handler


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Portal web del propietario - Veterinaria V4")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--db", default=DB_ARCHIVO)
    args = ap.parse_args()
    try:
        servidor = ServidorPortal(args.db, args.host, args.puerto)
    except OSError as e:
        raise SystemExit(f"No se pudo iniciar el portal en {args.host}:{args.puerto}: {e}")
    print(f"Portal del propietario en {servidor.url}  (Ctrl+C para detener)")
    try:
        servidor.httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo portal...")
    finally:
        servidor.detener()


if __name__ == "__main__":
    main()
