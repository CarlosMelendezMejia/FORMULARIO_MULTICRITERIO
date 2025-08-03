from flask import Flask, render_template, request, redirect, url_for, flash, session, g
import os
import mysql.connector
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
load_dotenv()

from db import get_connection

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")



app = Flask(__name__)
app.secret_key = 'clave-secreta-sencilla'


@app.before_request
def before_request():
    g.conn = get_connection()
    g.cursor = g.conn.cursor(dictionary=True)


@app.teardown_appcontext
def teardown_db(exception):
    cursor = g.pop('cursor', None)
    if cursor is not None:
        cursor.close()
    conn = g.pop('conn', None)
    if conn is not None:
        conn.close()


@app.after_request
def add_no_cache_headers(response):
    """Evita el cacheo de páginas protegidas para rutas de administrador."""
    if request.path.startswith('/admin'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# ==============================
# RUTA PRINCIPAL
# ==============================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/formulario_redirect', methods=['POST'])
def formulario_redirect():
    usuario_id = request.form['usuario_id']
    return redirect(url_for('mostrar_formulario', id_usuario=usuario_id))



# ==============================
# RUTA PARA FORMULARIO DE USUARIO
# ==============================



@app.route('/formulario/<int:id_usuario>')
def mostrar_formulario(id_usuario):
    """Muestra el formulario asignado al usuario.

    Se selecciona directamente el primer formulario asignado que no tenga
    respuestas previas. Si todos los formularios ya tienen respuesta, se
    elige el primero asignado.
    """

    g.cursor.execute(
        """
        SELECT a.id_formulario, f.nombre AS nombre_formulario
        FROM asignacion a
        JOIN formulario f ON a.id_formulario = f.id
        LEFT JOIN respuesta r
            ON r.id_usuario = a.id_usuario AND r.id_formulario = a.id_formulario
        WHERE a.id_usuario = %s
        ORDER BY r.id IS NOT NULL, a.id_formulario
        LIMIT 1
        """,
        (id_usuario,),
    )
    asignacion = g.cursor.fetchone()

    if not asignacion:
        return "No se encontró un formulario asignado."

    id_formulario = asignacion["id_formulario"]

    # Obtener factores
    g.cursor.execute("SELECT * FROM factor")
    factores = g.cursor.fetchall()

    # Obtener datos del usuario
    g.cursor.execute("SELECT * FROM usuario WHERE id = %s", (id_usuario,))
    usuario = g.cursor.fetchone()

    # Obtener respuestas anteriores (si existen)
    g.cursor.execute("""
        SELECT rd.id_factor, rd.valor_usuario
        FROM respuesta r
        JOIN respuesta_detalle rd ON r.id = rd.id_respuesta
        WHERE r.id_usuario = %s AND r.id_formulario = %s
    """, (id_usuario, id_formulario))
    respuestas_previas = g.cursor.fetchall()

    # Convertir a diccionario {id_factor: valor}
    respuestas_dict = {r['id_factor']: r['valor_usuario'] for r in respuestas_previas}

    return render_template(
        'formulario.html',
        usuario_id=id_usuario,
        formulario=asignacion,
        factores=factores,
        usuario=usuario,
        respuestas_previas=respuestas_dict
    )

# ==============================
# GUARDAR RESPUESTA DE FORMULARIO
# ==============================

@app.route('/guardar_respuesta', methods=['POST'])
def guardar_respuesta():
    id_usuario = int(request.form['usuario_id'])
    id_formulario = int(request.form['formulario_id'])
    exit_redirect = request.form.get('exit_redirect')

    # Datos personales
    nombre = request.form['nombre'].strip()
    apellidos = request.form['apellidos'].strip()
    cargo = request.form['cargo'].strip()
    dependencia = request.form['dependencia'].strip()

    # 1. Actualizar los datos del usuario
    g.cursor.execute("""
        UPDATE usuario
        SET nombre = %s,
            apellidos = %s,
            cargo = %s,
            dependencia = %s
        WHERE id = %s
    """, (nombre, apellidos, cargo, dependencia, id_usuario))
    g.conn.commit()

    # 2. Verificar si ya hay una respuesta existente → si sí, eliminarla
    g.cursor.execute("""
        SELECT id FROM respuesta
        WHERE id_usuario = %s AND id_formulario = %s
    """, (id_usuario, id_formulario))
    anterior = g.cursor.fetchone()

    if anterior:
        id_anterior = anterior['id']
        # Eliminar ponderaciones si existen
        g.cursor.execute("DELETE FROM ponderacion_admin WHERE id_respuesta = %s", (id_anterior,))
        g.cursor.execute("DELETE FROM respuesta_detalle WHERE id_respuesta = %s", (id_anterior,))
        g.cursor.execute("DELETE FROM respuesta WHERE id = %s", (id_anterior,))
        g.conn.commit()

    # 3. Leer los 10 valores únicos de los factores
    valores = []
    for i in range(1, 11):
        factor_id = int(request.form[f'factor_id_{i}'])
        valor = int(request.form[f'valor_{i}'])
        if not 1 <= valor <= 10:
            flash("Cada valor debe estar entre 1 y 10.")
            return redirect(url_for('mostrar_formulario', id_usuario=id_usuario))
        valores.append((factor_id, valor))

    usados = [v[1] for v in valores]
    if len(set(usados)) != 10:
        flash("Cada valor del 1 al 10 debe ser único. No se permiten duplicados.")
        return redirect(url_for('mostrar_formulario', id_usuario=id_usuario))

    # 4. Insertar nueva respuesta
    try:
        g.cursor.execute("""
            INSERT INTO respuesta (id_usuario, id_formulario)
            VALUES (%s, %s)
        """, (id_usuario, id_formulario))
        g.conn.commit()
        id_respuesta = g.cursor.lastrowid
    except mysql.connector.IntegrityError:
        g.conn.rollback()
        flash("Ya se registró una respuesta para este formulario.")
        return redirect(url_for('mostrar_formulario', id_usuario=id_usuario))

    # 5. Insertar detalle de factores
    detalles = [(id_respuesta, factor_id, valor) for factor_id, valor in valores]
    g.cursor.executemany(
        """
            INSERT INTO respuesta_detalle (id_respuesta, id_factor, valor_usuario)
            VALUES (%s, %s, %s)
        """,
        detalles,
    )
    g.conn.commit()
    if exit_redirect:
        return redirect(url_for('index'))
    return render_template('confirmacion.html')



@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('panel_admin'))
        flash('Contraseña incorrecta.')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))


# ==============================
# PANEL DE ADMINISTRADOR (resumen)
# ==============================

@app.route('/admin')
def panel_admin():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    g.cursor.execute("""
        SELECT r.id AS id_respuesta, u.nombre, u.apellidos, f.nombre AS formulario, r.fecha_respuesta
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        ORDER BY r.fecha_respuesta DESC
    """)
    respuestas = g.cursor.fetchall()

    return render_template('admin.html', respuestas=respuestas)


@app.route('/admin/formularios', methods=['GET', 'POST'])
def administrar_formularios():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    # Obtener el próximo ID para sugerir un nombre por defecto
    g.cursor.execute(
        """
        SELECT AUTO_INCREMENT AS siguiente_id
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'formulario'
        """
    )
    siguiente_id = g.cursor.fetchone()["siguiente_id"]
    default_name = f"Formulario {siguiente_id:02d}"

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip() or default_name
        g.cursor.execute(
            "INSERT INTO formulario (nombre) VALUES (%s)",
            (nombre,),
        )
        g.conn.commit()
        flash("Formulario creado correctamente.")
        return redirect(url_for('administrar_formularios'))

    g.cursor.execute(
        """
        SELECT f.id, f.nombre, COUNT(r.id) AS respuestas
        FROM formulario f
        LEFT JOIN respuesta r ON r.id_formulario = f.id
        GROUP BY f.id, f.nombre
        ORDER BY f.id
        """
    )
    formularios = g.cursor.fetchall()

    return render_template(
        'admin_formularios.html',
        formularios=formularios,
        default_name=default_name,
    )


@app.route('/admin/formularios/eliminar/<int:id>', methods=['POST'])
def eliminar_formulario(id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    g.cursor.execute(
        "SELECT COUNT(*) AS total FROM respuesta WHERE id_formulario = %s",
        (id,),
    )
    total_respuestas = g.cursor.fetchone()["total"]

    confirm = request.form.get('confirm')
    expected = request.form.get('expected_count')

    if total_respuestas > 0 and confirm != 'yes':
        return render_template(
            'confirmar_eliminacion_formulario.html',
            id_formulario=id,
            respuestas=total_respuestas,
        )

    if confirm == 'yes':
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            expected = None
        if expected is not None:
            g.cursor.execute(
                "SELECT COUNT(*) AS total FROM respuesta WHERE id_formulario = %s",
                (id,),
            )
            total_actual = g.cursor.fetchone()["total"]
            if total_actual != expected:
                flash("El número de respuestas cambió; operación cancelada.")
                return redirect(url_for('administrar_formularios'))

        g.cursor.execute("DELETE FROM respuesta WHERE id_formulario = %s", (id,))
        g.cursor.execute("DELETE FROM asignacion WHERE id_formulario = %s", (id,))
        g.cursor.execute("DELETE FROM formulario WHERE id = %s", (id,))
        g.conn.commit()
        flash("Formulario eliminado correctamente.")
        return redirect(url_for('administrar_formularios'))

    flash("Eliminación cancelada.")
    return redirect(url_for('administrar_formularios'))


@app.route('/admin/factores', methods=['GET', 'POST'])
def administrar_factores():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        for i in range(1, 11):
            nombre = request.form.get(f'nombre_{i}')
            descripcion = request.form.get(f'descripcion_{i}')
            g.cursor.execute(
                "UPDATE factor SET nombre=%s, descripcion=%s WHERE id=%s",
                (nombre, descripcion, i)
            )
        g.conn.commit()
        flash("Factores actualizados correctamente.")
        return redirect(url_for('administrar_factores'))

    g.cursor.execute("SELECT * FROM factor ORDER BY id")
    factores = g.cursor.fetchall()
    return render_template('admin_factores.html', factores=factores)

# ==============================
# DETALLE DE RESPUESTA (ADMIN)
# ==============================

@app.route('/admin/respuesta/<int:id_respuesta>')
def detalle_respuesta(id_respuesta):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    # Datos generales
    g.cursor.execute("""
        SELECT r.id AS id_respuesta, u.nombre, u.apellidos, f.nombre AS formulario
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        WHERE r.id = %s
    """, (id_respuesta,))
    respuesta = g.cursor.fetchone()

    # Factores con valor del usuario + ponderación previa
    g.cursor.execute("""
        SELECT rd.id_factor, fa.nombre, fa.descripcion, rd.valor_usuario,
               COALESCE(pa.peso_admin, '') AS peso_admin
        FROM respuesta_detalle rd
        JOIN factor fa ON rd.id_factor = fa.id
        LEFT JOIN ponderacion_admin pa
          ON pa.id_respuesta = rd.id_respuesta AND pa.id_factor = rd.id_factor
        WHERE rd.id_respuesta = %s
        ORDER BY fa.id
    """, (id_respuesta,))
    factores = g.cursor.fetchall()

    # Ranking acumulado (de todas las ponderaciones globales)
    g.cursor.execute("""
        SELECT f.nombre, SUM(p.peso_admin * rd.valor_usuario) AS total
        FROM ponderacion_admin p
        JOIN respuesta_detalle rd ON rd.id_respuesta = p.id_respuesta AND rd.id_factor = p.id_factor
        JOIN factor f ON f.id = p.id_factor
        GROUP BY f.id
        ORDER BY total DESC
    """)
    ranking = g.cursor.fetchall()

    return render_template(
        'admin_detalle.html',
        respuesta=respuesta,
        factores=factores,
        ranking=ranking
    )


# ==============================
# GUARDAR PONDERACIÓN (ADMIN)
# ==============================

@app.route('/admin/ponderar', methods=['POST'])
def guardar_ponderacion():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    id_respuesta = request.form['id_respuesta']
    ponderaciones = []

    for key, value in request.form.items():
        if not key.startswith('ponderacion_'):
            continue
        valor = value.strip()
        if valor == '':
            continue
        try:
            peso = Decimal(valor)
        except InvalidOperation:
            flash("Las ponderaciones deben ser valores numéricos.")
            return redirect(url_for('detalle_respuesta', id_respuesta=id_respuesta))

        if peso < 0 or peso > 10:
            flash("Cada ponderación debe estar entre 0 y 10.")
            return redirect(url_for('detalle_respuesta', id_respuesta=id_respuesta))

        peso = peso.quantize(Decimal('0.1'))
        id_factor = key.split('_')[1]
        ponderaciones.append((id_respuesta, id_factor, float(peso)))

    if ponderaciones:
        g.cursor.executemany(
            """
                INSERT INTO ponderacion_admin (id_respuesta, id_factor, peso_admin)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE peso_admin = VALUES(peso_admin)
            """,
            ponderaciones,
        )
    g.conn.commit()

    flash("Ponderaciones guardadas correctamente.")
    return redirect(url_for('detalle_respuesta', id_respuesta=id_respuesta))

# ==============================
# RANKING DE FACTORES (ADMIN)
# ==============================

@app.route('/admin/ranking')
def vista_ranking():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    # Contar formularios asignados y formularios con respuesta
    g.cursor.execute("SELECT COUNT(*) AS total FROM asignacion")
    total_asignados = g.cursor.fetchone()["total"]

    g.cursor.execute("SELECT COUNT(*) AS total FROM respuesta")
    total_respuestas = g.cursor.fetchone()["total"]

    pendientes = total_respuestas < total_asignados

    # Contar ponderaciones por respuesta para detectar incompletas
    g.cursor.execute(
        """
        SELECT r.id AS id_respuesta, COUNT(p.id_factor) AS total
        FROM respuesta r
        LEFT JOIN ponderacion_admin p ON r.id = p.id_respuesta
        GROUP BY r.id
        """
    )
    ponderaciones = g.cursor.fetchall()
    incompletas = [row["id_respuesta"] for row in ponderaciones if row["total"] < 10]

    # Generar ranking excluyendo respuestas incompletas e incluyendo factores sin ponderación
    join_condition = "f.id = p.id_factor"
    params = ()
    if incompletas:
        placeholders = ",".join(["%s"] * len(incompletas))
        join_condition += f" AND p.id_respuesta NOT IN ({placeholders})"
        params = tuple(incompletas)
    ranking_query = f"""
        SELECT f.nombre, SUM(COALESCE(p.peso_admin,0) * COALESCE(rd.valor_usuario,0)) AS total
        FROM factor f
        LEFT JOIN ponderacion_admin p ON {join_condition}
        LEFT JOIN respuesta_detalle rd ON rd.id_respuesta = p.id_respuesta AND rd.id_factor = f.id
        GROUP BY f.id ORDER BY total DESC
        """
    g.cursor.execute(ranking_query, params)
    ranking = g.cursor.fetchall()

    # Determinar si no hay datos
    estado_ranking = None
    if not ranking:
        estado_ranking = "sin_datos"

    return render_template(
        'admin_ranking.html',
        ranking=ranking,
        pendientes=pendientes,
        total_asignados=total_asignados,
        total_respuestas=total_respuestas,
        incompletas=incompletas,
        estado_ranking=estado_ranking,
    )


# ==============================
# ERRORES
# ==============================

@app.errorhandler(400)
def handle_bad_request(error):
    return render_template('error_400.html'), 400

@app.errorhandler(404)
def handle_bad_request(error):
    return render_template('error_404.html'), 404

@app.errorhandler(500)
def handle_server_error(error):
    return render_template('error_500.html'), 500

# ==============================
# MAIN
# ==============================

if __name__ == '__main__':
    app.run(debug=True)
