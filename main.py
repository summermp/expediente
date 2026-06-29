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

        # El índice empieza en 1 y se llama "#"
        df.index = range(1, len(df) + 1)
        df.index.name = "#"

        st.dataframe(
            df,
            width="stretch",
            column_config={
                "#": st.column_config.NumberColumn(
                    "#",
                    width="small"
                ),
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

 # =========================
# BOTÓN PRINCIPAL
# =========================
col1, col2, col3 = st.columns([2, 1, 2])
with col2:
    if st.button("🔄 Consultar Expedientes", use_container_width=True):
        st.session_state['resultados'] = consultar_todos_expedientes()

# =========================
# MOSTRAR RESULTADOS (SI EXISTEN)
# =========================
if 'resultados' in st.session_state and st.session_state['resultados']:
    resultados = st.session_state['resultados']

    # Clasificar
    admitidos, inadmisibles, recibidos = clasificar_expedientes(resultados)

    mostrar_tabla(admitidos, "✅ ADMITIDOS", "🟢")

    mostrar_tabla(inadmisibles, "❌ INADMISIBLES", "🔴")

    mostrar_tabla(recibidos, "📋 RECIBIDOS", "🟡")

    # Estadísticas generales
    st.markdown("---")
    st.subheader("📊 Resumen General")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Expedientes", len(resultados))
    with col2:
        st.metric("Admitidos", len(admitidos),
                  delta=f"{len(admitidos)/len(resultados)*100:.1f}%")
    with col3:
        st.metric("Inadmisibles", len(inadmisibles),
                  delta=f"{len(inadmisibles)/len(resultados)*100:.1f}%")
    with col4:
        st.metric("Recibidos", len(recibidos),
                  delta=f"{len(recibidos)/len(resultados)*100:.1f}%")

else:
    st.info("👆 Haz clic en 'Consultar Expedientes' para obtener la información actualizada")

# =========================
# PIE DE PÁGINA
# =========================
st.markdown("---")
st.caption("🔹 Datos obtenidos de la API del JNE - Actualización en tiempo real")
