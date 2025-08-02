from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import mysql.connector
from collections import defaultdict
from dotenv import load_dotenv
load_dotenv()

from db import get_connection, get_cursor

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")



app = Flask(__name__)
app.secret_key = 'clave-secreta-sencilla'

# Conexión a la base de datos
conn = get_connection()
cursor = get_cursor(conn)


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
    # Obtener el formulario asignado
    cursor.execute("""
        SELECT a.id_formulario, f.nombre AS nombre_formulario
        FROM asignacion a
        JOIN formulario f ON a.id_formulario = f.id
        WHERE a.id_usuario = %s
    """, (id_usuario,))
    asignacion = cursor.fetchone()

    if not asignacion:
        return "No se encontró un formulario asignado."

    id_formulario = asignacion['id_formulario']

    # Obtener factores
    cursor.execute("SELECT * FROM factor")
    factores = cursor.fetchall()

    # Obtener datos del usuario
    cursor.execute("SELECT * FROM usuario WHERE id = %s", (id_usuario,))
    usuario = cursor.fetchone()

    # Obtener respuestas anteriores (si existen)
    cursor.execute("""
        SELECT rd.id_factor, rd.valor_usuario
        FROM respuesta r
        JOIN respuesta_detalle rd ON r.id = rd.id_respuesta
        WHERE r.id_usuario = %s AND r.id_formulario = %s
    """, (id_usuario, id_formulario))
    respuestas_previas = cursor.fetchall()

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

    # Datos personales
    nombre = request.form['nombre'].strip()
    apellidos = request.form['apellidos'].strip()
    cargo = request.form['cargo'].strip()
    dependencia = request.form['dependencia'].strip()

    # 1. Actualizar los datos del usuario
    cursor.execute("""
        UPDATE usuario
        SET nombre = %s,
            apellidos = %s,
            cargo = %s,
            dependencia = %s
        WHERE id = %s
    """, (nombre, apellidos, cargo, dependencia, id_usuario))
    conn.commit()

    # 2. Verificar si ya hay una respuesta existente → si sí, eliminarla
    cursor.execute("""
        SELECT id FROM respuesta
        WHERE id_usuario = %s AND id_formulario = %s
    """, (id_usuario, id_formulario))
    anterior = cursor.fetchone()

    if anterior:
        id_anterior = anterior['id']
        # Eliminar ponderaciones si existen
        cursor.execute("DELETE FROM ponderacion_admin WHERE id_respuesta = %s", (id_anterior,))
        cursor.execute("DELETE FROM respuesta_detalle WHERE id_respuesta = %s", (id_anterior,))
        cursor.execute("DELETE FROM respuesta WHERE id = %s", (id_anterior,))
        conn.commit()

    # 3. Leer los 10 valores únicos de los factores
    valores = []
    for i in range(1, 11):
        factor_id = int(request.form[f'factor_id_{i}'])
        valor = int(request.form[f'valor_{i}'])
        valores.append((factor_id, valor))

    usados = [v[1] for v in valores]
    if len(set(usados)) != 10:
        flash("Cada valor del 1 al 10 debe ser único. No se permiten duplicados.")
        return redirect(url_for('mostrar_formulario', id_usuario=id_usuario))

    # 4. Insertar nueva respuesta
    cursor.execute("""
        INSERT INTO respuesta (id_usuario, id_formulario)
        VALUES (%s, %s)
    """, (id_usuario, id_formulario))
    conn.commit()
    id_respuesta = cursor.lastrowid

    # 5. Insertar detalle de factores
    for factor_id, valor in valores:
        cursor.execute("""
            INSERT INTO respuesta_detalle (id_respuesta, id_factor, valor_usuario)
            VALUES (%s, %s, %s)
        """, (id_respuesta, factor_id, valor))
    conn.commit()

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
    cursor.execute("""
        SELECT r.id AS id_respuesta, u.nombre, u.apellidos, f.nombre AS formulario, r.fecha_respuesta
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        ORDER BY r.fecha_respuesta DESC
    """)
    respuestas = cursor.fetchall()

    return render_template('admin.html', respuestas=respuestas)

# ==============================
# DETALLE DE RESPUESTA (ADMIN)
# ==============================

@app.route('/admin/respuesta/<int:id_respuesta>')
def detalle_respuesta(id_respuesta):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    # Datos generales
    cursor.execute("""
        SELECT r.id AS id_respuesta, u.nombre, u.apellidos, f.nombre AS formulario
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        WHERE r.id = %s
    """, (id_respuesta,))
    respuesta = cursor.fetchone()

    # Factores con valor del usuario + ponderación previa
    cursor.execute("""
        SELECT rd.id_factor, fa.nombre, fa.descripcion, rd.valor_usuario,
               COALESCE(pa.peso_admin, '') AS peso_admin
        FROM respuesta_detalle rd
        JOIN factor fa ON rd.id_factor = fa.id
        LEFT JOIN ponderacion_admin pa
          ON pa.id_respuesta = rd.id_respuesta AND pa.id_factor = rd.id_factor
        WHERE rd.id_respuesta = %s
        ORDER BY fa.id
    """, (id_respuesta,))
    factores = cursor.fetchall()

    # Ranking acumulado (de todas las ponderaciones globales)
    cursor.execute("""
        SELECT f.nombre, SUM(p.peso_admin * rd.valor_usuario) AS total
        FROM ponderacion_admin p
        JOIN respuesta_detalle rd ON rd.id_respuesta = p.id_respuesta AND rd.id_factor = p.id_factor
        JOIN factor f ON f.id = p.id_factor
        GROUP BY f.id
        ORDER BY total DESC
    """)
    ranking = cursor.fetchall()

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
        if key.startswith('ponderacion_') and value.strip() != '':
            id_factor = key.split('_')[1]
            ponderaciones.append((id_respuesta, id_factor, float(value)))

    for id_respuesta, id_factor, peso in ponderaciones:
        # UPSERT (actualizar si existe, insertar si no)
        cursor.execute("""
            INSERT INTO ponderacion_admin (id_respuesta, id_factor, peso_admin)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE peso_admin = VALUES(peso_admin)
        """, (id_respuesta, id_factor, peso))
    conn.commit()

    flash("Ponderaciones guardadas correctamente.")
    return redirect(url_for('detalle_respuesta', id_respuesta=id_respuesta))

# ==============================
# RANKING DE FACTORES (ADMIN)
# ==============================

@app.route('/admin/ranking')
def vista_ranking():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    cursor.execute("""
        SELECT f.nombre, SUM(p.peso_admin * rd.valor_usuario) AS total
        FROM ponderacion_admin p
        JOIN respuesta_detalle rd ON rd.id_respuesta = p.id_respuesta AND rd.id_factor = p.id_factor
        JOIN factor f ON f.id = p.id_factor
        GROUP BY f.id
        ORDER BY total DESC
    """)
    ranking = cursor.fetchall()
    return render_template('admin_ranking.html', ranking=ranking)


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
