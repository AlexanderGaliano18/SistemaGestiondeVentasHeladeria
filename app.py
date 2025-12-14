import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Heladería Artesanal Pro", layout="wide", page_icon="🍦")

# --- ESTILOS CSS ---
st.markdown("""
<style>
    .big-font { font-size:18px !important; }
    .stMetric { background-color: #f8f9fa; border-radius: 10px; padding: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    .alerta-box { background-color: #ffcccc; color: #cc0000; padding: 10px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; }
    .estrella-box { background-color: #e6f7ff; color: #0066cc; padding: 10px; border-radius: 5px; margin-bottom: 10px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('heladeria_pro.db')
    c = conn.cursor()
    # Tablas
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
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
        return None

# --- LÓGICA DE NEGOCIO ---
def descontar_inventario_por_venta(nombre_producto, cantidad_vendida, tiene_cono_extra, tiene_topping):
    conn = sqlite3.connect('heladeria_pro.db')
    c = conn.cursor()
    c.execute("SELECT id FROM menu WHERE nombre = ?", (nombre_producto,))
    res = c.fetchone()
    if res:
        prod_id = res[0]
        c.execute("SELECT insumo_id, cantidad_insumo FROM recetas WHERE menu_id = ?", (prod_id,))
        ingredientes = c.fetchall()
        for insumo_id, cant_requerida in ingredientes:
            total_descontar = cant_requerida * cantidad_vendida
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (total_descontar, insumo_id))
    
    if tiene_cono_extra:
        c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%'", (cantidad_vendida,))
    if tiene_topping:
        c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre LIKE '%Topping%'", (cantidad_vendida,))
    conn.commit()
    conn.close()

def obtener_alertas_criticas():
    """Devuelve lista de insumos en rojo (menos de la mitad del mínimo)"""
    df = run_query("SELECT nombre, cantidad, minimo FROM insumos", return_data=True)
    lista_alertas = []
    if not df.empty:
        for _, row in df.iterrows():
            if row['cantidad'] <= (row['minimo'] / 2):
                lista_alertas.append(f"{row['nombre']} (Quedan: {row['cantidad']})")
    return lista_alertas

def obtener_producto_estrella():
    """Devuelve el producto más vendido de HOY"""
    hoy = datetime.now().date()
    # Consulta SQL mágica para sumar ventas agrupadas por nombre
    query = """
    SELECT producto, SUM(cantidad) as total_vendido 
    FROM ventas 
    WHERE date(fecha) = ? 
    GROUP BY producto 
    ORDER BY total_vendido DESC 
    LIMIT 1
    """
    conn = sqlite3.connect('heladeria_pro.db')
    c = conn.cursor()
    c.execute(query, (hoy,))
    resultado = c.fetchone()
    conn.close()
    
    if resultado:
        return resultado[0], resultado[1] # Nombre, Cantidad
    return None, 0

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Reporte Heladería', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_dia, fecha):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, txt=f"Fecha: {fecha}", ln=1)
    
    pdf.set_fill_color(220, 230, 240)
    pdf.cell(70, 10, "Producto", 1, 0, 'C', 1)
    pdf.cell(20, 10, "Cant.", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Total", 1, 0, 'C', 1)
    pdf.cell(40, 10, "Pago", 1, 1, 'C', 1)
    
    for _, row in df_ventas.iterrows():
        nombre = row['producto'][:30]
        pdf.cell(70, 10, nombre, 1)
        pdf.cell(20, 10, str(row['cantidad']), 1, 0, 'C')
        pdf.cell(30, 10, f"{row['total']:.2f}", 1, 0, 'C')
        pdf.cell(40, 10, row['metodo_pago'], 1, 1, 'C')
    
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"TOTAL: S/ {total_dia:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN ---
def main():
    init_db()
    if 'form_nombre' not in st.session_state: st.session_state.form_nombre = ""
    
    st.sidebar.title("🍦 Heladería System")
    opcion = st.sidebar.radio("Menú", ["🛒 Venta & Caja", "📦 Inventario", "📝 Productos", "📊 Reportes"])

    # ---------------------------------------------------------
    # 1. VENTA & CAJA (DASHBOARD PRINCIPAL)
    # ---------------------------------------------------------
    if opcion == "🛒 Venta & Caja":
        st.header("Punto de Venta")
        
        # --- SECCIÓN SUPERIOR: ALERTAS Y ESTRELLAS ---
        col_alert, col_star = st.columns([2, 1])
        
        # A. Alertas Críticas (Visible aquí para no ir a inventario)
        alertas = obtener_alertas_criticas()
        with col_alert:
            if alertas:
                st.markdown(f"""
                <div class="alerta-box">
                    🚨 ATENCIÓN - STOCK CRÍTICO:<br>
                    {' | '.join(alertas)}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.success("✅ Inventario Saludable")
        
        # B. Producto Estrella
        nom_estrella, cant_estrella = obtener_producto_estrella()
        with col_star:
            if nom_estrella:
                st.markdown(f"""
                <div class="estrella-box">
                    🏆 <b>Más Vendido Hoy:</b><br>
                    {nom_estrella} ({cant_estrella} un.)
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Sin ventas aún hoy")

        st.divider()
        
        # --- ZONA DE REGISTRO ---
        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        
        if not df_menu.empty:
            c1, c2 = st.columns([3, 1])
            with c1:
                lista_prods = [f"{row['nombre']} - S/{row['precio']}" for i, row in df_menu.iterrows()]
                seleccion = st.selectbox("Producto a Vender", lista_prods)
            with c2:
                cantidad = st.number_input("Cantidad", min_value=1, value=1)

            nombre_prod = seleccion.split(" - S/")[0]
            precio_base = float(seleccion.split(" - S/")[1])
            
            # Extras
            col_x1, col_x2, col_x3 = st.columns(3)
            with col_x1: add_top = st.checkbox("🍬 Topping (+S/1)")
            with col_x2: add_con = st.checkbox("🍦 Cono Extra (+S/1)")
            
            extra_total = (1 if add_top else 0) * cantidad + (1 if add_con else 0) * cantidad
            total_final = (precio_base * cantidad) + extra_total
            
            # Botón de Cobro Gigante
            st.markdown(f"### Total: S/ {total_final:.2f}")
            metodo = st.radio("Pago:", ["Efectivo", "Yape/Plin", "Tarjeta"], horizontal=True)
            
            if st.button("✅ COBRAR VENTA", type="primary", use_container_width=True):
                run_query("""INSERT INTO ventas (producto, precio_base, cantidad, extras, total, metodo_pago, fecha)
                             VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                             (nombre_prod, precio_base, cantidad, extra_total, total_final, metodo, datetime.now()))
                descontar_inventario_por_venta(nombre_prod, cantidad, add_con, add_top)
                st.toast(f"¡Venta de {nombre_prod} registrada!")
                st.rerun() # Recarga para actualizar alertas y producto estrella
        else:
            st.warning("Agrega productos en el menú primero.")

    # ---------------------------------------------------------
    # 2. INVENTARIO (SEMAFORO)
    # ---------------------------------------------------------
    elif opcion == "📦 Inventario":
        st.header("Almacén de Insumos")
        
        # Agregar
        with st.expander("➕ Ingresar Mercadería (Compras)"):
            with st.form("add_inv", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                n_nom = c1.text_input("Nombre (ej. Vasos)")
                n_cant = c2.number_input("Cantidad", min_value=0.0)
                n_min = c3.number_input("Avisar si baja de:", min_value=1.0, value=10.0)
                n_uni = st.text_input("Unidad (Cajas, Litros)")
                if st.form_submit_button("Guardar"):
                    run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?, ?, ?, ?)", 
                              (n_nom, n_cant, n_uni, n_min))
                    st.success("Guardado")
                    st.rerun()

        st.subheader("Estado del Stock")
        df_inv = run_query("SELECT * FROM insumos", return_data=True)
        
        if not df_inv.empty:
            for _, row in df_inv.iterrows():
                # Lógica del Semáforo
                stock = row['cantidad']
                minimo = row['minimo']
                
                estado_color = "green"
                estado_txt = "OK"
                bg_color = "#f0fff4" # Verde claro
                
                if stock <= (minimo / 2):
                    estado_color = "red"
                    estado_txt = "CRÍTICO"
                    bg_color = "#ffe6e6" # Rojo claro
                elif stock <= minimo:
                    estado_color = "orange"
                    estado_txt = "BAJO"
                    bg_color = "#fff8e1" # Amarillo claro
                
                with st.container():
                    st.markdown(f"""
                    <div style="background-color: {bg_color}; padding: 10px; border-radius: 10px; margin-bottom: 5px; border-left: 5px solid {estado_color};">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <h4 style="margin:0; color:black;">{row['nombre']}</h4>
                                <small>{row['unidad']}</small>
                            </div>
                            <div style="text-align:right;">
                                <h3 style="margin:0; color:{estado_color};">{stock}</h3>
                                <small style="color:{estado_color}; font-weight:bold;">{estado_txt}</small>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Edición rápida
                    with st.popover(f"✏️ Editar {row['nombre']}"):
                         new_val = st.number_input(f"Corrección manual", value=float(stock), key=row['id'])
                         if st.button("Actualizar", key=f"b_{row['id']}"):
                             run_query("UPDATE insumos SET cantidad = ? WHERE id = ?", (new_val, row['id']))
                             st.rerun()
        else:
            st.info("Inventario vacío.")

    # ---------------------------------------------------------
    # 3. PRODUCTOS (RECETAS)
    # ---------------------------------------------------------
    elif opcion == "📝 Productos":
        st.header("Menú y Recetas")
        
        with st.form("nuevo_prod", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            p_nom = c1.text_input("Nombre Producto")
            p_prec = c2.number_input("Precio", min_value=0.0)
            p_cat = c3.selectbox("Categoría", ["Helado", "Paleta", "Bebida"])
            if st.form_submit_button("Crear Producto"):
                run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?, ?, ?)", (p_nom, p_prec, p_cat))
                st.success("Creado. Ahora vincula sus ingredientes abajo.")
                st.rerun()
        
        st.divider()
        st.subheader("🔗 Vincular Ingredientes (Receta)")
        c_prod, c_insu, c_cant, c_btn = st.columns([3, 3, 2, 2])
        
        df_p = run_query("SELECT * FROM menu", return_data=True)
        df_i = run_query("SELECT * FROM insumos", return_data=True)
        
        if not df_p.empty and not df_i.empty:
            sel_p = c_prod.selectbox("Al vender:", df_p['nombre'].unique())
            sel_i = c_insu.selectbox("Se gasta:", df_i['nombre'].unique())
            sel_q = c_cant.number_input("Cantidad", 0.1, 10.0, 1.0)
            
            if c_btn.button("Vincular"):
                pid = df_p[df_p['nombre']==sel_p]['id'].values[0]
                iid = df_i[df_i['nombre']==sel_i]['id'].values[0]
                run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?, ?, ?)", (pid, iid, sel_q))
                st.toast("Vinculado correctamente")

            # Tabla de recetas
            st.write("Recetario Actual:")
            recetas = run_query("""SELECT m.nombre as Producto, i.nombre as Insumo, r.cantidad_insumo 
                                   FROM recetas r JOIN menu m ON m.id=r.menu_id JOIN insumos i ON i.id=r.insumo_id""", return_data=True)
            st.dataframe(recetas, use_container_width=True)

    # ---------------------------------------------------------
    # 4. REPORTES
    # ---------------------------------------------------------
    elif opcion == "📊 Reportes":
        st.header("Cierre del Día")
        hoy = datetime.now().date()
        
        df = run_query("SELECT * FROM ventas", return_data=True)
        if not df.empty:
            df['fecha'] = pd.to_datetime(df['fecha'])
            hoy_data = df[df['fecha'].dt.date == hoy]
            
            total = hoy_data['total'].sum()
            col1, col2 = st.columns(2)
            col1.metric("Ventas Hoy", f"S/ {total:,.2f}")
            col2.metric("Tickets", len(hoy_data))
            
            st.dataframe(hoy_data, use_container_width=True)
            
            # Descargas
            try:
                pdf = generar_pdf(hoy_data, total, str(hoy))
                st.download_button("📄 Descargar PDF", pdf, f"cierre_{hoy}.pdf", "application/pdf")
            except:
                st.error("Error generando PDF")
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer) as writer: hoy_data.to_excel(writer)
            st.download_button("📊 Descargar Excel", buffer.getvalue(), f"ventas_{hoy}.xlsx")

if __name__ == '__main__':
    main()
