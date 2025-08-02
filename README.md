# FORMULARIO MULTICRITERIO

Aplicación Flask que se conecta a una base de datos MySQL.

## Variables de entorno necesarias

Configura las siguientes variables de entorno antes de ejecutar la aplicación:

- `DB_HOST`: host de la base de datos.
- `DB_USER`: usuario de la base de datos.
- `DB_PASSWORD`: contraseña del usuario.
- `DB_NAME`: nombre de la base de datos.

Ejemplo en Linux/Mac:

```bash
export DB_HOST=localhost
export DB_USER=root
export DB_PASSWORD=tu_contraseña
export DB_NAME=sistema_formularios
```

Luego puedes iniciar la aplicación con:

```bash
python app.py
```
