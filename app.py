import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Heladería Artesanal", layout="wide", page_icon="🍦")

# --- BASE DE DATOS LOCAL ---
def init_db():
    conn = sqlite3.connect('heladeria_local.db')
    c = conn.cursor()
    
    # Tabla MENÚ (Lo que vendes y cobras)
    c.execute('''CREATE TABLE IF NOT EXISTS menu
                 (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    
    # Tabla INSUMOS (Tus materiales: vasos, conos, leche)
    c.execute('''CREATE TABLE IF NOT EXISTS insumos
                 (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT)''')
    
    # Tabla VENTAS
    c.execute('''CREATE TABLE IF NOT EXISTS ventas
                 (id INTEGER PRIMARY KEY, producto TEXT, precio REAL, cantidad INTEGER, 
                  total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    
    # Tabla DESPERDICIOS/MERMAS
    c.execute('''CREATE TABLE IF NOT EXISTS mermas
                 (id INTEGER PRIMARY KEY, insumo TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
                 
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect('heladeria_local.db')
    c = conn.cursor()
    c.execute(query, params)
    if return_data:
        data = c.fetchall()
        cols = [description[0] for description in c.description]
        conn.close()
        return pd.DataFrame(data, columns=cols)
    else:
        conn.commit()
        conn.close()
        return None

# --- GENERADOR DE PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Reporte de Cierre de Caja - Heladería', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_diario(df_ventas, total_dia, fecha_hoy):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    pdf.cell(0, 10, txt=f"Fecha del Reporte: {fecha_hoy}", ln=1, align='L')
    pdf.ln(10)
    
    # Tabla de Ventas
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(80, 10, "Producto", 1)
    pdf.cell(30, 10, "Cant.", 1)
    pdf.cell(40, 10, "Método", 1)
    pdf.cell(40, 10, "Total ($)", 1)
    pdf.ln()
    
    pdf.set_font("Arial", size=10)
    for index, row in df_ventas.iterrows():
        # Cortar nombres muy largos
        nombre = (row['producto'][:35] + '..') if len(row['producto']) > 35 else row['producto']
        pdf.cell(80, 10, nombre, 1)
        pdf.cell(30, 10, str(row['cantidad']), 1)
        pdf.cell(40, 10, row['metodo_pago'], 1)
        pdf.cell(40, 10, f"${row['total']:.2f}", 1)
        pdf.ln()
        
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, txt=f"TOTAL VENDIDO HOY: ${total_dia:,.2f}", ln=1, align='R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- INTERFAZ PRINCIPAL ---
def main():
    init_db()
    st.sidebar.title("🍦 Menú Principal")
    opcion = st.sidebar.radio("Ir a:", ["🛒 Registrar Venta", "📦 Inventario de Insumos", "📉 Registrar Merma", "📝 Configurar Menú", "📊 Reportes y Cierre"])

    # 1. REGISTRAR VENTA
    if opcion == "🛒 Registrar Venta":
        st.header("Nueva Venta")
        
        df_menu = run_query("SELECT * FROM menu", return_data=True)
        
        if not df_menu.empty:
            # Selector de productos
            opciones_menu = [f"{row['nombre']} - ${row['precio']}" for i, row in df_menu.iterrows()]
            seleccion = st.selectbox("Selecciona Producto", opciones_menu)
            
            # Extraer datos
            nombre_prod = seleccion.split(" - $")[0]
            precio_prod = float(seleccion.split(" - $")[1])
            
            col1, col2 = st.columns(2)
            with col1:
                cantidad = st.number_input("Cantidad", min_value=1, value=1)
            with col2:
                metodo = st.selectbox("Método de Pago", ["Efectivo", "Tarjeta", "Yape/Plin/Transferencia"])
            
            total = precio_prod * cantidad
            st.metric("Total a Cobrar", f"${total:,.2f}")
            
            if st.button("✅ Cobrar y Guardar", type="primary"):
                run_query("INSERT INTO ventas (producto, precio, cantidad, total, metodo_pago, fecha) VALUES (?, ?, ?, ?, ?, ?)",
                          (nombre_prod, precio_prod, cantidad, total, metodo, datetime.now()))
                st.success(f"Venta de {cantidad} {nombre_prod}(s) guardada.")
                st.rerun()
        else:
            st.warning("No hay productos en el menú. Ve a 'Configurar Menú' para agregar precios.")

    # 2. INVENTARIO (INSUMOS)
    elif opcion == "📦 Inventario de Insumos":
        st.header("Control de Insumos (Materiales)")
        st.info("Aquí cuentas tus vasos, barquillos, leche, azúcar, etc.")
        
        # Ver tabla
        df_insumos = run_query("SELECT * FROM insumos", return_data=True)
        st.dataframe(df_insumos, use_container_width=True)
        
        st.divider()
        col1, col2 = st.columns(2)
        
        # Agregar Nuevo
        with col1:
            st.subheader("Nuevo Insumo")
            with st.form("add_insumo"):
                nom = st.text_input("Nombre (ej. Cono Waffle)")
                cant = st.number_input("Cantidad Inicial", min_value=0)
                uni = st.text_input("Unidad (ej. Cajas, Unidades)")
                if st.form_submit_button("Agregar"):
                    run_query("INSERT INTO insumos (nombre, cantidad, unidad) VALUES (?, ?, ?)", (nom, cant, uni))
                    st.rerun()
                    
        # Actualizar Existente
        with col2:
            st.subheader("Actualizar Stock")
            if not df_insumos.empty:
                insumo_sel = st.selectbox("Seleccionar Insumo", df_insumos['nombre'].unique())
                cant_actual = df_insumos[df_insumos['nombre']==insumo_sel]['cantidad'].values[0]
                st.write(f"Stock actual: {cant_actual}")
                
                nueva_cant = st.number_input("Nueva Cantidad (Conteo Real)", min_value=0.0)
                if st.button("Actualizar Stock"):
                    run_query("UPDATE insumos SET cantidad = ? WHERE nombre = ?", (nueva_cant, insumo_sel))
                    st.success("Stock actualizado.")
                    st.rerun()

    # 3. REGISTRAR MERMA
    elif opcion == "📉 Registrar Merma":
        st.header("Registro de Desperdicios")
        st.warning("Usa esto si se cayó un helado, se venció la leche o se rompió un envase.")
        
        df_insumos = run_query("SELECT * FROM insumos", return_data=True)
        
        if not df_insumos.empty:
            insumo_merma = st.selectbox("¿Qué se desperdició?", df_insumos['nombre'].unique())
            cant_merma = st.number_input("Cantidad perdida", min_value=0.1)
            razon = st.text_input("Razón (ej. Se cayó al piso, Vencido)")
            
            if st.button("Registrar Pérdida"):
                # Guardar registro
                run_query("INSERT INTO mermas (insumo, cantidad, razon, fecha) VALUES (?, ?, ?, ?)",
                          (insumo_merma, cant_merma, razon, datetime.now()))
                # Descontar del inventario
                run_query("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre = ?", (cant_merma, insumo_merma))
                st.error(f"Se descontaron {cant_merma} de {insumo_merma}.")
                st.rerun()

    # 4. CONFIGURAR MENÚ
    elif opcion == "📝 Configurar Menú":
        st.header("Lista de Precios")
        
        with st.form("nuevo_precio"):
            col_a, col_b, col_c = st.columns(3)
            n_nombre = col_a.text_input("Producto (ej. Vaso 2 Bolas)")
            n_precio = col_b.number_input("Precio ($)", min_value=0.0)
            n_cat = col_c.selectbox("Categoría", ["Helado", "Paleta", "Bebida", "Otro"])
            
            if st.form_submit_button("Guardar Producto"):
                run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?, ?, ?)", (n_nombre, n_precio, n_cat))
                st.success("Agregado al menú.")
                st.rerun()
        
        st.subheader("Menú Actual")
        df_menu = run_query("SELECT * FROM menu", return_data=True)
        st.dataframe(df_menu, use_container_width=True)
        
        if not df_menu.empty:
             if st.button("Borrar todo el menú (Cuidado)"):
                 run_query("DELETE FROM menu")
                 st.rerun()

    # 5. REPORTES
    elif opcion == "📊 Reportes y Cierre":
        st.header("Cierre del Día")
        
        hoy = datetime.now().date()
        st.write(f"Mostrando datos para: **{hoy}**")
        
        df_ventas = run_query("SELECT * FROM ventas", return_data=True)
        
        if not df_ventas.empty:
            # Filtrar solo hoy
            df_ventas['fecha'] = pd.to_datetime(df_ventas['fecha'])
            ventas_hoy = df_ventas[df_ventas['fecha'].dt.date == hoy]
            
            total = ventas_hoy['total'].sum()
            
            # Métricas
            m1, m2, m3 = st.columns(3)
            m1.metric("Ventas Totales", f"${total:,.2f}")
            m2.metric("Tickets", len(ventas_hoy))
            m3.metric("Promedio ticket", f"${total/len(ventas_hoy):,.2f}" if len(ventas_hoy) > 0 else "$0")
            
            st.subheader("Detalle de Ventas")
            st.dataframe(ventas_hoy, use_container_width=True)
            
            st.divider()
            st.subheader("Descargar Reportes")
            
            col_pdf, col_excel = st.columns(2)
            
            # 1. Botón PDF
            try:
                pdf_data = generar_pdf_diario(ventas_hoy, total, str(hoy))
                col_pdf.download_button(
                    label="📄 Descargar Cierre PDF",
                    data=pdf_data,
                    file_name=f"Cierre_Caja_{hoy}.pdf",
                    mime="application/pdf"
                )
            except Exception as e:
                col_pdf.error(f"Error generando PDF: {e}")
            
            # 2. Botón Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                ventas_hoy.to_excel(writer, sheet_name='Ventas', index=False)
            
            col_excel.download_button(
                label="📊 Descargar Excel Completo",
                data=buffer.getvalue(),
                file_name=f"Reporte_Ventas_{hoy}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        else:
            st.info("No hay ventas registradas en el sistema.")

if __name__ == '__main__':
    main()
