import os
import json
import uuid
import time
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from google import genai
from google.genai import types

# Importamos la lógica robusta (asegúrate de que insights.py tenga el código que me pasaste)
from insights import clean_dataframe, apply_global_filters, process_component_data

load_dotenv()

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key_super_segura")
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_page'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DASHBOARD_DIR = os.path.join(DATA_DIR, 'dashboards')

for d in [DATA_DIR, UPLOAD_FOLDER, DASHBOARD_DIR]:
    os.makedirs(d, exist_ok=True)

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f: json.dump({}, f)

# ==========================================
# CONFIGURACIÓN IA (GEMINI)
# ==========================================

MODEL_NAME = "gemini-2.5-flash" 
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# PROMPT MAESTRO CON "INMUNIDAD DIPLOMÁTICA" PARA TUS COLUMNAS
SYSTEM_PROMPT = """
Eres un experto en Business Intelligence. Tu trabajo es traducir datos en configuraciones JSON.

INFORMACIÓN CRÍTICA SOBRE EL SISTEMA DE RENDERIZADO:
1. **NO TE PREOCUPES POR LA CARDINALIDAD:** El sistema visual (frontend) tiene una función automática que agrupa valores pequeños en "Otros". 
2. **TEXTO > IDs:** Para gráficos de Pie y Barras, los humanos prefieren leer "Hospital" (texto) antes que "COD_12" (ID). Si hay una columna descriptiva, ÚSALA aunque tenga muchos valores únicos.
3. **OBEDIENCIA TOTAL:** Si el usuario menciona el nombre de una columna, ES UNA ORDEN DIRECTA. Ignora tus criterios de "mejor visualización" y usa esa columna exacta.

TU MISIÓN:
Genera un JSON con:
1. **KPI 1 y 2:** Indicadores numéricos.
2. **GRÁFICO BARRAS:** Comparativa.
3. **GRÁFICO PIE:** Distribución.
4. **MAPA:** Solo si hay lat/lon o X/Y.

ESTRUCTURA JSON DE RESPUESTA:
{
  "title": "Título del Dashboard",
  "components": [
    {
      "id": "kpi1", "type": "kpi", "title": "...", 
      "config": { "operation": "sum", "column": "amount" }
    },
    {
      "id": "chart1", "type": "chart", "chart_type": "bar", "title": "...",
      "config": { "x": "COLUMNA_TEXTO", "y": "VALOR", "operation": "count", "limit": 10 }
    },
    {
      "id": "chart2", "type": "chart", "chart_type": "pie", "title": "...",
      "config": { "x": "COLUMNA_TEXTO", "y": "VALOR", "operation": "sum" }
    },
    {
      "id": "map1", "type": "map", "title": "...",
      "config": { "lat": "Y", "lon": "X", "label": "name" }
    }
  ]
}
"""

# ==========================================
# HELPERS
# ==========================================

def read_file_robust(filepath):
    """Lectura resiliente de archivos."""
    if filepath.endswith('.csv'):
        encodings = ['utf-8', 'latin-1', 'cp1252']
        for enc in encodings:
            try:
                df = pd.read_csv(filepath, engine='python', on_bad_lines='skip', encoding=enc)
                df.columns = df.columns.astype(str).str.strip()
                return df
            except UnicodeDecodeError:
                continue
            except Exception as e:
                raise e
        raise ValueError("Error de codificación en CSV.")
    else:
        df = pd.read_excel(filepath)
        df.columns = df.columns.astype(str).str.strip()
        return df

# ==========================================
# GESTIÓN USUARIOS
# ==========================================

class User(UserMixin):
    def __init__(self, id, email, password_hash):
        self.id = id
        self.email = email
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    try:
        with open(USERS_FILE, 'r') as f: users = json.load(f)
        if user_id in users:
            u = users[user_id]
            return User(user_id, u['email'], u['password'])
    except: pass
    return None

def get_user_by_email(email):
    with open(USERS_FILE, 'r') as f: users = json.load(f)
    for uid, data in users.items():
        if data['email'] == email: return User(uid, data['email'], data['password'])
    return None

# ==========================================
# RUTAS FRONTEND
# ==========================================

@app.route("/")
def index():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template("home.html")

@app.route("/auth")
def auth_page():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template("auth.html")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)

@app.route("/view/<dash_id>")
@login_required
def view_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return "Dashboard no encontrado", 404
    return render_template("share.html", dash_id=dash_id)

# ==========================================
# API AUTH
# ==========================================

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json
    user = get_user_by_email(data.get('email'))
    if user and bcrypt.check_password_hash(user.password_hash, data.get('password')):
        login_user(user)
        return jsonify({"message": "OK", "redirect": url_for('dashboard')})
    return jsonify({"error": "Credenciales incorrectas"}), 401

@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"redirect": url_for('index')})

# ==========================================
# LÓGICA CORE (SUBIDA Y GENERACIÓN)
# ==========================================

@app.route("/upload_and_analyze", methods=["POST"])
@login_required
def upload_and_analyze():
    if 'file' not in request.files: return jsonify({"error": "Falta archivo"}), 400
    file = request.files['file']
    
    file.seek(0, os.SEEK_END)
    if file.tell() > 25 * 1024 * 1024:
        return jsonify({"error": "Archivo > 25MB"}), 400
    file.seek(0)

    user_path = os.path.join(UPLOAD_FOLDER, current_user.id)
    os.makedirs(user_path, exist_ok=True)
    
    original_name = file.filename
    filename = f"{uuid.uuid4().hex[:8]}_{original_name}"
    filepath = os.path.join(user_path, filename)
    file.save(filepath)

    try:
        df = read_file_robust(filepath)
        df = clean_dataframe(df)
        
        # Generamos resumen para la IA
        summary = [f"Archivo: {original_name}", f"Filas: {len(df)}"]
        for col in df.columns:
            dtype = str(df[col].dtype)
            n_unique = df[col].nunique()
            # Muestras más largas para que la IA entienda el contexto del texto
            sample = [str(x)[:60] for x in df[col].dropna().head(3).tolist()]
            
            # INFO CLAVE: Le decimos cuántos únicos hay
            summary.append(f"- {col} ({dtype}) [Únicos: {n_unique}]: {sample}")
            
        return jsonify({
            "summary": "\n".join(summary),
            "file_path": os.path.join(current_user.id, filename),
            "original_name": original_name 
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/generate_dashboard", methods=["POST"])
@login_required
def generate_dashboard():
    if not client: return jsonify({"error": "Falta API KEY"}), 500

    data = request.json
    full_path = os.path.join(UPLOAD_FOLDER, data.get('file_path'))
    user_instruction = data.get('instruction', '')
    
    if not os.path.exists(full_path): return jsonify({"error": "Archivo perdido"}), 404

    try:
        df = read_file_robust(full_path)
        df = clean_dataframe(df)

        # --- LÓGICA DE FUERZA BRUTA (COLUMN ENFORCER) ---
        # Detectamos si el usuario escribió el nombre de una columna
        forced_cols = []
        clean_instruction = user_instruction.upper().replace("_", " ") # Normalizar espacios
        
        for col in df.columns:
            # Comparamos ignorando mayusculas y guiones bajos para ser flexibles
            clean_col = col.upper().replace("_", " ")
            if clean_col in clean_instruction:
                forced_cols.append(col)
        
        system_msg_extra = ""
        if forced_cols:
            system_msg_extra = (
                f"\n\n🚨 ALERTA DE PRIORIDAD MÁXIMA 🚨\n"
                f"El usuario ha mencionado explícitamente estas columnas: {forced_cols}\n"
                f"ESTÁ PROHIBIDO USAR OTRAS COLUMNAS. Si el usuario pidió un gráfico sobre '{forced_cols[0]}', "
                f"debes configurar 'x': '{forced_cols[0]}' OBLIGATORIAMENTE.\n"
                f"NO uses IDs o códigos (como CODI_...) si el usuario pidió el nombre (NOM_...).\n"
                f"El sistema backend agrupará los datos automáticamente, NO intentes simplificarlos tú.\n"
            )
        # ------------------------------------------------

        prompt = (
            f"DATOS DEL ARCHIVO:\n{data.get('summary')}\n\n"
            f"PETICIÓN DEL USUARIO: \"{user_instruction}\"\n"
            f"{system_msg_extra}\n"
            "Genera el JSON del dashboard ahora."
        )
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.1 # Bajamos temperatura para que sea más "robot" obediente
            )
        )

        config_json = json.loads(response.text)

        processed_components = []
        for comp in config_json.get('components', []):
            comp_data = process_component_data(df, comp)
            if comp_data:
                comp['data'] = comp_data
                processed_components.append(comp)

        final_config = {
            "title": config_json.get('title', "Dashboard Generado"),
            "components": processed_components
        }

        dash_id = str(uuid.uuid4())
        user_dash_dir = os.path.join(DASHBOARD_DIR, current_user.id)
        os.makedirs(user_dash_dir, exist_ok=True)
        
        with open(os.path.join(user_dash_dir, f"{dash_id}.json"), 'w') as f:
            json.dump({
                "id": dash_id,
                "created_at": datetime.now().isoformat(),
                "config": final_config,
                "file_path": data.get('file_path')
            }, f)

        return jsonify(final_config)

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

# ==========================================
# RUTAS DE GESTIÓN (IGUAL QUE ANTES)
# ==========================================

@app.route("/api/dashboards", methods=["GET"])
@login_required
def list_dashboards():
    user_dir = os.path.join(DASHBOARD_DIR, current_user.id)
    if not os.path.exists(user_dir): return jsonify([])
    items = []
    for f in os.listdir(user_dir):
        if f.endswith('.json'):
            try:
                with open(os.path.join(user_dir, f)) as file:
                    d = json.load(file)
                    items.append({"id": d['id'], "title": d.get('config', {}).get('title'), "created_at": d.get('created_at')})
            except: pass
    items.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(items)

@app.route("/api/dashboards/<dash_id>", methods=["GET"])
@login_required
def get_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "404"}), 404
    with open(path) as f: return jsonify(json.load(f)['config'])

@app.route("/api/dashboards/<dash_id>", methods=["DELETE"])
@login_required
def delete_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if os.path.exists(path): os.remove(path)
    return jsonify({"message": "OK"})

@app.route("/api/dashboards/<dash_id>/filter", methods=["POST"])
@login_required
def filter_dashboard(dash_id):
    filters = request.json.get('filters', {})
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "404"}), 404
    
    with open(path) as f: dash_data = json.load(f)
    full_path = os.path.join(UPLOAD_FOLDER, dash_data['file_path'])
    
    try:
        df = read_file_robust(full_path)
        df = clean_dataframe(df)
        df_filtered = apply_global_filters(df, filters)
        
        updated_components = []
        for comp in dash_data['config']['components']:
            new_data = process_component_data(df_filtered, comp)
            if new_data:
                comp['data'] = new_data
                updated_components.append(comp)
        return jsonify({"components": updated_components, "active_filters": filters})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)