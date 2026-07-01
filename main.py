# -*- coding: utf-8 -*-
"""
app_jne_async.py - Ultra rápido con Redis Cloud + Auto-refresh inteligente
"""

import streamlit as st
import pandas as pd
import asyncio
import aiohttp
import time
import json
import redis
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

try:
    from datos import expedientes
except ImportError:
    st.error("🚨 No se encontró el archivo 'datos.py'")
    st.stop()

# ==========================================
# CONFIGURACIÓN ULTRA RÁPIDA
# ==========================================
API_URL = "https://apiplataformaelectoral3.jne.gob.pe/api/v1/expediente/detalle?CodExpedienteExt={}"

CONFIG = {
    'semaphore_limit': 20,  # Más concurrente
    'request_timeout': 8,
    'max_retries': 2,
    'retry_delay': 0.5,
    'aiohttp_limit': 200,
    'aiohttp_limit_per_host': 50,
    'redis_ttl': 7200,  # 2 horas
    'refresh_interval': 300,  # 5 minutos
    'max_requests_per_hour': 120,
    'cooldown_seconds': 60,
}

# ==========================================
# REDIS CLOUD CON CACHE
# ==========================================
@st.cache_resource
def init_redis():
    try:
        return redis.Redis(
            host=st.secrets["redis"]["host"],
            port=st.secrets["redis"]["port"],
            password=st.secrets["redis"]["password"],
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
            retry_on_timeout=True
        )
    except:
        return None

redis_client = init_redis()

# ==========================================
# RATE LIMITER
# ==========================================
class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    def can_request(self):
        now = time.time()
        self.requests = [t for t in self.requests if t > now - self.time_window]
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        return False

rate_limiter = RateLimiter(
    max_requests=CONFIG['max_requests_per_hour'],
    time_window=3600
)

# ==========================================
# FUNCIÓN PRINCIPAL ULTRA RÁPIDA
# ==========================================
@st.cache_data(ttl=CONFIG['redis_ttl'])
def get_cached_resultados():
    """Obtiene resultados con caché de Streamlit + Redis"""
    
    # Intentar obtener de Redis primero
    if redis_client:
        try:
            cached = redis_client.get('todos_resultados')
            if cached:
                return json.loads(cached)
        except:
            pass
    
    # Consultar API
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    resultados = loop.run_until_complete(consultar_todos_expedientes_async(expedientes))
    loop.close()
    
    # Guardar en Redis
    if redis_client and resultados:
        try:
            redis_client.setex('todos_resultados', CONFIG['redis_ttl'], json.dumps(resultados))
        except:
            pass
    
    return resultados

async def fetch_expediente_rapido(session, item, semaphore):
    """Versión ultra rápida con Redis por expediente"""
    expediente = item["expediente"]
    codigo_api = f"ERM.2026{expediente}"
    cache_key = f"exp:{codigo_api}"
    
    # Check Redis individual
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except:
            pass
    
    # Consultar API
    for attempt in range(CONFIG['max_retries'] + 1):
        try:
            async with semaphore:
                async with session.get(
                    API_URL.format(codigo_api),
                    timeout=aiohttp.ClientTimeout(total=CONFIG['request_timeout'])
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        estado = data.get("datoGeneral", {}).get("estadoLista", "").strip().upper()
                        
                        pron = None
                        for x in data.get("expedienteActuado", []):
                            if x.get("txTipoExpediente") == "PRONUNCIAMIENTO":
                                pron = x
                                break
                        
                        resultado = {
                            "Expediente": expediente,
                            "Entidad": item["entidad"],
                            "Estado Lista": estado,
                            "Ruta Documento": pron.get("txRutaDocumento", "") if pron else "",
                            "Fecha Publicación": pron.get("txFechaPublicacion", "") if pron else "",
                        }
                        
                        # Guardar en Redis
                        if redis_client:
                            try:
                                redis_client.setex(cache_key, CONFIG['redis_ttl'], json.dumps(resultado))
                            except:
                                pass
                        
                        return resultado
                        
        except:
            if attempt < CONFIG['max_retries']:
                await asyncio.sleep(CONFIG['retry_delay'] * (attempt + 1))
            else:
                break
    
    return {
        "Expediente": expediente,
        "Entidad": item["entidad"],
        "Estado Lista": "ERROR",
        "Ruta Documento": "",
        "Fecha Publicación": "",
    }

async def consultar_todos_expedientes_async(expedientes_a_consultar):
    """Orquesta consultas ultra rápidas"""
    semaphore = asyncio.Semaphore(CONFIG['semaphore_limit'])
    connector = aiohttp.TCPConnector(
        limit=CONFIG['aiohttp_limit'],
        limit_per_host=CONFIG['aiohttp_limit_per_host'],
        ttl_dns_cache=300,
        enable_cleanup_closed=True
    )
    timeout = aiohttp.ClientTimeout(total=CONFIG['request_timeout'])
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = [fetch_expediente_rapido(session, item, semaphore) for item in expedientes_a_consultar]
        resultados = await asyncio.gather(*tasks)
    
    return resultados

# ==========================================
# FUNCIONES DE UI
# ==========================================
def clasificar_expedientes(resultados):
    admitidos, inadmisibles, recibidos, errores = [], [], [], []
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

def mostrar_tabla(datos):
    if not datos:
        st.caption("📭 Sin resultados")
        return
    df = pd.DataFrame(datos)
    df.index = range(1, len(df) + 1)
    column_config = {}
    if "Ruta Documento" in df.columns:
        column_config["Ruta Documento"] = st.column_config.LinkColumn(
            "Ruta Documento",
            display_text="📄 Abrir"
        )
    st.dataframe(df, column_config=column_config, width='stretch')

# ==========================================
# INTERFAZ STREAMLIT
# ==========================================
st.set_page_config(
    page_title="JNE - Expedientes",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS Ultra Rápido
st.markdown("""
    <style>
    .stButton button { 
        font-weight: 600 !important;
        transition: all 0.2s !important;
    }
    .stMetric { background-color: #f8f9fa; border-radius: 10px; padding: 10px; }
    </style>
""", unsafe_allow_html=True)

# Estado
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = None
if 'resultados' not in st.session_state:
    st.session_state.resultados = None
# Auto-refresh inteligente

def should_refresh():
    if st.session_state.resultados is None:
        return True
    if st.session_state.last_refresh is None:
        return True
    elapsed = (datetime.now() - st.session_state.last_refresh).total_seconds()
    return elapsed > CONFIG['refresh_interval']

# Carga ultra rápida
if should_refresh() and rate_limiter.can_request():
    with st.spinner("⚡ Consultando 40 expedientes...Por favor, espere 🙏"):
        start = time.time()
        st.session_state.resultados = get_cached_resultados()
        st.session_state.last_refresh = datetime.now()
        elapsed = time.time() - start
        
        if elapsed < 2:
            st.balloons()
        # st.text(f"✅ ¡Listo! {elapsed:.1f}s")

# Mostrar resultados
if st.session_state.resultados:
    resultados = st.session_state.resultados
    admitidos, inadmisibles, recibidos, errores = clasificar_expedientes(resultados)
    
    # Última actualización
    if st.session_state.last_refresh:
        from datetime import timezone, timedelta
        peru_offset = timezone(timedelta(hours=-5))
        hora_peru = st.session_state.last_refresh.astimezone(peru_offset)
        st.markdown(f"🕐 Actualizado: {hora_peru.strftime('%H:%M:%S')} | Total 40 expedientes")
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["✅ Admitidos "+str(len(admitidos)), "❌ Inadmisibles "+str(len(inadmisibles)), "📦 Recibidos "+str(len(recibidos))])
    with tab1:
        mostrar_tabla(admitidos)
    with tab2:
        mostrar_tabla(inadmisibles)
    with tab3:
        mostrar_tabla(recibidos)
