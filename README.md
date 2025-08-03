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

## Inicializar la base de datos

Para crear las tablas e insertar los 54 formularios base, ejecuta el siguiente comando:

```bash
mysql -u <usuario> -p < database/modelo.sql
```

Esto creará la base de datos `sistema_formularios` y poblará la tabla `formulario` con los formularios numerados del 1 al 54.

### Insertar formularios manualmente

Si ya tienes la base de datos pero la tabla `formulario` está vacía, ejecuta solamente el bloque `INSERT INTO formulario` presente en `database/modelo.sql`:

```sql
INSERT INTO formulario (nombre)
SELECT CONCAT('Formulario ', LPAD(n, 2, '0'))
FROM (SELECT @row := @row + 1 AS n FROM (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
      UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
      UNION ALL SELECT 9) t1, (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
      UNION ALL SELECT 4 UNION ALL SELECT 5) t2, (SELECT @row := 0) t0) AS numeros
WHERE n <= 54;
```

Ejecuta ese fragmento en la base de datos `sistema_formularios` para disponer de los formularios desde el inicio.

