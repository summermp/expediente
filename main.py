import streamlit as st
import pandas as pd
import requests
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datos import expedientes

API_URL = (
    "https://apiplataformaelectoral3.jne.gob.pe/api/v1/"
    "expediente/detalle?CodExpedienteExt={}"
)

ARCHIVO_ADMITIDOS = "admitidos.json"
ARCHIVO_INADMISIBLES = "inadmisible.json"


# =========================
# JSON UTILITIES
# =========================
def cargar_json(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def guardar_unico(path, nuevo):
    data = cargar_json(path)
    existentes = {d["Expediente"] for d in data if "Expediente" in d}

    if nuevo["Expediente"] not in existentes:
        data.append(nuevo)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# =========================
# PENDIENTES
# =========================
def obtener_expedientes_pendientes():
    admitidos = cargar_json(ARCHIVO_ADMITIDOS)
    inadmisibles = cargar_json(ARCHIVO_INADMISIBLES)

    procesados = {d["Expediente"] for d in admitidos + inadmisibles}

    return [
        item for item in expedientes
        if item["expediente"] not in procesados
    ]


# =========================
# API
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
        estado_lista = ""

    resultado = {
        "Expediente": expediente,
        "Entidad": entidad,
        "Estado Lista": estado_lista,
        "Ruta Documento": ruta_pronunciamiento
    }

    # =========================
    # CLASIFICACIÓN
    # =========================
    if "ADMIT" in estado_lista:
        guardar_unico(ARCHIVO_ADMITIDOS, resultado)

    elif "INADM" in estado_lista:
        guardar_unico(ARCHIVO_INADMISIBLES, resultado)

    return resultado


# =========================
# UI
# =========================
st.header("📊 Consulta de Expedientes JNE")

# =========================
# ADMITIDOS
# =========================
st.subheader("📄 Admitidos")

admitidos = cargar_json(ARCHIVO_ADMITIDOS)

if admitidos:
    st.dataframe(
        pd.DataFrame(admitidos),
        width="stretch",
        column_config={
            "Ruta Documento": st.column_config.LinkColumn(
                "Ruta Documento",
                display_text="Abrir"
            )
        }
    )
else:
    st.info("Sin admitidos")


# =========================
# INADMISIBLES
# =========================
st.subheader("📄 Inadmisibles")

inadmisibles = cargar_json(ARCHIVO_INADMISIBLES)

if inadmisibles:
    st.dataframe(
        pd.DataFrame(inadmisibles),
        width="stretch",
        column_config={
            "Ruta Documento": st.column_config.LinkColumn(
                "Ruta Documento",
                display_text="Abrir"
            )
        }
    )
else:
    st.info("Sin inadmisibles")


# =========================
# CONSULTA EN VIVO (UNA SOLA TABLA)
# =========================
st.divider()

st.subheader("📊 Consulta en tiempo real")

if st.button("🚀 Consultar expedientes pendientes"):

    pendientes = obtener_expedientes_pendientes()

    if not pendientes:
        st.warning("No hay expedientes nuevos por consultar")
        st.stop()

    resultados = []
    placeholder = st.empty()
    progress = st.progress(0)

    def render():
        placeholder.dataframe(
            pd.DataFrame(resultados),
            width="stretch"
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(consultar_api, i) for i in pendientes]

        for i, f in enumerate(as_completed(futures), start=1):
            resultados.append(f.result())

            render()
            progress.progress(i / len(pendientes))

    st.success("Consulta finalizada")