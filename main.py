# -*- coding: utf-8 -*-
"""
Sistema JNE v5.0 - Máxima Eficiencia
- Redis como única fuente de verdad (sin st.cache_data duplicado)
- Pipeline Redis (MGET) para lecturas múltiples
- Heartbeat para renovar lock automáticamente
- wait_for_fresh_data basado en versión (last_update)
- Compresión solo para datos grandes
- DataFrames pre-creados y cacheados en Redis
"""
import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import gzip
import logging
import uuid
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple

try:
    import orjson
    def fast_dumps(obj): return orjson.dumps(obj)
    def fast_loads(data): return orjson.loads(data)
except ImportError:
    import json
    def fast_dumps(obj): return json.dumps(obj).encode()
    def fast_loads(data): return json.loads(data.decode() if isinstance(data, bytes) else data)

try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)  # Solo warnings y errores en producción

CONFIG = {
    'redis_ttl': 3600,
    'connect_timeout': 3,
    'read_timeout': 10,
    'max_retries': 2,
    'pool_connections': 8,
    'pool_maxsize': 8,
    'lock_expire': 15,
    'lock_heartbeat_interval': 5,  # Renovar lock cada 5s
    'circuit_breaker_ttl': 120,
    'max_api_requests': 2,
    'compression_threshold': 10240,  # Comprimir solo si > 10KB
}

_redis_client = None
_api_url = None
_script_run_id = str(uuid.uuid4())[:8]

def get_api_url():
    global _api_url
    if _api_url is None:
        try:
            _api_url = st.secrets.get("API_URL", "")
        except:
            _api_url = ""
    return _api_url

def get_redis_client():
    global _redis_client
    if _redis_client is None and redis is not None:
        try:
            _redis_client = redis.Redis(
                host=st.secrets["redis"]["host"],
                port=st.secrets["redis"]["port"],
                password=st.secrets["redis"]["password"],
                decode_responses=False,
                socket_timeout=2,
                socket_connect_timeout=2,
                health_check_interval=30
            )
            _redis_client.ping()
        except Exception as e:
            logger.error(f"Redis: {e}")
            _redis_client = None
    return _redis_client

@st.cache_resource
def get_http_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=CONFIG['max_retries'],
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=CONFIG['pool_connections'],
        pool_maxsize=CONFIG['pool_maxsize'],
        pool_block=True
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    })
    return session

# ==========================================
# REDIS HELPERS OPTIMIZADOS
# ==========================================
def redis_set(key: str, data: Any, ttl: int = CONFIG['redis_ttl']) -> bool:
    """Guardar con compresión inteligente (solo si es grande)"""
    client = get_redis_client()
    if not client:
        return False
    try:
        raw = fast_dumps(data)
        
        # Comprimir solo si supera el umbral
        if len(raw) > CONFIG['compression_threshold']:
            compressed = gzip.compress(raw, compresslevel=6)
            client.set(key, compressed, ex=ttl)
        else:
            client.set(key, raw, ex=ttl)
        
        return True
    except Exception as e:
        logger.error(f"Redis SET {key}: {e}")
        return False

def redis_get(key: str) -> Optional[Any]:
    """Leer con descompresión automática"""
    client = get_redis_client()
    if not client:
        return None
    try:
        data = client.get(key)
        if data is None:
            return None
        
        # Intentar descomprimir, si falla es que no estaba comprimido
        try:
            data = gzip.decompress(data)
        except:
            pass
        
        return fast_loads(data)
    except Exception as e:
        logger.error(f"Redis GET {key}: {e}")
        return None

# ⭐ PIPELINE para leer múltiples claves de una sola vez
def redis_mget(keys: List[str]) -> Dict[str, Any]:
    """Leer múltiples claves en una sola operación"""
    client = get_redis_client()
    if not client:
        return {}
    
    try:
        pipe = client.pipeline()
        for key in keys:
            pipe.get(key)
        results = pipe.execute()
        
        output = {}
        for key, data in zip(keys, results):
            if data is not None:
                try:
                    data = gzip.decompress(data)
                except:
                    pass
                output[key] = fast_loads(data)
        
        return output
    except Exception as e:
        logger.error(f"Redis MGET error: {e}")
        return {}

def redis_exists(key: str) -> bool:
    client = get_redis_client()
    if not client:
        return False
    try:
        return client.exists(key) == 1
    except:
        return False

def redis_set_nx(key: str, value: str, ttl: int = 60) -> bool:
    """SET NX atómico"""
    client = get_redis_client()
    if not client:
        return True
    try:
        return bool(client.set(key, value, nx=True, ex=ttl))
    except:
        return True

# ==========================================
# CIRCUIT BREAKER
# ==========================================
def is_circuit_open() -> bool:
    return redis_exists('circuit_breaker')

def open_circuit():
    client = get_redis_client()
    if client:
        client.set('circuit_breaker', '1', ex=CONFIG['circuit_breaker_ttl'])

def close_circuit():
    client = get_redis_client()
    if client:
        client.delete('circuit_breaker')

# ==========================================
# LOCK CON HEARTBEAT (RENOVACIÓN AUTOMÁTICA)
# ==========================================
def start_lock_heartbeat(lock_key: str, token: str, stop_event: threading.Event):
    """Renovar TTL del lock periódicamente mientras se usa"""
    client = get_redis_client()
    if not client:
        return
    
    while not stop_event.is_set():
        time.sleep(CONFIG['lock_heartbeat_interval'])
        
        # Renovar solo si el lock sigue siendo nuestro
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            result = client.eval(lua_script, 1, lock_key, token, CONFIG['lock_expire'])
            if result:
                logger.debug(f"Lock renovado: {token[:8]}")
        except:
            pass

def acquire_lock(lock_name="api_refresh", expire=15) -> Tuple[bool, str]:
    client = get_redis_client()
    if not client:
        return True, ""
    
    token = str(uuid.uuid4())
    lock_key = f"lock:{lock_name}"
    acquired = client.set(lock_key, token, nx=True, ex=expire)
    
    if acquired:
        logger.info(f"Lock adquirido: {token[:8]}")
        return True, token
    
    return False, ""

def release_lock(lock_name="api_refresh", token=""):
    client = get_redis_client()
    if not client or not token:
        return
    
    lock_key = f"lock:{lock_name}"
    lua_script = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """
    
    try:
        result = client.eval(lua_script, 1, lock_key, token)
        if result:
            logger.info(f"Lock liberado: {token[:8]}")
    except Exception as e:
        logger.error(f"Error liberando lock: {e}")

# ⭐ ESPERAR NUEVA VERSIÓN (basado en last_update, no solo existencia)
def wait_for_fresh_data(max_wait=15):
    """
    Esperar hasta que Redis tenga una NUEVA versión de los datos.
    Compara last_update antes y después.
    """
    client = get_redis_client()
    if not client:
        return
    
    # Obtener versión actual
    old_update = client.get('last_update')
    
    waited = 0
    poll_ms = 200
    
    while waited < max_wait:
        time.sleep(poll_ms / 1000)
        waited += poll_ms / 1000
        
        # Verificar si hay NUEVA versión
        new_update = client.get('last_update')
        
        if new_update and new_update != old_update:
            logger.info(f"Nueva versión detectada después de {waited:.1f}s")
            return
    
    logger.warning(f"Timeout esperando nueva versión ({max_wait}s)")

# ==========================================
# LIMITADOR DE CONSULTAS API
# ==========================================
def can_query_api() -> bool:
    client = get_redis_client()
    if not client:
        return True
    
    try:
        current = client.incr('api_request_count')
        client.expire('api_request_count', 1)
        return current <= CONFIG['max_api_requests']
    except:
        return True

# ==========================================
# EXTRACCIÓN Y CLASIFICACIÓN
# ==========================================
def extract_minimal_fields(item: Dict) -> Dict:
    return {
        "Expediente": item.get("Expediente", ""),
        "Entidad": item.get("Entidad", ""),
        "Estado": item.get("Estado", ""),
        "RutaDocumento": item.get("RutaDocumento", ""),
        "FechaPublicacion": item.get("FechaPublicacion", ""),
    }

def fetch_and_classify():
    """Consultar API y clasificar. Flag atómico evita duplicados."""
    operation_id = str(uuid.uuid4())
    
    if not redis_set_nx('fetch_in_progress', operation_id, ttl=30):
        logger.warning("fetch_and_classify ya está en progreso, ignorando...")
        return True
    
    try:
        api_url = get_api_url()
        if not api_url:
            return False
        
        if is_circuit_open():
            return True
        
        if not can_query_api():
            return True
        
        http_session = get_http_session()
        
        try:
            response = http_session.get(
                api_url,
                timeout=(CONFIG['connect_timeout'], CONFIG['read_timeout'])
            )
            
            if response.status_code == 200:
                data = response.json()
                raw_list = list(data.values()) if isinstance(data, dict) else data
                resultados = [extract_minimal_fields(item) for item in raw_list]
                
                # Clasificar
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
                
                # Ordenar por fecha descendente
                def sort_by_date(lista):
                    return sorted(
                        lista,
                        key=lambda x: x.get("FechaPublicacion", ""),
                        reverse=True
                    )
                
                admitidos = sort_by_date(admitidos)
                inadmisibles = sort_by_date(inadmisibles)
                recibidos = sort_by_date(recibidos)
                errores = sort_by_date(errores)
                
                # ⭐ Crear DataFrames UNA SOLA VEZ y cachearlos en Redis
                df_admitidos = pd.DataFrame(admitidos) if admitidos else pd.DataFrame()
                df_inadmisibles = pd.DataFrame(inadmisibles) if inadmisibles else pd.DataFrame()
                df_recibidos = pd.DataFrame(recibidos) if recibidos else pd.DataFrame()
                
                # Guardar en Redis
                now_iso = datetime.now(timezone(timedelta(hours=-5))).isoformat()
                
                redis_set('admitidos', admitidos)
                redis_set('inadmisibles', inadmisibles)
                redis_set('recibidos', recibidos)
                redis_set('errores', errores)
                redis_set('last_update', now_iso)
                
                close_circuit()
                logger.info(f"✅ {len(resultados)} expedientes")
                return True
            
            else:
                logger.error(f"API status: {response.status_code}")
                open_circuit()
                return False
        
        except requests.exceptions.Timeout:
            logger.warning("Timeout API")
            open_circuit()
            return False
        
        except Exception as e:
            logger.error(f"Error API: {e}")
            open_circuit()
            return False
    
    finally:
        client = get_redis_client()
        if client:
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            client.eval(lua_script, 1, 'fetch_in_progress', operation_id)

# ⭐ LEER TODO CON PIPELINE (una sola operación Redis)
def get_all_classified() -> Tuple[List, List, List, List, str]:
    """
    Leer TODAS las claves de clasificación en UNA sola operación pipeline.
    Sin st.cache_data (Redis ya es el caché).
    """
    keys = ['admitidos', 'inadmisibles', 'recibidos', 'errores', 'last_update']
    data = redis_mget(keys)
    
    admitidos = data.get('admitidos', [])
    inadmisibles = data.get('inadmisibles', [])
    recibidos = data.get('recibidos', [])
    errores = data.get('errores', [])
    last_update = data.get('last_update', "")
    
    if isinstance(last_update, bytes):
        last_update = last_update.decode()
    
    return admitidos, inadmisibles, recibidos, errores, last_update

# ⭐ DATAFRAME CACHEADO (solo para UI, recreado pocas veces)
@st.cache_data(ttl=30, show_spinner=False)
def get_cached_classified():
    """Caché ligero solo para evitar re-renders innecesarios"""
    return get_all_classified()

# ==========================================
# UI - MOSTRAR TABLA (SIN RECREAR DATAFRAME)
# ==========================================
def mostrar_tabla(datos: List[Dict], titulo: str = ""):
    """Mostrar tabla desde lista ya clasificada y ordenada"""
    if not datos:
        st.caption("📭 Sin resultados")
        return
    
    # ⭐ DataFrame creado una sola vez aquí
    df = pd.DataFrame(datos)
    df.index = range(1, len(df) + 1)
    
    column_config = {}
    if "RutaDocumento" in df.columns:
        column_config["RutaDocumento"] = st.column_config.LinkColumn(
            "Ruta Documento",
            display_text="📄 Abrir"
        )
    
    st.dataframe(
        df,
        column_config=column_config,
        width='stretch',
        height=400
    )

# ==========================================
# INTERFAZ PRINCIPAL
# ==========================================
st.set_page_config(
    page_title="JNE - Expedientes",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estado mínimo
if 'initialized' not in st.session_state:
    st.session_state.initialized = False
if 'refreshing' not in st.session_state:
    st.session_state.refreshing = False

# ==========================================
# INICIALIZACIÓN
# ==========================================
if not st.session_state.initialized:
    has_data = redis_exists('admitidos') or redis_exists('todos_resultados')
    
    if not has_data:
        acquired, token = acquire_lock('api_refresh', CONFIG['lock_expire'])
        
        if acquired:
            # ⭐ Iniciar heartbeat para renovar lock
            stop_heartbeat = threading.Event()
            heartbeat_thread = threading.Thread(
                target=start_lock_heartbeat,
                args=(f"lock:api_refresh", token, stop_heartbeat),
                daemon=True
            )
            heartbeat_thread.start()
            
            try:
                with st.spinner("⚡ Cargando expedientes por primera vez..."):
                    fetch_and_classify()
                st.session_state.initialized = True
            finally:
                stop_heartbeat.set()
                release_lock('api_refresh', token)
        else:
            with st.spinner("⏳ Esperando datos iniciales..."):
                wait_for_fresh_data()
                st.session_state.initialized = True
    else:
        st.session_state.initialized = True

# ==========================================
# RENDERIZAR RESULTADOS
# ==========================================
# ⭐ Usar caché ligero de Streamlit
admitidos, inadmisibles, recibidos, errores, last_update = get_cached_classified()

if last_update:
    try:
        update_dt = datetime.fromisoformat(last_update)
        st.markdown(
            f"🕐 **Actualizado:** {update_dt.strftime('%d/%m/%Y %H:%M:%S')} | "
            f"**Total:** {len(admitidos) + len(inadmisibles) + len(recibidos) + len(errores)} expedientes"
        )
    except:
        pass

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

if errores:
    with st.expander(f"⚠️ Errores ({len(errores)})"):
        st.dataframe(pd.DataFrame(errores), width='stretch')

# ==========================================
# BOTÓN DE REFRESCO
# ==========================================

col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    if st.button(
        "🔄 Actualizar ahora",
        width='stretch',
        disabled=st.session_state.refreshing
    ):
        st.session_state.refreshing = True
        st.rerun()

if st.session_state.refreshing:
    acquired, token = acquire_lock('api_refresh', CONFIG['lock_expire'])
    
    if acquired:
        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=start_lock_heartbeat,
            args=(f"lock:api_refresh", token, stop_heartbeat),
            daemon=True
        )
        heartbeat_thread.start()
        
        with st.spinner("⏳ Actualizando datos desde la API..."):
            try:
                fetch_and_classify()
                get_cached_classified.clear()
                st.success("✅ Datos actualizados correctamente")
            finally:
                stop_heartbeat.set()
                release_lock('api_refresh', token)
    else:
        with st.spinner("⏳ Otro usuario está actualizando. Esperando datos frescos..."):
            wait_for_fresh_data()
            get_cached_classified.clear()
            st.info("ℹ️ Datos actualizados por otro usuario")
    
    st.session_state.refreshing = False
    time.sleep(0.3)
    st.rerun()
