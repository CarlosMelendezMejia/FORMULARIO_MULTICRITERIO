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
    nombre VARCHAR(100) NOT NULL,
    requiere_password TINYINT(1) DEFAULT NULL,
    password_hash VARCHAR(255) DEFAULT NULL -- Hash de la contraseña del formulario
);

-- Tabla de asignación usuario-formulario
CREATE TABLE asignacion (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL,
    id_formulario INT NOT NULL,
    UNIQUE (id_usuario),
    FOREIGN KEY (id_usuario) REFERENCES usuario(id),
    FOREIGN KEY (id_formulario) REFERENCES formulario(id)
);

-- Tabla de factores (descripción fija para los 10 factores)
CREATE TABLE factor (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT NOT NULL,
    color VARCHAR(7) NOT NULL,
    dimension TINYINT NOT NULL DEFAULT 1,
    CHECK (dimension IN (1,2))
);

-- Tabla de respuestas de los usuarios a los factores
CREATE TABLE respuesta (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL,
    id_formulario INT NOT NULL,
    bloqueado TINYINT(1) NOT NULL DEFAULT 1,
    fecha_respuesta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_usuario) REFERENCES usuario(id),
    FOREIGN KEY (id_formulario) REFERENCES formulario(id),
    UNIQUE (id_usuario, id_formulario)
);

-- Índice para búsquedas por usuario, formulario y bloqueo
CREATE INDEX idx_respuesta_usuario_formulario_bloqueado
    ON respuesta (id_usuario, id_formulario, bloqueado);

-- Detalle de las respuestas por factor (valor >= 1, sin repetir por respuesta)
CREATE TABLE respuesta_detalle (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_respuesta INT NOT NULL,
    id_factor INT NOT NULL,
    valor_usuario INT NOT NULL,
    CONSTRAINT chk_valor_usuario CHECK (valor_usuario >= 1),
    FOREIGN KEY (id_respuesta) REFERENCES respuesta(id) ON DELETE CASCADE,
    FOREIGN KEY (id_factor) REFERENCES factor(id),
    UNIQUE (id_respuesta, valor_usuario),  -- impide duplicar valores
    UNIQUE (id_respuesta, id_factor)       -- impide duplicar factores
);

-- Índice para acelerar consultas por respuesta y factor
CREATE INDEX idx_respuesta_detalle_respuesta_factor
    ON respuesta_detalle (id_respuesta, id_factor);

-- Tabla de ponderación del administrador sobre cada respuesta
CREATE TABLE ponderacion_admin (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_respuesta INT NOT NULL,
    id_factor INT NOT NULL,
    peso_admin DECIMAL(4,1) NOT NULL,  -- Puedes usar INT si prefieres solo enteros
    FOREIGN KEY (id_respuesta) REFERENCES respuesta(id) ON DELETE CASCADE,
    FOREIGN KEY (id_factor) REFERENCES factor(id),
    UNIQUE (id_respuesta, id_factor)
);

-- Índice para búsquedas por respuesta en ponderaciones
CREATE INDEX idx_ponderacion_admin_respuesta
    ON ponderacion_admin (id_respuesta);

-- Insertar los 55 formularios
INSERT INTO formulario (nombre)
SELECT CONCAT('Formulario ', LPAD(n, 2, '0'))
FROM (SELECT @row := @row + 1 AS n FROM (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
      UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
      UNION ALL SELECT 9) t1, (SELECT 0 UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
      UNION ALL SELECT 4 UNION ALL SELECT 5) t2, (SELECT @row := 0) t0) AS numeros
WHERE n <= 55;

-- Insertar los 10 factores (nombres y descripciones ejemplo)
INSERT INTO factor (nombre, descripcion, color, dimension) VALUES
('Formación académica', 'Conjunto de conocimientos, habilidades y destrezas que se adquieren en la educación formal y a través de los diversos niveles o grados de escolarización que permiten desempeñarse en un ambiente laboral específico. Incluye también la formación académica en educación u otros aspectos relacionados con la didáctica, psicología educativa o materias afines.', '#FF5733', 1),
('Actualización en Formación y Profesionalización Docente', 'Conjunto de actividades académicas que se cursan y acreditan las cuales permiten introducir, renovar y perfeccionar el conocimiento en materia de educación universitaria que favorecen el desempeño como formador.', '#33C1FF', 1),
('Reconocimientos y distinciones', 'Conjunto de premios, honores o menciones especiales que se han recibido en reconocimiento a la excelencia, logros o contribuciones en materia de formación docente y docencia universitaria.', '#FF33A8', 1),
('Experiencia en la educación universitaria', 'Práctica adquirida a través del tiempo en el desempeño de una actividad profesional y académica en la educación universitaria, la cual puede determinarse en temporalidades (0-6 meses, 6 meses-1 año, 2 años, 3 años 5 o más años).', '#75FF33', 1),
('Conocimientos y habilidades específicas', 'Conjunto de conocimientos y hablidades específicas en temas, técnicas, metodologías o habilidades para desempeñarse como formador del profesorado universitario.', '#FFC300', 1),
('Productividad académica', 'Se refiere a las contribuciones intelectuales que ha realizado en su campo de conocimiento aplicado a la formación docente tales como: artículos científicos en revistas académicas, ponencias, proyectos de investigación, autoría o coautoría de libros o capítulos.', '#DAF7A6', 1),
('Ethos institucional', 'Conjunto de rasgos y modos de comportamiento que conforman el carácter o la identidad de una persona o una comunidad. Para el caso del Ethos de un formador docente de la UNAM, éste estará conformado por el conocimiento de la institución (proyecto educativo), normatividad, valores y código de ética.', '#C70039', 1),
('Actitudes', 'Predisposición cognitiva, emocional y conductual ante situaciones, personas o eventos que influye en la manera en que un individuo responde a su entorno.', '#900C3F', 1),
('Trámites y procesos académico-administrativos', 'Compromiso y resguardo de la documentación oficial, así como el cumplimiento de los procesos de gestión que la institución determine para la certificación de actividades de formación docente.', '#581845', 2),
('Materiales y equipos para la formación docente', 'Resguardo de los equipos de cómputo, materiales didácticos y demás insumos que le sean proporcionados para el desarrollo de actividades para la formación y profesionalización docente.', '#1C2833', 2);



INSERT INTO usuario (id, nombre, apellidos, cargo, dependencia) VALUES
(1, 'Nombre1', 'Apellidos1', 'Cargo1', 'Dependencia1'),
(2, 'Nombre2', 'Apellidos2', 'Cargo2', 'Dependencia2'),
(3, 'Nombre3', 'Apellidos3', 'Cargo3', 'Dependencia3'),
(4, 'Nombre4', 'Apellidos4', 'Cargo4', 'Dependencia4'),
(5, 'Nombre5', 'Apellidos5', 'Cargo5', 'Dependencia5'),
(6, 'Nombre6', 'Apellidos6', 'Cargo6', 'Dependencia6'),
(7, 'Nombre7', 'Apellidos7', 'Cargo7', 'Dependencia7'),
(8, 'Nombre8', 'Apellidos8', 'Cargo8', 'Dependencia8'),
(9, 'Nombre9', 'Apellidos9', 'Cargo9', 'Dependencia9'),
(10, 'Nombre10', 'Apellidos10', 'Cargo10', 'Dependencia10'),
(11, 'Nombre11', 'Apellidos11', 'Cargo11', 'Dependencia11'),
(12, 'Nombre12', 'Apellidos12', 'Cargo12', 'Dependencia12'),
(13, 'Nombre13', 'Apellidos13', 'Cargo13', 'Dependencia13'),
(14, 'Nombre14', 'Apellidos14', 'Cargo14', 'Dependencia14'),
(15, 'Nombre15', 'Apellidos15', 'Cargo15', 'Dependencia15'),
(16, 'Nombre16', 'Apellidos16', 'Cargo16', 'Dependencia16'),
(17, 'Nombre17', 'Apellidos17', 'Cargo17', 'Dependencia17'),
(18, 'Nombre18', 'Apellidos18', 'Cargo18', 'Dependencia18'),
(19, 'Nombre19', 'Apellidos19', 'Cargo19', 'Dependencia19'),
(20, 'Nombre20', 'Apellidos20', 'Cargo20', 'Dependencia20'),
(21, 'Nombre21', 'Apellidos21', 'Cargo21', 'Dependencia21'),
(22, 'Nombre22', 'Apellidos22', 'Cargo22', 'Dependencia22'),
(23, 'Nombre23', 'Apellidos23', 'Cargo23', 'Dependencia23'),
(24, 'Nombre24', 'Apellidos24', 'Cargo24', 'Dependencia24'),
(25, 'Nombre25', 'Apellidos25', 'Cargo25', 'Dependencia25'),
(26, 'Nombre26', 'Apellidos26', 'Cargo26', 'Dependencia26'),
(27, 'Nombre27', 'Apellidos27', 'Cargo27', 'Dependencia27'),
(28, 'Nombre28', 'Apellidos28', 'Cargo28', 'Dependencia28'),
(29, 'Nombre29', 'Apellidos29', 'Cargo29', 'Dependencia29'),
(30, 'Nombre30', 'Apellidos30', 'Cargo30', 'Dependencia30'),
(31, 'Nombre31', 'Apellidos31', 'Cargo31', 'Dependencia31'),
(32, 'Nombre32', 'Apellidos32', 'Cargo32', 'Dependencia32'),
(33, 'Nombre33', 'Apellidos33', 'Cargo33', 'Dependencia33'),
(34, 'Nombre34', 'Apellidos34', 'Cargo34', 'Dependencia34'),
(35, 'Nombre35', 'Apellidos35', 'Cargo35', 'Dependencia35'),
(36, 'Nombre36', 'Apellidos36', 'Cargo36', 'Dependencia36'),
(37, 'Nombre37', 'Apellidos37', 'Cargo37', 'Dependencia37'),
(38, 'Nombre38', 'Apellidos38', 'Cargo38', 'Dependencia38'),
(39, 'Nombre39', 'Apellidos39', 'Cargo39', 'Dependencia39'),
(40, 'Nombre40', 'Apellidos40', 'Cargo40', 'Dependencia40'),
(41, 'Nombre41', 'Apellidos41', 'Cargo41', 'Dependencia41'),
(42, 'Nombre42', 'Apellidos42', 'Cargo42', 'Dependencia42'),
(43, 'Nombre43', 'Apellidos43', 'Cargo43', 'Dependencia43'),
(44, 'Nombre44', 'Apellidos44', 'Cargo44', 'Dependencia44'),
(45, 'Nombre45', 'Apellidos45', 'Cargo45', 'Dependencia45'),
(46, 'Nombre46', 'Apellidos46', 'Cargo46', 'Dependencia46'),
(47, 'Nombre47', 'Apellidos47', 'Cargo47', 'Dependencia47'),
(48, 'Nombre48', 'Apellidos48', 'Cargo48', 'Dependencia48'),
(49, 'Nombre49', 'Apellidos49', 'Cargo49', 'Dependencia49'),
(50, 'Nombre50', 'Apellidos50', 'Cargo50', 'Dependencia50'),
(51, 'Nombre51', 'Apellidos51', 'Cargo51', 'Dependencia51'),
(52, 'Nombre52', 'Apellidos52', 'Cargo52', 'Dependencia52'),
(53, 'Nombre53', 'Apellidos53', 'Cargo53', 'Dependencia53'),
(54, 'Nombre54', 'Apellidos54', 'Cargo54', 'Dependencia54'),
(55, 'Nombre55', 'Apellidos55', 'Cargo55', 'Dependencia55'),
(56, 'Nombre56', 'Apellidos56', 'Cargo56', 'Dependencia56'),
(57, 'Nombre57', 'Apellidos57', 'Cargo57', 'Dependencia57'),
(58, 'Nombre58', 'Apellidos58', 'Cargo58', 'Dependencia58'),
(59, 'Nombre59', 'Apellidos59', 'Cargo59', 'Dependencia59'),
(60, 'Nombre60', 'Apellidos60', 'Cargo60', 'Dependencia60');

INSERT INTO asignacion (id_usuario, id_formulario) VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5),
(6, 6),
(7, 7),
(8, 8),
(9, 9),
(10, 10),
(11, 11),
(12, 12),
(13, 13),
(14, 14),
(15, 15),
(16, 16),
(17, 17),
(18, 18),
(19, 19),
(20, 20),
(21, 21),
(22, 22),
(23, 23),
(24, 24),
(25, 25),
(26, 26),
(27, 27),
(28, 28),
(29, 29),
(30, 30),
(31, 31),
(32, 32),
(33, 33),
(34, 34),
(35, 35),
(36, 36),
(37, 37),
(38, 38),
(39, 39),
(40, 40),
(41, 41),
(42, 42),
(43, 43),
(44, 44),
(45, 45),
(46, 46),
(47, 47),
(48, 48),
(49, 49),
(50, 50),
(51, 51),
(52, 52),
(53, 53),
(54, 54),
(55, 55);
