import streamlit as __st
from supabase import create_client as __create_client, Client as __Client
import easyocr as __easyocr
import numpy as __np
from PIL import Image as __Image, ImageOps as __ImageOps
import io
import re

# Configuración inicial de la página
__st.set_page_config(
    page_title="Control Vehicular - ACAPOMIL",
    layout="centered"
)

__st.title("Control de Acceso Vehicular - Regimiento")
__st.write("Sistema de lectura de patentes mediante OCR y verificación en base de datos.")

# Cargar credenciales desde los secretos de Streamlit
try:
    __SUPABASE_URL = __st.secrets["supabase"]["url"]
    __SUPABASE_KEY = __st.secrets["supabase"]["key"]
except Exception as __e:
    __st.error("No se encontraron las credenciales de Supabase en secrets.toml.")
    __st.stop()

# Inicializar cliente de Supabase
@__st.cache_resource
def __init_supabase() -> __Client:
    return __create_client(__SUPABASE_URL, __SUPABASE_KEY)

__supabase: __Client = __init_supabase()

# Inicializar lector OCR en caché
@__st.cache_resource
def __init_ocr():
    return __easyocr.Reader(['es', 'en'], gpu=False)

__reader = __init_ocr()

# Función para consultar los datos del vehículo en Supabase
def __consultar_vehiculo(__patente: str):
    try:
        __response = __supabase.table("vehiculos").select("*").eq("patente", __patente).execute()
        if __response.data:
            return __response.data[0]
        return None
    except Exception as __e:
        __st.error(f"Error al consultar la base de datos: {__e}")
        return None

# Confusiones típicas del OCR entre letras y números
__A_LETRA = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
__A_NUMERO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "A": "4", "S": "5", "G": "6", "B": "8"}

# Genera variantes de la patente según el formato chileno: nuevo (LLLL00) y antiguo (LL0000)
def __variantes_patente(__patente: str):
    __variantes = [__patente]
    if len(__patente) == 6:
        for __letras in (4, 2):
            __corregida = "".join(
                __A_LETRA.get(__c, __c) if __i < __letras else __A_NUMERO.get(__c, __c)
                for __i, __c in enumerate(__patente)
            )
            if __corregida not in __variantes:
                __variantes.append(__corregida)
    return __variantes

# Busca la patente en los textos del OCR, aunque venga separada en varios trozos (ej: "VHGZ" y "72")
def __extraer_patente(__resultados):
    # Dejar solo letras y números (quita espacios, guiones y puntos) y descartar la palabra CHILE
    __limpio = lambda __t: "".join(__c for __c in __t.upper() if __c.isalnum())
    __trozos = [__r for __r in __resultados if __limpio(__r[1]) not in ("", "CHILE")]
    # Ordenar de izquierda a derecha y unir todos los textos
    __trozos.sort(key=lambda __r: __r[0][0][0])
    __unido = "".join(__limpio(__r[1]) for __r in __trozos)
    # Recorrer el texto unido buscando 6 caracteres con formato de patente
    for __i in range(len(__unido) - 5):
        for __variante in __variantes_patente(__unido[__i:__i + 6]):
            if re.fullmatch(r"[A-Z]{4}[0-9]{2}|[A-Z]{2}[0-9]{4}", __variante):
                return __unido[__i:__i + 6]
    # Si no hay formato de patente, usar el texto con mayor confianza
    return __limpio(max(__resultados, key=lambda x: x[2])[1])

# --- SECCIÓN 1: CAPTURA Y OCR ---
__st.subheader("1. Captura de Placa Patente")
# En iPhone, "Subir foto" permite usar la cámara trasera en resolución completa
__origen = __st.radio("Origen de la imagen:", ["Cámara", "Subir foto"], horizontal=True)
if __origen == "Cámara":
    __imagen_capturada = __st.camera_input("Fotografiar patente del vehículo")
else:
    __imagen_capturada = __st.file_uploader("Tomar o subir foto de la patente", type=["jpg", "jpeg", "png"])

__patente_detectada = ""

if __imagen_capturada is not None:
    __bytes_imagen = __imagen_capturada.getvalue()
    __imagen_pil = __Image.open(io.BytesIO(__bytes_imagen))
    # Respetar la orientación de las fotos del celular y reducir el tamaño para acelerar el OCR
    __imagen_pil = __ImageOps.exif_transpose(__imagen_pil).convert("RGB")
    __imagen_pil.thumbnail((1600, 1600))
    __imagen_np = __np.array(__imagen_pil)
    
    with __st.spinner("Procesando imagen con OCR..."):
        __resultados = __reader.readtext(__imagen_np)
        
    if __resultados:
        __patente_detectada = __extraer_patente(__resultados)
        __st.success(f"Patente detectada por OCR: **{__patente_detectada}**")
    else:
        __st.warning("No se logró detectar texto en la imagen. Ingrese la patente manualmente.")

__st.divider()

# --- SECCIÓN 2: CONSULTA Y VERIFICACIÓN ---
__st.subheader("2. Verificación de Datos Vehiculares")

__patente_busqueda = __st.text_input("Confirmar o ingresar patente:", value=__patente_detectada)

if __patente_busqueda.strip():
    __patente_limpia = "".join(__c for __c in __patente_busqueda.upper() if __c.isalnum())

    # Probar la lectura original y sus variantes corregidas hasta encontrar el vehículo
    __vehiculo_info = None
    for __variante in __variantes_patente(__patente_limpia):
        __vehiculo_info = __consultar_vehiculo(__variante)
        if __vehiculo_info:
            if __variante != __patente_limpia:
                __st.info(f"Lectura corregida: {__patente_limpia} → **{__variante}**")
            __patente_limpia = __variante
            break

    if __vehiculo_info:
        # Mostrar información detallada del vehículo
        if __vehiculo_info["autorizado"]:
            __st.success("ESTADO: VEHÍCULO AUTORIZADO")
        else:
            __st.error("ESTADO: VEHÍCULO NO AUTORIZADO / DENEGADO")
            
        __col1, __col2 = __st.columns(2)
        with __col1:
            __st.write(f"**Marca:** {__vehiculo_info['marca']}")
            __st.write(f"**Modelo:** {__vehiculo_info['modelo']}")
            __st.write(f"**Color:** {__vehiculo_info['color']}")
        with __col2:
            __st.write(f"**Propietario:** {__vehiculo_info['propietario']}")
            __st.write(f"**Unidad/Dependencia:** {__vehiculo_info['unidad']}")
            
        # Formulario para registrar el evento de acceso
        with __st.form("form_registro"):
            __tipo_movimiento = __st.selectbox("Seleccionar Movimiento:", ["ENTRADA", "SALIDA"])
            __btn_registrar = __st.form_submit_button("Confirmar y Registrar Movimiento")
            
            if __btn_registrar:
                try:
                    __supabase.table("registros_acceso").insert({
                        "patente": __patente_limpia,
                        "movimiento": __tipo_movimiento
                    }).execute()
                    __st.success(f"Movimiento de {__tipo_movimiento} registrado con éxito para {__patente_limpia}.")
                    __st.rerun()
                except Exception as __e:
                    __st.error(f"Error al guardar el registro: {__e}")
    else:
        __st.warning(f"La patente **{__patente_limpia}** no se encuentra registrada en la base de datos de la unidad.")

__st.divider()

# --- SECCIÓN 3: HISTORIAL DE REGISTROS ---
__st.subheader("3. Últimos Accesos Registrados")
try:
    __historial = __supabase.table("registros_acceso").select("*").order("id", desc=True).limit(5).execute().data
    if __historial:
        for __registro in __historial:
            __st.write(f"ID: {__registro['id']} | Patente: {__registro['patente']} | Movimiento: {__registro['movimiento']} | Fecha/Hora UTC: {__registro['fecha_hora']}")
    else:
        __st.info("Sin registros de accesos recientes.")
except Exception as __e:
    __st.error(f"Error al cargar el historial: {__e}")