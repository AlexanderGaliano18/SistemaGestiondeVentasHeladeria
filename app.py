import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF
import pytz

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Heladería Master", layout="wide", page_icon="🍦")

# --- NOMBRE DE LA BD (V12 con restauración de stock) ---
DB_NAME = 'heladeria_v12_restore.db'

# --- HORA PERÚ ---
def get_hora_peru():
    return datetime.now(pytz.timezone('America/Lima'))

# --- ESTILOS ---
st.markdown("""
<style>
    /* Métricas */
    .stMetric { background-color: rgba(128, 128, 128, 0.1); border: 1px solid rgba(128, 128, 128, 0.2); padding: 10px; border-radius: 5px; }
    
    /* Alertas */
    .alert-critico { background-color: rgba(255, 0, 0, 0.15); border-left: 5px solid #ff0000; padding: 10px; border-radius: 5px; color: #ff4b4b; font-weight: bold; margin-bottom: 5px;}
    .alert-bajo { background-color: rgba(255, 193, 7, 0.15); border-left: 5px solid #ffc107; padding: 10px; border-radius: 5px; color: #d39e00; font-weight: bold; margin-bottom: 5px;}
    
    /* Cajas */
    .merma-box { background-color: rgba(255, 75, 75, 0.1); border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 5px; }
    .gasto-box { background-color: rgba(255, 159, 67, 0.1); border-left: 5px solid #ff9f43; padding: 15px; border-radius: 5px; }
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

# --- BASE DE DATOS Y MIGRACIÓN AUTOMÁTICA ---
def init_and_migrate_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Tablas base
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    
    # VENTAS ACTUALIZADA: Ahora guarda cant_toppings y cant_conos para poder devolverlos
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto_nombre TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP, cant_toppings INTEGER DEFAULT 0, cant_conos INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, tipo TEXT, razon TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cierres (id INTEGER PRIMARY KEY, fecha_cierre TIMESTAMP, total_turno REAL, responsable TEXT, tipo_cierre TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reportes_pdf (id INTEGER PRIMARY KEY, fecha TIMESTAMP, nombre_archivo TEXT, pdf_data BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS gastos (id INTEGER PRIMARY KEY, razon TEXT, monto REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    
    # --- MIGRACIONES PARA BASES DE DATOS ANTIGUAS ---
    try:
        c.execute("SELECT cant_toppings FROM ventas LIMIT 1")
    except:
        # Si falla, agregamos las columnas nuevas
        c.execute("ALTER TABLE ventas ADD COLUMN cant_toppings INTEGER DEFAULT 0")
        c.execute("ALTER TABLE ventas ADD COLUMN cant_conos INTEGER DEFAULT 0")
    
    try:
        c.execute("SELECT tipo_cierre FROM cierres LIMIT 1")
    except:
        c.execute("ALTER TABLE cierres ADD COLUMN tipo_cierre TEXT")

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

# --- FUNCIONES LÓGICAS ---
def get_ultimo_cierre():
    df = run_query("SELECT fecha_cierre FROM cierres ORDER BY id DESC LIMIT 1", return_data=True)
    if not df.empty:
        return pd.to_datetime(df.iloc[0]['fecha_cierre']).tz_convert('America/Lima')
    return None

def cerrar_turno_db(total, responsable, tipo):
    ahora = get_hora_peru()
    run_query("INSERT INTO cierres (fecha_cierre, total_turno, responsable, tipo_cierre) VALUES (?,?,?,?)", (ahora, total, responsable, tipo))

def guardar_pdf_en_bd(nombre_archivo, pdf_bytes):
    ahora = get_hora_peru()
    run_query("INSERT INTO reportes_pdf (fecha, nombre_archivo, pdf_data) VALUES (?,?,?)", (ahora, nombre_archivo, pdf_bytes))

def log_movimiento(insumo, cantidad, tipo, razon):
    ahora = get_hora_peru()
    run_query("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
              (insumo, cantidad, tipo, razon, ahora))

# --- DASHBOARD ALERTAS ---
def obtener_alertas_stock():
    df = run_query("SELECT nombre, cantidad, minimo, unidad FROM insumos", return_data=True)
    alertas_html = ""
    if not df.empty:
        for _, row in df.iterrows():
            stock = row['cantidad']
            minimo = row['minimo']
            if stock <= (minimo / 2):
                alertas_html += f"<div class='alert-critico'>🚨 CRÍTICO: {row['nombre']} ({stock} {row['unidad']})</div>"
            elif stock <= minimo:
                alertas_html += f"<div class='alert-bajo'>⚠️ BAJO: {row['nombre']} ({stock} {row['unidad']})</div>"
    return alertas_html

def obtener_producto_estrella():
    hoy = get_hora_peru().date()
    df = run_query("SELECT * FROM ventas", return_data=True)
    if not df.empty:
        df['fecha'] = pd.to_datetime(df['fecha']).dt.tz_convert('America/Lima')
        v_hoy = df[df['fecha'].dt.date == hoy]
        if not v_hoy.empty:
            top = v_hoy.groupby('producto_nombre')['cantidad'].sum().sort_values(ascending=False).head(1)
            if not top.empty:
                return top.index[0], int(top.values[0])
    return None, 0

# --- LÓGICA DE INVENTARIO (DESCONTAR Y RESTAURAR) ---

def procesar_descuento_stock(producto_nombre, cantidad_vendida, cant_conos_extra, cant_toppings):
    # Esta función DESCUENTA del inventario al vender
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ahora = get_hora_peru()
    
    # 1. Receta Base
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

    # 2. Extras
    if cant_conos_extra > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
        res_cono = c.fetchone()
        if res_cono:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_conos_extra, res_cono[0]))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_cono[1], cant_conos_extra, 'SALIDA', 'Venta: Cono Extra', ahora))

    if cant_toppings > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
        res_top = c.fetchone()
        if res_top:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_toppings, res_top[0]))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_top[1], cant_toppings, 'SALIDA', 'Venta: Topping Extra', ahora))

    conn.commit()
    conn.close()

def revertir_stock_por_eliminacion(venta_id):
    """
    Restaura el stock cuando se elimina una venta.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ahora = get_hora_peru()
    
    # 1. Obtener datos de la venta a eliminar
    c.execute("SELECT producto_nombre, cantidad, cant_toppings, cant_conos FROM ventas WHERE id = ?", (venta_id,))
    venta = c.fetchone()
    
    if venta:
        prod_nombre, cant_vendida, c_tops, c_conos = venta
        
        # 2. Restaurar Receta Base
        c.execute("SELECT id FROM menu WHERE nombre = ?", (prod_nombre,))
        res_prod = c.fetchone()
        if res_prod:
            prod_id = res_prod[0]
            c.execute("SELECT r.insumo_id, r.cantidad_insumo, i.nombre FROM recetas r JOIN insumos i ON r.insumo_id = i.id WHERE r.menu_id = ?", (prod_id,))
            ingredientes = c.fetchall()
            for insumo_id, cant_receta, nom_insumo in ingredientes:
                total_subir = cant_receta * cant_vendida
                c.execute("UPDATE insumos SET cantidad = cantidad + ? WHERE id = ?", (total_subir, insumo_id))
                # Log en verde (Devolución)
                c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                          (nom_insumo, total_subir, 'DEVOLUCIÓN', f'Anulación Venta: {prod_nombre}', ahora))
        
        # 3. Restaurar Extras (Si existen columnas y valores)
        if c_conos and c_conos > 0:
            c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
            res_cono = c.fetchone()
            if res_cono:
                c.execute("UPDATE insumos SET cantidad = cantidad + ? WHERE id = ?", (c_conos, res_cono[0]))
                c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                          (res_cono[1], c_conos, 'DEVOLUCIÓN', 'Anulación: Cono Extra', ahora))

        if c_tops and c_tops > 0:
            c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
            res_top = c.fetchone()
            if res_top:
                c.execute("UPDATE insumos SET cantidad = cantidad + ? WHERE id = ?", (c_tops, res_top[0]))
                c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                          (res_top[1], c_tops, 'DEVOLUCIÓN', 'Anulación: Topping Extra', ahora))

    conn.commit()
    conn.close()

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Neverita - Reporte', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_ventas, fecha, titulo="Reporte", total_gastos=0.0):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, txt=f"{titulo} - {fecha}", ln=1)
    
    # TABLA VENTAS
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, 10, "Detalle de Ventas", 0, 1)
    
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Arial", 'B', 8)
    pdf.cell(15, 8, "Hora", 1, 0, 'C', 1)
    pdf.cell(65, 8, "Producto", 1, 0, 'C', 1)
    pdf.cell(15, 8, "Cant", 1, 0, 'C', 1)
    pdf.cell(20, 8, "Extras", 1, 0, 'C', 1)
    pdf.cell(25, 8, "Total", 1, 0, 'C', 1)
    pdf.cell(30, 8, "Metodo", 1, 1, 'C', 1)
    
    pdf.set_font("Arial", size=8)
    
    total_efectivo = 0
    total_yape = 0
    
    for _, row in df_ventas.iterrows():
        try: hora = row['fecha'].strftime('%H:%M')
        except: hora = str(row['fecha'])[-8:-3]
        
        if "Efectivo" in row['metodo_pago']: total_efectivo += row['total']
        else: total_yape += row['total']

        pdf.cell(15, 8, hora, 1, 0, 'C')
        pdf.cell(65, 8, str(row['producto_nombre'])[:30], 1)
        pdf.cell(15, 8, str(row['cantidad']), 1, 0, 'C')
        pdf.cell(20, 8, f"{row['extras']:.2f}", 1, 0, 'C')
        pdf.cell(25, 8, f"{row['total']:.2f}", 1, 0, 'C')
        pdf.cell(30, 8, row['metodo_pago'], 1, 1, 'C')
        
    pdf.ln(10)
    
    # RESUMEN
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 10, "Resumen Financiero", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(100, 8, "Ventas Totales:", 1)
    pdf.cell(40, 8, f"S/ {total_ventas:,.2f}", 1, 1, 'R')
    pdf.cell(100, 8, "Gastos del Turno/Dia:", 1)
    pdf.cell(40, 8, f"- S/ {total_gastos:,.2f}", 1, 1, 'R')
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(100, 10, "GANANCIA NETA:", 1)
    pdf.cell(40, 10, f"S/ {(total_ventas - total_gastos):,.2f}", 1, 1, 'R')
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, 10, "Metodos de Pago", 0, 1)
    pdf.set_font("Arial", '', 10)
    pdf.cell(70, 8, f"Efectivo: S/ {total_efectivo:,.2f}", 1, 1)
    pdf.cell(70, 8, f"Yape/Plin: S/ {total_yape:,.2f}", 1, 1)

    return pdf.output(dest='S').encode('latin-1')

# --- MAIN ---
def main():
    init_and_migrate_db()
    
    if 'carrito' not in st.session_state: st.session_state.carrito = []
    if 'logs' not in st.session_state: st.session_state.logs = []

    try: st.sidebar.image("img/logo1.png", use_container_width=True)
    except: st.sidebar.warning("Falta logo")

    st.sidebar.title("Menú Principal")
    
    opcion = st.sidebar.radio("Ir a:", [
        "🛒 Caja (Vender)", 
        "💸 Registrar Gastos",
        "🔒 Cierre de Caja", 
        "📦 Inventario", 
        "📉 Mermas", 
        "📝 Productos", 
        "📊 Reportes",
        "💾 Respaldo"
    ])

    # -----------------------------------------------------------
    # 1. CAJA (VENDER)
    # -----------------------------------------------------------
    if opcion == "🛒 Caja (Vender)":
        st.header("Punto de Venta")
        
        # Dashboard
        col_alerts, col_star = st.columns([2, 1])
        with col_alerts:
            html_alerts = obtener_alertas_stock()
            if html_alerts: st.markdown(html_alerts, unsafe_allow_html=True)
            else: st.success("✅ Inventario Saludable")
        with col_star:
            nom, cant = obtener_producto_estrella()
            if nom: st.markdown(f"<div class='star-product'>🏆 <b>Top Ventas:</b><br>{nom} ({cant})</div>", unsafe_allow_html=True)
        
        st.divider()
        
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
                    "cant_toppings": n_toppings, "cant_conos": n_conos, "extras_costo": (n_toppings+n_conos), "subtotal": subtotal
                })
                st.toast("Agregado")

        st.divider()
        if len(st.session_state.carrito) > 0:
            st.write("### 🛒 Carrito")
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
                        # GUARDAR VENTA CON LOS DETALLES DE EXTRAS PARA PODER RESTAURAR DESPUÉS
                        run_query("""INSERT INTO ventas 
                                     (producto_nombre, precio_base, cantidad, extras, total, metodo_pago, fecha, cant_toppings, cant_conos) 
                                     VALUES (?,?,?,?,?,?,?,?,?)""",
                                  (item['producto'], item['precio_base'], item['cantidad'], item['extras_costo'], item['subtotal'], metodo, hora, item['cant_toppings'], item['cant_conos']))
                        
                        procesar_descuento_stock(item['producto'], item['cantidad'], item['cant_conos'], item['cant_toppings'])
                    
                    st.session_state.carrito = []
                    st.success("Venta registrada")
                    st.rerun()
            
            if st.button("Vaciar Lista"):
                st.session_state.carrito = []
                st.rerun()

    # -----------------------------------------------------------
    # NUEVO: REGISTRAR GASTOS
    # -----------------------------------------------------------
    elif opcion == "💸 Registrar Gastos":
        st.header("Control de Gastos")
        st.markdown("""<div class="gasto-box">Salida de dinero de la caja.</div>""", unsafe_allow_html=True)
        st.divider()
        with st.form("form_gasto"):
            c1, c2 = st.columns(2)
            razon = c1.text_input("Motivo")
            monto = c2.number_input("Monto (S/)", min_value=0.1)
            metodo_gasto = st.selectbox("Pagado con:", ["Efectivo", "Yape", "Otro"])
            if st.form_submit_button("💸 Registrar"):
                if razon and monto > 0:
                    run_query("INSERT INTO gastos (razon, monto, metodo_pago, fecha) VALUES (?,?,?,?)", 
                              (razon, monto, metodo_gasto, get_hora_peru()))
                    st.success(f"Gasto registrado: S/ {monto}")
                    st.rerun()
                else: st.warning("Faltan datos")
        
        st.subheader("Gastos Recientes")
        df_g = run_query("SELECT * FROM gastos ORDER BY id DESC", return_data=True)
        if not df_g.empty:
            df_g['fecha'] = pd.to_datetime(df_g['fecha']).dt.tz_convert('America/Lima')
            st.dataframe(df_g, use_container_width=True)
            with st.expander("Eliminar Gasto"):
                for i, r in df_g.iterrows():
                    c1, c2 = st.columns([4,1])
                    c1.write(f"{r['razon']} - S/{r['monto']}")
                    if c2.button("❌", key=f"dg_{r['id']}"):
                        run_query("DELETE FROM gastos WHERE id=?", (r['id'],))
                        st.rerun()

    # -----------------------------------------------------------
    # 2. CIERRE DE CAJA
    # -----------------------------------------------------------
    elif opcion == "🔒 Cierre de Caja":
        st.header("Cierre de Caja")
        st.markdown("""<div class="cierre-box">⚠️ Ambas opciones reinician el contador a 0.</div>""", unsafe_allow_html=True)
        st.divider()
        
        ultimo_cierre = get_ultimo_cierre()
        
        # VENTAS Y GASTOS DEL TURNO
        df_todas = run_query("SELECT * FROM ventas", return_data=True)
        df_g_all = run_query("SELECT * FROM gastos", return_data=True)
        df_turno = pd.DataFrame()
        total_ventas = 0.0
        total_gastos = 0.0
        
        if not df_todas.empty:
            df_todas['fecha'] = pd.to_datetime(df_todas['fecha']).dt.tz_convert('America/Lima')
            df_turno = df_todas[df_todas['fecha'] > ultimo_cierre] if ultimo_cierre else df_todas
            total_ventas = df_turno['total'].sum()
            
        if not df_g_all.empty:
            df_g_all['fecha'] = pd.to_datetime(df_g_all['fecha']).dt.tz_convert('America/Lima')
            g_turno = df_g_all[df_g_all['fecha'] > ultimo_cierre] if ultimo_cierre else df_g_all
            total_gastos = g_turno['monto'].sum()
        
        col_info, col_action = st.columns([2, 1])
        
        with col_info:
            inicio_str = ultimo_cierre.strftime('%d/%m %H:%M') if ultimo_cierre else 'Inicio'
            st.caption(f"Desde: {inicio_str}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Ventas (+)", f"S/ {total_ventas:,.2f}")
            m2.metric("Gastos (-)", f"S/ {total_gastos:,.2f}")
            m3.metric("Neto", f"S/ {(total_ventas - total_gastos):,.2f}")
        
        with col_action:
            responsable = st.text_input("Responsable")
            if st.button("🔓 Cierre Turno"):
                if responsable:
                    cerrar_turno_db(total_ventas, responsable, "TURNO")
                    try:
                        ahora = get_hora_peru().strftime('%d-%m-%Y_%H-%M')
                        pdf = generar_pdf(df_turno, total_ventas, ahora, f"Cierre Turno - {responsable}", total_gastos)
                        guardar_pdf_en_bd(f"Turno_{ahora}.pdf", pdf)
                        st.download_button("⬇️ PDF", pdf, f"Turno_{ahora}.pdf", "application/pdf")
                        st.success("Hecho.")
                    except: st.error("Error PDF")
                else: st.warning("Nombre?")
            
            if st.button("🏁 CIERRE DÍA", type="primary"):
                if responsable:
                    cerrar_turno_db(total_ventas, responsable, "DEFINITIVO")
                    try:
                        ahora = get_hora_peru().strftime('%d-%m-%Y_%H-%M')
                        pdf = generar_pdf(df_turno, total_ventas, ahora, f"FINAL - {responsable}", total_gastos)
                        guardar_pdf_en_bd(f"FINAL_{ahora}.pdf", pdf)
                        st.download_button("⬇️ PDF FINAL", pdf, f"FINAL_{ahora}.pdf", "application/pdf")
                        st.success("Hecho.")
                    except: st.error("Error PDF")
                else: st.warning("Nombre?")
        
        if not df_turno.empty:
            with st.expander("📝 Eliminar Ventas del Turno (Devuelve Stock)"):
                for i, row in df_turno.iterrows():
                    c1, c2, c3 = st.columns([4, 2, 1])
                    c1.write(f"{row['producto_nombre']} ({row['cantidad']})")
                    c2.write(f"S/ {row['total']}")
                    if c3.button("❌", key=f"dvt_{row['id']}"):
                        revertir_stock_por_eliminacion(row['id']) # <--- RESTAURA STOCK
                        run_query("DELETE FROM ventas WHERE id=?", (row['id'],))
                        st.success("Venta eliminada y stock restaurado.")
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
            st.markdown("""<div class="compra-box">Registrar Compras</div>""", unsafe_allow_html=True)
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
                        cant = st.number_input("Cantidad", step=step, format=fmt, min_value=0.1)
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
                    q = c3.number_input("Cant", step=step, format=fmt)
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
        df_ins = run_query("SELECT * FROM insumos", return_data=True)
        if not df_ins.empty:
            with st.form("merm"):
                c1, c2 = st.columns(2)
                i_sel = c1.selectbox("Insumo", df_ins['nombre'].unique())
                t_dato = c2.radio("Medida", ["Unidades", "Decimales"], horizontal=True)
                step = 1.0 if "Unidades" in t_dato else 0.1
                fmt = "%d" if "Unidades" in t_dato else "%.2f"
                q = st.number_input("Cantidad", step=step, format=fmt, min_value=0.1)
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
            df_g = run_query("SELECT * FROM gastos", return_data=True)
            
            v_hoy = pd.DataFrame()
            tot_v, tot_g = 0.0, 0.0
            tot_efectivo, tot_yape = 0.0, 0.0
            
            if not df_v.empty:
                df_v['fecha'] = pd.to_datetime(df_v['fecha']).dt.tz_convert('America/Lima')
                v_hoy = df_v[df_v['fecha'].dt.date == hoy]
                tot_v = v_hoy['total'].sum()
                # Calculo desglose
                for _, r in v_hoy.iterrows():
                    if "Efectivo" in r['metodo_pago']: tot_efectivo += r['total']
                    else: tot_yape += r['total']
            
            if not df_g.empty:
                df_g['fecha'] = pd.to_datetime(df_g['fecha']).dt.tz_convert('America/Lima')
                g_hoy = df_g[df_g['fecha'].dt.date == hoy]
                tot_g = g_hoy['monto'].sum()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Venta Bruta", f"S/ {tot_v:,.2f}")
            c2.metric("Gastos", f"S/ {tot_g:,.2f}")
            c3.metric("GANANCIA", f"S/ {(tot_v - tot_g):,.2f}")
            
            st.info(f"💵 Efectivo: S/ {tot_efectivo:,.2f} | 📱 Digital: S/ {tot_yape:,.2f}")
            
            c1, c2 = st.columns(2)
            try:
                pdf = generar_pdf(v_hoy, tot_v, str(hoy), "Reporte Global", tot_g)
                c1.download_button("PDF Día", pdf, f"Dia_{hoy}.pdf")
            except: pass
            
            if not v_hoy.empty:
                # Excel
                v_hoy_exc = v_hoy.copy()
                v_hoy_exc['fecha'] = v_hoy_exc['fecha'].astype(str)
                buff = io.BytesIO()
                with pd.ExcelWriter(buff, engine='openpyxl') as w: v_hoy_exc.to_excel(w, index=False)
                c2.download_button("Excel", buff.getvalue(), f"Dia_{hoy}.xlsx")
                
                with st.expander("Eliminar Ventas Históricas (Devuelve Stock)"):
                    for i, r in v_hoy.iterrows():
                        cols = st.columns([2, 2, 1])
                        cols[0].write(r['producto_nombre'])
                        cols[1].write(f"S/ {r['total']}")
                        if cols[2].button("❌", key=f"del_h_{r['id']}"):
                            revertir_stock_por_eliminacion(r['id'])
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
