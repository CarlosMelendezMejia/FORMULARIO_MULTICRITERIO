-- Base de datos
CREATE DATABASE IF NOT EXISTS sistema_formularios;
USE sistema_formularios;

-- Tabla de usuarios que responden formularios
CREATE TABLE usuario (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    cargo VARCHAR(100),
    dependencia VARCHAR(100)
);

-- Tabla de formularios (puedes ajustar los títulos si lo deseas)
CREATE TABLE formulario (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL
);

-- Tabla de asignación usuario-formulario
CREATE TABLE asignacion (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL,
    id_formulario INT NOT NULL,
    UNIQUE (id_usuario, id_formulario),
    FOREIGN KEY (id_usuario) REFERENCES usuario(id),
    FOREIGN KEY (id_formulario) REFERENCES formulario(id)
);

-- Tabla de factores (descripción fija para los 10 factores)
CREATE TABLE factor (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT NOT NULL
);

-- Tabla de respuestas de los usuarios a los factores
CREATE TABLE respuesta (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL,
    id_formulario INT NOT NULL,
    fecha_respuesta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_usuario) REFERENCES usuario(id),
    FOREIGN KEY (id_formulario) REFERENCES formulario(id)
);

-- Detalle de las respuestas por factor (valor de 1 a 10, sin repetir por respuesta)
CREATE TABLE respuesta_detalle (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_respuesta INT NOT NULL,
    id_factor INT NOT NULL,
    valor_usuario INT NOT NULL CHECK (valor_usuario BETWEEN 1 AND 10),
    FOREIGN KEY (id_respuesta) REFERENCES respuesta(id) ON DELETE CASCADE,
    FOREIGN KEY (id_factor) REFERENCES factor(id),
    UNIQUE (id_respuesta, valor_usuario),  -- impide duplicar valores
    UNIQUE (id_respuesta, id_factor)       -- impide duplicar factores
);

-- Tabla de ponderación del administrador sobre cada respuesta
CREATE TABLE ponderacion_admin (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_respuesta INT NOT NULL,
    id_factor INT NOT NULL,
    peso_admin FLOAT NOT NULL,  -- Puedes usar INT si prefieres solo enteros
    FOREIGN KEY (id_respuesta) REFERENCES respuesta(id) ON DELETE CASCADE,
    FOREIGN KEY (id_factor) REFERENCES factor(id),
    UNIQUE (id_respuesta, id_factor)
);

-- Insertar los 54 formularios
INSERT INTO formulario (nombre)
SELECT CONCAT('Formulario ', LPAD(n, 2, '0'))
FROM (SELECT @row := @row + 1 AS n FROM (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 
      UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 
      UNION ALL SELECT 9) t1, (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 
      UNION ALL SELECT 4 UNION ALL SELECT 5) t2, (SELECT @row := 0) t0) AS numeros
WHERE n <= 54;

-- Insertar los 10 factores (nombres y descripciones ejemplo)
INSERT INTO factor (nombre, descripcion) VALUES
('Factor 1', 'Descripción del factor 1'),
('Factor 2', 'Descripción del factor 2'),
('Factor 3', 'Descripción del factor 3'),
('Factor 4', 'Descripción del factor 4'),
('Factor 5', 'Descripción del factor 5'),
('Factor 6', 'Descripción del factor 6'),
('Factor 7', 'Descripción del factor 7'),
('Factor 8', 'Descripción del factor 8'),
('Factor 9', 'Descripción del factor 9'),
('Factor 10', 'Descripción del factor 10');
