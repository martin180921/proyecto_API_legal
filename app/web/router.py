"""Pantalla mínima que consume la API ya construida (Etapa Entrada, S3–4):
login, lista de expedientes, alta. Mismo repo, mismo deploy que `/v1` — sin
prefijo, montada en la raíz (`app/main.py`).

Reutiliza `app/services/expedientes.py` y `app/services/autenticacion.py`
directamente, con la misma sesión de base de datos que usan los endpoints
JSON — no hay una segunda copia de la lógica de negocio, solo una superficie
de presentación distinta.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.red import ip_cliente
from app.models.expediente import Seguimiento, TipoIdentificador, TipoProceso
from app.schemas.expediente import ExpedienteCrear
from app.services import expedientes
from app.services.autenticacion import intentar_login
from app.web.auth import (
    actor_verificado_desde_cookie,
    borrar_cookie_sesion,
    poner_cookie_sesion,
)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

LIMITE_POR_PAGINA = 20


@router.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    return RedirectResponse(url="/expedientes")


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def formulario_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", include_in_schema=False)
def procesar_login(
    request: Request,
    organizacion: str = Form(...),
    email: str = Form(...),
    contrasena: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = ip_cliente(request)
    try:
        resultado = intentar_login(db, organizacion, email, contrasena, ip)
    except HTTPException as error:
        return templates.TemplateResponse(
            request, "login.html", {"error": error.detail}, status_code=error.status_code
        )

    respuesta = RedirectResponse(url="/expedientes", status_code=status.HTTP_303_SEE_OTHER)
    poner_cookie_sesion(respuesta, resultado.token)
    return respuesta


@router.post("/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    respuesta = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    borrar_cookie_sesion(respuesta)
    return respuesta


@router.get("/expedientes", response_class=HTMLResponse, include_in_schema=False)
def lista_expedientes(
    request: Request,
    offset: int = Query(default=0, ge=0),
    actor=Depends(actor_verificado_desde_cookie),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    items, total = expedientes.listar(db, actor.organizacion_id, LIMITE_POR_PAGINA, offset)
    return templates.TemplateResponse(
        request,
        "expedientes_lista.html",
        {
            "items": items,
            "total": total,
            "offset": offset,
            "limite": LIMITE_POR_PAGINA,
            "hay_siguiente": offset + LIMITE_POR_PAGINA < total,
            "hay_anterior": offset > 0,
        },
    )


@router.get("/expedientes/nuevo", response_class=HTMLResponse, include_in_schema=False)
def formulario_expediente_nuevo(
    request: Request, actor=Depends(actor_verificado_desde_cookie)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "expediente_nuevo.html",
        {
            "error": None,
            "valores": {},
            "tipos": list(TipoProceso),
            "tipos_identificador": list(TipoIdentificador),
            "seguimientos": list(Seguimiento),
        },
    )


@router.post("/expedientes/nuevo", include_in_schema=False)
def crear_expediente(
    request: Request,
    identificador: str = Form(...),
    tipo_identificador: str = Form(...),
    seguimiento: str = Form(...),
    tipo_proceso: str = Form(...),
    juzgado: str = Form(""),
    despacho: str = Form(""),
    partes: str = Form(""),
    ultima_actuacion_al_importar: str = Form(""),
    actor=Depends(actor_verificado_desde_cookie),
    db: Session = Depends(get_db),
):
    valores = {
        "identificador": identificador,
        "tipo_identificador": tipo_identificador,
        "seguimiento": seguimiento,
        "tipo_proceso": tipo_proceso,
        "juzgado": juzgado,
        "despacho": despacho,
        "partes": partes,
        "ultima_actuacion_al_importar": ultima_actuacion_al_importar,
    }

    def _error(mensaje: str, codigo: int = status.HTTP_400_BAD_REQUEST):
        return templates.TemplateResponse(
            request,
            "expediente_nuevo.html",
            {
                "error": mensaje,
                "valores": valores,
                "tipos": list(TipoProceso),
                "tipos_identificador": list(TipoIdentificador),
                "seguimientos": list(Seguimiento),
            },
            status_code=codigo,
        )

    try:
        payload = ExpedienteCrear(
            identificador=identificador,
            tipo_identificador=tipo_identificador,
            seguimiento=seguimiento,
            tipo_proceso=tipo_proceso,
            juzgado=juzgado or None,
            despacho=despacho or None,
            partes=partes or None,
            ultima_actuacion_al_importar=ultima_actuacion_al_importar or None,
        )
    except ValueError as error:
        primer_error = error.errors()[0]["msg"] if hasattr(error, "errors") else str(error)
        return _error(primer_error)

    try:
        expedientes.crear(db, actor.organizacion_id, actor.usuario_id, payload)
    except IntegrityError:
        db.rollback()
        return _error(
            "Ya existe un expediente con ese identificador en esta organización.",
            status.HTTP_409_CONFLICT,
        )

    return RedirectResponse(url="/expedientes", status_code=status.HTTP_303_SEE_OTHER)
