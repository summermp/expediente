# -*- coding: utf-8 -*-
"""
app_jne_async.py - Versión asíncrona de alto rendimiento y robustez para consultas al JNE.
Soluciona problemas de pérdida de datos, bloqueos de API y velocidad en Streamlit.
"""

import streamlit as st
import pandas as pd
import asyncio
import aiohttp
import time
from typing import List, Dict, Any, Optional

# --- ¡IMPORTANTE! ---
# Asegúrate de que tu archivo 'datos.py' esté en el mismo directorio
# y que contenga la lista 'expedientes' como en tu ejemplo original.
try:
    from datos import expedientes
except ImportError:
    st.error("🚨 No se encontró el archivo 'datos.py'. Asegúrate de que esté en la misma carpeta.")
    st.stop()

# ==========================================
# CONFIGURACIÓN
# ==========================================
API_URL = "https://apiplataformaelectoral3.jne.gob.pe/api/v1/expediente/detalle?CodExpedienteExt={}"

CONFIG = {
    # Control de concurrencia: ¡Clave para no saturar la API!
    # Empieza con 10-15 y ajusta si la API lo permite.
    'semaphore_limit': 15,
    'request_timeout': 10,  # Timeout en segundos
    'max_retries': 3,       # Reintentos por petición fallida
    'retry_delay': 1.5,     # Delay base entre reintentos (backoff exponencial)
    # Configuración aiohttp
    'aiohttp_limit': 100,   # Límite total de conexiones simultáneas del pool
    'aiohttp_limit_per_host': 30, # Conexiones simultáneas al mismo host (JNE)
}

# ==========================================
# FUNCIONES ASÍNCRONAS DEL CORE
# ==========================================

async def fetch_expediente(session: aiohttp.ClientSession, item: Dict[str, str], semaphore: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
    """
    Consulta un solo expediente a la API de forma asíncrona con control de concurrencia y reintentos.
    """
    expediente = item["expediente"]
    codigo_api = f"ERM.2026{expediente}"
    url = API_URL.format(codigo_api)
    entidad = item["entidad"]

    for attempt in range(CONFIG['max_retries'] + 1):
        try:
            # El semáforo controla cuántas peticiones vuelan al mismo tiempo
            async with semaphore:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=CONFIG['request_timeout'])) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extraer datos
                        estado = (
                            data.get("datoGeneral", {})
                            .get("estadoLista", "")
                            .strip()
                            .upper()
                        )

                        # Buscar pronunciamiento
                        pron = None
                        for x in data.get("expedienteActuado", []):
                            if x.get("txTipoExpediente") == "PRONUNCIAMIENTO":
                                pron = x
                                break

                        return {
                            "Expediente": expediente,
                            "Entidad": entidad,
                            "Estado Lista": estado,
                            "Ruta Documento": pron.get("txRutaDocumento", "") if pron else "",
                            "Fecha Publicación": pron.get("txFechaPublicacion", "") if pron else "",
                        }
                    elif response.status == 429:  # Too Many Requests
                        # Esperar un poco más si nos están rate-limitando
                        await asyncio.sleep(CONFIG['retry_delay'] * (2 ** attempt))
                        continue
                    else:
                        # Para otros errores (4xx, 5xx), reintentamos si quedan intentos
                        if attempt < CONFIG['max_retries']:
                            await asyncio.sleep(CONFIG['retry_delay'] * (attempt + 1))
                            continue
                        else:
                            break

        except asyncio.TimeoutError:
            if attempt < CONFIG['max_retries']:
                await asyncio.sleep(CONFIG['retry_delay'] * (attempt + 1))
                continue
            else:
                break
        except Exception:
            if attempt < CONFIG['max_retries']:
                await asyncio.sleep(CONFIG['retry_delay'] * (attempt + 1))
                continue
            else:
                break

    # Si llegamos aquí, agotamos los reintentos o fue un error irrecuperable
    return {
        "Expediente": expediente,
        "Entidad": entidad,
        "Estado Lista": "ERROR",
        "Ruta Documento": "",
        "Fecha Publicación": "",
    }

async def consultar_todos_expedientes_async(expedientes_a_consultar: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Orquesta todas las consultas asíncronas con un pool de conexiones persistente.
    """
    semaphore = asyncio.Semaphore(CONFIG['semaphore_limit'])
    connector = aiohttp.TCPConnector(limit=CONFIG['aiohttp_limit'], limit_per_host=CONFIG['aiohttp_limit_per_host'])
    timeout = aiohttp.ClientTimeout(total=CONFIG['request_timeout'])

    resultados = []

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [
            fetch_expediente(session, item, semaphore)
            for item in expedientes_a_consultar
        ]
        
        # Ejecutar las tareas concurrentemente y recoger los resultados
        # Usamos asyncio.as_completed para mostrar progreso (opcional pero bueno)
        for coro in asyncio.as_completed(tasks):
            resultado = await coro
            resultados.append(resultado)
            
    return resultados

# ==========================================
# FUNCIONES DE CLASIFICACIÓN E INTERFAZ
# ==========================================

def clasificar_expedientes(resultados):
    """Clasifica los resultados (síncrono, muy rápido)"""
    admitidos = []
    inadmisibles = []
    recibidos = []
    errores = []
    for item in resultados:
        estado = item["Estado Lista"]
        if estado.startswith("ERROR"):
            errores.append(item)
        elif "ADMIT" in estado:
            admitidos.append(item)
        elif "INADM" in estado:
            inadmisibles.append(item)
        else:
            recibidos.append(item)
    return admitidos, inadmisibles, recibidos, errores

@st.cache_data(ttl=600)
def convertir_a_dataframe(datos):
    """Caché para evitar recrear DataFrames idénticos en cada rerun."""
    if not datos:
        return pd.DataFrame()
    df = pd.DataFrame(datos)
    df.index = range(1, len(df) + 1)
    return df

def mostrar_tabla(datos, titulo):
    if not datos:
        st.caption("📭 Sin resultados")
        return
    df = convertir_a_dataframe(datos)
    column_config = {}
    if "Ruta Documento" in df.columns:
        column_config["Ruta Documento"] = st.column_config.LinkColumn(
            "Ruta Documento",
            display_text="📄 Abrir"
        )
    st.dataframe(df, column_config=column_config, width='stretch')

# ==========================================
# INTERFAZ GRÁFICA DE STREAMLIT
# ==========================================

st.set_page_config(
    page_title="JNE - Expedientes (Async)",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    div[data-testid="metric-container"] {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
    }
    .stButton button {
        transition: all 0.3s ease !important;
        font-weight: 600 !important;
    }
    .stButton button:hover {
        transform: scale(1.02);
    }
    </style>
""", unsafe_allow_html=True)

# Inicializar estado de sesión
if 'procesando' not in st.session_state:
    st.session_state.procesando = False
if 'resultados' not in st.session_state:
    st.session_state.resultados = None

# Layout del botón
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    consultar_btn = st.button(
        "🔍 CONSULTAR EXPEDIENTES",
        width='stretch',
        type="primary",
        disabled=st.session_state.procesando
    )

# Lógica de consulta
if consultar_btn and not st.session_state.procesando:
    st.session_state.procesando = True
    st.session_state.resultados = None
    # Forzar rerun para mostrar el estado 'procesando'
    st.rerun()

# Muestra spinner y procesa si está en estado 'procesando'
if st.session_state.procesando:
    with st.spinner("⏳ Realizando consultas asíncronas... Por favor, espere."):
        start_time = time.time()
        try:
            # Crear un nuevo event loop para Streamlit
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            resultados_async = loop.run_until_complete(
                consultar_todos_expedientes_async(expedientes)
            )
            loop.close()

            st.session_state.resultados = resultados_async
            elapsed_time = time.time() - start_time
            st.success(f"✅ ¡Consulta completada en {elapsed_time:.2f} segundos!")
        except Exception as e:
            st.error(f"💥 Error fatal durante la consulta: {e}")
            st.session_state.resultados = None
        finally:
            st.session_state.procesando = False
            st.rerun()

# Mostrar resultados si existen
if st.session_state.resultados:
    resultados = st.session_state.resultados
    admitidos, inadmisibles, recibidos, errores = clasificar_expedientes(resultados)

    # Métricas
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📊 Total", len(resultados))
    col2.metric("✅ Admitidos", len(admitidos))
    col3.metric("❌ Inadmisibles", len(inadmisibles))
    col4.metric("📦 Recibidos", len(recibidos))
    
    if errores:
        st.warning(f"⚠️ {len(errores)} consultas resultaron en error después de múltiples intentos.")

    # Tabs con resultados
    tab1, tab2, tab3 = st.tabs(["✅ Admitidos", "❌ Inadmisibles", "📦 Recibidos"])
    with tab1:
        mostrar_tabla(admitidos, "✅ Admitidos")
    with tab2:
        mostrar_tabla(inadmisibles, "❌ Inadmisibles")
    with tab3:
        mostrar_tabla(recibidos, "📦 Recibidos")
