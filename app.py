import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Heladería Final", layout="wide", page_icon="🍦")

# --- ESTILOS ---
st.markdown("""
<style>
    .stMetric { border: 1px solid #ddd; padding: 10px; border-radius: 5px; }
    .merma-box { background-color: #fff5f5; border-left: 5px solid #ff4b4b; padding: 15px; border-radius: 5px; color: #8a1f1f; }
</style>
""", unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('heladeria_completa.db')
    c = conn.cursor()
    # 1. Menú
    c.execute('''CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, nombre TEXT, precio REAL, categoria TEXT)''')
    # 2. Insumos
    c.execute('''CREATE TABLE IF NOT EXISTS insumos (id INTEGER PRIMARY KEY, nombre TEXT, cantidad REAL, unidad TEXT, minimo REAL DEFAULT 10)''')
    # 3. Recetas
    c.execute('''CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY, menu_id INTEGER, insumo_id INTEGER, cantidad_insumo REAL)''')
    # 4. Ventas
    c.execute('''CREATE TABLE IF NOT EXISTS ventas (id INTEGER PRIMARY KEY, producto_nombre TEXT, precio_base REAL, cantidad INTEGER, extras REAL, total REAL, metodo_pago TEXT, fecha TIMESTAMP)''')
    # 5. MERMAS (NUEVA TABLA)
    c.execute('''CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY, insumo_nombre TEXT, cantidad REAL, razon TEXT, fecha TIMESTAMP)''')
    
    conn.commit()
    conn.close()

def run_query(query, params=(), return_data=False):
    conn = sqlite3.connect('heladeria_completa.db')
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

# --- LÓGICA DE INVENTARIO (VENTAS) ---
def procesar_descuento_stock(producto_nombre, cantidad_vendida, tiene_cono, tiene_top):
    mensajes = []
    conn = sqlite3.connect('heladeria_completa.db')
    c = conn.cursor()
    
    # Buscar producto
    c.execute("SELECT id FROM menu WHERE nombre = ?", (producto_nombre,))
    res_prod = c.fetchone()
    
    if res_prod:
        prod_id = res_prod[0]
        # Buscar receta vinculada
        c.execute("SELECT r.insumo_id, r.cantidad_insumo, i.nombre FROM recetas r JOIN insumos i ON r.insumo_id = i.id WHERE r.menu_id = ?", (prod_id,))
        ingredientes = c.fetchall()
        
        if ingredientes:
            for insumo_id, cant_receta, nom_insumo in ingredientes:
                total_bajar = cant_receta * cantidad_vendida
                c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE id = ?", (total_bajar, insumo_id))
                mensajes.append(f"📉 {nom_insumo}: -{total_bajar}")
        else:
            mensajes.append(f"ℹ️ {producto_nombre} no descuenta stock base.")
    
    # Extras
    if tiene_cono:
        c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre LIKE '%Cono%' OR nombre LIKE '%Barquillo%'", (cantidad_vendida,))
        mensajes.append(f"📉 Extra Cono: -{cantidad_vendida}")
    
    if tiene_top:
        c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre LIKE '%Topping%'", (cantidad_vendida,))
        mensajes.append(f"📉 Extra Topping: -{cantidad_vendida}")

    conn.commit()
    conn.close()
    return mensajes

# --- LÓGICA DE MERMA (NUEVA) ---
def registrar_merma_db(insumo_nom, cantidad, razon):
    # 1. Guardar registro
    run_query("INSERT INTO mermas (insumo_nombre, cantidad, razon, fecha) VALUES (?,?,?,?)", 
              (insumo_nom, cantidad, razon, datetime.now()))
    
    # 2. Descontar del inventario físico (SIN tocar dinero)
    conn = sqlite3.connect('heladeria_completa.db')
    c = conn.cursor()
    c.execute("UPDATE insumos SET cantidad = cantidad - ? WHERE nombre = ?", (cantidad, insumo_nom))
    conn.commit()
    conn.close()

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
    if 'logs' not in st.session_state: st.session_state.logs = []

    st.sidebar.title("🍦 Sistema Heladería")
    # Agregamos "Registrar Merma" al menú
    opcion = st.sidebar.radio("Ir a:", ["🛒 Vender (Caja)", "📉 Registrar Merma", "📦 Insumos (CRUD)", "📝 Productos (CRUD)", "📊 Reportes & Eliminar"])

    # -----------------------------------------------------------
    # 1. CAJA Y VENTAS (Igual que antes)
    # -----------------------------------------------------------
    if opcion == "🛒 Vender (Caja)":
        st.header("Punto de Venta")
        
        if st.session_state.logs:
            for log in st.session_state.logs:
                st.info(log)
            st.session_state.logs = [] # Limpiar

        df_menu = run_query("SELECT * FROM menu ORDER BY nombre", return_data=True)
        
        if not df_menu.empty:
            c1, c2 = st.columns([3, 1])
            lista_nombres = [f"{row['nombre']} | S/{row['precio']}" for i, row in df_menu.iterrows()]
            eleccion = c1.selectbox("Producto", lista_nombres)
            cantidad = c2.number_input("Cantidad", 1, 100, 1)
            
            nombre_real = eleccion.split(" | S/")[0]
            precio_real = float(eleccion.split(" | S/")[1])
            
            col_x1, col_x2 = st.columns(2)
            add_top = col_x1.checkbox("Topping (+ S/1)")
            add_con = col_x2.checkbox("Cono Extra (+ S/1)")
            
            total_extra = (cantidad if add_top else 0) + (cantidad if add_con else 0)
            total_final = (precio_real * cantidad) + total_extra
            
            st.markdown(f"### 💰 Total: S/ {total_final:.2f}")
            metodo = st.radio("Pago", ["Efectivo", "Yape", "Tarjeta"], horizontal=True)
            
            if st.button("✅ REGISTRAR VENTA", type="primary", use_container_width=True):
                # 1. Guardar Venta
                run_query("INSERT INTO ventas (producto_nombre, precio_base, cantidad, extras, total, metodo_pago, fecha) VALUES (?,?,?,?,?,?,?)",
                          (nombre_real, precio_real, cantidad, total_extra, total_final, metodo, datetime.now()))
                
                # 2. Descontar Inventario
                logs = procesar_descuento_stock(nombre_real, cantidad, add_con, add_top)
                
                st.session_state.logs = logs
                st.session_state.logs.append(f"✅ Venta de {nombre_real} guardada.")
                st.rerun()
        else:
            st.warning("No hay productos. Ve a 'Productos (CRUD)' para crear uno.")

    # -----------------------------------------------------------
    # 2. REGISTRAR MERMA (NUEVA PESTAÑA AGREGADA)
    # -----------------------------------------------------------
    elif opcion == "📉 Registrar Merma":
        st.header("Control de Mermas / Desperdicios")
        
        st.markdown("""
        <div class="merma-box">
            <b>⚠️ Módulo de Pérdidas:</b><br>
            Usa esto si se cayó un helado, venció un producto o hubo un accidente.<br>
            <i>Esto descontará el stock físico pero NO afectará el dinero de la caja.</i>
        </div>
        """, unsafe_allow_html=True)
        st.divider()

        df_ins = run_query("SELECT * FROM insumos ORDER BY nombre", return_data=True)
        
        if not df_ins.empty:
            with st.form("form_merma", clear_on_submit=True):
                c1, c2 = st.columns([2, 1])
                insumo_sel = c1.selectbox("¿Qué se perdió?", df_ins['nombre'].unique())
                cant_sel = c2.number_input("Cantidad perdida", min_value=0.1, step=1.0)
                
                razon = st.text_input("Razón (Obligatorio)", placeholder="Ej: Se cayó al piso, Vencimiento, Degustación...")
                
                if st.form_submit_button("🚨 REGISTRAR PÉRDIDA"):
                    if razon:
                        registrar_merma_db(insumo_sel, cant_sel, razon)
                        st.error(f"Se descontaron {cant_sel} de {insumo_sel} del inventario.")
                        st.rerun()
                    else:
                        st.warning("Debes escribir la razón de la pérdida.")
            
            # Historial de mermas
            st.subheader("Historial de Mermas")
            df_mermas = run_query("SELECT * FROM mermas ORDER BY id DESC", return_data=True)
            st.dataframe(df_mermas, use_container_width=True)

        else:
            st.info("No hay insumos en el inventario para mermar.")

    # -----------------------------------------------------------
    # 3. PRODUCTOS (CRUD) - IGUAL QUE ANTES
    # -----------------------------------------------------------
    elif opcion == "📝 Productos (CRUD)":
        st.header("Gestión de Productos")
        
        with st.expander("➕ Crear Nuevo Producto", expanded=True):
            with st.form("new_prod", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                nom = c1.text_input("Nombre (ej. Vaso 2 Bolas)")
                pre = c2.number_input("Precio", min_value=0.0)
                cat = c3.selectbox("Categoría", ["Helado", "Paleta", "Bebida", "Otro/Consumible"])
                
                st.markdown("---")
                vincular = st.checkbox("¿Descuenta Inventario?", value=True)
                
                insumo_id = None
                cant_gasto = 0
                
                if vincular:
                    df_ins = run_query("SELECT * FROM insumos", return_data=True)
                    if not df_ins.empty:
                        mapa_insumos = {row['nombre']: row['id'] for i, row in df_ins.iterrows()}
                        insumo_sel = st.selectbox("Selecciona insumo:", list(mapa_insumos.keys()))
                        insumo_id = mapa_insumos[insumo_sel]
                        cant_gasto = st.number_input("Cantidad a descontar:", value=1.0)
                    else:
                        st.error("No hay insumos creados.")
                
                if st.form_submit_button("Guardar Producto"):
                    pid = run_query("INSERT INTO menu (nombre, precio, categoria) VALUES (?,?,?)", (nom, pre, cat))
                    if vincular and insumo_id:
                        run_query("INSERT INTO recetas (menu_id, insumo_id, cantidad_insumo) VALUES (?,?,?)", (pid, insumo_id, cant_gasto))
                        st.success(f"Producto '{nom}' creado y vinculado.")
                    else:
                        st.success(f"Producto '{nom}' creado (Sin inventario).")
                    st.rerun()

        st.divider()
        st.subheader("Lista de Productos")
        
        df_prods = run_query("""
            SELECT m.id, m.nombre, m.precio, m.categoria, i.nombre as Gasta_Insumo, r.cantidad_insumo as Cantidad_Gasto
            FROM menu m
            LEFT JOIN recetas r ON m.id = r.menu_id
            LEFT JOIN insumos i ON r.insumo_id = i.id
        """, return_data=True)
        
        if not df_prods.empty:
            for i, row in df_prods.iterrows():
                col1, col2, col3, col4, col5 = st.columns([1, 3, 2, 3, 1])
                col1.write(f"ID: {row['id']}")
                col2.write(f"**{row['nombre']}**")
                col3.write(f"S/ {row['precio']}")
                receta_txt = f"Gasta: {row['Cantidad_Gasto']} de {row['Gasta_Insumo']}" if row['Gasta_Insumo'] else "No vinculado"
                col4.caption(receta_txt)
                
                if col5.button("🗑️", key=f"del_prod_{row['id']}"):
                    run_query("DELETE FROM menu WHERE id = ?", (row['id'],))
                    run_query("DELETE FROM recetas WHERE menu_id = ?", (row['id'],))
                    st.rerun()
                st.markdown("<hr style='margin: 5px 0'>", unsafe_allow_html=True)

    # -----------------------------------------------------------
    # 4. INSUMOS (CRUD) - IGUAL QUE ANTES (Data Editor)
    # -----------------------------------------------------------
    elif opcion == "📦 Insumos (CRUD)":
        st.header("Gestión de Inventario")
        
        with st.expander("➕ Nuevo Insumo"):
            with st.form("add_ins", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                n = c1.text_input("Nombre")
                q = c2.number_input("Cantidad", 0.0)
                u = c3.text_input("Unidad")
                m = c4.number_input("Mínimo Alerta", 5.0)
                if st.form_submit_button("Guardar"):
                    run_query("INSERT INTO insumos (nombre, cantidad, unidad, minimo) VALUES (?,?,?,?)", (n, q, u, m))
                    st.rerun()
        
        st.subheader("Inventario (Edita directo en la tabla)")
        df_ins = run_query("SELECT * FROM insumos ORDER BY id", return_data=True)
        
        edited_df = st.data_editor(
            df_ins,
            column_config={
                "id": st.column_config.NumberColumn(disabled=True),
                "cantidad": st.column_config.NumberColumn("Stock Actual", min_value=0, format="%.1f"),
                "minimo": st.column_config.NumberColumn("Alerta Mínima", min_value=0),
            },
            hide_index=True,
            use_container_width=True,
            key="editor_insumos"
        )
        
        if not df_ins.equals(edited_df):
            for index, row in edited_df.iterrows():
                run_query("UPDATE insumos SET nombre=?, cantidad=?, unidad=?, minimo=? WHERE id=?", 
                          (row['nombre'], row['cantidad'], row['unidad'], row['minimo'], row['id']))
            st.toast("✅ Inventario actualizado.")
            
        st.markdown("##### Eliminar Insumos")
        with st.expander("Ver opciones de borrado"):
            for i, row in df_ins.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.text(f"{row['nombre']} ({row['cantidad']})")
                if c2.button("Borrar", key=f"del_ins_{row['id']}"):
                    run_query("DELETE FROM insumos WHERE id=?", (row['id'],))
                    st.rerun()

    # -----------------------------------------------------------
    # 5. REPORTES - IGUAL QUE ANTES
    # -----------------------------------------------------------
    elif opcion == "📊 Reportes & Eliminar":
        st.header("Reporte de Ventas")
        hoy = datetime.now().date()
        
        df_ventas = run_query("SELECT * FROM ventas ORDER BY id DESC", return_data=True)
        
        if not df_ventas.empty:
            df_ventas['fecha'] = pd.to_datetime(df_ventas['fecha'])
            ventas_hoy = df_ventas[df_ventas['fecha'].dt.date == hoy]
            
            t = ventas_hoy['total'].sum()
            col1, col2 = st.columns(2)
            col1.metric("Total Hoy", f"S/ {t:,.2f}")
            col2.metric("Ventas Hoy", len(ventas_hoy))
            
            st.divider()
            st.subheader("Transacciones (Opción de Borrar)")
            
            # Encabezados
            c1, c2, c3, c4, c5 = st.columns([1, 3, 1, 2, 1])
            c1.write("Hora"); c2.write("Producto"); c3.write("Cant"); c4.write("Total"); c5.write("Acción")
            
            for i, row in ventas_hoy.iterrows():
                c1, c2, c3, c4, c5 = st.columns([1, 3, 1, 2, 1])
                c1.write(row['fecha'].strftime("%H:%M"))
                c2.write(row['producto_nombre'])
                c3.write(str(row['cantidad']))
                c4.write(f"S/ {row['total']:.2f}")
                
                if c5.button("❌", key=f"del_venta_{row['id']}"):
                    run_query("DELETE FROM ventas WHERE id=?", (row['id'],))
                    st.rerun()
            
            st.divider()
            try:
                pdf = generar_pdf(ventas_hoy, t, str(hoy))
                st.download_button("📄 PDF Reporte", pdf, f"Reporte_{hoy}.pdf")
            except:
                st.error("Librería FPDF no instalada o error generando PDF.")
                
        else:
            st.info("No hay ventas.")

if __name__ == '__main__':
    main()
