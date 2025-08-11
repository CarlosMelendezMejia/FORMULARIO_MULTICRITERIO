# FORMULARIO MULTICRITERIO

Aplicación Flask que se conecta a una base de datos MySQL.

## Variables de entorno necesarias

Configura las siguientes variables de entorno antes de ejecutar la aplicación:

- `DB_HOST`: host de la base de datos.
- `DB_USER`: usuario de la base de datos.
- `DB_PASSWORD`: contraseña del usuario.
- `DB_NAME`: nombre de la base de datos.
- `SECRET_KEY`: clave utilizada por Flask para firmar las cookies y proteger la sesión.
- `BLOQUEO_CACHE_TTL`: (opcional) segundos que permanece en caché el estado de bloqueo de un formulario. Valor por defecto: 30.
- `CACHE_TYPE`: (opcional) backend de caché a utilizar. Por defecto `RedisCache`.
- `CACHE_REDIS_HOST`, `CACHE_REDIS_PORT`, `CACHE_REDIS_DB`, `CACHE_REDIS_PASSWORD`: parámetros de conexión para Redis. Valores por defecto: `localhost`, `6379`, `0` y sin contraseña.
- `CACHE_REDIS_URL`: si se define, se utiliza como URL completa de conexión a Redis.
- `RANKING_CACHE_TTL`: (opcional) segundos que permanece en caché el ranking. Valor por defecto: 300.

Ejemplo en Linux/Mac:

```bash
export DB_HOST=localhost
export DB_USER=root
export DB_PASSWORD=tu_contraseña
export DB_NAME=sistema_formularios
export SECRET_KEY=alguna_cadena_secreta
# export CACHE_TYPE=SimpleCache  # para usar caché en memoria
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

## Actualización de esquema

La columna `respuesta_detalle.valor_usuario` ahora valida únicamente que el valor sea mayor o igual a 1, eliminando el límite superior de 10 para permitir cualquier número de factores.

Para actualizar una instalación existente, ejecuta el siguiente comando (ajusta el nombre del `CHECK` original según tu instancia, puedes consultarlo con `SHOW CREATE TABLE respuesta_detalle;`):

```sql
ALTER TABLE respuesta_detalle
  DROP CHECK respuesta_detalle_chk_1,
  ADD CONSTRAINT chk_valor_usuario CHECK (valor_usuario >= 1);
```

Si deseas mantener un rango acotado, reemplaza la última línea por:

```sql
  ADD CONSTRAINT chk_valor_usuario CHECK (valor_usuario BETWEEN 1 AND <numero_maximo_de_factores>);
```

Sustituye `<numero_maximo_de_factores>` por la cantidad máxima de factores que esperas manejar.

### Cambiar `ponderacion_admin.peso_admin` a `DECIMAL(4,1)`

Para evitar problemas de precisión con los valores de ponderación, la columna
`peso_admin` ahora utiliza el tipo `DECIMAL(4,1)`. En instalaciones existentes
puedes aplicar la migración con:

```bash
mysql -u <usuario> -p < database/migrate_peso_admin_decimal.sql
```

Este script crea una columna temporal, copia los valores existentes, elimina la
columna original de tipo `FLOAT` y renombra la columna temporal.

## Caché de bloqueos

El estado de bloqueo de cada formulario se almacena en el backend de caché
configurado (por defecto Redis o un caché simple en memoria) durante un
tiempo determinado por `BLOQUEO_CACHE_TTL`. Cualquier acción administrativa
que altere el campo `bloqueado` debe llamar a `invalidate_bloqueo_cache` con
el identificador del usuario y del formulario para eliminar la entrada
correspondiente y evitar inconsistencias visibles.

