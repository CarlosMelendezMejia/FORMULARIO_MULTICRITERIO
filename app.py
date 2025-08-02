from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'clave-secreta-sencilla'

# Conexión a la base de datos
conn = mysql.connector.connect(
    host='localhost',
    user='tu_usuario',
    password='tu_password',
    database='sistema_formularios'
)
cursor = conn.cursor(dictionary=True)

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
# MAIN
# ==============================

if __name__ == '__main__':
    app.run(debug=True)
