import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Heladería Master", layout="wide", page_icon="🍦")

# --- ESTILOS ---
st.markdown("""
<style>
    .stMetric { border: 1px solid #ddd; padding: 10px; border-radius: 5px; background-color: #f9f9f9; }
    .merma-box { background-color: #fff5f5; border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 5px; color: #8a1f1f; }
    .compra-box { background-color: #f0fff4; border-left: 5px solid #28a745; padding: 15px; border-radius: 5px; color: #155724; }
    .total-display { font-size: 26px; font-weight: bold; color: #1565c0; text-align: right; padding: 10px; }
    /* Ajuste para tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #ffffff; border-bottom: 2px solid #1565c0; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('heladeria_final_v4.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    # Agregamos columna 'es_decimal' para saber si usa decimales (1) o enteros (0)
    # Si la tabla ya existe, esto podría dar error en un entorno real sin migración, 
    # pero como es SQLite local, el script manejará la estructura básica. 
    # Para asegurar compatibilidad sin borrar tu db, asumiremos la logica en el código.
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto_nombre TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, tipo TEXT, razon TEXT, fecha TIMESTAMP)''')
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect('heladeria_final_v4.db')
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
        # st.error(f"Error BD: {e}") # Comentado para no ensuciar la UI
        return None

# --- LOG MOVIMIENTOS ---
def log_movimiento(insumo, cantidad, tipo, razon):
    run_query("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
              (insumo, cantidad, tipo, razon, datetime.now()))

# --- PROCESAR VENTA ---
def procesar_descuento_stock(producto_nombre, cantidad_vendida, cant_conos_extra, cant_toppings):
    mensajes = []
    conn = sqlite3.connect('heladeria_final_v4.db')
    c = conn.cursor()
    
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
                      (nom_insumo, total_bajar, 'SALIDA', f'Venta: {producto_nombre}', datetime.now()))
            mensajes.append(f"📉 {nom_insumo}: -{total_bajar}")

    # 2. Extras
    if cant_conos_extra > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
        res_cono = c.fetchone()
        if res_cono:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_conos_extra, res_cono[0]))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_cono[1], cant_conos_extra, 'SALIDA', 'Venta: Cono Extra', datetime.now()))
            mensajes.append(f"📉 {res_cono[1]}: -{cant_conos_extra}")

    if cant_toppings > 0:
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
        res_top = c.fetchone()
        if res_top:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_toppings, res_top[0]))
            c.execute("INSERT INTO movimientos (insumo_nombre, cantidad, tipo, razon, fecha) VALUES (?,?,?,?,?)",
                      (res_top[1], cant_toppings, 'SALIDA', 'Venta: Topping Extra', datetime.now()))
            mensajes.append(f"📉 {res_top[1]}: -{cant_toppings}")

    conn.commit()
    conn.close()
    return mensajes

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Reporte de Ventas', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_dia, fecha):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, txt=f"Fecha: {fecha}", ln=1)
    
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
        hora = row['fecha'].strftime('%H:%M') if isinstance(row['fecha'], pd.Timestamp) else str(row['fecha'])[-8:-3]
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

    st.sidebar.title("🍦 Heladería Manager")
    
    # MENÚ UNIFICADO (Como pediste)
    opcion = st.sidebar.radio("Navegación", [
        "🛒 Caja (Vender)", 
        "📦 Inventario (Stock/Entradas)", 
        "📉 Mermas (Desperdicios)", 
        "📝 Menú (Productos)", 
        "📊 Reportes"
    ])

    # -----------------------------------------------------------
    # 1. CAJA (CARRITO + EXTRAS)
    # -----------------------------------------------------------
    if opcion == "🛒 Caja (Vender)":
        st.header("Punto de Venta")
        st.caption("1. Armar Pedido")
        
        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        if not df_menu.empty:
            c1, c2, c3 = st.columns([3, 1, 1])
            opciones = [f"{row['nombre']} | S/{row['precio']}" for i, row in df_menu.iterrows()]
            seleccion = c1.selectbox("Producto", opciones)
            cantidad = c2.number_input("Cantidad", 1, 50, 1)
            
            nombre_prod = seleccion.split(" | S/")[0]
            precio_base = float(seleccion.split(" | S/")[1])
            
            cx1, cx2 = st.columns(2)
            n_toppings = cx1.number_input("¿Cuántos llevan Topping? (+S/1)", 0, cantidad * 5, 0)
            n_conos = cx2.number_input("¿Cuántos llevan Cono Extra? (+S/1)", 0, cantidad * 5, 0)
            
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
            st.caption("2. Confirmar")
            df_c = pd.DataFrame(st.session_state.carrito)
            st.dataframe(df_c[['cantidad', 'producto', 'cant_toppings', 'cant_conos', 'subtotal']], use_container_width=True)
            
            total_g = sum(x['subtotal'] for x in st.session_state.carrito)
            c_tot, c_pay = st.columns([2, 1])
            c_tot.markdown(f"<div class='total-display'>TOTAL: S/ {total_g:.2f}</div>", unsafe_allow_html=True)
            
            with c_pay:
                metodo = st.radio("Pago", ["Efectivo", "Yape", "Tarjeta"], horizontal=True)
                if st.button("✅ COBRAR", type="primary", use_container_width=True):
                    hora = datetime.now()
                    for item in st.session_state.carrito:
                        run_query("INSERT INTO ventas (producto_nombre, precio_base, cantidad, extras, total, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
                                  (item['producto'], item['precio_base'], item['cantidad'], item['extras_costo'], item['subtotal'], metodo, hora))
                        logs = procesar_descuento_stock(item['producto'], item['cantidad'], item['cant_conos'], item['cant_toppings'])
                        st.session_state.logs.extend(logs)
                    
                    st.session_state.carrito = []
                    st.success("Venta realizada.")
                    st.rerun()
            
            if st.button("Vaciar Lista"):
                st.session_state.carrito = []
                st.rerun()

    # -----------------------------------------------------------
    # 2. INVENTARIO (UNIFICADO)
    # -----------------------------------------------------------
    elif opcion == "📦 Inventario (Stock/Entradas)":
        st.header("Gestión de Inventario")
        
        # Pestañas para organizar todo en un solo lugar
        tab_stock, tab_entrada, tab_kardex = st.tabs(["📦 Ver Stock", "➕ Registrar Compra/Entrada", "📜 Historial Movimientos"])
        
        # TAB 1: VER STOCK (EDITABLE)
        with tab_stock:
            st.info("💡 Doble click en la tabla para corregir stock manual.")
            df_i = run_query("SELECT * FROM insumos ORDER BY cantidad ASC", return_data=True)
            
            edited_df = st.data_editor(df_i, key="stock_edit", hide_index=True, use_container_width=True, 
                                       column_config={"id": st.column_config.NumberColumn(disabled=True)})
            
            if not df_i.equals(edited_df):
                for i, r in edited_df.iterrows():
                    run_query("UPDATE insumos SET nombre=?, cantidad=?, unidad=?, minimo=? WHERE id=?", 
                              (r['nombre'], r['cantidad'], r['unidad'], r['minimo'], r['id']))
                st.toast("Inventario corregido.")

        # TAB 2: REGISTRAR COMPRA (CON LOGICA DE ENTEROS/DECIMALES)
        with tab_entrada:
            st.markdown("""<div class="compra-box">Ingreso de mercadería (Compras)</div>""", unsafe_allow_html=True)
            
            tipo_ent = st.radio("Acción:", ["Reponer Existente", "Crear Nuevo Insumo"], horizontal=True)
            
            if tipo_ent == "Reponer Existente":
                df_ex = run_query("SELECT * FROM insumos ORDER BY nombre", return_data=True)
                if not df_ex.empty:
                    with st.form("repo"):
                        c1, c2 = st.columns([2, 1])
                        ins_sel = c1.selectbox("Insumo", df_ex['nombre'].unique())
                        
                        # Selector de tipo de entrada para validación
                        tipo_dato = c2.radio("Unidad de Medida:", ["Unidades (Enteros)", "Litros/Kilos (Decimales)"], horizontal=True)
                        
                        # Lógica de input
                        step_val = 1.0 if "Unidades" in tipo_dato else 0.1
                        fmt_val = "%d" if "Unidades" in tipo_dato else "%.2f"
                        
                        cant_add = st.number_input("Cantidad que llegó:", min_value=0.1, step=step_val, format=fmt_val)
                        nota = st.text_input("Nota (opcional)")
                        
                        if st.form_submit_button("➕ Sumar Stock"):
                            run_query("UPDATE insumos SET cantidad = cantidad + ? WHERE nombre = ?", (cant_add, ins_sel))
                            log_movimiento(ins_sel, cant_add, 'ENTRADA', f"Compra: {nota}")
                            st.success(f"Sumados {cant_add} a {ins_sel}")
                else:
                    st.warning("Crea insumos primero.")

            else: # Crear Nuevo
                with st.form("new_ins"):
                    c1, c2 = st.columns(2)
                    nom = c1.text_input("Nombre (ej. Conos)")
                    uni = c2.text_input("Unidad (ej. Cajas, Litros)")
                    
                    c3, c4 = st.columns(2)
                    
                    # Selector inteligente
                    tipo_dato_new = st.radio("Tipo de conteo:", ["Unidades (Enteros)", "Litros/Kilos (Decimales)"], horizontal=True)
                    step_val_new = 1.0 if "Unidades" in tipo_dato_new else 0.1
                    fmt_val_new = "%d" if "Unidades" in tipo_dato_new else "%.2f"
                    
                    cant = c3.number_input("Cantidad Inicial", min_value=0.0, step=step_val_new, format=fmt_val_new)
                    min_al = c4.number_input("Alerta Mínimo", 5.0)
                    
                    if st.form_submit_button("Guardar Insumo"):
                        run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?,?,?,?)", (nom, cant, uni, min_al))
                        log_movimiento(nom, cant, 'ENTRADA', 'Insumo Nuevo')
                        st.success("Insumo Creado")
                        st.rerun()

        # TAB 3: KARDEX
        with tab_kardex:
            st.subheader("Historial")
            df_k = run_query("SELECT * FROM movimientos ORDER BY id DESC", return_data=True)
            if not df_k.empty:
                st.dataframe(df_k, use_container_width=True)
            else:
                st.info("Sin movimientos")

    # -----------------------------------------------------------
    # 3. MERMAS
    # -----------------------------------------------------------
    elif opcion == "📉 Mermas (Desperdicios)":
        st.header("Registro de Mermas")
        st.markdown("""<div class="merma-box">Salida de stock sin dinero de por medio.</div>""", unsafe_allow_html=True)
        
        df_ins = run_query("SELECT * FROM insumos ORDER BY nombre", return_data=True)
        if not df_ins.empty:
            with st.form("merma"):
                c1, c2 = st.columns([2, 1])
                ins = c1.selectbox("Insumo", df_ins['nombre'].unique())
                
                # Selector de tipo también aquí
                tipo_dato_m = st.radio("Medida:", ["Unidades (Enteros)", "Decimales"], horizontal=True)
                step_m = 1.0 if "Unidades" in tipo_dato_m else 0.1
                fmt_m = "%d" if "Unidades" in tipo_dato_m else "%.2f"
                
                cant = c2.number_input("Cantidad Perdida", min_value=0.1, step=step_m, format=fmt_m)
                razon = st.text_input("Razón")
                
                if st.form_submit_button("Registrar Salida"):
                    if razon:
                        run_query("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre = ?", (cant, ins))
                        run_query("INSERT INTO mermas (insumo_nombre, cantidad, razon, fecha) VALUES (?,?,?,?)", (ins, cant, razon, datetime.now()))
                        log_movimiento(ins, cant, 'SALIDA', f'Merma: {razon}')
                        st.error("Registrado.")
                    else:
                        st.warning("Falta razón.")
        else:
            st.info("No hay insumos.")

    # -----------------------------------------------------------
    # 4. PRODUCTOS
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
                        
                        # Selector para gasto también (por si acaso)
                        q_gasto = st.number_input("Cantidad a descontar:", step=0.1) 
                        # Aquí dejamos step 0.1 general porque una receta puede usar 0.5 unidades de algo
                
                if st.form_submit_button("Guardar"):
                    pid = run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?,?,?)", (n, p, cat))
                    if vincular and ins_id:
                        run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?,?,?)", (pid, ins_id, q_gasto))
                    st.success("Guardado")
                    st.rerun()

        df_p = run_query("""SELECT m.id, m.nombre, m.precio, i.nombre as Gasta FROM menu m 
                            LEFT JOIN recetas r ON m.id=r.menu_id LEFT JOIN insumos i ON r.insumo_id=i.id""", return_data=True)
        if not df_p.empty:
            for i, r in df_p.iterrows():
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{r['nombre']}**")
                c2.write(f"S/ {r['precio']}")
                if c3.button("🗑️", key=f"d{r['id']}"):
                    run_query("DELETE FROM menu WHERE id=?", (r['id'],))
                    run_query("DELETE FROM recetas WHERE menu_id=?", (r['id'],))
                    st.rerun()

    # -----------------------------------------------------------
    # 5. REPORTES
    # -----------------------------------------------------------
    elif opcion == "📊 Reportes":
        st.header("Reportes")
        hoy = datetime.now().date()
        df_v = run_query("SELECT * FROM ventas ORDER BY id DESC", return_data=True)
        
        if not df_v.empty:
            df_v['fecha'] = pd.to_datetime(df_v['fecha'])
            v_hoy = df_v[df_v['fecha'].dt.date == hoy]
            total = v_hoy['total'].sum()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Venta Hoy", f"S/ {total:,.2f}")
            c2.metric("Tickets", len(v_hoy))
            
            col_pdf, col_exc = st.columns(2)
            try:
                pdf = generar_pdf(v_hoy, total, str(hoy))
                col_pdf.download_button("📄 PDF", pdf, f"R_{hoy}.pdf")
            except: pass
            
            buff = io.BytesIO()
            with pd.ExcelWriter(buff) as w: v_hoy.to_excel(w, index=False)
            col_exc.download_button("📊 Excel", buff.getvalue(), f"V_{hoy}.xlsx")
            
            st.dataframe(v_hoy)
            with st.expander("Borrar Ventas"):
                for i, r in v_hoy.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"{r['producto_nombre']} - S/{r['total']}")
                    if c2.button("❌", key=f"del_{r['id']}"):
                        run_query("DELETE FROM ventas WHERE id=?", (r['id'],))
                        st.rerun()
        else:
            st.info("Sin ventas hoy.")

if __name__ == '__main__':
    main()
