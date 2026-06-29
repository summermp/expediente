# import streamlit as st
# import pandas as pd
# import requests
# import json
# import os
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from datos import expedientes

# API_URL = (
#     "https://apiplataformaelectoral3.jne.gob.pe/api/v1/"
#     "expediente/detalle?CodExpedienteExt={}"
# )

# ARCHIVO_ADMITIDOS = "admitidos.json"
# ARCHIVO_INADMISIBLES = "inadmisible.json"


# # =========================
# # JSON UTILITIES
# # =========================
# def cargar_json(path):
#     if not os.path.exists(path):
#         return []
#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             return json.load(f)
#     except:
#         return []


# def guardar_unico(path, nuevo):
#     data = cargar_json(path)
#     existentes = {d["Expediente"] for d in data if "Expediente" in d}

#     if nuevo["Expediente"] not in existentes:
#         data.append(nuevo)

#         with open(path, "w", encoding="utf-8") as f:
#             json.dump(data, f, ensure_ascii=False, indent=2)


# # =========================
# # PENDIENTES
# # =========================
# def obtener_expedientes_pendientes():
#     admitidos = cargar_json(ARCHIVO_ADMITIDOS)
#     inadmisibles = cargar_json(ARCHIVO_INADMISIBLES)

#     procesados = {d["Expediente"] for d in admitidos + inadmisibles}

#     return [
#         item for item in expedientes
#         if item["expediente"] not in procesados
#     ]


# # =========================
# # API
# # =========================
# def consultar_api(item):
#     expediente = item["expediente"]
#     entidad = item["entidad"]

#     codigo_api = f"ERM.2026{expediente}"

#     estado_lista = ""
#     ruta_pronunciamiento = ""

#     try:
#         r = requests.get(API_URL.format(codigo_api), timeout=20)
#         r.raise_for_status()
#         data = r.json()

#         estado_lista = (
#             data.get("datoGeneral", {})
#             .get("estadoLista", "")
#             .strip()
#             .upper()
#         )

#         for actuado in data.get("expedienteActuado", []):
#             if actuado.get("txTipoExpediente") == "PRONUNCIAMIENTO":
#                 ruta_pronunciamiento = actuado.get("txRutaDocumento", "")
#                 break

#     except Exception:
#         estado_lista = ""

#     resultado = {
#         "Expediente": expediente,
#         "Entidad": entidad,
#         "Estado Lista": estado_lista,
#         "Ruta Documento": ruta_pronunciamiento
#     }

#     # =========================
#     # CLASIFICACIÓN
#     # =========================
#     if "ADMIT" in estado_lista:
#         guardar_unico(ARCHIVO_ADMITIDOS, resultado)

#     elif "INADM" in estado_lista:
#         guardar_unico(ARCHIVO_INADMISIBLES, resultado)

#     return resultado


# # =========================
# # UI
# # =========================
# st.header("📊 Consulta de Expedientes JNE")

# # =========================
# # ADMITIDOS
# # =========================
# st.subheader("📄 Admitidos")

# admitidos = cargar_json(ARCHIVO_ADMITIDOS)

# if admitidos:
#     st.dataframe(
#         pd.DataFrame(admitidos),
#         width="stretch",
#         column_config={
#             "Ruta Documento": st.column_config.LinkColumn(
#                 "Ruta Documento",
#                 display_text="Abrir"
#             )
#         }
#     )
# else:
#     st.info("Sin admitidos")


# # =========================
# # INADMISIBLES
# # =========================
# st.subheader("📄 Inadmisibles")

# inadmisibles = cargar_json(ARCHIVO_INADMISIBLES)

# if inadmisibles:
#     st.dataframe(
#         pd.DataFrame(inadmisibles),
#         width="stretch",
#         column_config={
#             "Ruta Documento": st.column_config.LinkColumn(
#                 "Ruta Documento",
#                 display_text="Abrir"
#             )
#         }
#     )
# else:
#     st.info("Sin inadmisibles")


# # =========================
# # CONSULTA EN VIVO (UNA SOLA TABLA)
# # =========================
# st.divider()

# st.subheader("📊 Consulta en tiempo real")

# if st.button("🚀 Consultar expedientes pendientes"):

#     pendientes = obtener_expedientes_pendientes()

#     if not pendientes:
#         st.warning("No hay expedientes nuevos por consultar")
#         st.stop()

#     resultados = []
#     placeholder = st.empty()
#     progress = st.progress(0)

#     def render():
#         placeholder.dataframe(
#             pd.DataFrame(resultados),
#             width="stretch"
#         )

#     with ThreadPoolExecutor(max_workers=10) as executor:
#         futures = [executor.submit(consultar_api, i) for i in pendientes]

#         for i, f in enumerate(as_completed(futures), start=1):
#             resultados.append(f.result())

#             render()
#             progress.progress(i / len(pendientes))

#     st.success("Consulta finalizada")


import streamlit as st
import pandas as pd
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datos import expedientes

API_URL = (
    "https://apiplataformaelectoral3.jne.gob.pe/api/v1/"
    "expediente/detalle?CodExpedienteExt={}"
)


# =========================
# CONSULTA API
# =========================
def consultar_api(item):
    expediente = item["expediente"]
    entidad = item["entidad"]
    codigo_api = f"ERM.2026{expediente}"

    estado_lista = ""
    ruta_pronunciamiento = ""

    try:
        r = requests.get(API_URL.format(codigo_api), timeout=20)
        r.raise_for_status()
        data = r.json()

        estado_lista = (
            data.get("datoGeneral", {})
            .get("estadoLista", "")
            .strip()
            .upper()
        )

        for actuado in data.get("expedienteActuado", []):
            if actuado.get("txTipoExpediente") == "PRONUNCIAMIENTO":
                ruta_pronunciamiento = actuado.get("txRutaDocumento", "")
                break

    except Exception:
        estado_lista = "ERROR"

    return {
        "Expediente": expediente,
        "Entidad": entidad,
        "Estado Lista": estado_lista,
        "Ruta Documento": ruta_pronunciamiento
    }


# =========================
# CONSULTAR TODOS (CON PROGRESO)
# =========================
def consultar_todos_expedientes():
    resultados = []
    total = len(expedientes)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(consultar_api, item): item for item in expedientes}
        
        for i, future in enumerate(as_completed(futures), 1):
            resultado = future.result()
            resultados.append(resultado)
            progress_bar.progress(i / total)
            status_text.text(f"Consultando {i} de {total} expedientes...")
    
    status_text.text("✅ ¡Consulta completada!")
    return resultados


# =========================
# CLASIFICAR RESULTADOS
# =========================
def clasificar_expedientes(resultados):
    admitidos = []
    inadmisibles = []
    recibidos = []
    
    for item in resultados:
        estado = item.get("Estado Lista", "")
        
        if "ADMIT" in estado:
            admitidos.append(item)
        elif "INADM" in estado:
            inadmisibles.append(item)
        elif "RECIBID" in estado:
            recibidos.append(item)
        else:
            # Si no tiene estado definido, lo ponemos como recibido por defecto
            # o puedes crear una categoría "PENDIENTE"
            recibidos.append(item)
    
    return admitidos, inadmisibles, recibidos


# =========================
# MOSTRAR TABLA
# =========================
def mostrar_tabla(datos, titulo, color):
    st.subheader(f"{color} {titulo}")
    
    if datos:
        df = pd.DataFrame(datos)
        st.dataframe(
            df,
            width="stretch",
            column_config={
                "Ruta Documento": st.column_config.LinkColumn(
                    "Ruta Documento",
                    display_text="Abrir"
                )
            }
        )
        st.caption(f"Total: {len(datos)} expedientes")
    else:
        st.info(f"No hay expedientes {titulo.lower()}")


# =========================
# UI PRINCIPAL
# =========================
st.set_page_config(page_title="Consulta JNE", layout="wide")

st.markdown("📊 Sistema de Consulta de Expedientes JNE")
st.markdown("---")

# =========================
# BOTÓN PRINCIPAL
# =========================
col1, col2, col3 = st.columns([2, 1, 2])
with col2:
    if st.button("🔄 Consultar Todos los Expedientes", use_container_width=True):
        st.session_state['resultados'] = consultar_todos_expedientes()

st.markdown("---")

# =========================
# MOSTRAR RESULTADOS (SI EXISTEN)
# =========================
if 'resultados' in st.session_state and st.session_state['resultados']:
    resultados = st.session_state['resultados']
    
    # Clasificar
    admitidos, inadmisibles, recibidos = clasificar_expedientes(resultados)
    
    # Mostrar en 3 columnas
    col1, col2, col3 = st.columns(3)
    
    with col1:
        mostrar_tabla(admitidos, "✅ ADMITIDOS", "🟢")
    
    with col2:
        mostrar_tabla(inadmisibles, "❌ INADMISIBLES", "🔴")
    
    with col3:
        mostrar_tabla(recibidos, "📋 RECIBIDOS", "🟡")
    
    # Estadísticas generales
    st.markdown("---")
    st.subheader("📊 Resumen General")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Expedientes", len(resultados))
    with col2:
        st.metric("Admitidos", len(admitidos), delta=f"{len(admitidos)/len(resultados)*100:.1f}%")
    with col3:
        st.metric("Inadmisibles", len(inadmisibles), delta=f"{len(inadmisibles)/len(resultados)*100:.1f}%")
    with col4:
        st.metric("Recibidos", len(recibidos), delta=f"{len(recibidos)/len(resultados)*100:.1f}%")

else:
    st.info("👆 Haz clic en 'Consultar Todos los Expedientes' para obtener la información actualizada")
    
    # Mostrar datos de ejemplo o mensaje
    st.markdown("""
    ### 📌 Instrucciones:
    1. Haz clic en el botón **"Consultar Todos los Expedientes"**
    2. Espera a que se complete la consulta (puede tomar varios segundos)
    3. Los resultados se mostrarán automáticamente en 3 tablas:
        - 🟢 **ADMITIDOS**: Expedientes con estado ADMITIDO
        - 🔴 **INADMISIBLES**: Expedientes con estado INADMISIBLE
        - 🟡 **RECIBIDOS**: Expedientes con estado RECIBIDO o sin estado definido
    """)

# =========================
# PIE DE PÁGINA
# =========================
st.markdown("---")
st.caption("🔹 Datos obtenidos de la API del JNE - Actualización en tiempo real")
