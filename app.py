from flask import Flask, render_template, request, redirect, url_for, flash, session, g
import os
import mysql.connector
from decimal import Decimal, InvalidOperation
import time
from dotenv import load_dotenv
import bleach
from flask_caching import Cache
import logging
from logging.handlers import RotatingFileHandler

load_dotenv()

from db import get_connection

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DEBUG_LOGS_ENABLED = os.getenv("ENABLE_DEBUG_LOGS") == "1"


app = Flask(__name__)
app.secret_key = "clave-secreta-sencilla"

# Configuración de registro
os.makedirs("static/logs", exist_ok=True)
log_handler = RotatingFileHandler(
    "static/logs/app.log", maxBytes=1_048_576, backupCount=10
)
log_handler.setLevel(logging.DEBUG)
log_formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
log_handler.setFormatter(log_formatter)
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.DEBUG)

# Configuración de caché compartido
CACHE_TTL = int(os.getenv("RANKING_CACHE_TTL", 300))
cache = Cache(
    app,
    config={
        "CACHE_TYPE": os.getenv("CACHE_TYPE", "SimpleCache"),
        "CACHE_DEFAULT_TIMEOUT": CACHE_TTL,
    },
)
RANKING_CACHE_KEY = "ranking_cache"


def sanitize(texto: str) -> str:
    """Sanitize user-provided text by stripping HTML tags and scripts."""
    return bleach.clean(texto or "", tags=[], attributes={}, strip=True)


def invalidate_ranking_cache():
    """Reset ranking cache to force recomputation on next request."""
    cache.delete(RANKING_CACHE_KEY)


# Cache sencillo para los factores
FACTORES_CACHE = {"data": None, "timestamp": 0}
FACTORES_CACHE_TTL = int(os.getenv("FACTORES_CACHE_TTL", 300))


# Cache ligero para estado de bloqueo por (id_usuario, id_formulario)
BLOQUEO_CACHE = {}
BLOQUEO_CACHE_TTL = int(os.getenv("BLOQUEO_CACHE_TTL", 30))


def is_formulario_bloqueado(id_usuario: int, id_formulario: int) -> bool:
    """Devuelve True si el formulario está bloqueado para el usuario."""
    key = (id_usuario, id_formulario)
    now = time.time()
    entry = BLOQUEO_CACHE.get(key)
    if entry and now - entry["timestamp"] <= BLOQUEO_CACHE_TTL:
        return entry["bloqueado"]

    get_db()
    g.cursor.execute(
        "SELECT 1 FROM respuesta WHERE id_usuario = %s AND id_formulario = %s AND bloqueado = 1",
        (id_usuario, id_formulario),
    )
    bloqueado = g.cursor.fetchone() is not None
    BLOQUEO_CACHE[key] = {"bloqueado": bloqueado, "timestamp": now}
    return bloqueado


def invalidate_bloqueo_cache(id_usuario: int, id_formulario: int):
    """Elimina la entrada de caché para un usuario y formulario.

    Esta función debe llamarse tras cualquier operación que modifique el
    campo ``bloqueado`` para evitar inconsistencias visibles entre el estado
    real y el estado almacenado en caché.
    """
    BLOQUEO_CACHE.pop((id_usuario, id_formulario), None)


def get_factores():
    """Obtiene la lista de factores usando caché en memoria."""
    now = time.time()
    if (
        FACTORES_CACHE["data"] is None
        or now - FACTORES_CACHE["timestamp"] > FACTORES_CACHE_TTL
    ):
        g.cursor.execute("SELECT * FROM factor")
        FACTORES_CACHE["data"] = g.cursor.fetchall()
        FACTORES_CACHE["timestamp"] = now
    return FACTORES_CACHE["data"]


def invalidate_factores_cache():
    """Reinicia el caché de factores y del ranking relacionado."""
    FACTORES_CACHE["data"] = None
    FACTORES_CACHE["timestamp"] = 0
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
    """Evita el cacheo de páginas protegidas para rutas de administrador."""
    if request.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ==============================
# RUTAS DE DEPURACIÓN
# ==============================


@app.route("/debug/logs_test")
def debug_logs_test():
    if not DEBUG_LOGS_ENABLED:
        return "Not found", 404
    return render_template("logs_test.html")


@app.route("/debug/logs")
def debug_logs():
    if not DEBUG_LOGS_ENABLED:
        return "Not found", 404
    log_path = os.path.join("static", "logs", "app.log")
    if not os.path.exists(log_path):
        return "", 200, {"Content-Type": "text/plain; charset=utf-8"}
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()
    return (
        content,
        200,
        {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-cache"},
    )


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
        SELECT a.id_formulario, f.nombre AS nombre_formulario
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
        return "No se encontró un formulario asignado."

    id_formulario = asignacion["id_formulario"]

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

    # 1. Leer los valores únicos de los factores
    valores = []
    try:
        for i in range(1, num_factores + 1):
            factor_key = f"factor_id_{i}"
            valor_key = f"valor_{i}"
            if factor_key not in request.form or valor_key not in request.form:
                flash(f"Faltan datos para el factor {i}.")
                return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))
            factor_id = int(request.form[factor_key])
            valor = int(request.form[valor_key])
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
    if len(set(usados)) != num_factores:
        flash(f"Cada valor del 1 al {num_factores} debe ser único. No se permiten duplicados.")
        return redirect(url_for("mostrar_formulario", id_usuario=id_usuario))

    # 2. Guardar información en la base de datos dentro de una transacción
    try:
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
            (id_usuario, id_formulario, 1),
        )
        id_respuesta = g.cursor.lastrowid

        # Insertar detalle de factores
        detalles = [(id_respuesta, factor_id, valor) for factor_id, valor in valores]
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
    if exit_redirect:
        app.logger.info(
            "Respuesta guardada usuario=%s formulario=%s con redireccion",
            id_usuario,
            id_formulario,
        )
        return redirect(url_for("index"))
    app.logger.info(
        "Respuesta guardada usuario=%s formulario=%s",
        id_usuario,
        id_formulario,
    )
    return render_template("confirmacion.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")
        ip = request.remote_addr
        app.logger.info("Intento login admin ip=%s", ip)
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
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
    per_page = 10
    offset = (page - 1) * per_page
    app.logger.info("panel_admin inicio ip=%s page=%s", ip, page)
    g.cursor.execute(
        """
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
        ORDER BY r.fecha_respuesta DESC
        LIMIT %s OFFSET %s
        """,
        (per_page + 1, offset),
    )
    respuestas = g.cursor.fetchall()
    has_next = len(respuestas) > per_page
    if has_next:
        respuestas = respuestas[:-1]
    app.logger.info(
        "panel_admin respuestas=%s ip=%s page=%s",
        len(respuestas),
        ip,
        page,
    )

    return render_template(
        "admin.html", respuestas=respuestas, page=page, has_next=has_next
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
        nombre = request.form.get("nombre", "").strip() or default_name
        g.cursor.execute(
            "INSERT INTO formulario (nombre) VALUES (%s)",
            (nombre,),
        )
        g.conn.commit()
        app.logger.info("Formulario creado '%s' ip=%s", nombre, ip)
        flash("Formulario creado correctamente.")
        return redirect(url_for("administrar_formularios"))

    g.cursor.execute(
        """
        SELECT f.id, f.nombre, COUNT(r.id) AS respuestas
        FROM formulario f
        LEFT JOIN respuesta r
          ON r.id_formulario = f.id
         AND r.bloqueado = 1
        GROUP BY f.id, f.nombre
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

    if total_respuestas > 0 and confirm != "yes":
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
        for (uid, fid) in list(BLOQUEO_CACHE.keys()):
            if fid == id:
                invalidate_bloqueo_cache(uid, fid)
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
    for key in list(BLOQUEO_CACHE.keys()):
        invalidate_bloqueo_cache(*key)
    invalidate_ranking_cache()
    app.logger.info("Reinicio completado ip=%s", ip)
    flash("Todos los formularios han sido reiniciados.")
    return redirect(url_for("administrar_formularios"))


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
            g.conn.start_transaction()

            # Actualizar los factores existentes
            for f in factores:
                nombre = request.form.get(f"nombre_{f['id']}")
                descripcion = request.form.get(f"descripcion_{f['id']}")
                color = request.form.get(f"color_{f['id']}")
                g.cursor.execute(
                    "UPDATE factor SET nombre=%s, descripcion=%s, color=%s WHERE id=%s",
                    (nombre, descripcion, color, f["id"]),
                )

            # Insertar un nuevo factor si se proporcionan los campos
            nuevo_nombre = request.form.get("nuevo_nombre")
            nuevo_descripcion = request.form.get("nuevo_descripcion")
            nuevo_color = request.form.get("nuevo_color")
            nuevo_factor = False
            if nuevo_nombre and nuevo_descripcion and nuevo_color:
                g.cursor.execute(
                    "INSERT INTO factor (nombre, descripcion, color) VALUES (%s, %s, %s)",
                    (nuevo_nombre, nuevo_descripcion, nuevo_color),
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
        SELECT r.id AS id_respuesta, u.nombre, u.apellidos, f.nombre AS formulario
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
        SELECT rd.id_factor, fa.nombre, fa.descripcion, rd.valor_usuario,
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
        # Número de factores a considerar en las consultas
        count_factores = len(get_factores())

        # Detectar respuestas con ponderaciones incompletas
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
    )


# ==============================
# ERRORES
# ==============================


@app.errorhandler(400)
def handle_bad_request(error):
    return render_template("error_400.html"), 400


@app.errorhandler(404)
def handle_not_found(error):
    return render_template("error_404.html"), 404


@app.errorhandler(500)
def handle_server_error(error):
    return render_template("error_500.html"), 500


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    app.run(debug=True)
