from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector
from collections import defaultdict

from db import get_connection, get_cursor




app = Flask(__name__)
app.secret_key = 'clave-secreta-sencilla'

# Conexión a la base de datos
conn = get_connection()
cursor = get_cursor(conn)

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
    # Obtener el formulario asignado al usuario
    cursor.execute("""
        SELECT a.id_formulario, f.nombre AS nombre_formulario
        FROM asignacion a
        JOIN formulario f ON a.id_formulario = f.id
        WHERE a.id_usuario = %s
    """, (id_usuario,))
    asignacion = cursor.fetchone()

    if not asignacion:
        return "No se encontró un formulario asignado."

    # Obtener factores
    cursor.execute("SELECT * FROM factor")
    factores = cursor.fetchall()

    return render_template('formulario.html', usuario_id=id_usuario, formulario=asignacion, factores=factores)

# ==============================
# GUARDAR RESPUESTA DE FORMULARIO
# ==============================

@app.route('/guardar_respuesta', methods=['POST'])
def guardar_respuesta():
    id_usuario = request.form['usuario_id']
    id_formulario = request.form['formulario_id']
    
    # Extraer los valores y verificar unicidad
    valores = []
    for i in range(1, 11):
        factor_id = request.form[f'factor_id_{i}']
        valor = int(request.form[f'valor_{i}'])
        valores.append((factor_id, valor))

    usados = [v[1] for v in valores]
    if len(set(usados)) != 10:
        flash("Cada valor del 1 al 10 debe ser único. No se permiten duplicados.")
        return redirect(url_for('mostrar_formulario', id_usuario=id_usuario))

    # Insertar respuesta general
    cursor.execute("INSERT INTO respuesta (id_usuario, id_formulario) VALUES (%s, %s)", (id_usuario, id_formulario))
    conn.commit()
    id_respuesta = cursor.lastrowid

    # Insertar detalle por factor
    for factor_id, valor in valores:
        cursor.execute("""
            INSERT INTO respuesta_detalle (id_respuesta, id_factor, valor_usuario)
            VALUES (%s, %s, %s)
        """, (id_respuesta, factor_id, valor))
    conn.commit()

    return "¡Respuestas registradas exitosamente!"

# ==============================
# PANEL DE ADMINISTRADOR (resumen)
# ==============================

@app.route('/admin')
def panel_admin():
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
    # Datos generales
    cursor.execute("""
        SELECT r.id AS id_respuesta, u.nombre, u.apellidos, f.nombre AS formulario
        FROM respuesta r
        JOIN usuario u ON r.id_usuario = u.id
        JOIN formulario f ON r.id_formulario = f.id
        WHERE r.id = %s
    """, (id_respuesta,))
    respuesta = cursor.fetchone()

    # Detalle de los factores
    cursor.execute("""
        SELECT fd.id_factor, fa.nombre, fa.descripcion, fd.valor_usuario,
               COALESCE(pa.peso_admin, '') AS peso_admin
        FROM respuesta_detalle fd
        JOIN factor fa ON fd.id_factor = fa.id
        LEFT JOIN ponderacion_admin pa ON pa.id_respuesta = fd.id_respuesta AND pa.id_factor = fd.id_factor
        WHERE fd.id_respuesta = %s
        ORDER BY fa.id
    """, (id_respuesta,))
    factores = cursor.fetchall()

    return render_template('admin_detalle.html', respuesta=respuesta, factores=factores)

# ==============================
# GUARDAR PONDERACIÓN (ADMIN)
# ==============================

@app.route('/admin/ponderar', methods=['POST'])
def guardar_ponderacion():
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
def ranking_factores():
    cursor.execute("""
        SELECT f.nombre, SUM(p.peso_admin) AS total
        FROM ponderacion_admin p
        JOIN factor f ON p.id_factor = f.id
        GROUP BY f.id
        ORDER BY total DESC
    """)
    ranking = cursor.fetchall()
    return render_template('admin_ranking.html', ranking=ranking)


# ==============================
# MAIN
# ==============================

if __name__ == '__main__':
    app.run(debug=True)
