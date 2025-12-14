import pandas as pd
import numpy as np
import re
from pyproj import Transformer

def smart_numeric_conversion(series):
    """
    Intenta convertir una columna a numérica manejando moneda y formatos.
    """
    if pd.api.types.is_numeric_dtype(series):
        return series
    
    # Copia para no alterar original por referencia
    s = series.astype(str).copy()
    
    # Limpieza AGRESIVA para detección (solo para probar si es número)
    # Eliminamos símbolos de moneda pero mantenemos signos negativos y decimales
    s_clean = s.apply(lambda x: re.sub(r'[^\d.,-]', '', x) if x and x.lower() != 'nan' else np.nan)
    
    # Detectar formato Europeo
    sample = s_clean.dropna().head(10).tolist()
    is_euro_format = False
    if sample:
        dots = sum(x.count('.') for x in sample)
        commas = sum(x.count(',') for x in sample)
        if commas > 0 and dots > 0:
            last_dot = max([x.rfind('.') for x in sample])
            last_comma = max([x.rfind(',') for x in sample])
            if last_comma > last_dot: is_euro_format = True
    
    if is_euro_format:
        s_clean = s_clean.str.replace('.', '').str.replace(',', '.')
    else:
        s_clean = s_clean.str.replace(',', '')

    return pd.to_numeric(s_clean, errors='coerce')

def clean_dataframe(df):
    """
    Limpieza profunda y detección de tipos RESILIENTE.
    """
    # 1. Eliminar filas/columnas completamente vacías
    df = df.dropna(how='all').dropna(axis=1, how='all')
    
    # 2. Reemplazar infinitos
    df = df.replace([np.inf, -np.inf], np.nan)

    # 3. Conversión inteligente de tipos CON SEGURIDAD
    for col in df.columns:
        original_series = df[col].copy()
        
        # A. Intentamos conversión numérica
        numeric_series = smart_numeric_conversion(df[col])
        
        # B. VERIFICACIÓN DE DAÑOS (La clave del arreglo)
        # Contamos cuántos datos válidos (no nulos) había antes y cuántos quedan después
        non_null_original = original_series.notna().sum()
        non_null_numeric = numeric_series.notna().sum()
        
        # Si la columna tenía datos y la conversión numérica mató más del 50% de ellos...
        # ¡ENTONCES NO ES NUMÉRICA! Es texto (ej: "Sants", "Gràcia").
        if non_null_original > 0:
            ratio_valid = non_null_numeric / non_null_original
            if ratio_valid < 0.5: 
                # Revertimos a la original: era texto
                df[col] = original_series
            else:
                # Aceptamos el cambio: era número sucio
                df[col] = numeric_series
        else:
            # Si estaba vacía, nos da igual
            df[col] = numeric_series

        # C. Intentar convertir a fecha (Solo si sobrevivió como objeto/texto)
        if df[col].dtype == 'object':
            try:
                temp_dates = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
                if temp_dates.notna().mean() > 0.6: 
                    df[col] = temp_dates
            except: pass

    # 4. Retorno limpio
    return df

def apply_global_filters(df, filters):
    if not filters: return df
    df_filtered = df.copy()
    for col, val in filters.items():
        if col in df_filtered.columns:
            df_filtered = df_filtered[df_filtered[col].astype(str) == str(val)]
    return df_filtered

def process_component_data(df, component):
    try:
        c_type = component.get('type')
        config = component.get('config', {})
        chart_type = component.get('chart_type')
        
        # --- 1. KPI ---
        if c_type == 'kpi':
            op = config.get('operation', 'count')
            col = config.get('column')
            
            val = 0
            if op == 'count':
                val = len(df)
            elif col and col in df.columns:
                series = df[col]
                if pd.api.types.is_numeric_dtype(series):
                    if op == 'sum': val = series.sum(min_count=0)
                    elif op == 'mean': val = series.mean()
                    elif op == 'max': val = series.max()
                    elif op == 'min': val = series.min()
                else:
                    val = 0
            
            if pd.isna(val): val = 0
            return {"value": val, "label": component.get('title')}

        # --- 2. MAPA ---
        elif c_type == 'map':
            lat_col = config.get('lat')
            lon_col = config.get('lon')
            label = config.get('label')
            
            if lat_col in df.columns and lon_col in df.columns:
                cols = [lat_col, lon_col]
                if label and label in df.columns: cols.append(label)
                
                df_map = df[cols].copy()
                # Coerce a numérico solo para el mapa, sin tocar el DF original
                df_map[lat_col] = pd.to_numeric(df_map[lat_col], errors='coerce')
                df_map[lon_col] = pd.to_numeric(df_map[lon_col], errors='coerce')
                df_map = df_map.dropna(subset=[lat_col, lon_col])

                if df_map.empty: return []

                # Transformación UTM -> WGS84
                max_val = max(df_map[lat_col].abs().max(), df_map[lon_col].abs().max())
                if max_val > 180:
                    try:
                        transformer = Transformer.from_crs("EPSG:25831", "EPSG:4326", always_xy=True)
                        x_vals = df_map[lon_col].values
                        y_vals = df_map[lat_col].values
                        lon_trans, lat_trans = transformer.transform(x_vals, y_vals)
                        df_map[lon_col] = lon_trans
                        df_map[lat_col] = lat_trans
                    except: return []
                
                df_map = df_map.where(pd.notnull(df_map), "Sin Información")
                return df_map.head(1000).to_dict(orient='records')
            return []

        # --- 3. CHART ---
        elif c_type == 'chart':
            x = config.get('x')
            y = config.get('y')
            op = config.get('operation', 'count')
            limit = config.get('limit', 20)
            
            if not x or x not in df.columns: return []

            df_chart = df.copy()
            # Rellenar nulos de texto
            df_chart[x] = df_chart[x].fillna("Sin Categoría").astype(str)

            if op == 'count':
                df_res = df_chart[x].value_counts().reset_index()
                df_res.columns = [x, 'value']
            
            elif y and y in df_chart.columns:
                if not pd.api.types.is_numeric_dtype(df_chart[y]):
                    # Intentamos convertir Y al vuelo si no es número, pero solo para el gráfico
                    df_chart[y] = smart_numeric_conversion(df_chart[y])
                
                if op == 'sum': df_res = df_chart.groupby(x)[y].sum(min_count=0).reset_index()
                elif op == 'mean': df_res = df_chart.groupby(x)[y].mean().reset_index()
                else: df_res = df_chart.groupby(x)[y].sum().reset_index()
                
                df_res.columns = [x, 'value']
                df_res['value'] = df_res['value'].fillna(0)
            else:
                return []

            df_res = df_res.sort_values(by='value', ascending=False)

            if chart_type == 'pie' and len(df_res) > 10:
                top_9 = df_res.iloc[:9]
                others_val = df_res.iloc[9:]['value'].sum()
                others_row = pd.DataFrame({x: ['Otros'], 'value': [others_val]})
                df_res = pd.concat([top_9, others_row])
            else:
                df_res = df_res.head(limit)
            
            return {
                "dimensions": [x, 'value'],
                "source": df_res.to_dict(orient='records')
            }
            
        return None
    except Exception as e:
        print(f"Error procesando componente {component.get('id')}: {e}")
        return None