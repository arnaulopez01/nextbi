import pandas as pd
import numpy as np
import re
from pyproj import Transformer

def try_numeric_conversion(series):
    """
    Intenta limpiar y convertir a números (quita €, $, espacios).
    """
    if pd.api.types.is_numeric_dtype(series):
        return series
    
    s = series.astype(str).copy()
    
    # Limpieza: quitamos todo lo que no sea dígito, punto, coma o guión
    s_clean = s.apply(lambda x: re.sub(r'[^\d.,-]', '', x) if pd.notnull(x) and x.lower() != 'nan' else np.nan)
    
    # Detección heurística de formato Europeo (1.000,00) vs USA (1,000.00)
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
    Limpieza conservadora: Si parece texto, lo deja como texto.
    """
    df = df.dropna(how='all').dropna(axis=1, how='all')
    df = df.replace([np.inf, -np.inf], np.nan)

    for col in df.columns:
        original_series = df[col].copy()
        
        # Intentamos convertir
        numeric_series = try_numeric_conversion(df[col])
        
        # Chequeo de seguridad: ¿Hemos destruido demasiada información?
        count_original = original_series.notna().sum()
        count_numeric = numeric_series.notna().sum()
        
        if count_original > 0:
            ratio = count_numeric / count_original
            # Si perdemos más del 50% de los datos, asumimos que NO era numérico
            if ratio < 0.5:
                df[col] = original_series
            else:
                df[col] = numeric_series
        else:
            df[col] = numeric_series

        # Intentar fechas solo si quedó como objeto
        if df[col].dtype == 'object':
            try:
                temp_dates = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
                if temp_dates.notna().mean() > 0.6: 
                    df[col] = temp_dates
            except: pass

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
        
        # --- 1. PROCESAR KPI (MEJORADO) ---
        if c_type == 'kpi':
            op = config.get('operation', 'count')
            col = config.get('column')
            val = 0
            
            # CASO A: NUNIQUE (Cuenta valores únicos, ideal para textos como "Barrios")
            if op == 'nunique' and col and col in df.columns:
                val = df[col].nunique()
            
            # CASO B: COUNT (Cuenta registros no nulos)
            elif op == 'count':
                if col and col in df.columns:
                    val = df[col].count() # Cuenta no nulos de esa columna
                else:
                    val = len(df) # Cuenta filas totales
            
            # CASO C: OPERACIONES MATEMÁTICAS (Sum, Mean, etc)
            elif col and col in df.columns:
                series = df[col]
                
                # Si piden sumar algo que parece texto, intentamos extraer números a la fuerza
                if not pd.api.types.is_numeric_dtype(series):
                    series_converted = try_numeric_conversion(series)
                    # Solo usamos la convertida si tiene sentido
                    if series_converted.notna().sum() > 0:
                        series = series_converted

                if pd.api.types.is_numeric_dtype(series):
                    if op == 'sum': val = series.sum(min_count=0)
                    elif op == 'mean': val = series.mean()
                    elif op == 'max': val = series.max()
                    elif op == 'min': val = series.min()
                else:
                    val = 0
            
            if pd.isna(val) or val is None: val = 0
            
            # Formateo si es entero
            if isinstance(val, float) and val.is_integer():
                val = int(val)

            return {"value": val, "label": component.get('title')}

        # --- 2. PROCESAR MAPA ---
        elif c_type == 'map':
            lat_col = config.get('lat')
            lon_col = config.get('lon')
            label = config.get('label')
            
            if lat_col in df.columns and lon_col in df.columns:
                cols = [lat_col, lon_col]
                if label and label in df.columns: cols.append(label)
                
                df_map = df[cols].copy()
                df_map[lat_col] = pd.to_numeric(df_map[lat_col], errors='coerce')
                df_map[lon_col] = pd.to_numeric(df_map[lon_col], errors='coerce')
                df_map = df_map.dropna(subset=[lat_col, lon_col])

                if df_map.empty: return []

                # Proyección
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

        # --- 3. PROCESAR GRÁFICO ---
        elif c_type == 'chart':
            x = config.get('x')
            y = config.get('y')
            op = config.get('operation', 'count')
            limit = config.get('limit', 20)
            
            if not x or x not in df.columns: return []

            df_chart = df.copy()
            df_chart[x] = df_chart[x].fillna("Sin Categoría").astype(str)

            if op == 'count':
                df_res = df_chart[x].value_counts().reset_index()
                df_res.columns = [x, 'value']
            
            elif y and y in df_chart.columns:
                if not pd.api.types.is_numeric_dtype(df_chart[y]):
                    df_chart[y] = try_numeric_conversion(df_chart[y])
                
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
        print(f"Error procesando {component.get('id')}: {e}")
        return None