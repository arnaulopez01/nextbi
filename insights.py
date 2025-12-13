import pandas as pd
import numpy as np
from pyproj import Transformer

def clean_dataframe(df):
    """Limpia valores infinitos y nulos básicos"""
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None)

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
        
        # --- 1. PROCESAR KPI ---
        if c_type == 'kpi':
            op = config.get('operation', 'count')
            col = config.get('column')
            
            val = 0
            if op == 'count':
                val = len(df)
            elif col and col in df.columns:
                numeric_series = pd.to_numeric(df[col], errors='coerce').fillna(0)
                if op == 'sum': val = numeric_series.sum()
                elif op == 'mean': val = numeric_series.mean()
                elif op == 'max': val = numeric_series.max()
                elif op == 'min': val = numeric_series.min()
            
            return {"value": val, "label": component.get('title')}

        # --- 2. PROCESAR MAPA (CON TRANSFORMACIÓN UTM -> WGS84) ---
        elif c_type == 'map':
            lat_col = config.get('lat')
            lon_col = config.get('lon') # En UTM esto suele ser X
            label = config.get('label')
            
            if lat_col in df.columns and lon_col in df.columns:
                cols = [lat_col, lon_col]
                if label and label in df.columns: cols.append(label)
                
                # 1. Copia segura y conversión a numérico
                df_map = df[cols].copy()
                df_map[lat_col] = pd.to_numeric(df_map[lat_col], errors='coerce')
                df_map[lon_col] = pd.to_numeric(df_map[lon_col], errors='coerce')
                df_map = df_map.dropna(subset=[lat_col, lon_col])

                if df_map.empty: return []

                # 2. DETECCIÓN INTELIGENTE DE CRS
                # WGS84 real: Lat (-90 a 90), Lon (-180 a 180)
                # Si detectamos valores fuera de rango, asumimos proyección (ej: UTM)
                max_val = max(df_map[lat_col].abs().max(), df_map[lon_col].abs().max())
                
                if max_val > 180:
                    try:
                        # Asumimos EPSG:25831 (UTM 31N - España/Europa Occidental)
                        # Si tus datos son de otra zona, cambia 'EPSG:25831'
                        transformer = Transformer.from_crs("EPSG:25831", "EPSG:4326", always_xy=True)
                        
                        # PyProj espera (x, y). En UTM: x=Este(lon), y=Norte(lat)
                        # IMPORTANTE: Asumimos que la columna mapeada como 'lon' es X y 'lat' es Y
                        x_vals = df_map[lon_col].values
                        y_vals = df_map[lat_col].values
                        
                        lon_trans, lat_trans = transformer.transform(x_vals, y_vals)
                        
                        df_map[lon_col] = lon_trans
                        df_map[lat_col] = lat_trans
                    except Exception as e:
                        print(f"Error transformando coordenadas: {e}")
                        return []

                # 3. Limitar puntos para no saturar el mapa
                return df_map.head(1000).to_dict(orient='records')
            return []

        # --- 3. PROCESAR GRÁFICO ---
        elif c_type == 'chart':
            x = config.get('x')
            y = config.get('y')
            op = config.get('operation', 'count')
            limit = config.get('limit', 20)
            
            if not x or x not in df.columns: return []

            # A. Agrupación
            if op == 'count':
                df_res = df[x].value_counts().reset_index()
                df_res.columns = [x, 'value']
            elif y and y in df.columns:
                df[y] = pd.to_numeric(df[y], errors='coerce').fillna(0)
                if op == 'sum': df_res = df.groupby(x)[y].sum().reset_index()
                elif op == 'mean': df_res = df.groupby(x)[y].mean().reset_index()
                else: df_res = df.groupby(x)[y].sum().reset_index()
                df_res.columns = [x, 'value']
            else:
                return []

            # B. Ordenar
            df_res = df_res.sort_values(by='value', ascending=False)

            # C. Lógica Pie Chart
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