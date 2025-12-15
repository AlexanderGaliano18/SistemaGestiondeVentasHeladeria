import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Heladería Final System", layout="wide", page_icon="🍦")

# --- ESTILOS ---
st.markdown("""
<style>
    .stMetric { border: 1px solid #ddd; padding: 10px; border-radius: 5px; background-color: #f9f9f9; }
    .merma-box { background-color: #fff5f5; border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 5px; color: #8a1f1f; }
    .cart-box { background-color: #e3f2fd; padding: 15px; border-radius: 10px; border: 1px solid #90caf9; }
    .total-display { font-size: 26px; font-weight: bold; color: #1565c0; text-align: right; padding: 10px; }
    .kardex-in { color: green; font-weight: bold; }
    .kardex-out { color: red; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('heladeria_master.db')
    c = conn.cursor()
    # 1. Menú
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    # 2. Insumos
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    # 3. Recetas
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    # 4. Ventas
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto_nombre TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    # 5. Mermas
    c.execute('''CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
    # 6. MOVIMIENTOS (KARDEX) - NUEVO
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, tipo TEXT, razon TEXT, fecha TIMESTAMP)''')
    
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect('heladeria_master.db')
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
        st.error(f"Error BD: {e}")
        return None

# --- REGISTRO DE MOVIMIENTOS (KARDEX) ---
def log_movimiento(insumo, cantidad, tipo, razon):
    """
    Registra entradas y salidas en el historial.
    tipo: 'ENTRADA' o 'SALIDA'
    """
    run_query("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
              (insumo, cantidad, tipo, razon, datetime.now()))

# --- LÓGICA DE INVENTARIO (VENTAS) ---
def procesar_descuento_stock(producto_nombre, cantidad_vendida, cant_conos_extra, cant_toppings):
    mensajes = []
    conn = sqlite3.connect('heladeria_master.db')
    c = conn.cursor()
    
    # 1. Descontar Insumos de Receta Base
    c.execute("SELECT id FROM menu WHERE nombre = ?", (producto_nombre,))
    res_prod = c.fetchone()
    
    if res_prod:
        prod_id = res_prod[0]
        c.execute("SELECT r.insumo_id, r.cantidad_insumo, i.nombre FROM recetas r JOIN insumos i ON r.insumo_id = i.id WHERE r.menu_id = ?", (prod_id,))
        ingredientes = c.fetchall()
        
        for insumo_id, cant_receta, nom_insumo in ingredientes:
            total_bajar = cant_receta * cantidad_vendida
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (total_bajar, insumo_id))
            # LOG KARDEX
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (nom_insumo, total_bajar, 'SALIDA', f'Venta: {producto_nombre}', datetime.now()))
            mensajes.append(f"📉 {nom_insumo}: -{total_bajar}")

    # 2. Extras (Conos)
    if cant_conos_extra > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
        res_cono = c.fetchone()
        if res_cono:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_conos_extra, res_cono[0]))
            # LOG KARDEX
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_cono[1], cant_conos_extra, 'SALIDA', 'Venta: Cono Extra', datetime.now()))
            mensajes.append(f"📉 {res_cono[1]}: -{cant_conos_extra}")

    # 3. Extras (Toppings)
    if cant_toppings > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
        res_top = c.fetchone()
        if res_top:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_toppings, res_top[0]))
            # LOG KARDEX
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_top[1], cant_toppings, 'SALIDA', 'Venta: Topping Extra', datetime.now()))
            mensajes.append(f"📉 {res_top[1]}: -{cant_toppings}")

    conn.commit()
    conn.close()
    return mensajes

# --- PDF MEJORADO ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Reporte de Ventas - Heladería', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_dia, fecha):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, txt=f"Fecha del Reporte: {fecha}", ln=1)
    
    # Encabezados
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
        # Formato de hora
        hora = row['fecha'].strftime('%H:%M') if isinstance(row['fecha'], pd.Timestamp) else str(row['fecha'])[-8:-3]
        
        pdf.cell(20, 8, hora, 1, 0, 'C')
        pdf.cell(70, 8, str(row['producto_nombre'])[:30], 1)
        pdf.cell(20, 8, str(row['cantidad']), 1, 0, 'C')
        pdf.cell(25, 8, f"{row['extras']:.2f}", 1, 0, 'C')
        pdf.cell(25, 8, f"{row['total']:.2f}", 1, 0, 'C')
        pdf.cell(30, 8, row['metodo_pago'], 1, 1, 'C')
        
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"TOTAL DEL DÍA: S/ {total_dia:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN APP ---
def main():
    init_db()
    if 'carrito' not in st.session_state: st.session_state.carrito = []
    if 'logs' not in st.session_state: st.session_state.logs = []

    st.sidebar.title("🍦 Heladería Manager")
    opcion = st.sidebar.radio("Menú", ["🛒 Caja (Vender)", "📉 Registrar Merma", "📦 Inventario & Kardex", "📝 Menú (Productos)", "📊 Reportes & Excel"])

    # -----------------------------------------------------------
    # 1. CAJA (VENDER)
    # -----------------------------------------------------------
    if opcion == "🛒 Caja (Vender)":
        st.header("Punto de Venta")
        
        # Selección
        st.caption("1. Armar Pedido")
        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        
        if not df_menu.empty:
            c1, c2, c3 = st.columns([3, 1, 1])
            opciones = [f"{row['nombre']} | S/{row['precio']}" for i, row in df_menu.iterrows()]
            seleccion = c1.selectbox("Producto", opciones)
            cantidad = c2.number_input("Cantidad", 1, 50, 1)
            
            # Parsing
            nombre_prod = seleccion.split(" | S/")[0]
            precio_base = float(seleccion.split(" | S/")[1])
            
            # Extras Inteligentes
            cx1, cx2 = st.columns(2)
            n_toppings = cx1.number_input("¿Cuántos con Topping? (+S/1)", 0, cantidad * 5, 0)
            n_conos = cx2.number_input("¿Cuántos con Cono Extra? (+S/1)", 0, cantidad * 5, 0)
            
            costo_extras = (n_toppings * 1.0) + (n_conos * 1.0)
            subtotal = (precio_base * cantidad) + costo_extras
            
            c3.metric("Subtotal Item", f"S/ {subtotal:.2f}")
            
            if st.button("➕ Agregar a la Lista"):
                st.session_state.carrito.append({
                    "producto": nombre_prod, "precio_base": precio_base, "cantidad": cantidad,
                    "cant_toppings": n_toppings, "cant_conos": n_conos, 
                    "extras_costo": costo_extras, "subtotal": subtotal
                })
                st.toast("Producto agregado")

        # Carrito
        st.divider()
        if len(st.session_state.carrito) > 0:
            st.caption("2. Confirmar Venta")
            df_c = pd.DataFrame(st.session_state.carrito)
            st.dataframe(df_c[['cantidad', 'producto', 'cant_toppings', 'cant_conos', 'subtotal']], use_container_width=True)
            
            total_g = sum(item['subtotal'] for item in st.session_state.carrito)
            
            c_tot, c_pay = st.columns([2, 1])
            c_tot.markdown(f"<div class='total-display'>TOTAL: S/ {total_g:.2f}</div>", unsafe_allow_html=True)
            
            with c_pay:
                metodo = st.radio("Pago", ["Efectivo", "Yape", "Tarjeta"], horizontal=True)
                if st.button("✅ COBRAR TODO", type="primary", use_container_width=True):
                    hora = datetime.now()
                    for item in st.session_state.carrito:
                        # Guardar Venta
                        run_query("INSERT INTO ventas (producto_nombre, precio_base, cantidad, extras, total, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
                                  (item['producto'], item['precio_base'], item['cantidad'], item['extras_costo'], item['subtotal'], metodo, hora))
                        # Descontar + Kardex
                        logs = procesar_descuento_stock(item['producto'], item['cantidad'], item['cant_conos'], item['cant_toppings'])
                        st.session_state.logs.extend(logs)
                    
                    st.session_state.carrito = []
                    st.success("Venta realizada.")
                    st.rerun()
            
            if st.button("Vaciar Lista"):
                st.session_state.carrito = []
                st.rerun()

    # -----------------------------------------------------------
    # 2. MERMA (SALIDA DE INVENTARIO)
    # -----------------------------------------------------------
    elif opcion == "📉 Registrar Merma":
        st.header("Registro de Mermas")
        st.warning("Esto descuenta stock pero NO afecta el dinero.")
        
        df_ins = run_query("SELECT * FROM insumos ORDER BY nombre", return_data=True)
        if not df_ins.empty:
            with st.form("merma"):
                c1, c2 = st.columns([2, 1])
                ins = c1.selectbox("Insumo", df_ins['nombre'].unique())
                cant = c2.number_input("Cantidad", 0.1, 100.0, 1.0)
                razon = st.text_input("Razón (Ej: Se cayó)")
                
                if st.form_submit_button("Registrar Pérdida"):
                    if razon:
                        # 1. Update Insumo
                        run_query("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre = ?", (cant, ins))
                        # 2. Log Merma
                        run_query("INSERT INTO mermas (insumo_nombre, cantidad, razon, fecha) VALUES (?,?,?,?)", (ins, cant, razon, datetime.now()))
                        # 3. Log Kardex
                        log_movimiento(ins, cant, 'SALIDA', f'Merma: {razon}')
                        st.error(f"Descontado {cant} de {ins}")
                        st.rerun()
                    else:
                        st.warning("Escribe la razón")
        else:
            st.info("No hay insumos.")

    # -----------------------------------------------------------
    # 3. INVENTARIO & KARDEX (MOVIMIENTOS)
    # -----------------------------------------------------------
    elif opcion == "📦 Inventario & Kardex":
        st.header("Gestión de Inventario")
        
        tab1, tab2 = st.tabs(["📦 Stock Actual & Compras", "📜 Historial (Kardex)"])
        
        with tab1:
            # 1. Registrar Compra (Entrada)
            with st.expander("➕ Registrar Compra / Entrada de Stock", expanded=True):
                with st.form("compra"):
                    c1, c2, c3 = st.columns(3)
                    df_existente = run_query("SELECT * FROM insumos", return_data=True)
                    lista_exist = df_existente['nombre'].unique() if not df_existente.empty else []
                    
                    modo = st.radio("Modo", ["Reponer Existente", "Crear Nuevo Insumo"], horizontal=True)
                    
                    if modo == "Reponer Existente" and len(lista_exist) > 0:
                        nom_ins = st.selectbox("Insumo", lista_exist)
                        cant_add = st.number_input("Cantidad a sumar", 0.1)
                        uni = "" # No cambia
                        min_alert = 0 # No cambia
                    else:
                        nom_ins = st.text_input("Nombre Nuevo Insumo")
                        cant_add = st.number_input("Cantidad Inicial", 0.1)
                        uni = st.text_input("Unidad (ej. Caja)")
                        min_alert = st.number_input("Alerta Mínimo", 5)
                    
                    notas = st.text_input("Nota (ej. Compra Makro)")
                    
                    if st.form_submit_button("Registrar Entrada"):
                        if modo == "Crear Nuevo Insumo":
                            run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?,?,?,?)", (nom_ins, cant_add, uni, min_alert))
                        else:
                            run_query("UPDATE insumos SET cantidad = cantidad + ? WHERE nombre = ?", (cant_add, nom_ins))
                        
                        # Log Kardex
                        log_movimiento(nom_ins, cant_add, 'ENTRADA', f'Compra: {notas}')
                        st.success("Stock actualizado.")
                        st.rerun()
            
            # 2. Tabla Stock
            st.subheader("Stock Actual")
            df_i = run_query("SELECT * FROM insumos ORDER BY cantidad", return_data=True)
            st.dataframe(df_i, use_container_width=True)

        with tab2:
            st.subheader("Historial de Movimientos (Entradas y Salidas)")
            df_k = run_query("SELECT * FROM movimientos ORDER BY id DESC", return_data=True)
            
            if not df_k.empty:
                # Colorear texto
                def color_tipo(val):
                    color = 'green' if val == 'ENTRADA' else 'red'
                    return f'color: {color}; font-weight: bold'
                
                st.dataframe(df_k.style.map(color_tipo, subset=['tipo']), use_container_width=True)
            else:
                st.info("No hay movimientos registrados aún.")

    # -----------------------------------------------------------
    # 4. MENU Y PRODUCTOS (CRUD)
    # -----------------------------------------------------------
    elif opcion == "📝 Menú (Productos)":
        st.header("Configurar Productos")
        with st.expander("Crear Producto"):
            with st.form("new_prod"):
                c1, c2, c3 = st.columns(3)
                n = c1.text_input("Nombre")
                p = c2.number_input("Precio", 0.0)
                cat = c3.selectbox("Categoría", ["Helado", "Paleta", "Bebida", "Otro"])
                
                vincular = st.checkbox("Descuenta Inventario", value=True)
                ins_id = None
                q_gasto = 0
                if vincular:
                    df_ins = run_query("SELECT * FROM insumos", return_data=True)
                    if not df_ins.empty:
                        mapa = {r['nombre']: r['id'] for i, r in df_ins.iterrows()}
                        sel = st.selectbox("Gasta:", list(mapa.keys()))
                        ins_id = mapa[sel]
                        q_gasto = st.number_input("Cantidad:", 1.0)
                
                if st.form_submit_button("Guardar"):
                    pid = run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?,?,?)", (n, p, cat))
                    if vincular and ins_id:
                        run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?,?,?)", (pid, ins_id, q_gasto))
                    st.success("Guardado")
                    st.rerun()
        
        df_p = run_query("SELECT * FROM menu", return_data=True)
        for i, r in df_p.iterrows():
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{r['nombre']}**")
            c2.write(f"S/ {r['precio']}")
            if c3.button("🗑️", key=f"d{r['id']}"):
                run_query("DELETE FROM menu WHERE id=?", (r['id'],))
                run_query("DELETE FROM recetas WHERE menu_id=?", (r['id'],))
                st.rerun()

    # -----------------------------------------------------------
    # 5. REPORTES & EXCEL (MEJORADO)
    # -----------------------------------------------------------
    elif opcion == "📊 Reportes & Excel":
        st.header("Reportes de Cierre")
        hoy = datetime.now().date()
        df_v = run_query("SELECT * FROM ventas ORDER BY id DESC", return_data=True)
        
        if not df_v.empty:
            df_v['fecha'] = pd.to_datetime(df_v['fecha'])
            v_hoy = df_v[df_v['fecha'].dt.date == hoy]
            
            total = v_hoy['total'].sum()
            
            # Métricas
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Vendido Hoy", f"S/ {total:,.2f}")
            c2.metric("Tickets", len(v_hoy))
            c3.metric("Promedio Ticket", f"S/ {total/len(v_hoy):,.2f}" if len(v_hoy)>0 else 0)
            
            st.divider()
            
            # DESCARGAS
            col_pdf, col_excel = st.columns(2)
            
            # 1. PDF
            try:
                pdf_bytes = generar_pdf(v_hoy, total, str(hoy))
                col_pdf.download_button("📄 Descargar PDF (Detallado)", pdf_bytes, f"Reporte_{hoy}.pdf", "application/pdf")
            except Exception as e:
                col_pdf.error("Error PDF")
            
            # 2. EXCEL (NUEVO)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                v_hoy.to_excel(writer, sheet_name='Ventas_Hoy', index=False)
            col_excel.download_button("📊 Descargar Excel (.xlsx)", buffer.getvalue(), f"Ventas_{hoy}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            st.subheader("Detalle Ventas Hoy")
            st.dataframe(v_hoy[['fecha', 'producto_nombre', 'cantidad', 'extras', 'total', 'metodo_pago']], use_container_width=True)
            
            with st.expander("Borrar Ventas (Corrección)"):
                for i, r in v_hoy.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"{r['producto_nombre']} - S/{r['total']}")
                    if c2.button("❌", key=f"delv_{r['id']}"):
                        run_query("DELETE FROM ventas WHERE id=?", (r['id'],))
                        st.rerun()
        else:
            st.info("Sin ventas.")

if __name__ == '__main__':
    main()
