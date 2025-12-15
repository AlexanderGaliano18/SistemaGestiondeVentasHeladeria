import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF
import pytz

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Heladería Master", layout="wide", page_icon="🍦")

# --- NOMBRE DE LA BD ---
DB_NAME = 'heladeria_v9_final.db'

# --- HORA PERÚ ---
def get_hora_peru():
    return datetime.now(pytz.timezone('America/Lima'))

# --- ESTILOS ---
st.markdown("""
<style>
    /* Métricas */
    .stMetric { background-color: rgba(128, 128, 128, 0.1); border: 1px solid rgba(128, 128, 128, 0.2); padding: 10px; border-radius: 5px; }
    
    /* Alertas Dashboard */
    .alert-critico { background-color: rgba(255, 0, 0, 0.15); border-left: 5px solid #ff0000; padding: 10px; border-radius: 5px; color: #ff4b4b; font-weight: bold; margin-bottom: 5px;}
    .alert-bajo { background-color: rgba(255, 193, 7, 0.15); border-left: 5px solid #ffc107; padding: 10px; border-radius: 5px; color: #d39e00; font-weight: bold; margin-bottom: 5px;}
    .star-product { background-color: rgba(0, 123, 255, 0.1); border: 1px solid #007bff; padding: 15px; border-radius: 10px; text-align: center; }
    
    /* Cajas Generales */
    .merma-box { background-color: rgba(255, 75, 75, 0.1); border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 5px; }
    .compra-box { background-color: rgba(40, 167, 69, 0.1); border-left: 5px solid #28a745; padding: 15px; border-radius: 5px; }
    .cierre-box { background-color: rgba(255, 193, 7, 0.1); border-left: 5px solid #ffc107; padding: 15px; border-radius: 5px; }
    .respaldo-box { background-color: rgba(23, 162, 184, 0.1); border: 1px solid #17a2b8; padding: 15px; border-radius: 5px; }
    .total-display { font-size: 26px; font-weight: bold; text-align: right; padding: 10px; border-top: 1px solid rgba(128, 128, 128, 0.2); }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: rgba(128, 128, 128, 0.1); border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: rgba(128, 128, 128, 0.05); border-bottom: 2px solid #1565c0; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto_nombre TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, tipo TEXT, razon TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cierres (id INTEGER PRIMARY KEY, fecha_cierre TIMESTAMP, total_turno REAL, responsable TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reportes_pdf (id INTEGER PRIMARY KEY, fecha TIMESTAMP, nombre_archivo TEXT, pdf_data BLOB)''')
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect(DB_NAME)
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

# --- FUNCIONES AUXILIARES ---
def get_ultimo_cierre():
    df = run_query("SELECT fecha_cierre FROM cierres ORDER BY id DESC LIMIT 1", return_data=True)
    if not df.empty:
        return pd.to_datetime(df.iloc[0]['fecha_cierre']).tz_convert('America/Lima')
    return None

def cerrar_turno_db(total, responsable):
    ahora = get_hora_peru()
    run_query("INSERT INTO cierres (fecha_cierre, total_turno, responsable) VALUES (?,?,?)", (ahora, total, responsable))

def guardar_pdf_en_bd(nombre_archivo, pdf_bytes):
    ahora = get_hora_peru()
    run_query("INSERT INTO reportes_pdf (fecha, nombre_archivo, pdf_data) VALUES (?,?,?)", (ahora, nombre_archivo, pdf_bytes))

def log_movimiento(insumo, cantidad, tipo, razon):
    ahora = get_hora_peru()
    run_query("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
              (insumo, cantidad, tipo, razon, ahora))

# --- FUNCIONES DASHBOARD (ALERTAS Y ESTRELLA) ---
def obtener_alertas_stock():
    """Devuelve HTML con las alertas de stock"""
    df = run_query("SELECT nombre, cantidad, minimo, unidad FROM insumos", return_data=True)
    alertas_html = ""
    if not df.empty:
        for _, row in df.iterrows():
            stock = row['cantidad']
            minimo = row['minimo']
            nombre = row['nombre']
            
            if stock <= (minimo / 2): # Crítico
                alertas_html += f"<div class='alert-critico'>🚨 CRÍTICO: {nombre} ({stock} {row['unidad']})</div>"
            elif stock <= minimo: # Bajo
                alertas_html += f"<div class='alert-bajo'>⚠️ BAJO: {nombre} ({stock} {row['unidad']})</div>"
    
    return alertas_html

def obtener_producto_estrella():
    """Devuelve el producto más vendido de HOY (Hora Perú)"""
    hoy = get_hora_peru().date()
    df = run_query("SELECT * FROM ventas", return_data=True)
    
    if not df.empty:
        df['fecha'] = pd.to_datetime(df['fecha']).dt.tz_convert('America/Lima')
        v_hoy = df[df['fecha'].dt.date == hoy]
        
        if not v_hoy.empty:
            # Agrupar por producto y sumar cantidad
            top = v_hoy.groupby('producto_nombre')['cantidad'].sum().sort_values(ascending=False).head(1)
            if not top.empty:
                return top.index[0], int(top.values[0])
    return None, 0

# --- PROCESAR VENTA ---
def procesar_descuento_stock(producto_nombre, cantidad_vendida, cant_conos_extra, cant_toppings):
    mensajes = []
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ahora = get_hora_peru()
    
    c.execute("SELECT id FROM menu WHERE nombre = ?", (producto_nombre,))
    res_prod = c.fetchone()
    if res_prod:
        prod_id = res_prod[0]
        c.execute("SELECT r.insumo_id, r.cantidad_insumo, i.nombre FROM recetas r JOIN insumos i ON r.insumo_id = i.id WHERE r.menu_id = ?", (prod_id,))
        ingredientes = c.fetchall()
        for insumo_id, cant_receta, nom_insumo in ingredientes:
            total_bajar = cant_receta * cantidad_vendida
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (total_bajar, insumo_id))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (nom_insumo, total_bajar, 'SALIDA', f'Venta: {producto_nombre}', ahora))
            mensajes.append(f"📉 {nom_insumo}: -{total_bajar}")

    if cant_conos_extra > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
        res_cono = c.fetchone()
        if res_cono:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_conos_extra, res_cono[0]))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_cono[1], cant_conos_extra, 'SALIDA', 'Venta: Cono Extra', ahora))
            mensajes.append(f"📉 {res_cono[1]}: -{cant_conos_extra}")

    if cant_toppings > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
        res_top = c.fetchone()
        if res_top:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_toppings, res_top[0]))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_top[1], cant_toppings, 'SALIDA', 'Venta: Topping Extra', ahora))
            mensajes.append(f"📉 {res_top[1]}: -{cant_toppings}")

    conn.commit()
    conn.close()
    return mensajes

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Neverita - Reporte', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_dia, fecha, titulo="Reporte"):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, txt=f"{titulo} - {fecha}", ln=1)
    
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(20, 8, "Hora", 1, 0, 'C', 1)
    pdf.cell(70, 8, "Producto", 1, 0, 'C', 1)
    pdf.cell(20, 8, "Cant.", 1, 0, 'C', 1)
    pdf.cell(25, 8, "Extras ($)", 1, 0, 'C', 1)
    pdf.cell(25, 8, "Total ($)", 1, 0, 'C', 1)
    pdf.cell(30, 8, "Pago", 1, 1, 'C', 1)
    
    pdf.set_font("Arial", size=9)
    for _, row in df_ventas.iterrows():
        try:
            hora = row['fecha'].strftime('%H:%M')
        except:
            hora = str(row['fecha'])[-8:-3]

        pdf.cell(20, 8, hora, 1, 0, 'C')
        pdf.cell(70, 8, str(row['producto_nombre'])[:30], 1)
        pdf.cell(20, 8, str(row['cantidad']), 1, 0, 'C')
        pdf.cell(25, 8, f"{row['extras']:.2f}", 1, 0, 'C')
        pdf.cell(25, 8, f"{row['total']:.2f}", 1, 0, 'C')
        pdf.cell(30, 8, row['metodo_pago'], 1, 1, 'C')
        
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"TOTAL: S/ {total_dia:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN ---
def main():
    init_db()
    if 'carrito' not in st.session_state: st.session_state.carrito = []
    if 'logs' not in st.session_state: st.session_state.logs = []

    # Logo
    try:
        st.sidebar.image("img/logo1.png", use_container_width=True)
    except:
        st.sidebar.warning("Falta logo")

    st.sidebar.title("Menú Principal")
    
    opcion = st.sidebar.radio("Ir a:", [
        "🛒 Caja (Vender)", 
        "🔒 Cierre de Caja", 
        "📦 Inventario", 
        "📉 Mermas", 
        "📝 Productos", 
        "📊 Reportes",
        "💾 Respaldo"
    ])

    # -----------------------------------------------------------
    # 1. CAJA (VENDER) - CON DASHBOARD RECUPERADO
    # -----------------------------------------------------------
    if opcion == "🛒 Caja (Vender)":
        st.header("Punto de Venta")
        
        # --- DASHBOARD SUPERIOR (ALERTAS Y ESTRELLA) ---
        col_alerts, col_star = st.columns([2, 1])
        
        with col_alerts:
            html_alerts = obtener_alertas_stock()
            if html_alerts:
                st.markdown(html_alerts, unsafe_allow_html=True)
            else:
                st.success("✅ Inventario Saludable (Sin alertas)")
        
        with col_star:
            nom_star, cant_star = obtener_producto_estrella()
            if nom_star:
                st.markdown(f"""
                <div class='star-product'>
                    🏆 <b>Más Vendido Hoy:</b><br>
                    <span style='font-size: 1.2em'>{nom_star}</span><br>
                    ({cant_star} un.)
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Sin ventas hoy")
        
        st.divider()
        
        # --- DINERO EN CAJA ---
        ultimo_cierre = get_ultimo_cierre()
        df_todas = run_query("SELECT * FROM ventas", return_data=True)
        total_turno_actual = 0.0
        
        if not df_todas.empty:
            df_todas['fecha'] = pd.to_datetime(df_todas['fecha']).dt.tz_convert('America/Lima')
            if ultimo_cierre:
                df_turno = df_todas[df_todas['fecha'] > ultimo_cierre]
            else:
                df_turno = df_todas
            total_turno_actual = df_turno['total'].sum()
        
        st.metric("💰 Dinero en Caja (Corte Actual)", f"S/ {total_turno_actual:,.2f}")
        
        st.subheader("Nueva Venta")
        
        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        if not df_menu.empty:
            c1, c2, c3 = st.columns([3, 1, 1])
            opciones = [f"{row['nombre']} | S/{row['precio']}" for i, row in df_menu.iterrows()]
            seleccion = c1.selectbox("Producto", opciones)
            cantidad = c2.number_input("Cantidad", 1, 50, 1)
            
            nombre_prod = seleccion.split(" | S/")[0]
            precio_base = float(seleccion.split(" | S/")[1])
            
            cx1, cx2 = st.columns(2)
            n_toppings = cx1.number_input("¿Cuántos con Topping?", 0, cantidad * 5, 0)
            n_conos = cx2.number_input("¿Cuántos con Cono Extra?", 0, cantidad * 5, 0)
            
            subtotal = (precio_base * cantidad) + (n_toppings * 1.0) + (n_conos * 1.0)
            c3.metric("Subtotal", f"S/ {subtotal:.2f}")
            
            if st.button("➕ Agregar al Carrito"):
                st.session_state.carrito.append({
                    "producto": nombre_prod, "precio_base": precio_base, "cantidad": cantidad,
                    "cant_toppings": n_toppings, "cant_conos": n_conos, 
                    "extras_costo": (n_toppings+n_conos), "subtotal": subtotal
                })
                st.toast("Agregado")

        st.divider()
        if len(st.session_state.carrito) > 0:
            st.write("### 🛒 Carrito de Compras")
            df_c = pd.DataFrame(st.session_state.carrito)
            st.dataframe(df_c[['cantidad', 'producto', 'cant_toppings', 'cant_conos', 'subtotal']], use_container_width=True)
            
            total_g = sum(x['subtotal'] for x in st.session_state.carrito)
            c_tot, c_pay = st.columns([2, 1])
            c_tot.markdown(f"<div class='total-display'>TOTAL: S/ {total_g:.2f}</div>", unsafe_allow_html=True)
            
            with c_pay:
                metodo = st.radio("Pago", ["Efectivo", "Yape", "Tarjeta"], horizontal=True)
                if st.button("✅ COBRAR", type="primary", use_container_width=True):
                    hora = get_hora_peru()
                    for item in st.session_state.carrito:
                        run_query("INSERT INTO ventas (producto_nombre, precio_base, cantidad, extras, total, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
                                  (item['producto'], item['precio_base'], item['cantidad'], item['extras_costo'], item['subtotal'], metodo, hora))
                        logs = procesar_descuento_stock(item['producto'], item['cantidad'], item['cant_conos'], item['cant_toppings'])
                        st.session_state.logs.extend(logs)
                    
                    st.session_state.carrito = []
                    st.success(f"Venta registrada {hora.strftime('%H:%M')}")
                    st.rerun()
            
            if st.button("Vaciar Lista"):
                st.session_state.carrito = []
                st.rerun()

    # -----------------------------------------------------------
    # 2. CIERRE DE CAJA
    # -----------------------------------------------------------
    elif opcion == "🔒 Cierre de Caja":
        st.header("Cierre de Caja")
        st.markdown("""<div class="cierre-box">⚠️ Al cerrar caja, el contador se reinicia a 0.</div>""", unsafe_allow_html=True)
        
        ultimo_cierre = get_ultimo_cierre()
        df_todas = run_query("SELECT * FROM ventas", return_data=True)
        df_turno = pd.DataFrame()
        total_turno = 0.0
        
        if not df_todas.empty:
            df_todas['fecha'] = pd.to_datetime(df_todas['fecha']).dt.tz_convert('America/Lima')
            if ultimo_cierre:
                df_turno = df_todas[df_todas['fecha'] > ultimo_cierre]
            else:
                df_turno = df_todas
            total_turno = df_turno['total'].sum()
        
        col_info, col_action = st.columns([2, 1])
        
        with col_info:
            inicio_str = ultimo_cierre.strftime('%d/%m/%Y %H:%M') if ultimo_cierre else 'Inicio histórico'
            st.metric("Total a Cerrar", f"S/ {total_turno:,.2f}")
            st.caption(f"Ventas desde: {inicio_str}")
        
        with col_action:
            responsable = st.text_input("Responsable")
            if st.button("🔒 CERRAR CAJA AHORA", type="primary"):
                if responsable:
                    cerrar_turno_db(total_turno, responsable)
                    try:
                        ahora_str = get_hora_peru().strftime('%d-%m-%Y_%H-%M')
                        nombre_pdf = f"Cierre_{ahora_str}_{responsable}.pdf"
                        pdf_bytes = generar_pdf(df_turno, total_turno, ahora_str, f"Cierre - {responsable}")
                        guardar_pdf_en_bd(nombre_pdf, pdf_bytes)
                        st.download_button("⬇️ Descargar Reporte", pdf_bytes, nombre_pdf, "application/pdf")
                        st.success("Caja Cerrada.")
                    except Exception as e:
                        st.error(f"Error PDF: {e}")
                else:
                    st.warning("Falta nombre.")
        
        if not df_turno.empty:
            st.divider()
            with st.expander("📝 Eliminar Ventas del Turno Actual"):
                for i, row in df_turno.iterrows():
                    cols = st.columns([1, 3, 2, 2, 1])
                    cols[0].write(row['fecha'].strftime('%H:%M'))
                    cols[1].write(f"{row['producto_nombre']}")
                    cols[2].write(f"Cant: {row['cantidad']}")
                    cols[3].write(f"S/ {row['total']:.2f}")
                    if cols[4].button("❌", key=f"del_vt_{row['id']}"):
                        run_query("DELETE FROM ventas WHERE id=?", (row['id'],))
                        st.rerun()

    # -----------------------------------------------------------
    # 3. INVENTARIO
    # -----------------------------------------------------------
    elif opcion == "📦 Inventario":
        st.header("Inventario")
        tab1, tab2, tab3 = st.tabs(["Stock", "Compras", "Kardex"])
        
        with tab1:
            df_i = run_query("SELECT * FROM insumos ORDER BY cantidad ASC", return_data=True)
            edited_df = st.data_editor(df_i, key="ed_st", hide_index=True, use_container_width=True, column_config={"id": st.column_config.NumberColumn(disabled=True)})
            if not df_i.equals(edited_df):
                for i, r in edited_df.iterrows():
                    run_query("UPDATE insumos SET nombre=?, cantidad=?, unidad=?, minimo=? WHERE id=?", (r['nombre'], r['cantidad'], r['unidad'], r['minimo'], r['id']))
                st.toast("Guardado")

        with tab2:
            st.markdown("""<div class="compra-box">Ingreso de Mercadería</div>""", unsafe_allow_html=True)
            mode = st.radio("Tipo:", ["Reponer", "Nuevo"], horizontal=True)
            if mode == "Reponer":
                df_x = run_query("SELECT * FROM insumos", return_data=True)
                if not df_x.empty:
                    with st.form("rep"):
                        c1, c2 = st.columns(2)
                        ins = c1.selectbox("Insumo", df_x['nombre'].unique())
                        t_dato = c2.radio("Medida", ["Unidades", "Decimales"], horizontal=True)
                        step = 1.0 if "Unidades" in t_dato else 0.1
                        fmt = "%d" if "Unidades" in t_dato else "%.2f"
                        min_v = 1.0 if "Unidades" in t_dato else 0.1
                        
                        cant = st.number_input("Cantidad", step=step, format=fmt, min_value=min_v)
                        nota = st.text_input("Nota")
                        if st.form_submit_button("Sumar"):
                            run_query("UPDATE insumos SET cantidad=cantidad+? WHERE nombre=?", (cant, ins))
                            log_movimiento(ins, cant, 'ENTRADA', f"Compra: {nota}")
                            st.success("Listo")
            else:
                with st.form("new"):
                    c1, c2 = st.columns(2)
                    n = c1.text_input("Nombre")
                    u = c2.text_input("Unidad")
                    c3, c4 = st.columns(2)
                    t_dato = st.radio("Medida", ["Unidades", "Decimales"], horizontal=True)
                    step = 1.0 if "Unidades" in t_dato else 0.1
                    fmt = "%d" if "Unidades" in t_dato else "%.2f"
                    min_v = 1.0 if "Unidades" in t_dato else 0.0
                    
                    q = c3.number_input("Cant", step=step, format=fmt, min_value=min_v)
                    m = c4.number_input("Min", 5.0)
                    if st.form_submit_button("Crear"):
                        run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?,?,?,?)", (n, q, u, m))
                        log_movimiento(n, q, 'ENTRADA', 'Nuevo')
                        st.success("Creado")
                        st.rerun()

        with tab3:
            df_k = run_query("SELECT * FROM movimientos ORDER BY id DESC", return_data=True)
            if not df_k.empty:
                df_k['fecha'] = pd.to_datetime(df_k['fecha']).dt.strftime('%d/%m %H:%M')
                st.dataframe(df_k, use_container_width=True)

    # -----------------------------------------------------------
    # 4. MERMAS
    # -----------------------------------------------------------
    elif opcion == "📉 Mermas":
        st.header("Mermas")
        st.markdown("""<div class="merma-box">Salida sin dinero.</div>""", unsafe_allow_html=True)
        df_ins = run_query("SELECT * FROM insumos", return_data=True)
        if not df_ins.empty:
            with st.form("merm"):
                c1, c2 = st.columns(2)
                i_sel = c1.selectbox("Insumo", df_ins['nombre'].unique())
                
                t_dato = c2.radio("Medida", ["Unidades", "Decimales"], horizontal=True)
                step_m = 1.0 if "Unidades" in t_dato else 0.1
                fmt_m = "%d" if "Unidades" in t_dato else "%.2f"
                min_m = 1.0 if "Unidades" in t_dato else 0.1
                
                q = st.number_input("Cantidad", step=step_m, format=fmt_m, min_value=min_m)
                r = st.text_input("Razón")
                if st.form_submit_button("Registrar"):
                    run_query("UPDATE insumos SET cantidad=cantidad-? WHERE nombre=?", (q, i_sel))
                    run_query("INSERT INTO mermas (insumo_nombre, cantidad, razon, fecha) VALUES (?,?,?,?)", (i_sel, q, r, get_hora_peru()))
                    log_movimiento(i_sel, q, 'SALIDA', f"Merma: {r}")
                    st.error("Registrado")

    # -----------------------------------------------------------
    # 5. PRODUCTOS
    # -----------------------------------------------------------
    elif opcion == "📝 Productos":
        st.header("Productos")
        with st.expander("Nuevo"):
            with st.form("np"):
                n = st.text_input("Nombre")
                p = st.number_input("Precio", 0.0)
                cat = st.selectbox("Cat", ["Helado", "Paleta", "Bebida", "Otro"])
                vinc = st.checkbox("Inventario", True)
                iid = None
                qg = 0
                if vinc:
                    df_i = run_query("SELECT * FROM insumos", return_data=True)
                    if not df_i.empty:
                        mapper = {row['nombre']:row['id'] for i,row in df_i.iterrows()}
                        s = st.selectbox("Gasta", list(mapper.keys()))
                        iid = mapper[s]
                        qg = st.number_input("Cant", 0.1)
                if st.form_submit_button("Guardar"):
                    pid = run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?,?,?)", (n, p, cat))
                    if vinc and iid:
                        run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?,?,?)", (pid, iid, qg))
                    st.success("Ok")
                    st.rerun()
        
        df_m = run_query("SELECT * FROM menu", return_data=True)
        if not df_m.empty:
            for i,r in df_m.iterrows():
                c1,c2,c3 = st.columns([3,1,1])
                c1.write(r['nombre'])
                c2.write(r['precio'])
                if c3.button("🗑️", key=f"dp{r['id']}"):
                    run_query("DELETE FROM menu WHERE id=?", (r['id'],))
                    run_query("DELETE FROM recetas WHERE menu_id=?", (r['id'],))
                    st.rerun()

    # -----------------------------------------------------------
    # 6. REPORTES
    # -----------------------------------------------------------
    elif opcion == "📊 Reportes":
        st.header("Reportes")
        tab_dia, tab_cierres, tab_pdfs = st.tabs(["Ventas del Día", "Cierres", "Historial PDF"])
        
        hoy = get_hora_peru().date()
        
        with tab_dia:
            st.write(f"Total Día: **{hoy}**")
            df_v = run_query("SELECT * FROM ventas ORDER BY id DESC", return_data=True)
            if not df_v.empty:
                df_v['fecha'] = pd.to_datetime(df_v['fecha']).dt.tz_convert('America/Lima')
                v_hoy = df_v[df_v['fecha'].dt.date == hoy]
                tot = v_hoy['total'].sum()
                st.metric("Total", f"S/ {tot:,.2f}")
                
                c1, c2 = st.columns(2)
                try:
                    pdf = generar_pdf(v_hoy, tot, str(hoy), "Reporte Global")
                    c1.download_button("PDF", pdf, f"Dia_{hoy}.pdf")
                except: pass
                
                buff = io.BytesIO()
                v_hoy_exc = v_hoy.copy()
                v_hoy_exc['fecha'] = v_hoy_exc['fecha'].astype(str)
                with pd.ExcelWriter(buff, engine='openpyxl') as w: v_hoy_exc.to_excel(w, index=False)
                c2.download_button("Excel", buff.getvalue(), f"Dia_{hoy}.xlsx")
                
                with st.expander("Eliminar Ventas Históricas"):
                    for i, r in v_hoy.iterrows():
                        cols = st.columns([2, 2, 1])
                        cols[0].write(r['producto_nombre'])
                        cols[1].write(f"S/ {r['total']}")
                        if cols[2].button("❌", key=f"del_h_{r['id']}"):
                            run_query("DELETE FROM ventas WHERE id=?", (r['id'],))
                            st.rerun()
        
        with tab_cierres:
            df_c = run_query("SELECT * FROM cierres ORDER BY id DESC", return_data=True)
            if not df_c.empty:
                df_c['fecha_cierre'] = pd.to_datetime(df_c['fecha_cierre']).dt.tz_convert('America/Lima').dt.strftime('%d/%m %H:%M')
                st.dataframe(df_c, use_container_width=True)

        with tab_pdfs:
            df_p = run_query("SELECT id, fecha, nombre_archivo, pdf_data FROM reportes_pdf ORDER BY id DESC", return_data=True)
            if not df_p.empty:
                for i, r in df_p.iterrows():
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(r['nombre_archivo'])
                    c2.download_button("⬇️", r['pdf_data'], r['nombre_archivo'])
                    if c3.button("🗑️", key=f"dpdf_{r['id']}"):
                        run_query("DELETE FROM reportes_pdf WHERE id=?", (r['id'],))
                        st.rerun()

    # -----------------------------------------------------------
    # 7. RESPALDO
    # -----------------------------------------------------------
    elif opcion == "💾 Respaldo":
        st.header("Respaldo")
        st.markdown("""<div class='respaldo-box'>Descarga tu copia diariamente.</div>""", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("⬇️ Descargar BD"):
                try:
                    with open(DB_NAME, "rb") as fp:
                        st.download_button("Guardar .db", fp, f"Respaldo_{get_hora_peru().date()}.db")
                except: st.error("Error BD")
        with c2:
            up = st.file_uploader("Subir .db", type="db")
            if up and st.button("Restaurar"):
                with open(DB_NAME, "wb") as f: f.write(up.getbuffer())
                st.success("Restaurado")
                st.rerun()

if __name__ == '__main__':
    main()
