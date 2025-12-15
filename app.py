import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Heladería Artesanal Pro", layout="wide", page_icon="🍦")

# --- ESTILOS VISUALES ---
st.markdown("""
<style>
    .stMetric { background-color: #f8f9fa; border-radius: 10px; padding: 10px; border: 1px solid #e0e0e0; }
    .alerta-box { background-color: #ffcccc; color: #cc0000; padding: 15px; border-radius: 8px; margin-bottom: 15px; font-weight: bold; border-left: 5px solid #cc0000; }
    .estrella-box { background-color: #e6f7ff; color: #0066cc; padding: 15px; border-radius: 8px; margin-bottom: 15px; text-align: center; border: 1px solid #b3e0ff; }
    .success-box { background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('heladeria_pro.db')
    c = conn.cursor()
    # 1. Menú
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    # 2. Insumos (Inventario)
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    # 3. Recetas (Vínculo)
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    # 4. Ventas
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    # 5. Mermas
    c.execute('''CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY, insumo TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect('heladeria_pro.db')
    c = conn.cursor()
    try:
        c.execute(query, params)
        if return_data:
            data = c.fetchall()
            cols = [description[0] for description in c.description]
            conn.close()
            return pd.DataFrame(data, columns=cols)
        else:
            conn.commit()
            last_id = c.lastrowid
            conn.close()
            return last_id
    except Exception as e:
        conn.close()
        st.error(f"Error en Base de Datos: {e}")
        return None

# --- LÓGICA DE DESCUENTO DE INVENTARIO (CRUCIAL) ---
def procesar_venta_inventario(nombre_producto, cantidad_vendida, tiene_cono_extra, tiene_topping):
    conn = sqlite3.connect('heladeria_pro.db')
    c = conn.cursor()
    msg_debug = []
    
    # 1. Buscar ID del producto
    c.execute("SELECT id FROM menu WHERE nombre = ?", (nombre_producto,))
    prod_res = c.fetchone()
    
    if prod_res:
        prod_id = prod_res[0]
        # 2. Buscar qué insumos gasta (RECETA)
        c.execute("SELECT insumo_id, cantidad_insumo FROM recetas WHERE menu_id = ?", (prod_id,))
        ingredientes = c.fetchall()
        
        if ingredientes:
            for insumo_id, cant_unitaria in ingredientes:
                total_a_descontar = cant_unitaria * cantidad_vendida
                # Ejecutar descuento
                c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (total_a_descontar, insumo_id))
                
                # Obtener nombre del insumo para confirmar
                c.execute("SELECT nombre, cantidad FROM insumos WHERE id = ?", (insumo_id,))
                datos_insumo = c.fetchone()
                if datos_insumo:
                    msg_debug.append(f"Stock {datos_insumo[0]}: -{total_a_descontar} (Quedan: {datos_insumo[1]})")
        else:
            msg_debug.append(f"⚠️ El producto '{nombre_producto}' no tiene insumos vinculados.")
            
    # 3. Descontar Extras (Genéricos)
    if tiene_cono_extra:
        # Busca insumo que contenga "Cono" o "Barquillo"
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
        res_cono = c.fetchone()
        if res_cono:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cantidad_vendida, res_cono[0]))
            msg_debug.append(f"Extra: -{cantidad_vendida} {res_cono[1]}")
            
    if tiene_topping:
        # Busca insumo que contenga "Topping"
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
        res_top = c.fetchone()
        if res_top:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cantidad_vendida, res_top[0]))
            msg_debug.append(f"Extra: -{cantidad_vendida} {res_top[1]}")

    conn.commit()
    conn.close()
    return msg_debug

# --- FUNCIONES AUXILIARES ---
def obtener_alertas():
    df = run_query("SELECT nombre, cantidad, minimo FROM insumos", return_data=True)
    alertas = []
    if not df.empty:
        for _, row in df.iterrows():
            if row['cantidad'] <= (row['minimo'] / 2): # Rojo crítico
                alertas.append(f"🔴 {row['nombre']} (Quedan: {row['cantidad']})")
            elif row['cantidad'] <= row['minimo']: # Amarillo alerta
                alertas.append(f"🟡 {row['nombre']} (Quedan: {row['cantidad']})")
    return alertas

def obtener_estrella():
    hoy = datetime.now().date()
    query = "SELECT producto, SUM(cantidad) as total FROM ventas WHERE date(fecha) = ? GROUP BY producto ORDER BY total DESC LIMIT 1"
    df = run_query(query, (hoy,), return_data=True)
    if not df.empty:
        return df.iloc[0]['producto'], df.iloc[0]['total']
    return None, 0

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Reporte de Caja - Heladería', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_dia, fecha):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, txt=f"Fecha: {fecha}", ln=1)
    
    # Encabezado Tabla
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(80, 8, "Producto", 1, 0, 'C', 1)
    pdf.cell(20, 8, "Cant.", 1, 0, 'C', 1)
    pdf.cell(25, 8, "Extra ($)", 1, 0, 'C', 1)
    pdf.cell(30, 8, "Total ($)", 1, 0, 'C', 1)
    pdf.cell(35, 8, "Pago", 1, 1, 'C', 1)
    
    for _, row in df_ventas.iterrows():
        nombre = str(row['producto'])[:35]
        pdf.cell(80, 8, nombre, 1)
        pdf.cell(20, 8, str(row['cantidad']), 1, 0, 'C')
        pdf.cell(25, 8, f"{row['extras']:.2f}", 1, 0, 'C')
        pdf.cell(30, 8, f"{row['total']:.2f}", 1, 0, 'C')
        pdf.cell(35, 8, row['metodo_pago'], 1, 1, 'C')
        
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"TOTAL VENDIDO: S/ {total_dia:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN ---
def main():
    init_db()
    if 'msg_inv' not in st.session_state: st.session_state.msg_inv = []
    
    st.sidebar.title("🍦 Heladería Pro")
    menu = st.sidebar.radio("Navegación", ["🛒 Caja & Ventas", "📝 Productos (Menú)", "📦 Insumos (Inventario)", "📊 Cierre de Día"])

    # ------------------------------------------------------------------
    # 1. CAJA Y VENTAS (PANTALLA PRINCIPAL)
    # ------------------------------------------------------------------
    if menu == "🛒 Caja & Ventas":
        st.header("Punto de Venta")

        # --- ALERTAS Y NOTIFICACIONES ---
        col_warn, col_star = st.columns([2, 1])
        alertas = obtener_alertas()
        
        with col_warn:
            if alertas:
                html_alertas = "<br>".join(alertas)
                st.markdown(f"<div class='alerta-box'>⚠️ ALERTA DE STOCK:<br>{html_alertas}</div>", unsafe_allow_html=True)
            else:
                st.info("✅ Inventario estable")
        
        prod_star, cant_star = obtener_estrella()
        with col_star:
            if prod_star:
                st.markdown(f"<div class='estrella-box'>🏆 <b>Más Vendido:</b><br>{prod_star}<br>({cant_star} un.)</div>", unsafe_allow_html=True)

        # Mostrar mensajes de descuento de inventario (Feedback)
        if st.session_state.msg_inv:
            for m in st.session_state.msg_inv:
                st.toast(m, icon="📉")
            st.session_state.msg_inv = [] # Limpiar mensajes

        st.divider()

        # --- FORMULARIO DE VENTA ---
        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        
        if not df_menu.empty:
            c1, c2 = st.columns([3, 1])
            opciones = [f"{row['nombre']} - S/{row['precio']}" for i, row in df_menu.iterrows()]
            seleccion = c1.selectbox("¿Qué lleva el cliente?", opciones)
            cantidad = c2.number_input("Cantidad", 1, 50, 1)
            
            # Datos base
            nombre_prod = seleccion.split(" - S/")[0]
            precio_base = float(seleccion.split(" - S/")[1])
            
            # Extras
            st.markdown("###### Adicionales (+ S/ 1.00)")
            col_x1, col_x2 = st.columns(2)
            add_top = col_x1.checkbox("🍬 Topping")
            add_con = col_x2.checkbox("🍦 Cono Extra")
            
            extras_total = (1 if add_top else 0) * cantidad + (1 if add_con else 0) * cantidad
            total_final = (precio_base * cantidad) + extras_total
            
            st.markdown(f"### 💰 Total a Cobrar: S/ {total_final:.2f}")
            metodo = st.radio("Pago:", ["Efectivo", "Yape/Plin", "Tarjeta"], horizontal=True)
            
            if st.button("✅ COBRAR", type="primary", use_container_width=True):
                # 1. Registrar venta
                run_query("INSERT INTO ventas (producto, precio_base, cantidad, extras, total, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
                          (nombre_prod, precio_base, cantidad, extras_total, total_final, metodo, datetime.now()))
                
                # 2. Descontar y guardar mensajes de confirmación
                msgs = procesar_venta_inventario(nombre_prod, cantidad, add_con, add_top)
                st.session_state.msg_inv = msgs # Guardar para mostrar al recargar
                
                st.rerun()
        else:
            st.warning("Ve a 'Productos' para configurar tu menú.")

    # ------------------------------------------------------------------
    # 2. PRODUCTOS (VINCULACIÓN INMEDIATA) - AQUÍ ESTÁ EL CAMBIO IMPORTANTE
    # ------------------------------------------------------------------
    elif menu == "📝 Productos (Menú)":
        st.header("Gestión de Productos")
        
        # Primero revisamos si hay insumos
        df_insu = run_query("SELECT * FROM insumos ORDER BY nombre", return_data=True)
        lista_insumos = df_insu['nombre'].unique() if not df_insu.empty else []
        
        st.subheader("Crear Nuevo Producto")
        st.markdown("Define el producto y **automáticamente** vincúlalo a un insumo (Ej: Cono Chocolate -> Gasta 1 Barquillo).")
        
        with st.form("nuevo_producto_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            nom = c1.text_input("Nombre (ej. Cono Doble)")
            pre = c2.number_input("Precio Venta (S/)", min_value=0.0)
            cat = c3.selectbox("Categoría", ["Helado", "Paleta", "Bebida", "Postre", "Otro/Consumible"])
            
            st.divider()
            st.markdown("🔻 **Vinculación con Inventario (Obligatorio para control)**")
            
            col_i1, col_i2 = st.columns(2)
            if len(lista_insumos) > 0:
                insumo_elegido = col_i1.selectbox("¿Qué insumo principal gasta?", lista_insumos)
                cant_gasto = col_i2.number_input(f"¿Cuánta cantidad de '{insumo_elegido}' usa?", value=1.0)
                sin_stock = False
            else:
                st.error("⚠️ No hay insumos registrados. Ve a 'Insumos' primero.")
                sin_stock = True
            
            btn_guardar = st.form_submit_button("Guardar Producto y Vincular")
            
            if btn_guardar and nom and not sin_stock:
                # 1. Crear Producto
                prod_id = run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?, ?, ?)", (nom, pre, cat))
                
                # 2. Crear Vinculo (Receta) INMEDIATAMENTE
                # Buscar ID del insumo seleccionado
                id_insumo = df_insu[df_insu['nombre'] == insumo_elegido]['id'].values[0]
                run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?, ?, ?)", (prod_id, id_insumo, cant_gasto))
                
                st.success(f"✅ Producto '{nom}' creado y vinculado a '{insumo_elegido}'.")
                st.rerun()

        st.divider()
        st.subheader("Lista de Productos y sus Recetas")
        recetas = run_query("""
            SELECT m.nombre as Producto, m.precio as Precio, m.categoria, i.nombre as Gasta_Insumo, r.cantidad_insumo as Cantidad
            FROM menu m
            LEFT JOIN recetas r ON m.id = r.menu_id
            LEFT JOIN insumos i ON r.insumo_id = i.id
        """, return_data=True)
        st.dataframe(recetas, use_container_width=True)

    # ------------------------------------------------------------------
    # 3. INSUMOS (INVENTARIO)
    # ------------------------------------------------------------------
    elif menu == "📦 Insumos (Inventario)":
        st.header("Almacén e Insumos")
        
        with st.expander("➕ Registrar Nuevo Insumo (Lo que compras)"):
            with st.form("form_insumo", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                i_nom = c1.text_input("Nombre (ej. Cono Waffle)")
                i_cant = c2.number_input("Stock Actual", min_value=0.0)
                i_uni = c3.text_input("Unidad (Caja, Pza)")
                i_min = c4.number_input("Mínimo (Alerta)", value=10.0)
                
                if st.form_submit_button("Guardar Insumo"):
                    run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?,?,?,?)", (i_nom, i_cant, i_uni, i_min))
                    st.success("Insumo guardado.")
                    st.rerun()
        
        st.subheader("Inventario en Tiempo Real")
        df_inv = run_query("SELECT * FROM insumos ORDER BY cantidad ASC", return_data=True)
        
        if not df_inv.empty:
            for _, row in df_inv.iterrows():
                # Colores semáforo
                bg = "white"
                borde = "green"
                txt_estado = "OK"
                
                if row['cantidad'] <= (row['minimo']/2):
                    bg = "#ffe6e6"
                    borde = "red"
                    txt_estado = "CRÍTICO"
                elif row['cantidad'] <= row['minimo']:
                    bg = "#fffbe6"
                    borde = "orange"
                    txt_estado = "BAJO"
                
                col_card, col_edit = st.columns([4, 1])
                with col_card:
                    st.markdown(f"""
                    <div style="background-color:{bg}; padding:10px; border-radius:5px; border-left: 5px solid {borde}; margin-bottom:5px;">
                        <b>{row['nombre']}</b> ({row['unidad']}) <br>
                        Stock: <span style="font-size:1.2em; font-weight:bold">{row['cantidad']}</span> 
                        <span style="float:right; color:{borde}; font-weight:bold">{txt_estado}</span>
                    </div>
                    """, unsafe_allow_html=True)
                with col_edit:
                    with st.popover("📝"):
                        nuevo_stock = st.number_input(f"Stock Real", value=float(row['cantidad']), key=f"inv_{row['id']}")
                        if st.button("Guardar", key=f"btn_{row['id']}"):
                            run_query("UPDATE insumos SET cantidad = ? WHERE id = ?", (nuevo_stock, row['id']))
                            st.rerun()
        else:
            st.info("No hay insumos registrados.")

    # ------------------------------------------------------------------
    # 4. CIERRE Y REPORTES
    # ------------------------------------------------------------------
    elif menu == "📊 Cierre de Día":
        st.header("Cierre de Caja")
        hoy = datetime.now().date()
        
        df_ventas = run_query("SELECT * FROM ventas", return_data=True)
        
        if not df_ventas.empty:
            df_ventas['fecha'] = pd.to_datetime(df_ventas['fecha'])
            ventas_hoy = df_ventas[df_ventas['fecha'].dt.date == hoy]
            
            total = ventas_hoy['total'].sum()
            extras = ventas_hoy['extras'].sum()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Ventas Totales", f"S/ {total:,.2f}")
            c2.metric("Extras Cobrados", f"S/ {extras:,.2f}")
            c3.metric("Transacciones", len(ventas_hoy))
            
            st.dataframe(ventas_hoy[['fecha', 'producto', 'cantidad', 'extras', 'total', 'metodo_pago']], use_container_width=True)
            
            col_pdf, col_excel = st.columns(2)
            
            try:
                pdf_bytes = generar_pdf(ventas_hoy, total, str(hoy))
                col_pdf.download_button("📄 Descargar Reporte PDF", pdf_bytes, f"Cierre_{hoy}.pdf", "application/pdf")
            except Exception as e:
                col_pdf.error("Error PDF. Revisa librería fpdf.")
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer) as writer:
                ventas_hoy.to_excel(writer, index=False)
            col_excel.download_button("📊 Descargar Excel", buffer.getvalue(), f"Ventas_{hoy}.xlsx")
            
        else:
            st.info("Aún no hay ventas registradas.")

if __name__ == '__main__':
    main()
