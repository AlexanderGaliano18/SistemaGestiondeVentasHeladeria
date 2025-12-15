import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Heladería Final Pro", layout="wide", page_icon="🍦")

# --- ESTILOS ---
st.markdown("""
<style>
    .stMetric { border: 1px solid #ddd; padding: 10px; border-radius: 5px; background-color: #f9f9f9; }
    .merma-box { background-color: #fff5f5; border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 5px; color: #8a1f1f; }
    .cart-box { background-color: #e3f2fd; padding: 15px; border-radius: 10px; border: 1px solid #90caf9; }
    .total-display { font-size: 24px; font-weight: bold; color: #1565c0; text-align: right; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('heladeria_v2.db')
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
    
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect('heladeria_v2.db')
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

# --- LÓGICA DE INVENTARIO (MEJORADA PARA CANTIDADES EXACTAS) ---
def procesar_descuento_stock(producto_nombre, cantidad_vendida, cant_conos_extra, cant_toppings):
    mensajes = []
    conn = sqlite3.connect('heladeria_v2.db')
    c = conn.cursor()
    
    # 1. Descontar Insumos de la Receta Base
    c.execute("SELECT id FROM menu WHERE nombre = ?", (producto_nombre,))
    res_prod = c.fetchone()
    
    if res_prod:
        prod_id = res_prod[0]
        # Buscar receta
        c.execute("SELECT r.insumo_id, r.cantidad_insumo, i.nombre FROM recetas r JOIN insumos i ON r.insumo_id = i.id WHERE r.menu_id = ?", (prod_id,))
        ingredientes = c.fetchall()
        
        if ingredientes:
            for insumo_id, cant_receta, nom_insumo in ingredientes:
                # Gasto total = lo que dice la receta * cantidad de productos vendidos
                total_bajar = cant_receta * cantidad_vendida
                c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (total_bajar, insumo_id))
                mensajes.append(f"📉 {nom_insumo}: -{total_bajar}")
        else:
            # Si no tiene receta (ej. una gaseosa que no registraste insumo), no pasa nada
            pass
    
    # 2. Descontar Extras (Conos Adicionales)
    if cant_conos_extra > 0:
        # Busca cualquier insumo que parezca un cono
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%' LIMIT 1")
        res_cono = c.fetchone()
        if res_cono:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_conos_extra, res_cono[0]))
            mensajes.append(f"📉 Extra {res_cono[1]}: -{cant_conos_extra}")

    # 3. Descontar Extras (Toppings)
    if cant_toppings > 0:
        # Busca cualquier insumo que parezca topping
        c.execute("SELECT id, nombre FROM insumos WHERE nombre LIKE '%Topping%' LIMIT 1")
        res_top = c.fetchone()
        if res_top:
            c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (cant_toppings, res_top[0]))
            mensajes.append(f"📉 Extra {res_top[1]}: -{cant_toppings}")

    conn.commit()
    conn.close()
    return mensajes

# --- PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Reporte Heladería', 0, 1, 'C')
        self.ln(5)

def generar_pdf(df_ventas, total_dia, fecha):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, txt=f"Fecha: {fecha}", ln=1)
    
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(80, 8, "Producto", 1, 0, 'C', 1)
    pdf.cell(20, 8, "Cant.", 1, 0, 'C', 1)
    pdf.cell(30, 8, "Total ($)", 1, 0, 'C', 1)
    pdf.ln()
    
    for _, row in df_ventas.iterrows():
        pdf.cell(80, 8, str(row['producto_nombre'])[:35], 1)
        pdf.cell(20, 8, str(row['cantidad']), 1, 0, 'C')
        pdf.cell(30, 8, f"{row['total']:.2f}", 1, 0, 'C')
        pdf.ln()
        
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"TOTAL: S/ {total_dia:,.2f}", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- MAIN APP ---
def main():
    init_db()
    # Inicializar Carrito y Logs en Sesión
    if 'carrito' not in st.session_state: st.session_state.carrito = []
    if 'logs' not in st.session_state: st.session_state.logs = []

    st.sidebar.title("🍦 Sistema Heladería")
    opcion = st.sidebar.radio("Ir a:", ["🛒 Vender (Caja)", "📉 Registrar Merma", "📦 Insumos (CRUD)", "📝 Productos (CRUD)", "📊 Reportes & Eliminar"])

    # -----------------------------------------------------------
    # 1. CAJA Y VENTAS (MODO CARRITO)
    # -----------------------------------------------------------
    if opcion == "🛒 Vender (Caja)":
        st.header("Punto de Venta")
        
        # --- ZONA 1: SELECCIONAR PRODUCTO ---
        st.markdown("##### 1. Agregar Producto a la Lista")
        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        
        if not df_menu.empty:
            # Layout de selección
            c1, c2, c3 = st.columns([3, 1, 1])
            lista_nombres = [f"{row['nombre']} | S/{row['precio']}" for i, row in df_menu.iterrows()]
            eleccion = c1.selectbox("Producto", lista_nombres)
            
            # Cantidad de productos
            cantidad_prod = c2.number_input("Cantidad", min_value=1, max_value=100, value=1)
            
            nombre_real = eleccion.split(" | S/")[0]
            precio_unitario = float(eleccion.split(" | S/")[1])
            
            # --- ZONA EXTRAS (MEJORADA) ---
            # Ahora preguntamos CUÁNTOS llevan extra
            col_x1, col_x2 = st.columns(2)
            
            # Lógica: No puedes agregar más toppings que la cantidad de helados (aunque si quieres permitir doble topping, quita el max_value)
            cant_toppings = col_x1.number_input("¿Cuántos llevan Topping? (+S/1)", min_value=0, max_value=cantidad_prod * 5, value=0)
            cant_conos = col_x2.number_input("¿Cuántos llevan Cono Extra? (+S/1)", min_value=0, max_value=cantidad_prod * 5, value=0)
            
            # Cálculos temporales
            precio_extras = (cant_toppings * 1.0) + (cant_conos * 1.0)
            subtotal_linea = (precio_unitario * cantidad_prod) + precio_extras
            
            c3.metric("Subtotal", f"S/ {subtotal_linea:.2f}")
            
            # BOTÓN AGREGAR AL CARRITO
            if st.button("➕ Agregar a la Lista"):
                item = {
                    "producto": nombre_real,
                    "precio_base": precio_unitario,
                    "cantidad": cantidad_prod,
                    "cant_toppings": cant_toppings,
                    "cant_conos": cant_conos,
                    "extras_costo": precio_extras,
                    "subtotal": subtotal_linea
                }
                st.session_state.carrito.append(item)
                st.toast(f"Agregado: {cantidad_prod} {nombre_real}")

        else:
            st.warning("No hay productos en el menú. Ve a 'Productos' para crear uno.")

        st.divider()

        # --- ZONA 2: EL CARRITO DE COMPRAS ---
        if len(st.session_state.carrito) > 0:
            st.markdown("##### 2. Lista de Compra (Carrito)")
            
            # Mostrar tabla bonita del carrito
            df_cart = pd.DataFrame(st.session_state.carrito)
            # Reordenar columnas para ver mejor
            df_display = df_cart[['cantidad', 'producto', 'cant_toppings', 'cant_conos', 'subtotal']]
            df_display.columns = ['Cant.', 'Producto', '# Toppings', '# Conos Extra', 'Importe']
            
            st.dataframe(df_display, use_container_width=True)
            
            # Calcular Total Global
            total_global = sum(item['subtotal'] for item in st.session_state.carrito)
            
            col_tot, col_pay = st.columns([2, 1])
            
            col_tot.markdown(f"<div class='total-display'>TOTAL A COBRAR: S/ {total_global:.2f}</div>", unsafe_allow_html=True)
            
            with col_pay:
                st.write("Método de Pago:")
                metodo = st.radio("Pago", ["Efectivo", "Yape", "Tarjeta"], label_visibility="collapsed", horizontal=True)
                
                # BOTÓN FINALIZAR (COBRA TODO EL CARRITO)
                if st.button("✅ FINALIZAR VENTA COMPLETA", type="primary", use_container_width=True):
                    fecha_hora = datetime.now()
                    
                    # Procesar cada item del carrito
                    for item in st.session_state.carrito:
                        # 1. Guardar en Base de Datos
                        run_query("""INSERT INTO ventas 
                                     (producto_nombre, precio_base, cantidad, extras, total, metodo_pago, fecha) 
                                     VALUES (?,?,?,?,?,?,?)""",
                                  (item['producto'], item['precio_base'], item['cantidad'], 
                                   item['extras_costo'], item['subtotal'], metodo, fecha_hora))
                        
                        # 2. Descontar Inventario (Usando las cantidades exactas de extras)
                        logs = procesar_descuento_stock(item['producto'], item['cantidad'], 
                                                        item['cant_conos'], item['cant_toppings'])
                        st.session_state.logs.extend(logs)

                    # Limpiar carrito y avisar
                    st.session_state.carrito = [] 
                    st.success("¡Venta registrada correctamente!")
                    st.rerun()

            # Botón para limpiar carrito si se equivocó
            if st.button("🗑️ Vaciar Lista"):
                st.session_state.carrito = []
                st.rerun()
                
        else:
            st.info("La lista de venta está vacía. Agrega productos arriba.")

        # Feedback de inventario (Logs)
        if st.session_state.logs:
            st.divider()
            st.caption("Movimientos de Inventario Recientes:")
            for log in st.session_state.logs:
                st.text(log)
            if st.button("Limpiar avisos"):
                st.session_state.logs = []
                st.rerun()

    # -----------------------------------------------------------
    # 2. REGISTRAR MERMA (MANTENIDO IGUAL)
    # -----------------------------------------------------------
    elif opcion == "📉 Registrar Merma":
        st.header("Control de Mermas")
        st.markdown("""<div class="merma-box">Aquí registras pérdidas físicas (roturas, vencimientos) SIN afectar el dinero de la caja.</div>""", unsafe_allow_html=True)
        st.divider()

        df_ins = run_query("SELECT * FROM insumos ORDER BY nombre", return_data=True)
        if not df_ins.empty:
            with st.form("form_merma", clear_on_submit=True):
                c1, c2 = st.columns([2, 1])
                insumo_sel = c1.selectbox("¿Qué se perdió?", df_ins['nombre'].unique())
                cant_sel = c2.number_input("Cantidad perdida", min_value=0.1, step=1.0)
                razon = st.text_input("Razón (Obligatorio)", placeholder="Ej: Se cayó al piso...")
                
                if st.form_submit_button("🚨 REGISTRAR PÉRDIDA"):
                    if razon:
                        run_query("INSERT INTO mermas (insumo_nombre, cantidad, razon, fecha) VALUES (?,?,?,?)", 
                                  (insumo_sel, cant_sel, razon, datetime.now()))
                        conn = sqlite3.connect('heladeria_v2.db')
                        c = conn.cursor()
                        c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre = ?", (cant_sel, insumo_sel))
                        conn.commit()
                        conn.close()
                        st.error(f"Se descontaron {cant_sel} de {insumo_sel}.")
                        st.rerun()
                    else:
                        st.warning("Escribe la razón.")
            
            st.subheader("Historial de Mermas")
            df_m = run_query("SELECT * FROM mermas ORDER BY id DESC", return_data=True)
            st.dataframe(df_m, use_container_width=True)
        else:
            st.info("No hay insumos.")

    # -----------------------------------------------------------
    # 3. INSUMOS (CRUD - MANTENIDO)
    # -----------------------------------------------------------
    elif opcion == "📦 Insumos (CRUD)":
        st.header("Gestión de Inventario")
        with st.expander("➕ Nuevo Insumo"):
            with st.form("add_ins", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                n = c1.text_input("Nombre")
                q = c2.number_input("Cantidad", 0.0)
                u = c3.text_input("Unidad")
                m = c4.number_input("Alerta Mínima", 5.0)
                if st.form_submit_button("Guardar"):
                    run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?,?,?,?)", (n, q, u, m))
                    st.rerun()
        
        st.subheader("Inventario Editable")
        df_ins = run_query("SELECT * FROM insumos ORDER BY id", return_data=True)
        edited_df = st.data_editor(df_ins, key="editor_ins", hide_index=True, use_container_width=True,
                                   column_config={"id": st.column_config.NumberColumn(disabled=True)})
        
        if not df_ins.equals(edited_df):
            for i, row in edited_df.iterrows():
                run_query("UPDATE insumos SET nombre=?, cantidad=?, unidad=?, minimo=? WHERE id=?", 
                          (row['nombre'], row['cantidad'], row['unidad'], row['minimo'], row['id']))
            st.toast("Inventario actualizado")

        with st.expander("Borrar Insumos"):
            for i, row in df_ins.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.text(row['nombre'])
                if c2.button("Borrar", key=f"d_i_{row['id']}"):
                    run_query("DELETE FROM insumos WHERE id=?", (row['id'],))
                    st.rerun()

    # -----------------------------------------------------------
    # 4. PRODUCTOS (CRUD - MANTENIDO)
    # -----------------------------------------------------------
    elif opcion == "📝 Productos (CRUD)":
        st.header("Gestión del Menú")
        with st.expander("➕ Crear Producto"):
            with st.form("new_prod", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                nom = c1.text_input("Nombre")
                pre = c2.number_input("Precio", min_value=0.0)
                cat = c3.selectbox("Categoría", ["Helado", "Paleta", "Bebida", "Otro"])
                
                st.markdown("---")
                vincular = st.checkbox("¿Descuenta Inventario?", value=True)
                insumo_id = None
                cant_gasto = 0
                if vincular:
                    df_i = run_query("SELECT * FROM insumos", return_data=True)
                    if not df_i.empty:
                        mapa = {row['nombre']: row['id'] for i, row in df_i.iterrows()}
                        sel = st.selectbox("Gasta Insumo:", list(mapa.keys()))
                        insumo_id = mapa[sel]
                        cant_gasto = st.number_input("Cantidad gasto:", value=1.0)
                
                if st.form_submit_button("Guardar"):
                    pid = run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?,?,?)", (nom, pre, cat))
                    if vincular and insumo_id:
                        run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?,?,?)", (pid, insumo_id, cant_gasto))
                    st.success("Guardado")
                    st.rerun()

        st.subheader("Lista Productos")
        df_p = run_query("""SELECT m.id, m.nombre, m.precio, i.nombre as Gasta FROM menu m 
                            LEFT JOIN recetas r ON m.id=r.menu_id LEFT JOIN insumos i ON r.insumo_id=i.id""", return_data=True)
        for i, row in df_p.iterrows():
            c1, c2, c3, c4 = st.columns([1, 3, 2, 1])
            c1.write(row['id'])
            c2.write(row['nombre'])
            c3.write(f"Gasta: {row['Gasta']}" if row['Gasta'] else "-")
            if c4.button("🗑️", key=f"dp_{row['id']}"):
                run_query("DELETE FROM menu WHERE id=?", (row['id'],))
                run_query("DELETE FROM recetas WHERE menu_id=?", (row['id'],))
                st.rerun()

    # -----------------------------------------------------------
    # 5. REPORTES (MANTENIDO)
    # -----------------------------------------------------------
    elif opcion == "📊 Reportes & Eliminar":
        st.header("Reporte Ventas")
        hoy = datetime.now().date()
        df_v = run_query("SELECT * FROM ventas ORDER BY id DESC", return_data=True)
        if not df_v.empty:
            df_v['fecha'] = pd.to_datetime(df_v['fecha'])
            v_hoy = df_v[df_v['fecha'].dt.date == hoy]
            total = v_hoy['total'].sum()
            st.metric("Total Hoy", f"S/ {total:,.2f}")
            
            st.dataframe(v_hoy)
            
            if st.button("Descargar PDF"):
                pdf = generar_pdf(v_hoy, total, str(hoy))
                st.download_button("Descargar", pdf, f"Reporte_{hoy}.pdf")
            
            st.subheader("Eliminar Ventas")
            for i, row in v_hoy.iterrows():
                c1, c2, c3 = st.columns([4, 2, 1])
                c1.write(f"{row['producto_nombre']} (x{row['cantidad']})")
                c2.write(f"S/ {row['total']}")
                if c3.button("❌", key=f"dv_{row['id']}"):
                    run_query("DELETE FROM ventas WHERE id=?", (row['id'],))
                    st.rerun()
        else:
            st.info("Sin ventas.")

if __name__ == '__main__':
    main()
