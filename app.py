import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Sistema Heladería", layout="wide", page_icon="🍦")

# --- BASE DE DATOS (SQLite) ---
def init_db():
    conn = sqlite3.connect('heladeria.db')
    c = conn.cursor()
    # Tabla Productos
    c.execute('''CREATE TABLE IF NOT EXISTS productos
                 (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, stock INTEGER)''')
    # Tabla Ventas
    c.execute('''CREATE TABLE IF NOT EXISTS ventas
                 (id INTEGER PRIMARY KEY, producto_id INTEGER, cantidad INTEGER, 
                  total REAL, fecha TIMESTAMP, producto_nombre TEXT)''')
    # Tabla Desperdicios
    c.execute('''CREATE TABLE IF NOT EXISTS desperdicios
                 (id INTEGER PRIMARY KEY, producto_id INTEGER, cantidad INTEGER, 
                  razon TEXT, fecha TIMESTAMP, producto_nombre TEXT)''')
    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect('heladeria.db')

# --- FUNCIONES DE LÓGICA ---

def registrar_venta(producto_id, cantidad, precio, nombre):
    conn = get_connection()
    c = conn.cursor()
    total = precio * cantidad
    
    # Registrar venta
    c.execute("INSERT INTO ventas (producto_id, cantidad, total, fecha, producto_nombre) VALUES (?, ?, ?, ?, ?)",
              (producto_id, cantidad, total, datetime.now(), nombre))
    
    # Descontar inventario
    c.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (cantidad, producto_id))
    
    conn.commit()
    conn.close()

def registrar_desperdicio(producto_id, cantidad, razon, nombre):
    conn = get_connection()
    c = conn.cursor()
    
    # Registrar desperdicio
    c.execute("INSERT INTO desperdicios (producto_id, cantidad, razon, fecha, producto_nombre) VALUES (?, ?, ?, ?, ?)",
              (producto_id, cantidad, razon, datetime.now(), nombre))
    
    # Descontar inventario
    c.execute("UPDATE productos SET stock = stock - ? WHERE id = ?", (cantidad, producto_id))
    
    conn.commit()
    conn.close()

def agregar_producto(nombre, precio, stock):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO productos (nombre, precio, stock) VALUES (?, ?, ?)", (nombre, precio, stock))
    conn.commit()
    conn.close()

# --- GENERADOR DE PDF ---
def generar_pdf(df_ventas, total_dia):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    pdf.cell(200, 10, txt=f"Reporte de Ventas - {datetime.now().strftime('%Y-%m-%d')}", ln=1, align='C')
    pdf.ln(10)
    
    # Encabezados
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(60, 10, "Producto", 1)
    pdf.cell(30, 10, "Cantidad", 1)
    pdf.cell(40, 10, "Total ($)", 1)
    pdf.cell(50, 10, "Hora", 1)
    pdf.ln()
    
    # Datos
    pdf.set_font("Arial", size=10)
    for index, row in df_ventas.iterrows():
        pdf.cell(60, 10, str(row['producto_nombre']), 1)
        pdf.cell(30, 10, str(row['cantidad']), 1)
        pdf.cell(40, 10, f"${row['total']:.2f}", 1)
        pdf.cell(50, 10, str(row['fecha']), 1)
        pdf.ln()
        
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt=f"TOTAL VENDIDO HOY: ${total_dia:.2f}", ln=1, align='R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- INTERFAZ PRINCIPAL ---
def main():
    init_db()
    st.title("🍦 Sistema de Gestión - Heladería")

    menu = ["🛒 Nueva Venta", "📉 Registrar Desperdicio", "📦 Inventario", "📊 Reportes"]
    choice = st.sidebar.selectbox("Navegación", menu)

    conn = get_connection()

    # --- MÓDULO VENTAS ---
    if choice == "🛒 Nueva Venta":
        st.header("Registrar Venta")
        
        df_prod = pd.read_sql("SELECT * FROM productos", conn)
        
        if not df_prod.empty:
            producto = st.selectbox("Seleccionar Producto", df_prod['nombre'].unique())
            datos_prod = df_prod[df_prod['nombre'] == producto].iloc[0]
            
            st.info(f"Precio: ${datos_prod['precio']} | Stock actual: {datos_prod['stock']}")
            
            cantidad = st.number_input("Cantidad", min_value=1, max_value=int(datos_prod['stock']), step=1)
            
            if st.button("Confirmar Venta"):
                if datos_prod['stock'] >= cantidad:
                    registrar_venta(int(datos_prod['id']), cantidad, datos_prod['precio'], producto)
                    st.success(f"Venta de {cantidad} {producto}(s) registrada correctamente.")
                    st.rerun()
                else:
                    st.error("No hay suficiente stock.")
        else:
            st.warning("No hay productos registrados. Ve a la pestaña Inventario.")

    # --- MÓDULO DESPERDICIOS ---
    elif choice == "📉 Registrar Desperdicio":
        st.header("Control de Mermas / Desperdicios")
        st.markdown("Usa esta opción si se cayó un helado, se venció un producto, etc.")
        
        df_prod = pd.read_sql("SELECT * FROM productos", conn)
        
        if not df_prod.empty:
            producto = st.selectbox("Producto Desperdiciado", df_prod['nombre'].unique())
            datos_prod = df_prod[df_prod['nombre'] == producto].iloc[0]
            
            col1, col2 = st.columns(2)
            with col1:
                cantidad = st.number_input("Cantidad Perdida", min_value=1, max_value=int(datos_prod['stock']), step=1)
            with col2:
                razon = st.selectbox("Razón", ["Se cayó al servir", "Vencimiento", "Defecto de fábrica", "Degustación / Regalo"])
            
            if st.button("Registrar Pérdida"):
                registrar_desperdicio(int(datos_prod['id']), cantidad, razon, producto)
                st.warning(f"Se descontaron {cantidad} {producto}(s) del inventario por: {razon}.")
                st.rerun()

    # --- MÓDULO INVENTARIO ---
    elif choice == "📦 Inventario":
        st.header("Gestión de Inventario")
        
        # Ver inventario
        st.subheader("Stock Actual")
        df_stock = pd.read_sql("SELECT * FROM productos", conn)
        st.dataframe(df_stock, use_container_width=True)
        
        st.divider()
        
        # Agregar nuevo producto
        st.subheader("Agregar Nuevo Producto")
        with st.form("nuevo_producto"):
            nuevo_nombre = st.text_input("Nombre del Producto (ej. Barquilla Chocolate)")
            nuevo_precio = st.number_input("Precio de Venta ($)", min_value=0.0)
            nuevo_stock = st.number_input("Stock Inicial (Cantidad)", min_value=0, step=1)
            
            submit = st.form_submit_button("Guardar Producto")
            if submit and nuevo_nombre:
                agregar_producto(nuevo_nombre, nuevo_precio, nuevo_stock)
                st.success("Producto agregado al sistema.")
                st.rerun()

    # --- MÓDULO REPORTES ---
    elif choice == "📊 Reportes":
        st.header("Reporte Diario")
        
        # Filtrar por fecha (simple: hoy)
        hoy = datetime.now().date()
        df_ventas = pd.read_sql("SELECT * FROM ventas", conn)
        
        # Convertir columna fecha a datetime
        if not df_ventas.empty:
            df_ventas['fecha'] = pd.to_datetime(df_ventas['fecha'])
            mask = df_ventas['fecha'].dt.date == hoy
            ventas_hoy = df_ventas[mask]
            
            total_ventas = ventas_hoy['total'].sum()
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Ventas de Hoy", f"${total_ventas:,.2f}")
            col2.metric("Transacciones", len(ventas_hoy))
            
            st.subheader("Detalle de Ventas (Hoy)")
            st.dataframe(ventas_hoy, use_container_width=True)
            
            st.divider()
            
            st.subheader("Descargas")
            col_d1, col_d2 = st.columns(2)
            
            # Descargar Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                ventas_hoy.to_excel(writer, index=False, sheet_name='Ventas')
            
            col_d1.download_button(
                label="📥 Descargar Excel",
                data=buffer.getvalue(),
                file_name=f"ventas_{hoy}.xlsx",
                mime="application/vnd.ms-excel"
            )
            
            # Descargar PDF
            try:
                pdf_bytes = generar_pdf(ventas_hoy, total_ventas)
                col_d2.download_button(
                    label="📄 Descargar Reporte PDF",
                    data=pdf_bytes,
                    file_name=f"reporte_{hoy}.pdf",
                    mime="application/pdf"
                )
            except Exception as e:
                st.error(f"Error generando PDF: {e}")
                
        else:
            st.info("No hay ventas registradas aún.")
            
    conn.close()

if __name__ == '__main__':
    main()
