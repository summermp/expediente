import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from datos import expedientes
import time
import threading
from queue import Queue
from collections import defaultdict

# ==========================================
# CONFIGURACIÓN OPTIMIZADA PARA MÁXIMA VELOCIDAD
# ==========================================

API_URL = "https://apiplataformaelectoral3.jne.gob.pe/api/v1/expediente/detalle?CodExpedienteExt={}"

# CONFIGURACIÓN ULTRA-RÁPIDA
CONFIG = {
    'max_workers': 80,          # Aumentado para más paralelismo
    'min_workers': 20,          # Mayor mínimo
    'timeout': 6,               # Reducido para mayor velocidad
    'retries': 2,               
    'batch_size': 30,           # Lotes más grandes
    'pool_size': 150,           # Pool más grande
    'backoff_factor': 0.2,      # Backoff más rápido
    'keep_alive': True,
    'compression': True,
    'prefetch': True            # Nuevo: precarga de conexiones
}

# ==========================================
# POOL DE CONEXIONES ULTRA-OPTIMIZADO
# ==========================================

class ConnectionPool:
    """Pool de conexiones con balanceo inteligente y precarga"""
    
    def __init__(self):
        self.sessions = []
        self.current = 0
        self.lock = threading.Lock()
        
        # Crear más sesiones para mejor balanceo
        num_sessions = 8  # Aumentado de 4 a 8
        for i in range(num_sessions):
            session = self._create_session()
            self.sessions.append(session)
    
    def _create_session(self):
        """Crear sesión ultra-optimizada"""
        session = requests.Session()
        
        # Configuración agresiva para máxima velocidad
        retry = Retry(
            total=CONFIG['retries'],
            backoff_factor=CONFIG['backoff_factor'],
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False
        )
        
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=CONFIG['pool_size'],
            pool_maxsize=CONFIG['pool_size'],
            pool_block=False
        )
        
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Headers optimizados para máxima velocidad
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br' if CONFIG['compression'] else '',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Connection': 'keep-alive' if CONFIG['keep_alive'] else 'close',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })
        
        return session
    
    def get_session(self):
        """Obtener sesión con balanceo round-robin mejorado"""
        with self.lock:
            session = self.sessions[self.current]
            self.current = (self.current + 1) % len(self.sessions)
            return session

# ==========================================
# CONSULTA ULTRA-RÁPIDA
# ==========================================

def consultar_api_optimizada(item, pool):
    """Consulta ultra-rápida con pipeline"""
    expediente = item["expediente"]
    codigo_api = f"ERM.2026{expediente}"
    
    session = pool.get_session()
    
    try:
        r = session.get(
            API_URL.format(codigo_api),
            timeout=CONFIG['timeout']
        )
        
        if r.status_code == 200:
            try:
                data = r.json()
                
                # Extraer datos de forma ultra-rápida
                estado = (
                    data.get("datoGeneral", {})
                    .get("estadoLista", "")
                    .strip()
                    .upper()
                )
                
                # Buscar pronunciamiento optimizado
                pron = None
                for x in data.get("expedienteActuado", []):
                    if x.get("txTipoExpediente") == "PRONUNCIAMIENTO":
                        pron = x
                        break
                
                return {
                    "Expediente": expediente,
                    "Entidad": item["entidad"],
                    "Estado Lista": estado,
                    "Ruta Documento": pron.get("txRutaDocumento", "") if pron else "",
                    "Fecha Publicación": pron.get("txFechaPublicacion", "") if pron else "",
                }
            except:
                pass
    
    except:
        pass
    
    # Respuesta rápida en error
    return {
        "Expediente": expediente,
        "Entidad": item["entidad"],
        "Estado Lista": "ERROR",
        "Ruta Documento": "",
        "Fecha Publicación": "",
    }

# ==========================================
# PROCESAMIENTO ULTRA-RÁPIDO CON PIPELINE
# ==========================================

def consultar_todos_expedientes():
    """Procesamiento con pipeline ultra-rápido"""
    total = len(expedientes)
    resultados = []
    
    # Determinar workers óptimos
    workers = min(CONFIG['max_workers'], max(CONFIG['min_workers'], total))
    
    # Crear pool de conexiones
    pool = ConnectionPool()
    
    # UI de progreso (solo en hilo principal)
    barra = st.progress(0)
    texto = st.empty()
    texto.text(f"⚡ Consultando 0/{total} expedientes")
    
    start_time = time.time()
    
    # Usar pipeline con todos los workers
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Enviar todas las tareas de una vez (más rápido)
        futures = {
            executor.submit(consultar_api_optimizada, item, pool): item 
            for item in expedientes
        }
        
        # Recolectar resultados a medida que llegan
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result(timeout=CONFIG['timeout'] + 1)
                resultados.append(result)
            except:
                # Si falla, agregar resultado de error
                item = futures[future]
                resultados.append({
                    "Expediente": item["expediente"],
                    "Entidad": item["entidad"],
                    "Estado Lista": "ERROR",
                    "Ruta Documento": "",
                    "Fecha Publicación": "",
                })
            
            # Actualizar progreso cada 2 resultados (más eficiente)
            if i % 2 == 0 or i == total:
                barra.progress(i / total)
                texto.text(f"⚡ Consultando {i}/{total} expedientes")
    
    # Estadísticas
    elapsed = time.time() - start_time
    speed = total / elapsed if elapsed > 0 else 0
    
    # Limpiar UI
    barra.empty()
    texto.empty()
    
    # st.success(f"✅ {total} expedientes en {elapsed:.1f}s ({speed:.1f} req/seg)")    
    return resultados

# ==========================================
# CLASIFICACIÓN ULTRARÁPIDA
# ==========================================

def clasificar_expedientes(resultados):
    """Clasificación optimizada con comprensión de listas"""
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

# ==========================================
# TABLAS CON CACHÉ Y RENDERIZADO RÁPIDO
# ==========================================

@st.cache_data(ttl=300)
def convertir_a_dataframe(datos):
    """Convertir a DataFrame con caché extendido"""
    if not datos:
        return pd.DataFrame()
    
    df = pd.DataFrame(datos)
    df.index = range(1, len(df) + 1)
    return df

def mostrar_tabla(datos, titulo, height=None):
    """Mostrar tabla optimizada"""
    
    if not datos:
        st.caption("📭 Sin resultados")
        return
    
    # DataFrame con caché
    df = convertir_a_dataframe(datos)
    
    # Configurar columnas solo si existen
    column_config = {}
    if "Ruta Documento" in df.columns:
        column_config["Ruta Documento"] = st.column_config.LinkColumn(
            "Ruta Documento",
            display_text="📄 Abrir"
        )
    
    # Mostrar dataframe con altura dinámica
    st.dataframe(
        df,
        column_config=column_config,
        width='stretch'
    )

# ==========================================
# INTERFAZ OPTIMIZADA CON CSS
# ==========================================

# CSS para mejorar la UI y centrar elementos
st.markdown("""
    <style>
    /* Centrar tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
        justify-content: center;
    }
    
    .stTabs [data-baseweb="tab"] {
        font-size: 16px !important;
        padding: 8px 24px !important;
        border-radius: 8px !important;
        transition: all 0.2s ease;
    }
    
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background-color: #1F2937 !important;
        border-bottom: 3px solid #ff4b4b !important;
    }
    
    /* Mejorar métricas */
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        transition: all 0.3s ease;
    }
    
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    /* Botón mejorado */
    .stButton button {
        transition: all 0.3s ease !important;
        font-weight: 600 !important;
    }
    
    .stButton button:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(255, 75, 75, 0.3);
    }
    
    .stButton button:disabled {
        opacity: 0.7;
        transform: none !important;
    }
    
    /* Spinner centrado */
    div[data-testid="stSpinner"] {
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CONFIGURACIÓN DE PÁGINA
# ==========================================

st.set_page_config(
    page_title="JNE - Expedientes",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==========================================
# BOTÓN PRINCIPAL CENTRADO
# ==========================================

col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    # Estado de procesamiento
    if "procesando" not in st.session_state:
        st.session_state.procesando = False
    
    # Botón con auto-deshabilitado
    if st.button(
        "🔍 CONSULTAR EXPEDIENTES", 
        width='stretch', 
        type="secondary",
        disabled=st.session_state.procesando
    ):
        st.session_state.procesando = True
        st.session_state.pop("resultados", None)
        
        with st.spinner("Por favor, espere 🙏"):
            try:
                resultados = consultar_todos_expedientes()
                st.session_state["resultados"] = resultados
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
            finally:
                st.session_state.procesando = False
        
        st.rerun()

# ==========================================
# MOSTRAR RESULTADOS
# ==========================================

if "resultados" in st.session_state:
    resultados = st.session_state["resultados"]
    
    # Clasificar resultados
    admitidos, inadmisibles, recibidos, errores = clasificar_expedientes(resultados)
    
    # Tabs centrados con CSS
    tabs = st.tabs([
        "✅ Admitidos",
        "❌ Inadmisibles", 
        "📦 Recibidos"
    ])
    
    with tabs[0]:
        mostrar_tabla(admitidos, "✅ Admitidos")
    
    with tabs[1]:
        mostrar_tabla(inadmisibles, "❌ Inadmisibles")
    
    with tabs[2]:
        mostrar_tabla(recibidos, "📦 Recibidos")
    
    
    # ==========================================
    # MÉTRICAS DE RESUMEN CENTRADAS
    # ==========================================
    #     
    # Centrar métricas
    col1, col2, col3 = st.columns([2, 4, 2])
    
    with col2:
        m1, m2, m3, m4 = st.columns(4)
        
        m1.metric("📊 Total", len(resultados))
        m2.metric("✅ Admitidos", len(admitidos))
        m3.metric("❌ Inadm.", len(inadmisibles))
        m4.metric("📦 Recibidos", len(recibidos))
