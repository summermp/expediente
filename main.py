import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from datos import expedientes

# ==========================================
# CONFIGURACIÓN
# ==========================================

API_URL = (
    "https://apiplataformaelectoral3.jne.gob.pe/api/v1/"
    "expediente/detalle?CodExpedienteExt={}"
)

MAX_WORKERS = 30

# ==========================================
# SESSION HTTP (MUCHO MÁS RÁPIDA)
# ==========================================

session = requests.Session()

retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)

adapter = HTTPAdapter(
    max_retries=retry,
    pool_connections=MAX_WORKERS,
    pool_maxsize=MAX_WORKERS
)

session.mount("https://", adapter)
session.mount("http://", adapter)


# ==========================================
# CONSULTAR UN EXPEDIENTE
# ==========================================

def consultar_api(item):

    expediente = item["expediente"]

    codigo_api = f"ERM.2026{expediente}"

    try:

        r = session.get(
            API_URL.format(codigo_api),
            timeout=8
        )

        r.raise_for_status()

        data = r.json()

        estado = (
            data.get("datoGeneral", {})
            .get("estadoLista", "")
            .strip()
            .upper()
        )

        pron = next(
            (
                x
                for x in data.get("expedienteActuado", [])
                if x.get("txTipoExpediente") == "PRONUNCIAMIENTO"
            ),
            {}
        )

        return {
            "Expediente": expediente,
            "Entidad": item["entidad"],
            "Estado Lista": estado,
            "Ruta Documento": pron.get("txRutaDocumento", ""),
            "Fecha Publicación": pron.get("txFechaPublicacion", "")
        }

    except Exception:

        return {
            "Expediente": expediente,
            "Entidad": item["entidad"],
            "Estado Lista": "ERROR",
            "Ruta Documento": "",
            "Fecha Publicación": ""
        }


# ==========================================
# CONSULTA PARALELA
# ==========================================

def consultar_todos_expedientes():

    resultados = []

    total = len(expedientes)

    barra = st.progress(0)

    texto = st.empty()

    with ThreadPoolExecutor(
        max_workers=min(MAX_WORKERS, total)
    ) as executor:

        futures = [
            executor.submit(consultar_api, item)
            for item in expedientes
        ]

        for i, future in enumerate(as_completed(futures), 1):

            resultados.append(future.result())

            if i % 5 == 0 or i == total:
                barra.progress(i / total)
                texto.text(f"Consultando {i}/{total}")

    barra.empty()
    texto.empty()

    return resultados


# ==========================================
# CLASIFICACIÓN
# ==========================================

def clasificar_expedientes(resultados):

    admitidos = []
    inadmisibles = []
    recibidos = []

    for item in resultados:

        estado = item["Estado Lista"]

        if "ADMIT" in estado:

            admitidos.append({
                "Expediente": item["Expediente"],
                "Entidad": item["Entidad"],
                "Estado Lista": estado,
                "Fecha Publicación": item["Fecha Publicación"]
            })

        elif "INADM" in estado:

            inadmisibles.append(item)

        else:

            recibidos.append(item)

    return admitidos, inadmisibles, recibidos


# ==========================================
# TABLAS
# ==========================================

def mostrar_tabla(datos, titulo):

    st.subheader(titulo)

    if not datos:
        st.info("Sin resultados")
        return

    df = pd.DataFrame(datos)

    df.index = range(1, len(df) + 1)

    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "Ruta Documento": st.column_config.LinkColumn(
                "Ruta Documento",
                display_text="Abrir"
            )
        }
    )

    st.caption(f"{len(df)} expedientes")


# ==========================================
# INTERFAZ
# ==========================================

st.set_page_config(
    page_title="Consulta JNE",
    layout="wide"
)

if st.button(
    "Consultar Expedientes",
    use_container_width=True
):

    st.session_state["resultados"] = consultar_todos_expedientes()

if "resultados" in st.session_state:

    resultados = st.session_state["resultados"]

    admitidos, inadmisibles, recibidos = clasificar_expedientes(resultados)

    mostrar_tabla(admitidos, "Admitidos")

    mostrar_tabla(inadmisibles, "Inadmisibles")

    mostrar_tabla(recibidos, "Recibidos")

    st.divider()

    total = len(resultados)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Admitidos", len(admitidos))
    c3.metric("Inadmisibles", len(inadmisibles))
    c4.metric("Recibidos", len(recibidos))
