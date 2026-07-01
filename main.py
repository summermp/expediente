# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import requests
import time
import json
import redis
from datetime import datetime, timezone, timedelta

# ==========================================
# CONFIGURACIÓN
# ==========================================
CONFIG = {
    'redis_ttl': 7200,
    'refresh_interval': 300,
}

API_URL = st.secrets["API_URL"]

# ==========================================
# REDIS CLOUD
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
# CONSULTA AL WORKER CON CACHE
# ==========================================
@st.cache_data(ttl=CONFIG['redis_ttl'])
def get_resultados():
    # 1. Intentar Redis
    if redis_client:
        try:
            cached = redis_client.get('todos_resultados')
            if cached:
                return json.loads(cached)
        except:
            pass
    
    # 2. Consultar Worker (solo 1 request)
    try:
        response = requests.get(API_URL, timeout=30)
        if response.status_code == 200:
            data = response.json()
            resultados = list(data.values())
            
            # 3. Guardar en Redis
            if redis_client and resultados:
                try:
                    redis_client.set('todos_resultados', CONFIG['redis_ttl'], json.dumps(resultados))
                except:
                    pass
            
            return resultados
        else:
            return []
    except:
        return []

# ==========================================
# FUNCIONES UI
# ==========================================
def clasificar_expedientes(resultados):
    admitidos, inadmisibles, recibidos, errores = [], [], [], []
    for item in resultados:
        estado = item.get("Estado", "")
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
    if "RutaDocumento" in df.columns:
        column_config["RutaDocumento"] = st.column_config.LinkColumn(
            "Ruta Documento",
            display_text="📄 Abrir"
        )
    st.dataframe(df, column_config=column_config, width='stretch')

# ==========================================
# INTERFAZ
# ==========================================
st.set_page_config(
    page_title="JNE - Expedientes",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = None
if 'resultados' not in st.session_state:
    st.session_state.resultados = None

def should_refresh():
    if st.session_state.resultados is None:
        return True
    if st.session_state.last_refresh is None:
        return True
    elapsed = (datetime.now() - st.session_state.last_refresh).total_seconds()
    return elapsed > CONFIG['refresh_interval']

if should_refresh():
    with st.spinner("⚡ Cargando expedientes..."):
        start = time.time()
        st.session_state.resultados = get_resultados()
        st.session_state.last_refresh = datetime.now()
        elapsed = time.time() - start
        if elapsed < 2:
            st.balloons()
        else:
            st.snow()

if st.session_state.resultados:
    resultados = st.session_state.resultados
    admitidos, inadmisibles, recibidos, errores = clasificar_expedientes(resultados)
    
    if st.session_state.last_refresh:
        peru_offset = timezone(timedelta(hours=-5))
        hora_peru = st.session_state.last_refresh.astimezone(peru_offset)
        st.markdown(f"🕐 Actualizado: {hora_peru.strftime('%H:%M:%S')} | Total 40 expedientes")
    
    tab1, tab2, tab3 = st.tabs([
        f"✅ Admitidos ({len(admitidos)})",
        f"❌ Inadmisibles ({len(inadmisibles)})",
        f"📦 Recibidos ({len(recibidos)})"
    ])
    
    with tab1:
        mostrar_tabla(admitidos)
    with tab2:
        mostrar_tabla(inadmisibles)
    with tab3:
        mostrar_tabla(recibidos)
