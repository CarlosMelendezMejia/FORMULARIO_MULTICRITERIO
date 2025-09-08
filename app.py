from flask import Flask, render_template, request, redirect, url_for, flash, session, g, Response
import os
import mysql.connector
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import bleach
from flask_caching import Cache
import logging
import io
import csv
from pathlib import Path
from concurrent_log_handler import ConcurrentRotatingFileHandler
from datetime import datetime, timedelta

app = Flask(__name__)

DOTENV_PATH = Path(app.root_path) / ".env"
DOTENV_PATH.touch(exist_ok=True)
load_dotenv(DOTENV_PATH)

from db import get_connection, PoolExhaustedError

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY environment variable not set")
app.secret_key = secret_key
app.permanent_session_lifetime = timedelta(
    minutes=int(os.getenv("SESSION_TIMEOUT_MINUTES", 10))
)

# ==============================
# Prefijo de aplicación opcional
# ==============================
# Para desplegar la app bajo una sub-ruta (p.ej. /FORMULARIO_MULTICRITERIO) sin
# reescribir todas las rutas o usar Blueprints, se puede establecer la variable
# de entorno APP_PREFIX. En entornos de desarrollo (tests) se deja vacío para
# no romper los paths existentes.
APP_PREFIX = os.getenv("APP_PREFIX", "").rstrip("/")
if APP_PREFIX and not APP_PREFIX.startswith("/"):
    APP_PREFIX = "/" + APP_PREFIX
if APP_PREFIX:
    app.config["APPLICATION_ROOT"] = APP_PREFIX

    from werkzeug.wrappers import Response  # súbelo fuera para reutilizar

    class PrefixMiddleware:
        def __init__(self, wsgi_app, prefix: str):
            self.wsgi_app = wsgi_app
            self.prefix = prefix

        def __call__(self, environ, start_response):
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(self.prefix + "/") or path_info == self.prefix:
                environ["SCRIPT_NAME"] = self.prefix
                trimmed = path_info[len(self.prefix):]
                environ["PATH_INFO"] = trimmed if trimmed else "/"
                return self.wsgi_app(environ, start_response)

            if path_info == "/":
                resp = Response("", status=302, headers={"Location": f"{self.prefix}/"})
                return resp(environ, start_response)

            resp = Response("Not Found", status=404)
            return resp(environ, start_response)

    app.wsgi_app = PrefixMiddleware(app.wsgi_app, APP_PREFIX)

# Asegurar que la cookie de sesión sea válida bajo un prefijo
# Si se despliega la app bajo un subpath, fijamos el "path" de la cookie
# explícitamente para que el navegador envíe la cookie tras redirecciones.
def _compute_cookie_path(prefix: str) -> str:
    if not prefix:
        return "/"
    # Garantizar que comience con '/'
    return prefix if prefix.startswith("/") else f"/{prefix}"

app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
app.config.setdefault("SESSION_COOKIE_SECURE", False)  # Cambiar a True si se usa HTTPS en prod
app.config["SESSION_COOKIE_PATH"] = _compute_cookie_path(APP_PREFIX)

# Configuración de registro
os.makedirs("static/logs", exist_ok=True)
log_handler = ConcurrentRotatingFileHandler(
    "static/logs/app.log", maxBytes=1_048_576, backupCount=10
)
log_handler.setLevel(logging.DEBUG)
log_formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
log_handler.setFormatter(log_formatter)
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.DEBUG)

# Configuración de caché compartido
CACHE_TTL = int(os.getenv("RANKING_CACHE_TTL", 300))
cache_type = os.getenv("CACHE_TYPE", "RedisCache")
cache_config = {"CACHE_DEFAULT_TIMEOUT": CACHE_TTL, "CACHE_TYPE": cache_type}

if cache_type == "RedisCache":
    cache_config.update(
        {
            "CACHE_REDIS_HOST": os.getenv("CACHE_REDIS_HOST", "localhost"),
            "CACHE_REDIS_PORT": int(os.getenv("CACHE_REDIS_PORT", 6379)),
            "CACHE_REDIS_DB": int(os.getenv("CACHE_REDIS_DB", 0)),
            "CACHE_REDIS_PASSWORD": os.getenv("CACHE_REDIS_PASSWORD"),
            "CACHE_REDIS_URL": os.getenv("CACHE_REDIS_URL"),
        }
    )

try:
    cache = Cache(app, config=cache_config)
    if cache_type == "RedisCache":
        cache.set("__cache_test__", 1, timeout=1)
        cache.delete("__cache_test__")
except Exception as e:  # pragma: no cover - fallback for missing redis
    app.logger.warning("Falling back to SimpleCache: %s", e)
    cache = Cache(
        app,
        config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": CACHE_TTL},
    )

RANKING_CACHE_KEY = "ranking_cache"


@app.before_request
def enforce_admin_session_timeout():
    prefixed_admin = f"{APP_PREFIX}/admin"
    path = request.path
    if not path.startswith(prefixed_admin):
        return
    if request.endpoint == "admin_login":
        return
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    last = session.get("last_activity")
    if last:
        try:
            last_dt = datetime.fromtimestamp(float(last))
        except (TypeError, ValueError):
            last_dt = None
        if last_dt and datetime.utcnow() - last_dt > app.permanent_session_lifetime:
            session.pop("is_admin", None)
            session.pop("last_activity", None)
            return redirect(url_for("admin_login"))
    session["last_activity"] = datetime.utcnow().timestamp()


# =====================================
# Utilidades de consultas / rendimiento
# =====================================

def build_admin_filters(estado, search, formulario_filter, fecha_desde, fecha_hasta):
    """Construye cláusula WHERE y parámetros para filtros del panel admin.

    Centraliza la lógica para reuso en listado y exportación.
    Devuelve (where_clause, params, fecha_desde_normalizada, fecha_hasta_normalizada)
    """
    conditions = ["1=1"]
    params = []
    # Estado
    if estado == "bloqueado":
        conditions.append("r.bloqueado = 1")
    elif estado == "abierto":
        conditions.append("r.bloqueado = 0")
    # Búsqueda textual
    if search:
        conditions.append("(u.nombre LIKE %s OR u.apellidos LIKE %s)")
        like_term = f"%{search}%"
        params.extend([like_term, like_term])
    # Filtro de formulario
    if formulario_filter:
        if formulario_filter.isdigit():
            conditions.append("f.id = %s")
            params.append(int(formulario_filter))
        else:
            conditions.append("f.nombre LIKE %s")
            params.append(f"%{formulario_filter}%")
    # Fechas
    from datetime import datetime, timedelta
    date_format = "%Y-%m-%d"
    fecha_desde_norm = fecha_desde
    fecha_hasta_norm = fecha_hasta
    if fecha_desde:
        try:
            dt_desde = datetime.strptime(fecha_desde, date_format)
            conditions.append("r.fecha_respuesta >= %s")
            params.append(dt_desde)
        except ValueError:
            fecha_desde_norm = ""
    if fecha_hasta:
        try:
            dt_hasta = datetime.strptime(fecha_hasta, date_format) + timedelta(days=1) - timedelta(seconds=1)
            conditions.append("r.fecha_respuesta <= %s")
            params.append(dt_hasta)
        except ValueError:
            fecha_hasta_norm = ""
    where_clause = " AND ".join(conditions)
    return where_clause, params, fecha_desde_norm, fecha_hasta_norm


def sanitize(texto: str) -> str:
    """Sanitize user-provided text by stripping HTML tags and scripts."""
    return bleach.clean(texto or "", tags=[], attributes={}, strip=True)


def invalidate_ranking_cache():
    """Reset ranking cache to force recomputation on next request."""
    cache.delete(RANKING_CACHE_KEY)


# TTLs para distintos cachés
FACTORES_CACHE_TTL = int(os.getenv("FACTORES_CACHE_TTL", 300))
BLOQUEO_CACHE_TTL = int(os.getenv("BLOQUEO_CACHE_TTL", 30))

FACTORES_CACHE_KEY = "factores_cache"


def _bloqueo_cache_key(id_usuario: int, id_formulario: int) -> str:
    return f"bloqueo:{id_usuario}:{id_formulario}"


def is_formulario_bloqueado(id_usuario: int, id_formulario: int) -> bool:
    """Devuelve True si el formulario está bloqueado para el usuario."""
    key = _bloqueo_cache_key(id_usuario, id_formulario)
    bloqueado = cache.get(key)
    if bloqueado is not None:
        return bloqueado

    get_db()
    g.cursor.execute(
        "SELECT 1 FROM respuesta WHERE id_usuario = %s AND id_formulario = %s AND bloqueado = 1",
        (id_usuario, id_formulario),
    )
    bloqueado = g.cursor.fetchone() is not None
    cache.set(key, bloqueado, timeout=BLOQUEO_CACHE_TTL)
    return bloqueado


def invalidate_bloqueo_cache(id_usuario: int, id_formulario: int):
    """Elimina la entrada de caché para un usuario y formulario.

    Esta función debe llamarse tras cualquier operación que modifique el
    campo ``bloqueado`` para evitar inconsistencias visibles entre el estado
    real y el estado almacenado en caché.
    """
    cache.delete(_bloqueo_cache_key(id_usuario, id_formulario))


def get_factores():
    """Obtiene la lista de factores usando el backend de caché."""
    factores = cache.get(FACTORES_CACHE_KEY)
    if factores is None:
        g.cursor.execute("SELECT * FROM factor")
        factores = g.cursor.fetchall()
        cache.set(FACTORES_CACHE_KEY, factores, timeout=FACTORES_CACHE_TTL)
    return factores


def invalidate_factores_cache():
    """Reinicia el caché de factores y del ranking relacionado."""
    cache.delete(FACTORES_CACHE_KEY)
    invalidate_ranking_cache()


def get_db():
    """Obtain a database connection and cursor lazily."""
    if "conn" not in g:
        g.conn = get_connection()
        g.cursor = g.conn.cursor(dictionary=True)
    return g.conn, g.cursor


@app.teardown_appcontext
def teardown_db(exception):
    cursor = g.pop("cursor", None)
    if cursor is not None:
        cursor.close()
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


@app.after_request
def add_no_cache_headers(response):
    """Evita el cacheo de páginas protegidas para rutas de administrador y formulario."""
    if request.path.startswith("/admin") or request.path.startswith("/formulario"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ==============================
# RUTA PRINCIPAL
# ==============================


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/formulario_redirect", methods=["POST"])
def formulario_redirect():
    usuario_id = request.form["usuario_id"]
    return redirect(url_for("mostrar_formulario", id_usuario=usuario_id))


# ==============================
# RUTA PARA PASSWORD DE FORMULARIO
# ==============================


@app.route("/formulario/<int:id_usuario>/password", methods=["GET", "POST"])
def formulario_password(id_usuario):
    """Solicita y valida la contraseña de un formulario protegido."""
    get_db()
    g.cursor.execute(
        """
        SELECT a.id_formulario, f.requiere_password, f.password_hash
        FROM asignacion a
        JOIN formulario f ON a.id_formulario = f.id
        LEFT JOIN respuesta r
            ON r.id_usuario = a.id_usuario
           AND r.id_formulario = a.id_formulario
           AND r.bloqueado = 0
        WHERE a.id_usuario = %s
        ORDER BY r.id IS NOT NULL, a.id_formulario
        LIMIT 1
        """,
        (id_usuario,),
    )
    asignacion = g.cursor.fetchone()
    if not asignacion:
        app.logger.info("Sin formulario asignado usuario=%s (password)", id_usuario)
        return render_template("formulario_no_disponible.html"), 404

    id_formulario = asignacion["id_formulario"]
    session_key = f"formulario_{id_formulario}_acceso"

    if not asignacion.get("requiere_password") or session.get(session_key):
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        expected_hash = asignacion.get("password_hash")
        if not expected_hash:
            app.logger.warning(
                "Contraseña del formulario %s no configurada",
                id_formulario,
            )
            return (
                render_template(
                    "formulario_password.html",
                    usuario_id=id_usuario,
                    error="La contraseña del formulario no está configurada",
                ),
                500,
            )
        if check_password_hash(expected_hash, password):
            session[session_key] = True
            session.modified = True  # Forzar escritura de cookie de sesión
            app.logger.debug(
                "Sesión %s establecida para usuario=%s (script_root=%s, cookie_path=%s)",
                session_key,
                id_usuario,
                getattr(request, 'script_root', ''),
                app.config.get('SESSION_COOKIE_PATH')
            )
            return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))
        return (
            render_template(
                "formulario_password.html",
                usuario_id=id_usuario,
                error="Contraseña incorrecta",
            ),
            401,
        )

    return render_template("formulario_password.html", usuario_id=id_usuario)


# ==============================
# RUTA PARA FORMULARIO DE USUARIO
# ==============================


@app.route("/formulario/<int:id_usuario>")
def mostrar_formulario(id_usuario):
    """Muestra el formulario asignado al usuario.

    Se selecciona directamente el primer formulario asignado que no tenga
    respuestas previas. Si todos los formularios ya tienen respuesta, se
    elige el primero asignado.
    """
    ip = request.remote_addr
    app.logger.info(
        "mostrar_formulario inicio usuario=%s ip=%s", id_usuario, ip
    )

    get_db()

    g.cursor.execute(
        """
        SELECT a.id_formulario, f.nombre AS nombre_formulario,
               f.requiere_password, f.password_hash
        FROM asignacion a
        JOIN formulario f ON a.id_formulario = f.id
        LEFT JOIN respuesta r
            ON r.id_usuario = a.id_usuario
           AND r.id_formulario = a.id_formulario
           AND r.bloqueado = 0
        WHERE a.id_usuario = %s
        ORDER BY r.id IS NOT NULL, a.id_formulario
        LIMIT 1
        """,
        (id_usuario,),
    )
    asignacion = g.cursor.fetchone()
    app.logger.info(
        "Asignacion usuario=%s resultado=%s", id_usuario, asignacion
    )

    if not asignacion:
        app.logger.info("Sin formulario asignado usuario=%s", id_usuario)
        return render_template("formulario_no_disponible.html"), 404

    id_formulario = asignacion["id_formulario"]

    if asignacion.get("requiere_password"):
        session_key = f"formulario_{id_formulario}_acceso"
        if not session.get(session_key):
            try:
                present_keys = list(session.keys())
            except Exception:
                present_keys = []
            app.logger.debug(
                "Sesión no contiene clave requerida. keys=%s buscada=%s",
                present_keys,
                session_key,
            )
            app.logger.debug(
                "Clave de sesión %s no presente para usuario=%s, redirigiendo a formulario_password",
                session_key,
                id_usuario,
            )
            return redirect(url_for("formulario_password", id_usuario=id_usuario))
        else:
            # Consumir la validación: se requerirá nuevamente en el próximo acceso
            session.pop(session_key, None)

    # Verificar si el formulario ya fue respondido y está bloqueado (usa caché)
    if is_formulario_bloqueado(id_usuario, id_formulario):
        app.logger.info(
            "Formulario bloqueado usuario=%s formulario=%s", id_usuario, id_formulario
        )
        return render_template("formulario_bloqueado.html")

    # Obtener factores (con caché)
    factores = get_factores()
    num_factores = len(factores)
    app.logger.info(
        "Formulario %s tiene %s factores para usuario=%s", id_formulario, num_factores, id_usuario
    )

    # Obtener datos del usuario
    g.cursor.execute("SELECT * FROM usuario WHERE id = %s", (id_usuario,))
    usuario = g.cursor.fetchone()
    app.logger.info(
        "Datos usuario=%s: %s", id_usuario, usuario
    )

    # Obtener respuestas anteriores (si existen)
    g.cursor.execute(
        """
        SELECT rd.id_factor, rd.valor_usuario
        FROM respuesta r
        JOIN respuesta_detalle rd ON r.id = rd.id_respuesta
        WHERE r.id_usuario = %s
          AND r.id_formulario = %s
          AND r.bloqueado = 0
    """,
        (id_usuario, id_formulario),
    )
    respuestas_previas = g.cursor.fetchall()
    app.logger.info(
        "Respuestas previas usuario=%s formulario=%s: %s", id_usuario, id_formulario, respuestas_previas
    )

    # Convertir a diccionario {id_factor: valor}
    respuestas_dict = {r["id_factor"]: r["valor_usuario"] for r in respuestas_previas}
    app.logger.info(
        "Render formulario usuario=%s formulario=%s", id_usuario, id_formulario
    )

    return render_template(
        "formulario.html",
        usuario_id=id_usuario,
        formulario=asignacion,
        factores=factores,
        num_factores=num_factores,
        usuario=usuario,
        respuestas_previas=respuestas_dict,
    )


# ==============================
# GUARDAR RESPUESTA DE FORMULARIO
# ==============================


@app.route("/guardar_respuesta", methods=["POST"])
def guardar_respuesta():
    id_usuario = int(request.form["usuario_id"])
    id_formulario = int(request.form["formulario_id"])
    exit_redirect = request.form.get("exit_redirect")
    ip = request.remote_addr
    app.logger.info(
        "guardar_respuesta inicio usuario=%s formulario=%s ip=%s",
        id_usuario,
        id_formulario,
        ip,
    )

    # Verificar bloqueo mediante caché antes de acceder a la base de datos
    if is_formulario_bloqueado(id_usuario, id_formulario):
        app.logger.info(
            "Formulario bloqueado usuario=%s formulario=%s",
            id_usuario,
            id_formulario,
        )
        return render_template("formulario_bloqueado.html")

    get_db()
    num_factores = len(get_factores())

    # Datos personales
    nombre = sanitize(request.form["nombre"].strip())
    apellidos = sanitize(request.form["apellidos"].strip())
    cargo = sanitize(request.form["cargo"].strip())
    dependencia = sanitize(request.form["dependencia"].strip())

    # 1. Leer los valores únicos de los factores enviados
    valores = []
    try:
        for i in range(1, num_factores + 1):
            factor_key = f"factor_id_{i}"
            valor_key = f"valor_{i}"
            if factor_key not in request.form:
                continue  # Datos faltantes → se considera incompleto
            raw_val = request.form.get(valor_key, "").strip()
            if not raw_val:
                continue  # Valor faltante → se considera incompleto
            factor_id = int(request.form[factor_key])
            valor = int(raw_val)
            if not 1 <= valor <= num_factores:
                flash(f"Cada valor debe estar entre 1 y {num_factores}.")
                return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))
            valores.append((factor_id, valor))
    except ValueError:
        flash("Los identificadores y valores de los factores deben ser números enteros.")
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))

    app.logger.info(
        "Valores recibidos usuario=%s formulario=%s: %s",
        id_usuario,
        id_formulario,
        valores,
    )

    usados = [v[1] for v in valores]
    if len(usados) != len(set(usados)):
        flash(
            f"Cada valor del 1 al {num_factores} debe ser único. No se permiten duplicados."
        )
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))

    completo = len(valores) == num_factores

    # 2. Guardar información en la base de datos dentro de una transacción
    try:
        # Asegurar estado limpio: rollback defensivo por si quedó algo abierto
        try:
            g.conn.rollback()
        except Exception:
            pass
        g.conn.start_transaction()

        # Actualizar los datos del usuario
        g.cursor.execute(
            """
            UPDATE usuario
            SET nombre = %s,
                apellidos = %s,
                cargo = %s,
                dependencia = %s
            WHERE id = %s
        """,
            (nombre, apellidos, cargo, dependencia, id_usuario),
        )

        # Verificar si ya hay una respuesta existente → si sí, eliminarla
        g.cursor.execute(
            """
            SELECT id FROM respuesta
            WHERE id_usuario = %s
              AND id_formulario = %s
              AND bloqueado = 0
        """,
            (id_usuario, id_formulario),
        )
        anterior = g.cursor.fetchone()

        if anterior:
            id_anterior = anterior["id"]
            # Eliminar ponderaciones si existen
            g.cursor.execute(
                "DELETE FROM ponderacion_admin WHERE id_respuesta = %s", (id_anterior,)
            )
            g.cursor.execute(
                "DELETE FROM respuesta_detalle WHERE id_respuesta = %s", (id_anterior,)
            )
            g.cursor.execute("DELETE FROM respuesta WHERE id = %s", (id_anterior,))

        # Insertar nueva respuesta
        g.cursor.execute(
            """
            INSERT INTO respuesta (id_usuario, id_formulario, bloqueado)
            VALUES (%s, %s, %s)
        """,
            (id_usuario, id_formulario, 1 if completo else 0),
        )
        id_respuesta = g.cursor.lastrowid

        # Insertar detalle de factores
        detalles = [(id_respuesta, factor_id, valor) for factor_id, valor in valores]
        if detalles:
            g.cursor.executemany(
                """
                    INSERT INTO respuesta_detalle (id_respuesta, id_factor, valor_usuario)
                    VALUES (%s, %s, %s)
                """,
                detalles,
            )

        g.conn.commit()
    except mysql.connector.IntegrityError:
        g.conn.rollback()
        app.logger.info(
            "Respuesta duplicada usuario=%s formulario=%s",
            id_usuario,
            id_formulario,
        )
        flash("Ya se registró una respuesta para este formulario.")
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))
    except Exception:
        g.conn.rollback()
        app.logger.exception(
            "Error al guardar respuesta usuario=%s formulario=%s",
            id_usuario,
            id_formulario,
        )
        flash("Error al guardar la respuesta. Intenta nuevamente.")
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))

    # Limpiar cachés dependientes
    invalidate_bloqueo_cache(id_usuario, id_formulario)
    invalidate_ranking_cache()

    if not completo:
        app.logger.info(
            "Respuesta incompleta usuario=%s formulario=%s",
            id_usuario,
            id_formulario,
        )
        if exit_redirect:
            return render_template("confirmacion.html", bloqueado=False)
        flash("Respuestas incompletas; se guardó el progreso sin bloquear")
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))

    if exit_redirect:
        app.logger.info(
            "Respuesta guardada usuario=%s formulario=%s con redireccion",
            id_usuario,
            id_formulario,
        )
    else:
        app.logger.info(
            "Respuesta guardada usuario=%s formulario=%s",
            id_usuario,
            id_formulario,
        )
    return render_template("confirmacion.html", bloqueado=True)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")
        ip = request.remote_addr
        app.logger.info("Intento login admin ip=%s", ip)
        if password == ADMIN_PASSWORD:
            session.permanent = True
            session["is_admin"] = True
            session["last_activity"] = datetime.utcnow().timestamp()
            app.logger.info("Login admin exitoso ip=%s", ip)
            return redirect(url_for("panel_admin"))
        app.logger.info("Login admin fallido ip=%s", ip)
        flash("Contraseña incorrecta.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    ip = request.remote_addr
    app.logger.info("Logout admin ip=%s", ip)
    session.pop("is_admin", None)
    session.pop("last_activity", None)
    return redirect(url_for("index"))


# ==============================
# PANEL DE ADMINISTRADOR (resumen)
# ==============================


@app.route("/admin")
def panel_admin():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    ip = request.remote_addr
    get_db()
    page = request.args.get("page", 1, type=int)
    # Selector dinámico de resultados por página
    try:
        per_page_candidate = int(request.args.get("per_page", 10))
    except (TypeError, ValueError):
        per_page_candidate = 10
    ALLOWED_PER_PAGE = [5, 10, 25, 50]
    per_page = per_page_candidate if per_page_candidate in ALLOWED_PER_PAGE else 10

    # Filtros
    clear = request.args.get("clear")
    if clear:
        session.pop("admin_filters", None)
    stored = session.get("admin_filters", {}) if not clear else {}

    # Leer filtros de query o fallback a sesión
    estado = request.args.get("estado")
    if estado is None:
        estado = stored.get("estado", "")
    estado = estado.strip().lower() if estado else ""

    search = request.args.get("search")
    if search is None:
        search = stored.get("search", "")
    search = search.strip() if search else ""

    formulario_filter = request.args.get("formulario")
    if formulario_filter is None:
        formulario_filter = stored.get("formulario", "")
    formulario_filter = formulario_filter.strip() if formulario_filter else ""

    fecha_desde = request.args.get("fecha_desde")
    if fecha_desde is None:
        fecha_desde = stored.get("fecha_desde", "")
    fecha_desde = fecha_desde.strip() if fecha_desde else ""

    fecha_hasta = request.args.get("fecha_hasta")
    if fecha_hasta is None:
        fecha_hasta = stored.get("fecha_hasta", "")
    fecha_hasta = fecha_hasta.strip() if fecha_hasta else ""

    # Guardar filtros en sesión (sin page ni per_page)
    session["admin_filters"] = {
        "estado": estado,
        "search": search,
        "formulario": formulario_filter,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    }

    where_clause, params, fecha_desde, fecha_hasta = build_admin_filters(
        estado, search, formulario_filter, fecha_desde, fecha_hasta
    )
    offset = (page - 1) * per_page
    # Total de respuestas para construir paginación
    counts_sql = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN r.bloqueado = 1 THEN 1 ELSE 0 END) AS bloqueados,
            SUM(CASE WHEN r.bloqueado = 0 THEN 1 ELSE 0 END) AS abiertos
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        WHERE {where_clause}
    """
    g.cursor.execute(counts_sql, tuple(params))
    counts_row = g.cursor.fetchone() or {"total": 0, "bloqueados": 0, "abiertos": 0}
    total_count = counts_row.get("total", 0) or 0
    count_bloqueados = counts_row.get("bloqueados", 0) or 0
    count_abiertos = counts_row.get("abiertos", 0) or 0
    app.logger.info("panel_admin inicio ip=%s page=%s", ip, page)
    data_sql = f"""
        SELECT r.id AS id_respuesta,
               u.nombre,
               u.apellidos,
               f.nombre AS formulario,
               r.fecha_respuesta,
               DATE_FORMAT(r.fecha_respuesta, '%Y-%m-%d %H:%i') AS fecha_respuesta_fmt,
               r.bloqueado
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        WHERE {where_clause}
        ORDER BY r.fecha_respuesta DESC, r.id DESC
        LIMIT %s OFFSET %s
    """
    g.cursor.execute(data_sql, tuple(params + [per_page + 1, offset]))
    respuestas = g.cursor.fetchall()
    has_next = len(respuestas) > per_page
    if has_next:
        respuestas = respuestas[:-1]
    # Calcular total de páginas (al menos 1 si hay elementos)
    total_pages = (total_count + per_page - 1) // per_page if total_count else 1
    app.logger.info(
        "panel_admin respuestas=%s ip=%s page=%s",
        len(respuestas),
        ip,
        page,
    )

    return render_template(
        "admin.html",
        respuestas=respuestas,
        page=page,
        has_next=has_next,
        total_pages=total_pages,
        per_page=per_page,
        total_count=total_count,
        allowed_per_page=ALLOWED_PER_PAGE,
        estado=estado,
        search=search,
        formulario_filter=formulario_filter,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        count_bloqueados=count_bloqueados,
        count_abiertos=count_abiertos,
    )


@app.route("/admin/export_csv")
def export_respuestas_csv():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    get_db()
    # Reutilizar lógica de filtros (similar a panel_admin, sin paginación)
    stored = session.get("admin_filters", {})
    estado = request.args.get("estado", stored.get("estado", "")).strip().lower()
    search = request.args.get("search", stored.get("search", "")).strip()
    formulario_filter = request.args.get("formulario", stored.get("formulario", "")).strip()
    fecha_desde = request.args.get("fecha_desde", stored.get("fecha_desde", "")).strip()
    fecha_hasta = request.args.get("fecha_hasta", stored.get("fecha_hasta", "")).strip()

    where_clause, params, _, _ = build_admin_filters(
        estado, search, formulario_filter, fecha_desde, fecha_hasta
    )

    factores = get_factores()
    factor_selects = []
    for idx, f in enumerate(factores, start=1):
        factor_selects.append(
            f"MAX(CASE WHEN rd.id_factor = {f['id']} THEN rd.valor_usuario END) AS factor_{idx}"
        )

    select_columns = [
        "f.nombre AS formulario",
        "u.nombre",
        "u.apellidos",
        "u.dependencia",
        "u.cargo",
        *factor_selects,
    ]

    export_sql = f"""
        SELECT {', '.join(select_columns)}
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        LEFT JOIN respuesta_detalle rd ON rd.id_respuesta = r.id
        WHERE {where_clause}
        GROUP BY r.id, u.nombre, u.apellidos, u.dependencia, u.cargo, f.nombre
        ORDER BY r.fecha_respuesta DESC, r.id DESC
    """
    g.cursor.execute(export_sql, tuple(params))
    rows = g.cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    header = ["formulario", "nombre", "apellidos", "dependencia", "cargo"]
    header.extend([f"factor_{i}" for i in range(1, len(factores) + 1)])
    writer.writerow(header)

    for r in rows:
        row = [
            r["formulario"],
            r["nombre"],
            r["apellidos"],
            r.get("dependencia") or "",
            r.get("cargo") or "",
        ]
        row.extend([
            r.get(f"factor_{i}") or "" for i in range(1, len(factores) + 1)
        ])
        writer.writerow(row)
    csv_data = output.getvalue()
    output.close()
    # Asegurar BOM UTF-8 para compatibilidad (p.ej., Excel)
    csv_data = "\ufeff" + csv_data
    filename = "respuestas_export.csv"
    return Response(
        csv_data,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/admin/formularios", methods=["GET", "POST"])
def administrar_formularios():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    ip = request.remote_addr
    get_db()

    # Obtener el próximo ID para sugerir un nombre por defecto
    g.cursor.execute(
        """
        SELECT AUTO_INCREMENT AS siguiente_id
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'formulario'
        """
    )
    row = g.cursor.fetchone()
    siguiente_id = int(row["siguiente_id"] or 1)
    default_name = f"Formulario {siguiente_id:02d}"

    if request.method == "POST":
        # Actualizar password de un formulario existente
        form_id = request.form.get("id_formulario")
        if form_id:
            form_id = int(form_id)
            requiere_password = 1 if request.form.get("requiere_password") else 0
            password = request.form.get("password", "").strip()
            current_hash = request.form.get("current_password_hash") or None
            new_hash = None

            if requiere_password:
                if password:
                    new_hash = generate_password_hash(password)
                else:
                    new_hash = current_hash
                    if not new_hash:
                        flash("Debe proporcionar una contraseña para activar la protección.")
                        return redirect(url_for("administrar_formularios"))
            else:
                new_hash = None

            g.cursor.execute(
                "UPDATE formulario SET requiere_password = %s, password_hash = %s WHERE id = %s",
                (requiere_password, new_hash, form_id),
            )
            g.conn.commit()
            flash("Configuración de protección actualizada.")
            return redirect(url_for("administrar_formularios"))

        # Crear un nuevo formulario
        nombre = request.form.get("nombre", "").strip() or default_name
        requiere_password = 1 if request.form.get("requiere_password") else 0
        password = request.form.get("password", "").strip()
        if requiere_password:
            if not password:
                flash("Debe proporcionar una contraseña para proteger el formulario.")
                return redirect(url_for("administrar_formularios"))
            password_hash = generate_password_hash(password)
            g.cursor.execute(
                "INSERT INTO formulario (nombre, requiere_password, password_hash) VALUES (%s, %s, %s)",
                (nombre, requiere_password, password_hash),
            )
            g.conn.commit()
            app.logger.info("Formulario protegido creado '%s' ip=%s", nombre, ip)
            flash("Formulario protegido creado correctamente.")
            return redirect(url_for("administrar_formularios"))
        else:
            g.cursor.execute(
                "INSERT INTO formulario (nombre, requiere_password, password_hash) VALUES (%s, %s, %s)",
                (nombre, requiere_password, None),
            )
            g.conn.commit()
            app.logger.info("Formulario creado '%s' ip=%s", nombre, ip)
            flash("Formulario creado correctamente.")
            return redirect(url_for("administrar_formularios"))

    g.cursor.execute(
        """
        SELECT f.id,
               f.nombre,
               f.requiere_password,
               f.password_hash,
               a.id_usuario AS id_usuario,
               u.nombre      AS nombre_usuario,
               u.apellidos   AS apellidos_usuario,
               u.cargo       AS cargo_usuario,
               u.dependencia AS dependencia_usuario,
               COUNT(r.id)   AS respuestas
        FROM formulario f
        LEFT JOIN asignacion a ON a.id_formulario = f.id
        LEFT JOIN usuario u    ON u.id = a.id_usuario
        LEFT JOIN respuesta r  ON r.id_formulario = f.id AND r.bloqueado = 1
        GROUP BY f.id, f.nombre, f.requiere_password, f.password_hash,
                 a.id_usuario, u.nombre, u.apellidos, u.cargo, u.dependencia
        ORDER BY f.id
        """
    )
    formularios = g.cursor.fetchall()

    app.logger.info("Listado formularios ip=%s total=%s", ip, len(formularios))
    return render_template(
        "admin_formularios.html",
        formularios=formularios,
        default_name=default_name,
    )


@app.route("/admin/usuarios/<int:id_usuario>/editar", methods=["POST"])
def editar_usuario_admin(id_usuario: int):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    get_db()
    nombre = sanitize(request.form.get("nombre", "").strip())
    apellidos = sanitize(request.form.get("apellidos", "").strip())
    cargo = sanitize(request.form.get("cargo", "").strip())
    dependencia = sanitize(request.form.get("dependencia", "").strip())

    if not nombre or not apellidos:
        flash("Nombre y apellidos son obligatorios.")
        return redirect(url_for("administrar_formularios"))

    g.cursor.execute(
        "UPDATE usuario SET nombre=%s, apellidos=%s, cargo=%s, dependencia=%s WHERE id=%s",
        (nombre, apellidos, cargo or None, dependencia or None, id_usuario),
    )
    g.conn.commit()
    app.logger.info(
        "Usuario %s actualizado por admin: %s %s, cargo=%s, dependencia=%s",
        id_usuario,
        nombre,
        apellidos,
        cargo,
        dependencia,
    )
    flash("Datos del usuario actualizados correctamente.")
    return redirect(url_for("administrar_formularios"))


@app.route("/admin/formularios/eliminar/<int:id>", methods=["POST"])
def eliminar_formulario(id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    ip = request.remote_addr

    get_db()

    g.cursor.execute(
        "SELECT COUNT(*) AS total FROM respuesta WHERE id_formulario = %s AND bloqueado = 1",
        (id,),
    )
    total_respuestas = g.cursor.fetchone()["total"]
    app.logger.info(
        "Eliminar formulario %s ip=%s respuestas=%s", id, ip, total_respuestas
    )

    confirm = request.form.get("confirm")
    expected = request.form.get("expected_count")

    # Siempre solicitar confirmación, tenga o no respuestas
    if confirm != "yes":
        return render_template(
            "confirmar_eliminacion_formulario.html",
            id_formulario=id,
            respuestas=total_respuestas,
        )

    if confirm == "yes":
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            expected = None
        if expected is not None:
            g.cursor.execute(
                "SELECT COUNT(*) AS total FROM respuesta WHERE id_formulario = %s AND bloqueado = 1",
                (id,),
            )
            total_actual = g.cursor.fetchone()["total"]
            if total_actual != expected:
                flash("El número de respuestas cambió; operación cancelada.")
                return redirect(url_for("administrar_formularios"))

        g.cursor.execute("DELETE FROM respuesta WHERE id_formulario = %s", (id,))
        g.cursor.execute("DELETE FROM asignacion WHERE id_formulario = %s", (id,))
        g.cursor.execute("DELETE FROM formulario WHERE id = %s", (id,))
        g.conn.commit()
        cache.clear()
        invalidate_ranking_cache()
        app.logger.info("Formulario %s eliminado ip=%s", id, ip)
        flash("Formulario eliminado correctamente.")
        return redirect(url_for("administrar_formularios"))

    app.logger.info("Eliminación cancelada formulario=%s ip=%s", id, ip)
    flash("Eliminación cancelada.")
    return redirect(url_for("administrar_formularios"))


@app.route("/admin/formularios/reiniciar", methods=["POST"])
def reiniciar_formularios():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    ip = request.remote_addr
    get_db()
    app.logger.info("Reiniciar formularios ip=%s", ip)

    g.cursor.execute("DELETE FROM ponderacion_admin")
    g.cursor.execute("DELETE FROM respuesta_detalle")
    g.cursor.execute("DELETE FROM respuesta")
    g.conn.commit()
    cache.clear()
    invalidate_ranking_cache()
    app.logger.info("Reinicio completado ip=%s", ip)
    flash("Todos los formularios han sido reiniciados.")
    return redirect(url_for("administrar_formularios"))


@app.route("/admin/ponderacion_universal", methods=["GET", "POST"])
def ponderacion_universal():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        valor_str = request.form.get("valor")
        try:
            valor = Decimal(valor_str)
        except (InvalidOperation, TypeError):
            flash("El valor debe ser numérico.")
            return redirect(url_for("ponderacion_universal"))
        if not (Decimal("0") <= valor <= Decimal("10")):
            flash("El valor debe estar entre 0 y 10.")
            return redirect(url_for("ponderacion_universal"))

        get_db()
        g.cursor.execute("SELECT id FROM respuesta")
        ids_respuesta = [row["id"] for row in g.cursor.fetchall()]
        factores = get_factores()

        g.cursor.execute("DELETE FROM ponderacion_admin")
        valores = [
            (id_resp, f["id"], valor)
            for id_resp in ids_respuesta
            for f in factores
        ]
        if valores:
            g.cursor.executemany(
                "INSERT INTO ponderacion_admin (id_respuesta, id_factor, peso_admin) VALUES (%s, %s, %s)",
                valores,
            )
        g.conn.commit()
        invalidate_ranking_cache()
        flash("Ponderación universal aplicada correctamente.")
        return redirect(url_for("panel_admin"))

    return render_template("admin_ponderacion_universal.html")


@app.route("/admin/formularios/abrir/<int:id_respuesta>", methods=["POST"])
def abrir_respuesta(id_respuesta):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    ip = request.remote_addr

    get_db()
    g.cursor.execute(
        "SELECT id_usuario, id_formulario FROM respuesta WHERE id = %s",
        (id_respuesta,),
    )
    datos = g.cursor.fetchone()
    g.cursor.execute(
        "UPDATE respuesta SET bloqueado = 0 WHERE id = %s",
        (id_respuesta,),
    )
    g.conn.commit()
    if datos:
        invalidate_bloqueo_cache(datos["id_usuario"], datos["id_formulario"])
        app.logger.info(
            "Respuesta %s reabierta usuario=%s formulario=%s ip=%s",
            id_respuesta,
            datos["id_usuario"],
            datos["id_formulario"],
            ip,
        )
    invalidate_ranking_cache()
    flash("Respuesta reabierta correctamente.")
    return redirect(url_for("panel_admin"))


@app.route("/admin/factores", methods=["GET", "POST"])
def administrar_factores():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    ip = request.remote_addr
    get_db()
    g.cursor.execute("SELECT * FROM factor ORDER BY id")
    factores = g.cursor.fetchall()
    app.logger.info("Admin factores inicio ip=%s total=%s", ip, len(factores))

    if request.method == "POST":
        try:
            # Limpiar cualquier estado previo
            try:
                g.conn.rollback()
            except Exception:
                pass
            g.conn.start_transaction()
            # Actualizar factores existentes
            for f in factores:
                nombre = request.form.get(f"nombre_{f['id']}")
                descripcion = request.form.get(f"descripcion_{f['id']}")
                color = request.form.get(f"color_{f['id']}")
                dimension_raw = request.form.get(f"dimension_{f['id']}")
                try:
                    dimension = int(dimension_raw)
                except (TypeError, ValueError):
                    dimension = f.get("dimension", 1)
                if dimension not in (1, 2):
                    dimension = 1
                g.cursor.execute(
                    "UPDATE factor SET nombre=%s, descripcion=%s, color=%s, dimension=%s WHERE id=%s",
                    (nombre, descripcion, color, dimension, f["id"]),
                )

            # Insertar un nuevo factor si se proporcionan los campos
            nuevo_nombre = request.form.get("nuevo_nombre")
            nuevo_descripcion = request.form.get("nuevo_descripcion")
            nuevo_color = request.form.get("nuevo_color")
            nuevo_factor = False
            nuevo_dimension_raw = request.form.get("nuevo_dimension")
            try:
                nuevo_dimension = int(nuevo_dimension_raw) if nuevo_dimension_raw else 1
            except ValueError:
                nuevo_dimension = 1
            if nuevo_dimension not in (1, 2):
                nuevo_dimension = 1
            if nuevo_nombre and nuevo_descripcion and nuevo_color:
                g.cursor.execute(
                    "INSERT INTO factor (nombre, descripcion, color, dimension) VALUES (%s, %s, %s, %s)",
                    (nuevo_nombre, nuevo_descripcion, nuevo_color, nuevo_dimension),
                )
                nuevo_factor = True

            g.conn.commit()
        except Exception:
            g.conn.rollback()
            app.logger.exception("Error al actualizar factores ip=%s", ip)
            flash("Error al actualizar los factores.")
            return redirect(url_for("administrar_factores"))

        invalidate_factores_cache()
        if nuevo_factor:
            flash("Nuevo factor agregado correctamente.")

        app.logger.info("Factores actualizados ip=%s", ip)
        flash("Factores actualizados correctamente.")
        return redirect(url_for("administrar_factores"))

    return render_template("admin_factores.html", factores=factores)


# ==============================
# DETALLE DE RESPUESTA (ADMIN)
# ==============================


@app.route("/admin/respuesta/<int:id_respuesta>")
def detalle_respuesta(id_respuesta):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    ip = request.remote_addr
    app.logger.info("detalle_respuesta inicio id=%s ip=%s", id_respuesta, ip)
    get_db()
    # Datos generales
    g.cursor.execute(
        """
    SELECT r.id AS id_respuesta,
           u.nombre,
           u.apellidos,
           u.cargo,
           u.dependencia,
           f.nombre AS formulario
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        -- No filtramos por "bloqueado" para permitir revisar respuestas recién enviadas
        WHERE r.id = %s
    """,
        (id_respuesta,),
    )
    respuesta = g.cursor.fetchone()
    app.logger.info("Datos generales respuesta=%s", respuesta)

    # Factores con valor del usuario + ponderación previa
    g.cursor.execute(
        """
    SELECT rd.id_factor,
           fa.nombre,
           fa.descripcion,
           fa.color,
           fa.dimension,
           rd.valor_usuario,
           COALESCE(pa.peso_admin, '') AS peso_admin
        FROM respuesta_detalle rd
        JOIN factor fa ON rd.id_factor = fa.id
        LEFT JOIN ponderacion_admin pa
          ON pa.id_respuesta = rd.id_respuesta AND pa.id_factor = rd.id_factor
        WHERE rd.id_respuesta = %s
        ORDER BY fa.id
    """,
        (id_respuesta,),
    )
    factores = g.cursor.fetchall()
    app.logger.info(
        "Factores respuesta=%s total=%s", id_respuesta, len(factores)
    )

    # Ranking acumulado (de todas las ponderaciones globales)
    g.cursor.execute(
        """
        SELECT f.nombre, SUM(p.peso_admin * rd.valor_usuario) AS total
        FROM ponderacion_admin p
        JOIN respuesta_detalle rd ON rd.id_respuesta = p.id_respuesta AND rd.id_factor = p.id_factor
        JOIN factor f ON f.id = p.id_factor
        GROUP BY f.id, f.nombre
        ORDER BY total DESC
    """
    )
    ranking = g.cursor.fetchall()
    app.logger.info(
        "Ranking respuesta=%s total=%s", id_respuesta, len(ranking)
    )

    app.logger.info("Render detalle_respuesta id=%s", id_respuesta)
    return render_template(
        "admin_detalle.html", respuesta=respuesta, factores=factores, ranking=ranking
    )


# ==============================
# GUARDAR PONDERACIÓN (ADMIN)
# ==============================


@app.route("/admin/ponderar", methods=["POST"])
def guardar_ponderacion():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    ip = request.remote_addr
    id_respuesta_raw = request.form.get("id_respuesta")
    app.logger.info(
        "guardar_ponderacion inicio id_respuesta=%s ip=%s", id_respuesta_raw, ip
    )
    if not id_respuesta_raw:
        app.logger.info("Falta id_respuesta ip=%s", ip)
        flash("Falta el identificador de la respuesta.")
        return redirect(url_for("panel_admin"))
    try:
        id_respuesta = int(id_respuesta_raw)
    except ValueError:
        app.logger.info("id_respuesta inválido=%s ip=%s", id_respuesta_raw, ip)
        flash("El identificador de la respuesta debe ser un número entero.")
        return redirect(url_for("panel_admin"))

    get_db()

    factores = get_factores()
    ponderaciones = []

    for factor in factores:
        id_factor = factor["id"]
        valor = request.form.get(f"ponderacion_{id_factor}", "").strip()
        if valor:
            try:
                peso = Decimal(valor)
            except InvalidOperation:
                flash("Las ponderaciones deben ser valores numéricos.")
                return redirect(url_for("detalle_respuesta", id_respuesta=id_respuesta))

            if peso < 0 or peso > 10:
                flash("Cada ponderación debe estar entre 0 y 10.")
                return redirect(url_for("detalle_respuesta", id_respuesta=id_respuesta))

            peso = peso.quantize(Decimal("0.1"))
        else:
            peso = Decimal("0.0")
        ponderaciones.append((id_respuesta, id_factor, peso))

    try:
        g.cursor.execute(
            "DELETE FROM ponderacion_admin WHERE id_respuesta = %s", (id_respuesta,)
        )
        if ponderaciones:
            g.cursor.executemany(
                """
                    INSERT INTO ponderacion_admin (id_respuesta, id_factor, peso_admin)
                    VALUES (%s, %s, %s)
                """,
                ponderaciones,
            )
        g.conn.commit()
    except Exception as e:
        g.conn.rollback()
        app.logger.error(
            "Error al guardar ponderaciones id_respuesta=%s ip=%s error=%s",
            id_respuesta,
            ip,
            e,
        )
        flash(f"Error al guardar las ponderaciones: {e}")
        return redirect(url_for("detalle_respuesta", id_respuesta=id_respuesta))

    invalidate_ranking_cache()

    app.logger.info("Ponderaciones guardadas id_respuesta=%s ip=%s", id_respuesta, ip)
    flash("Ponderaciones guardadas correctamente.")
    return redirect(url_for("detalle_respuesta", id_respuesta=id_respuesta))


# ==============================
# RANKING DE FACTORES (ADMIN)
# ==============================


@app.route("/admin/ranking")
def vista_ranking():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    ip = request.remote_addr
    app.logger.info("vista_ranking inicio ip=%s", ip)
    get_db()
    # Contar formularios asignados y formularios con respuesta
    g.cursor.execute("SELECT COUNT(*) AS total FROM asignacion")
    total_asignados = g.cursor.fetchone()["total"]

    g.cursor.execute("SELECT COUNT(*) AS total FROM respuesta WHERE bloqueado = 1")
    total_respuestas = g.cursor.fetchone()["total"]

    g.cursor.execute("SELECT COUNT(*) AS total FROM respuesta WHERE bloqueado = 0")
    total_desbloqueados = g.cursor.fetchone()["total"]

    pendientes = total_respuestas < total_asignados
    hay_desbloqueados = total_desbloqueados > 0

    cached = cache.get(RANKING_CACHE_KEY)
    if cached is not None:
        ranking = cached["ranking"]
        incompletas = cached["incompletas"]
    else:
        count_factores = len(get_factores())
        # Respuestas incompletas (bloqueadas pero sin todas las ponderaciones)
        incompletas_query = """
            SELECT r.id AS id_respuesta
            FROM respuesta r
            LEFT JOIN ponderacion_admin p ON r.id = p.id_respuesta
            WHERE r.bloqueado = 1
            GROUP BY r.id
            HAVING COUNT(p.id_factor) < %s
        """
        g.cursor.execute(incompletas_query, (count_factores,))
        incompletas_rows = g.cursor.fetchall()
        incompletas = [row["id_respuesta"] for row in incompletas_rows]

        ranking_query = """
            SELECT f.nombre,
                   f.color,
                   SUM(pa.peso_admin * rd.valor_usuario) AS total
            FROM factor f
            JOIN ponderacion_admin pa ON f.id = pa.id_factor
            JOIN (
                SELECT id_respuesta
                FROM ponderacion_admin
                GROUP BY id_respuesta
                HAVING COUNT(id_factor) = %s
            ) rc ON pa.id_respuesta = rc.id_respuesta
            JOIN respuesta r ON r.id = rc.id_respuesta AND r.bloqueado = 1
            JOIN respuesta_detalle rd
                ON rd.id_respuesta = pa.id_respuesta AND rd.id_factor = f.id
            GROUP BY f.id, f.nombre, f.color
            ORDER BY total DESC
        """
        g.cursor.execute(ranking_query, (count_factores,))
        ranking = g.cursor.fetchall()

        cache.set(
            RANKING_CACHE_KEY,
            {"ranking": ranking, "incompletas": incompletas},
            timeout=CACHE_TTL,
        )

    # Métricas adicionales
    max_total = max((r.get("total") or 0) for r in ranking) if ranking else 0
    # Número de respuestas completas = total bloqueadas - incompletas
    completas_count = (total_respuestas - len(incompletas)) if total_respuestas else 0
    completas_pct = (completas_count / total_respuestas * 100) if total_respuestas else 0.0
    from datetime import datetime as _dt
    generated_at = _dt.utcnow()

    # Determinar si no hay datos
    estado_ranking = None
    if not ranking:
        estado_ranking = "sin_datos"
    app.logger.info(
        "vista_ranking resultados ip=%s total=%s", ip, len(ranking)
    )

    return render_template(
        "admin_ranking.html",
        ranking=ranking,
        pendientes=pendientes,
        total_asignados=total_asignados,
        total_respuestas=total_respuestas,
        incompletas=incompletas,
        estado_ranking=estado_ranking,
        hay_desbloqueados=hay_desbloqueados,
        max_total=max_total,
        completas_count=completas_count,
        completas_pct=completas_pct,
        generated_at=generated_at,
    )


@app.route("/admin/ranking/export_csv")
def export_ranking_csv():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    get_db()
    cached = cache.get(RANKING_CACHE_KEY)
    if cached is None:
        # Fuerza recalculo reutilizando la vista
        cache.delete(RANKING_CACHE_KEY)
        # Llamada interna lógica: replicamos parte menor necesaria
        count_factores = len(get_factores())
        ranking_query = """
            SELECT f.nombre,
                   f.color,
                   SUM(pa.peso_admin * rd.valor_usuario) AS total
            FROM factor f
            JOIN ponderacion_admin pa ON f.id = pa.id_factor
            JOIN (
                SELECT id_respuesta
                FROM ponderacion_admin
                GROUP BY id_respuesta
                HAVING COUNT(id_factor) = %s
            ) rc ON pa.id_respuesta = rc.id_respuesta
            JOIN respuesta r ON r.id = rc.id_respuesta AND r.bloqueado = 1
            JOIN respuesta_detalle rd
                ON rd.id_respuesta = pa.id_respuesta AND rd.id_factor = f.id
            GROUP BY f.id, f.nombre, f.color
            ORDER BY total DESC
        """
        g.cursor.execute(ranking_query, (count_factores,))
        ranking = g.cursor.fetchall()
    else:
        ranking = cached["ranking"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["puesto", "factor", "total", "color_hex"])
    for idx, r in enumerate(ranking, start=1):
        writer.writerow([idx, r.get("nombre"), r.get("total"), r.get("color")])
    csv_data = output.getvalue()
    output.close()
    # Asegurar BOM UTF-8 para compatibilidad (p.ej., Excel)
    csv_data = "\ufeff" + csv_data
    return Response(
        csv_data,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=ranking_factores.csv"},
    )


# ==============================
# ERRORES
# ==============================


@app.errorhandler(PoolExhaustedError)
def handle_pool_exhausted(error):
    app.logger.error("Pool de conexiones agotado: %s", error)
    return (
        "La base de datos está saturada. Intenta de nuevo más tarde.",
        503,
    )


@app.errorhandler(400)
def handle_bad_request(error):
    app.logger.error("Error 400: %s", error)
    return render_template("error_400.html"), 400


@app.errorhandler(404)
def handle_not_found(error):
    app.logger.error("Error 404: %s", error)
    return render_template("error_404.html"), 404


@app.errorhandler(500)
def handle_server_error(error):
    app.logger.error("Error 500: %s", error)
    return render_template("error_500.html"), 500


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    app.run(debug=True)
