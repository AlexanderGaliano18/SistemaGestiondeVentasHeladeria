# 🍦 Sistema de Gestión para Heladería

Este es un sistema web desarrollado en Python con **Streamlit** para automatizar el control de ventas e inventario de una heladería. El objetivo es reemplazar el registro manual (papel y lápiz) por una interfaz digital amigable que genere reportes automáticos.

## 🚀 Funcionalidades

1.  **🛒 Registro de Ventas:**
    * Selección de producto desde el inventario.
    * Cálculo automático del total.
    * Descuento inmediato del stock.

2.  **📦 Gestión de Inventario:**
    * Visualización de stock actual en tiempo real.
    * Formulario para agregar nuevos productos y precios.

3.  **📉 Control de Desperdicios (Mermas):**
    * Registro de pérdidas (ej. helado caído, vencimientos, degustaciones).
    * Clasificación por motivo de la pérdida.

4.  **📊 Reportes y Exportación:**
    * Vista rápida de ventas totales del día.
    * **Excel:** Descarga del detalle de ventas.
    * **PDF:** Generación de comprobante/reporte diario imprimible.

## 📂 Estructura del Proyecto

* `app.py`: El código principal de la aplicación.
* `requirements.txt`: Lista de librerías necesarias.
* `packages.txt`: Dependencias del sistema (necesario para generar PDFs en la nube).
* `heladeria.db`: Base de datos local (se crea automáticamente al ejecutar la app).

## 💻 Instalación Local (En tu computadora)

Si quieres usar la app en tu PC para que los datos se guarden siempre en tu disco duro:

1.  **Clonar el repositorio:**
    ```bash
    git clone [https://github.com/TU_USUARIO/TU_REPOSITORIO.git](https://github.com/TU_USUARIO/TU_REPOSITORIO.git)
    cd TU_REPOSITORIO
    ```

2.  **Instalar dependencias:**
    Asegúrate de tener Python instalado y ejecuta:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Ejecutar la aplicación:**
    ```bash
    streamlit run app.py
    ```

## ☁️ Despliegue en Streamlit Cloud

1.  Sube este código a un repositorio de GitHub.
2.  Entra a [share.streamlit.io](https://share.streamlit.io).
3.  Conecta tu repositorio y despliega.

> **⚠️ ADVERTENCIA IMPORTANTE SOBRE LA NUBE:**
> Esta versión utiliza **SQLite** (una base de datos local). Si despliegas esta app en **Streamlit Cloud** (versión gratuita), la base de datos se reiniciará (se borrarán los datos) cada vez que la app se actualice o reinicie el servidor (aprox. cada 24-48 horas o tras inactividad).
>
> **Para uso comercial real en la nube:** Se recomienda cambiar la base de datos por **Google Sheets** o una base de datos externa (PostgreSQL/Supabase) para asegurar la persistencia de los datos.

## 🛠️ Tecnologías

* Python 3.9+
* Streamlit
* Pandas
* FPDF (Reportes PDF)
* SQLite3

---
Hecho con ❤️ para optimizar tu negocio.
