import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json, base64, os, anthropic, requests, hashlib
import streamlit.components.v1 as components

# ════════════════════════════════════════════════════════════
#  CONFIGURAÇÃO DE STORAGE (GIST vs LOCAL)
# ════════════════════════════════════════════════════════════
# Em produção (Streamlit Cloud), GITHUB_TOKEN e GIST_ID vêm de st.secrets.
# Em local, se não existirem secrets, cai automaticamente pro filesystem.
def _get_secret(key, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

GITHUB_TOKEN = _get_secret("GITHUB_TOKEN")
GIST_ID      = _get_secret("GIST_ID")
APP_PASSWORD = _get_secret("APP_PASSWORD")
USE_GIST     = bool(GITHUB_TOKEN and GIST_ID)

# ════════════════════════════════════════════════════════════
#  CAMADA DE STORAGE — GIST
# ════════════════════════════════════════════════════════════
GIST_API = "https://api.github.com/gists"

def _gist_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

@st.cache_data(ttl=10, show_spinner=False)
def _gist_fetch_all():
    """Busca todos os arquivos do Gist. Cache curto pra evitar bater na API a cada rerun."""
    r = requests.get(f"{GIST_API}/{GIST_ID}", headers=_gist_headers(), timeout=15)
    r.raise_for_status()
    files = r.json().get("files", {})
    return {name: meta.get("content", "") for name, meta in files.items()}

def _gist_list_files():
    try:
        return sorted([n for n in _gist_fetch_all().keys() if n.endswith(".json")])
    except Exception as e:
        st.error(f"Erro ao listar arquivos do Gist: {e}")
        return []

def _gist_read_file(name):
    try:
        return _gist_fetch_all().get(name, "")
    except Exception as e:
        st.error(f"Erro ao ler {name}: {e}")
        return ""

def _gist_write_file(name, content):
    """PATCH no Gist atualizando um arquivo. Limpa cache pra próxima leitura ver o novo conteúdo."""
    payload = {"files": {name: {"content": content}}}
    r = requests.patch(f"{GIST_API}/{GIST_ID}", headers=_gist_headers(),
                       data=json.dumps(payload), timeout=15)
    r.raise_for_status()
    _gist_fetch_all.clear()
    return True

# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
#  CONSTANTES
# ════════════════════════════════════════════════════════════
ANO_ATUAL   = datetime.now().year
MES_ATUAL   = datetime.now().month - 1
MESES_C     = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
MESES_E     = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
CATEGORIAS  = ['🍔 Alimentação','💳 Alimentação (VR)','🚌 Transporte',
               '🏥 Saúde','🎉 Lazer','🏠 Moradia','👕 Vestuário','📚 Educação','📦 Outros']
TIPOS_INV   = ['Renda Fixa','Renda Variável','Fundos','Criptomoedas','Outros']
PASTA_APP   = os.path.dirname(os.path.abspath(__file__))

# ════════════════════════════════════════════════════════════
#  PERSISTÊNCIA
# ════════════════════════════════════════════════════════════
def listar_perfis():
    if USE_GIST:
        return _gist_list_files()
    return sorted([f for f in os.listdir(PASTA_APP) if f.endswith(".json")])

def _load_json(path):
    """Lê JSON do filesystem (modo local)."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def _load_dados(identificador):
    """Carrega dados de um perfil. Identificador é nome de arquivo no Gist OU caminho local."""
    if USE_GIST:
        nome = os.path.basename(identificador) if os.sep in identificador else identificador
        raw  = _gist_read_file(nome)
        if not raw: return {}
        try: return json.loads(raw)
        except: return {}
    return _load_json(identificador)

def salvar():
    if not st.session_state.get("arquivo_ativo"): return
    dados = {k: st.session_state[k] for k in
             ["salario_mes","vr_mes","receitas_extras","gastos_fixos",
              "gastos","reservaFaculdade","investimentos","dividas"]}
    try:
        if USE_GIST:
            nome = os.path.basename(st.session_state.arquivo_ativo)
            _gist_write_file(nome, json.dumps(dados, indent=2, ensure_ascii=False))
        else:
            with open(st.session_state.arquivo_ativo, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
    except Exception as e:
        st.toast(f"Erro ao salvar: {e}", icon="⚠️")

def carregar_perfil(caminho):
    d = _load_dados(caminho)
    ss = st.session_state
    ss.arquivo_ativo   = caminho
    ss.salario_mes     = {int(k): float(v) for k,v in d.get("salario_mes",{str(i):0.0 for i in range(12)}).items()}
    ss.vr_mes          = {int(k): float(v) for k,v in d.get("vr_mes",    {str(i):0.0 for i in range(12)}).items()}
    ss.receitas_extras = d.get("receitas_extras", [])
    ss.gastos_fixos    = d.get("gastos_fixos", [])
    ss.gastos          = d.get("gastos", [])
    ss.reservaFaculdade= d.get("reservaFaculdade", {"total":0.0,"usado":0.0})
    ss.dividas         = d.get("dividas", [])
    ss.mesAtivo        = MES_ATUAL
    ss.feedback_ia     = ""
    ss.feedback_mes    = -1
    invs = d.get("investimentos", [])
    ss.investimentos   = [
        inv if 'aportes' in inv
        else {**inv, 'aportes': [{"mes":"Histórico","valor":float(inv.get('valor',0)),"data":""}]}
        for inv in invs
    ]

# ════════════════════════════════════════════════════════════
#  CÁLCULOS
# ════════════════════════════════════════════════════════════
def rec_fixa(m):  return st.session_state.salario_mes.get(m,0.0) + st.session_state.vr_mes.get(m,0.0)
def rec_extra(m): return sum(r['valor'] for r in st.session_state.receitas_extras if r['mes']==m)
def rec_total(m): return rec_fixa(m) + rec_extra(m)
def gas_fixos(m): return sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g.get('fixo'))
def gas_pix(m):   return sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g.get('pix'))
def gas_avuls(m): return sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and not g.get('fixo') and not g.get('pix'))
def gas_total(m): return gas_fixos(m) + gas_avuls(m) + gas_pix(m)
def inv_valor(inv): return sum(a['valor'] for a in inv.get('aportes',[]))
def total_reservas():
    t = sum(inv_valor(i) for i in st.session_state.investimentos)
    rf = st.session_state.reservaFaculdade
    return t + max(0.0, rf['total'] - rf['usado'])
def parc_auto(d):
    if not d.get('data_inicio'): return d.get('parcPagas',0)
    try:
        ini = datetime.strptime(d['data_inicio'],"%Y-%m")
        h   = datetime.now()
        # O max(0, ...) garante que não teremos parcelas negativas no futuro
        return max(0, min((h.year-ini.year)*12+(h.month-ini.month), d['parcelas']))
    except: return d.get('parcPagas',0)
    try:
        ini = datetime.strptime(d['data_inicio'],"%Y-%m")
        h   = datetime.now()
        return min((h.year-ini.year)*12+(h.month-ini.month), d['parcelas'])
    except: return d.get('parcPagas',0)

# ════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ════════════════════════════════════════════════════════════
st.set_page_config(page_title="Financer", layout="wide", page_icon="💎",
                   initial_sidebar_state="collapsed")

# ════════════════════════════════════════════════════════════
#  CSS GLOBAL
# ════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Sora:wght@700;800&display=swap');

/* ── Base ── */
html, body { background: #080c14 !important; }
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section {
    background: #080c14 !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stHeader"] { background: #080c14 !important; }
[data-testid="stToolbar"] { display: none !important; }

/* ── Sidebar toggle button (collapsed state) ── */
[data-testid="stSidebarCollapsedControl"] {
    background: #0c1120 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 0 8px 8px 0 !important;
    width: 2rem !important;
    height: 2.5rem !important;
    top: 50% !important;
    position: fixed !important;
    left: 0 !important;
    z-index: 9999 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    cursor: pointer !important;
}
[data-testid="stSidebarCollapsedControl"]:hover {
    background: rgba(59,130,246,0.15) !important;
    border-color: rgba(59,130,246,0.4) !important;
}
[data-testid="stSidebarCollapsedControl"] svg {
    color: #64748b !important;
    width: 16px !important;
    height: 16px !important;
}
/* Hide the expand/collapse button inside open sidebar (use our nav instead) */
[data-testid="stSidebarCollapseButton"] button {
    background: transparent !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 6px !important;
    color: #475569 !important;
}
* { box-sizing: border-box; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0c1120 !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
    width: 240px !important;
}
[data-testid="stSidebar"] > div { padding: 0 !important; }
[data-testid="stSidebarNavItems"] { display:none !important; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { margin:0; }

/* Sidebar buttons */
[data-testid="stSidebar"] button[kind="secondary"] {
    background: transparent !important;
    border: 1px solid transparent !important;
    border-radius: 8px !important;
    color: #64748b !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    text-align: left !important;
    padding: 8px 12px !important;
    justify-content: flex-start !important;
}
[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: rgba(59,130,246,0.08) !important;
    border-color: rgba(59,130,246,0.2) !important;
    color: #94a3b8 !important;
}
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    color: #475569 !important;
    font-size: 0.82rem !important;
}

/* ── Main padding ── */
[data-testid="stMainBlockContainer"] { padding: 28px 32px 40px 32px !important; }

/* ── Typography ── */
h1,h2,h3,h4,h5,h6 { font-family:'Sora',sans-serif !important; color:#f1f5f9 !important; }
p, label { font-family:'Inter',sans-serif !important; }

/* ── Buttons ── */
button[kind="primary"] {
    background: linear-gradient(135deg,#3b82f6 0%,#6366f1 100%) !important;
    border: none !important; border-radius: 8px !important;
    font-family:'Inter',sans-serif !important; font-weight:600 !important;
    font-size:0.85rem !important; letter-spacing:0.01em !important;
    color: #fff !important;
    transition: opacity .2s !important;
}
button[kind="primary"]:hover { opacity:.88 !important; }
button[kind="secondary"] {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important; color: #94a3b8 !important;
    font-family:'Inter',sans-serif !important; font-size:0.85rem !important;
    transition: all .2s !important;
}
button[kind="secondary"]:hover {
    background: rgba(59,130,246,0.1) !important;
    border-color: rgba(59,130,246,0.4) !important;
    color: #e2e8f0 !important;
}
div[data-testid="stButton"] button { width:100%; }

/* ── Inputs ── */
input, textarea {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important; color: #e2e8f0 !important;
    font-family:'Inter',sans-serif !important;
}
input:focus, textarea:focus { border-color: rgba(59,130,246,0.5) !important; box-shadow: 0 0 0 2px rgba(59,130,246,0.15) !important; }
[data-baseweb="select"] > div {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important;
}
[data-baseweb="select"] svg { color: #64748b !important; }
label { color: #64748b !important; font-size:0.78rem !important; font-weight:500 !important; text-transform:uppercase; letter-spacing:0.06em !important; }

/* ── Metrics ── */
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 12px !important; padding: 18px 20px !important;
    transition: border-color .2s !important;
}
[data-testid="stMetric"]:hover { border-color: rgba(59,130,246,0.25) !important; }
[data-testid="stMetricValue"] {
    font-family:'JetBrains Mono',monospace !important;
    font-size:1.3rem !important; color:#f1f5f9 !important;
    letter-spacing:-.01em !important;
}
[data-testid="stMetricLabel"] {
    font-size:0.68rem !important; text-transform:uppercase !important;
    letter-spacing:0.1em !important; color:#475569 !important;
    font-weight:600 !important;
}
[data-testid="stMetricDelta"] { font-size:0.78rem !important; font-family:'Inter',sans-serif !important; }
[data-testid="stMetricDeltaIcon"] { display:none !important; }

/* ── Containers with border ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 14px !important;
    padding: 4px !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important;
}
[data-testid="stExpander"]:hover { border-color: rgba(59,130,246,0.3) !important; }
summary p { color: #94a3b8 !important; font-size:0.85rem !important; font-weight:500 !important; }
[data-testid="stExpanderToggleIcon"] { display: none !important; }

/* ── Progress ── */
[data-testid="stProgress"] [role="progressbar"] { 
    background: rgba(255,255,255,0.08) !important; 
    border-radius: 99px !important; 
    height: 8px !important; /* Aumentei levemente para 8px para ficar mais elegante */
}
[data-testid="stProgress"] [role="progressbar"] > div { 
    background: linear-gradient(90deg,#3b82f6,#6366f1) !important; 
    border-radius: 99px !important; 
}
[data-testid="stProgress"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.85rem !important;
    color: #94a3b8 !important;
    font-weight: 500 !important;
    margin-bottom: 6px !important; /* Dá um respiro entre o texto e a barra */
}
/* ── Dataframe ── */
[data-testid="stDataFrame"] { border-radius:10px !important; overflow:hidden !important; }
.stDataFrame { border: 1px solid rgba(255,255,255,0.07) !important; border-radius:10px !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.12); border-radius:99px; }

/* ── Alerts ── */
[data-testid="stAlert"] { border-radius:10px !important; border:1px solid rgba(255,255,255,0.08) !important; }

/* ── Divider ── */
hr { border-color: rgba(255,255,255,0.07) !important; }

/* ── Tabs (hidden - using sidebar nav) ── */
div[data-baseweb="tab-list"] { display:none !important; }

/* ── Form ── */
[data-testid="stForm"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important; padding: 16px !important;
}

/* ── Number input buttons ── */
button[data-testid="stNumberInputStepDown"],
button[data-testid="stNumberInputStepUp"] {
    background: rgba(255,255,255,0.06) !important;
    border-color: rgba(255,255,255,0.1) !important;
}
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
#  ESTADO INICIAL
# ════════════════════════════════════════════════════════════
if "app_init" not in st.session_state:
    st.session_state.app_init     = True
    st.session_state.arquivo_ativo = None
    st.session_state.pagina       = "visao_geral"
    st.session_state.feedback_ia  = ""
    st.session_state.feedback_mes = -1
    st.session_state.mesAtivo     = MES_ATUAL
    st.session_state.autenticado  = False

# ════════════════════════════════════════════════════════════
#  TELA DE LOGIN (APENAS QUANDO HÁ SENHA CONFIGURADA)
# ════════════════════════════════════════════════════════════
def _gravar_auth_sessionstorage_js(value: str):
    """Grava AUTH_TOKEN no sessionStorage do navegador (storage da pagina pai)."""
    components.html(
        f"""
        <script>
          try {{
            window.parent.sessionStorage.setItem("financer_auth", "{value}");
          }} catch (e) {{
            sessionStorage.setItem("financer_auth", "{value}");
          }}
        </script>
        """,
        height=0,
    )

def _checar_sessionstorage_js():
    """Le sessionStorage e injeta o token na URL via history.replaceState (sem reload).
    O Streamlit re-le query_params naturalmente."""
    components.html(
        """
        <script>
          (function() {
            let storage;
            try { storage = window.parent.sessionStorage; }
            catch (e) { storage = sessionStorage; }
            const token = storage.getItem("financer_auth");
            if (!token) return;
            let loc;
            try { loc = window.parent.location; }
            catch (e) { loc = window.location; }
            const url = new URL(loc.href);
            if (url.searchParams.get("auth") === token) return;
            url.searchParams.set("auth", token);
            try {
              window.parent.history.replaceState({}, "", url.toString());
              window.parent.location.reload();
            } catch (e) {
              window.location.href = url.toString();
            }
          })();
        </script>
        """,
        height=0,
    )

if APP_PASSWORD:
    # Hash da senha + um "tempero" fixo. Se alguem souber a senha, gera o hash;
    # sem saber a senha, nao consegue forjar.
    AUTH_TOKEN = hashlib.sha256(f"financer-auth::{APP_PASSWORD}".encode()).hexdigest()

    # Le token do query param (que o JS coloca a partir do sessionStorage).
    auth_qp = st.query_params.get("auth", "")
    if auth_qp == AUTH_TOKEN:
        st.session_state.autenticado = True

    # Se ainda nao esta autenticado, tenta puxar do sessionStorage via JS.
    # O JS recarrega a pagina com ?auth=<token> e o Python autentica na proxima execucao.
    if not st.session_state.get("autenticado"):
        _checar_sessionstorage_js()

    if not st.session_state.get("autenticado"):
        st.markdown("""
        <style>
        [data-testid="stSidebar"] { display:none !important; }
        [data-testid="stMainBlockContainer"] { padding: 0 !important; }
        </style>
        """, unsafe_allow_html=True)

        _, col, _ = st.columns([1, 1.2, 1])
        with col:
            st.markdown("<div style='height:80px'></div>", unsafe_allow_html=True)
            st.markdown("""
            <div style='text-align:center;margin-bottom:36px'>
                <div style='font-size:2.8rem;margin-bottom:12px;filter:drop-shadow(0 0 24px rgba(59,130,246,.5))'>🔒</div>
                <h1 style='font-family:"Sora",sans-serif;font-size:2.2rem;font-weight:800;margin:0;
                           background:linear-gradient(135deg,#f1f5f9 0%,#3b82f6 50%,#6366f1 100%);
                           -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                           letter-spacing:-.03em'>Financer</h1>
                <p style='color:#334155;font-size:.85rem;margin:10px 0 0'>
                    Digite a senha para acessar
                </p>
            </div>
            """, unsafe_allow_html=True)

            with st.form("login_form"):
                pwd = st.text_input("Senha", type="password", label_visibility="collapsed", placeholder="Senha")
                if st.form_submit_button("Entrar", type="primary", use_container_width=True):
                    if pwd == APP_PASSWORD:
                        # Grava token no sessionStorage (vale pra futuras sessoes/abas/F5).
                        _gravar_auth_sessionstorage_js(AUTH_TOKEN)
                        # Autentica a sessao ATUAL via session_state e segue.
                        st.session_state.autenticado = True
                        st.rerun()
                    else:
                        st.error("Senha incorreta.")
        st.stop()

# Restaura arquivo_ativo do query param se perdeu no rerun de navegação
if not st.session_state.arquivo_ativo:
    _arq_qp = st.query_params.get("arq", "")
    if _arq_qp:
        if USE_GIST:
            if _arq_qp in listar_perfis():
                carregar_perfil(_arq_qp)
        else:
            _caminho = os.path.join(PASTA_APP, _arq_qp)
            if os.path.exists(_caminho):
                carregar_perfil(_caminho)

# ════════════════════════════════════════════════════════════
#  HELPERS HTML
# ════════════════════════════════════════════════════════════
def card_titulo(icon, titulo, subtitulo=""):
    sub = f"<p style='margin:3px 0 0;color:#475569;font-size:.78rem;font-weight:400;letter-spacing:.02em'>{subtitulo}</p>" if subtitulo else ""
    st.markdown(f"""
    <div style='margin-bottom:20px;display:flex;align-items:center;gap:12px;'>
        <div style='width:38px;height:38px;background:linear-gradient(135deg,rgba(59,130,246,.2),rgba(99,102,241,.2));
                    border:1px solid rgba(99,102,241,.3);border-radius:10px;
                    display:flex;align-items:center;justify-content:center;font-size:1.1rem;'>{icon}</div>
        <div><h4 style='margin:0;font-size:1rem;font-weight:700;color:#f1f5f9;letter-spacing:-.01em'>{titulo}</h4>{sub}</div>
    </div>""", unsafe_allow_html=True)

def badge(texto, cor="#3b82f6"):
    st.markdown(f"<span style='display:inline-block;padding:2px 10px;border-radius:99px;font-size:.72rem;font-weight:600;background:{cor}22;color:{cor};border:1px solid {cor}44;letter-spacing:.04em'>{texto}</span>", unsafe_allow_html=True)

def linha_divisoria(label=""):
    if label:
        st.markdown(f"<div style='display:flex;align-items:center;gap:10px;margin:20px 0 14px'><div style='flex:1;height:1px;background:rgba(255,255,255,.07)'></div><span style='color:#334155;font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.1em'>{label}</span><div style='flex:1;height:1px;background:rgba(255,255,255,.07)'></div></div>", unsafe_allow_html=True)
    else:
        st.markdown("<hr style='margin:16px 0'>", unsafe_allow_html=True)

def kpi(label, valor, cor="#f1f5f9", delta=None):
    # Use native st.metric which renders correctly inside columns
    delta_str = f"{delta:+.1f}%" if delta is not None else None
    st.metric(label=label, value=valor, delta=delta_str)

def fmt(v): return f"R$ {v:,.2f}".replace(",","X").replace(".",",").replace("X",".")

# ════════════════════════════════════════════════════════════
#  TELA DE LOGIN / SELEÇÃO DE PERFIL
# ════════════════════════════════════════════════════════════
if not st.session_state.arquivo_ativo:
    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display:none !important; }
    [data-testid="stMainBlockContainer"] { padding: 0 !important; }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
        # Logo
        st.markdown("""
        <div style='text-align:center;margin-bottom:40px'>
            <div style='font-size:2.8rem;margin-bottom:12px;filter:drop-shadow(0 0 24px rgba(59,130,246,.5))'>💎</div>
            <h1 style='font-family:"Sora",sans-serif;font-size:2.4rem;font-weight:800;margin:0;
                       background:linear-gradient(135deg,#f1f5f9 0%,#3b82f6 50%,#6366f1 100%);
                       -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                       letter-spacing:-.03em'>Financer</h1>
            <p style='color:#334155;font-size:.88rem;margin:8px 0 0;letter-spacing:.06em;text-transform:uppercase'>
                Controle Financeiro Pessoal
            </p>
        </div>
        """, unsafe_allow_html=True)

        perfis = listar_perfis()

        if perfis:
            st.markdown("<p style='color:#475569;font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px'>Seus arquivos</p>", unsafe_allow_html=True)
            for nome in perfis:
                with st.container(border=True):
                    c1, c2 = st.columns([3,1])
                    if USE_GIST:
                        sub = "Armazenado no GitHub Gist (nuvem)"
                    else:
                        path = os.path.join(PASTA_APP, nome)
                        stat = os.stat(path)
                        mod  = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")
                        kb   = round(stat.st_size/1024, 1)
                        sub  = f"{mod} · {kb} KB"
                    with c1:
                        st.markdown(f"<p style='margin:0;font-weight:600;color:#e2e8f0;font-size:.9rem'>{nome}</p><p style='margin:2px 0 0;color:#475569;font-size:.75rem'>{sub}</p>", unsafe_allow_html=True)
                    with c2:
                        if st.button("Abrir", key=f"p_{nome}", use_container_width=True, type="primary"):
                            if USE_GIST:
                                carregar_perfil(nome)
                            else:
                                carregar_perfil(os.path.join(PASTA_APP, nome))
                            st.query_params["arq"] = nome
                            st.rerun()
        else:
            st.info("Nenhum arquivo encontrado. Crie um novo abaixo.")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        linha_divisoria("novo arquivo")

        novo = st.text_input("Nome do arquivo", placeholder="meus_dados_2026", label_visibility="collapsed")
        if st.button("✦  Criar e Entrar", type="primary", use_container_width=True):
            n = novo.strip().replace(" ","_")
            if n:
                if not n.endswith(".json"): n += ".json"
                if USE_GIST:
                    carregar_perfil(n)
                else:
                    _novo_path = os.path.join(PASTA_APP, n)
                    carregar_perfil(_novo_path)
                salvar()
                st.query_params["arq"] = n
                st.rerun()
            else:
                st.warning("Digite um nome.")

        st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
    st.stop()

# ════════════════════════════════════════════════════════════
#  NAVEGAÇÃO — ICON RAIL FIXO
# ════════════════════════════════════════════════════════════
nome_ativo = os.path.basename(st.session_state.arquivo_ativo)

NAV = [
    ("visao_geral", "🏠", "Visão Geral"),
    ("lancamentos", "💸", "Lançamentos"),
    ("reservas",    "💰", "Reservas"),
    ("dividas",     "📋", "Dívidas"),
    ("dashboard",   "📊", "Dashboard"),
    ("ia",          "🤖", "Análise IA"),
]

# Seletor de mês — fica no topo do conteúdo
if "mesAtivo" not in st.session_state:
    st.session_state.mesAtivo = MES_ATUAL

# ── CSS: esconde sidebar nativa, injeta icon rail fixo ──
st.markdown("""
<style>
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
button[data-testid="stBaseButton-headerNoPadding"] {
    display: none !important;
}
[data-testid="stHeader"] {
    display: none !important;
}
[data-testid="stMainBlockContainer"] {
    padding-left: 72px !important;
    padding-top: 24px !important;
    padding-right: 28px !important;
}
/* Icon rail */
.icon-rail {
    position: fixed;
    left: 0; top: 0; bottom: 0;
    width: 56px;
    background: #0c1120;
    border-right: 1px solid rgba(255,255,255,0.07);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16px 0;
    gap: 4px;
    z-index: 9999;
}
.rail-logo {
    font-size: 1.3rem;
    margin-bottom: 16px;
    filter: drop-shadow(0 0 8px rgba(59,130,246,.6));
    cursor: default;
}
.rail-btn {
    width: 40px; height: 40px;
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.1rem;
    cursor: pointer;
    border: 1px solid transparent;
    background: transparent;
    color: #475569;
    position: relative;
    transition: all 0.15s ease;
    text-decoration: none;
}
.rail-btn:hover {
    background: rgba(59,130,246,0.12);
    border-color: rgba(59,130,246,0.25);
    color: #94a3b8;
}
.rail-btn.active {
    background: rgba(59,130,246,0.18);
    border-color: rgba(59,130,246,0.4);
    color: #3b82f6;
}
.rail-btn .tip {
    position: absolute;
    left: 50px;
    background: #1e293b;
    color: #e2e8f0;
    font-size: 0.75rem;
    font-weight: 500;
    white-space: nowrap;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,0.1);
    pointer-events: none;
    opacity: 0;
    transform: translateX(-4px);
    transition: all 0.15s ease;
    font-family: Inter, sans-serif;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    z-index: 99999;
}
.rail-btn:hover .tip {
    opacity: 1;
    transform: translateX(0);
}
.rail-divider {
    width: 28px; height: 1px;
    background: rgba(255,255,255,0.07);
    margin: 6px 0;
}

/* ── Overlay de loading na troca de pagina ── */
#nav-loader {
    position: fixed;
    inset: 0;
    background: rgba(8, 12, 20, 0.75);
    backdrop-filter: blur(2px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 999999;
    pointer-events: none;
}
#nav-loader.show { display: flex; }
#nav-loader .spinner {
    width: 36px; height: 36px;
    border: 3px solid rgba(99,102,241,0.2);
    border-top-color: #6366f1;
    border-radius: 50%;
    animation: nav-spin 0.7s linear infinite;
}
@keyframes nav-spin {
    to { transform: rotate(360deg); }
}

</style>
""", unsafe_allow_html=True)

# ── Lê página da URL (query param) ──
_pag_qp = st.query_params.get("p", "visao_geral")
PAGINAS_VALIDAS = [pid for pid, _, _ in NAV]
pag = _pag_qp if _pag_qp in PAGINAS_VALIDAS else "visao_geral"
st.session_state.pagina = pag

# ── Nome do arquivo para preservar nos links ──
_arq_nome = os.path.basename(st.session_state.arquivo_ativo) if st.session_state.arquivo_ativo else ""

# ── Renderiza icon rail com links que preservam ?arq= ──
nav_html = '<div class="icon-rail"><div class="rail-logo">💎</div>'
for pid, icon, label in NAV:
    active_cls = "active" if pag == pid else ""
    nav_html += f'<a class="rail-btn {active_cls}" data-nav href="?p={pid}&arq={_arq_nome}" target="_self"><span style="font-size:1.2rem">{icon}</span><span class="tip">{label}</span></a>'
nav_html += '<div style="flex:1"></div>'
nav_html += f'<a class="rail-btn" data-nav href="?arq=" target="_self" style="font-size:1rem;opacity:.5;" title="Trocar arquivo">↩<span class="tip">Trocar arquivo</span></a>'
nav_html += '</div>'

# Overlay de loading + JS que ativa ao clicar em qualquer link de navegacao
nav_html += """
<div id="nav-loader"><div class="spinner"></div></div>
<script>
(function() {
  const overlay = document.getElementById("nav-loader");
  document.querySelectorAll("a.rail-btn[data-nav]").forEach(a => {
    a.addEventListener("click", () => {
      if (overlay) overlay.classList.add("show");
    });
  });
})();
</script>
"""
st.markdown(nav_html, unsafe_allow_html=True)

# ── Handle "trocar arquivo" ──
if st.query_params.get("arq") == "":
    st.session_state.arquivo_ativo = None
    st.query_params.clear()
    st.rerun()

# ── Dados pra exportação (usados pelo cabecalho_pagina) ──
dados_exp = {k: st.session_state[k] for k in
             ["salario_mes","vr_mes","receitas_extras","gastos_fixos",
              "gastos","reservaFaculdade","investimentos","dividas"]}

def cabecalho_pagina(titulo: str, subtitulo: str = ""):
    """Renderiza título da página + seletor de mês + botão Exportar na mesma linha."""
    hc1, hc2, hc3 = st.columns([3.5, 1, 1], vertical_alignment="center")
    with hc1:
        sub = f"<p style='margin:0;color:#475569;font-size:.85rem'>{subtitulo}</p>" if subtitulo else ""
        st.markdown(f"""
        <div>
            <h2 style='margin:0 0 4px;font-size:1.6rem;font-weight:800;letter-spacing:-.02em'>{titulo}</h2>
            {sub}
        </div>""", unsafe_allow_html=True)
    with hc2:
        st.session_state.mesAtivo = st.selectbox(
            "Mês", range(12),
            format_func=lambda x: MESES_E[x],
            index=st.session_state.get("mesAtivo", MES_ATUAL),
            label_visibility="collapsed", key="mes_sel"
        )
    with hc3:
        st.download_button("⬇ Exportar",
            data=json.dumps(dados_exp, indent=2, ensure_ascii=False),
            file_name=f"financer_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json", use_container_width=True)
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

# ── Sidebar oculta (não usada na navegação) ──
with st.sidebar:
    st.caption("Financer")

# ════════════════════════════════════════════════════════════
#  PÁGINA: VISÃO GERAL
# ════════════════════════════════════════════════════════════
if pag == "visao_geral":
    cabecalho_pagina("Visão Geral", f"{MESES_E[st.session_state.mesAtivo]} · {ANO_ATUAL}")
    m = st.session_state.mesAtivo  # re-le após cabeçalho (que tem o selectbox)

    receita  = rec_total(m)
    gasto    = gas_total(m)
    saldo    = receita - gasto
    reservas = total_reservas()
    div_rest = sum(d['total']-(d['total']/d['parcelas'])*parc_auto(d) for d in st.session_state.dividas)
    patrim   = reservas + saldo - div_rest
    comprm   = (gasto/receita*100) if receita > 0 else 0

    # Banner de status
    if comprm == 0:
        cor, icone, msg = "#3b82f6","◌","Sem lançamentos neste mês."
    elif comprm <= 70:
        cor, icone, msg = "#22c55e","✓",f"Controle excelente — {comprm:.1f}% da renda comprometida."
    elif comprm <= 90:
        cor, icone, msg = "#f59e0b","!",f"Atenção — {comprm:.1f}% da renda comprometida."
    else:
        cor, icone, msg = "#ef4444","✕",f"Alerta — {comprm:.1f}% da renda comprometida!"

    st.markdown(f"""
    <div style='background:{cor}12;border:1px solid {cor}30;border-left:3px solid {cor};
                border-radius:10px;padding:14px 18px;margin-bottom:24px;
                display:flex;align-items:center;gap:12px;'>
        <span style='font-size:1.1rem;color:{cor}'>{icone}</span>
        <span style='color:{cor};font-weight:500;font-size:.9rem'>{msg}</span>
    </div>""", unsafe_allow_html=True)

    # KPIs principais
    gastos_vr_kpi = sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g['cat']=='💳 Alimentação (VR)')
    gasto_sem_vr = gasto - gastos_vr_kpi # Filtra para mostrar apenas gastos "reais" do banco

    k1,k2,k3,k4 = st.columns(4)
    with k1: kpi("Receita do Mês",   fmt(receita), "#22c55e", (saldo/receita*100) if receita>0 else None)
    with k2: kpi("Total de Gastos",  fmt(gasto_sem_vr),   "#ef4444")
    with k3: kpi("Saldo Disponível", fmt(saldo),   "#3b82f6" if saldo>=0 else "#ef4444")
    with k4: kpi("Patrimônio Líq.",  fmt(patrim),  "#a78bfa")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    k5,k6,k7,k8 = st.columns(4)
    gastos_vr = sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g['cat']=='💳 Alimentação (VR)')
    saldo_din = st.session_state.salario_mes.get(m,0) + rec_extra(m) - (gasto - gastos_vr)
    saldo_vr  = st.session_state.vr_mes.get(m,0) - gastos_vr
    with k5: kpi("Saldo Conta",      fmt(saldo_din), "#22c55e" if saldo_din>=0 else "#ef4444")
    with k6: kpi("Saldo VR",         fmt(saldo_vr),  "#22c55e" if saldo_vr>=0 else "#ef4444")
    with k7: kpi("Total Reservas",   fmt(reservas),  "#a78bfa")
    with k8: kpi("Dívidas Restantes",fmt(div_rest),  "#f59e0b")

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # Gráficos
    c1, c2 = st.columns(2, gap="large")

    with c1:
        with st.container(border=True):
            card_titulo("📈","Evolução do Saldo","Ano corrente")
            saldos = [rec_total(i)-gas_total(i) for i in range(m+1)]
            cores  = ["#22c55e" if s >= 0 else "#ef4444" for s in saldos]
            fig = go.Figure(go.Bar(
                x=MESES_C[:m+1], y=saldos,
                marker_color=cores,
                marker_line_width=0,
            ))
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0,r=0,t=0,b=0), height=220,
                xaxis=dict(showgrid=False, color="#475569", tickfont_size=11),
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)", color="#475569", tickfont_size=11),
                font_family="Inter",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})

    with c2:
        with st.container(border=True):
            card_titulo("🍩","Gastos por Categoria",MESES_E[m])
            gastos_m = [g for g in st.session_state.gastos if g['mes']==m]
            if gastos_m:
                df_cat = pd.DataFrame(gastos_m)
                fig2 = go.Figure(go.Pie(
                    labels=df_cat['cat'].str.split(' ',n=1).str[-1],
                    values=df_cat['valor'],
                    hole=.55,
                    textinfo="percent",
                    textfont_size=11,
                    marker=dict(colors=["#3b82f6","#6366f1","#22c55e","#f59e0b","#ef4444","#a78bfa","#ec4899","#14b8a6","#f97316"],
                                line=dict(color="#080c14",width=2))
                ))
                fig2.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0,r=0,t=0,b=0), height=220,
                    legend=dict(font_size=11, font_color="#64748b", bgcolor="rgba(0,0,0,0)"),
                    font_family="Inter",
                )
                st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar":False})
            else:
                st.markdown("<p style='color:#334155;text-align:center;padding:40px 0'>Nenhum gasto lançado.</p>", unsafe_allow_html=True)

    # Últimos lançamentos
    linha_divisoria("últimos lançamentos")
    gastos_recentes = sorted([g for g in st.session_state.gastos if g['mes']==m], key=lambda x: x['id'], reverse=True)[:5]
    if gastos_recentes:
        for g in gastos_recentes:
            with st.container(border=False):
                c1, c2 = st.columns([4, 1])
                with c1:
                    fixo_badge = " 🔄" if g.get('fixo') else ""
                    pix_badge  = " 💠" if g.get('pix') else ""
                    st.markdown(f"**{g['nome']}{fixo_badge}{pix_badge}**")
                    st.caption(g['cat'])
                with c2:
                    st.markdown(f"<p style='text-align:right;color:#ef4444;font-family:monospace;font-size:.9rem;margin:0'>{fmt(g['valor'])}</p>", unsafe_allow_html=True)
            st.divider()
    else:
        st.caption("Nenhum gasto lançado este mês.")

# ════════════════════════════════════════════════════════════
#  PÁGINA: LANÇAMENTOS
# ════════════════════════════════════════════════════════════
elif pag == "lancamentos":
    cabecalho_pagina("Lançamentos", f"{MESES_E[st.session_state.mesAtivo]} · {ANO_ATUAL}")
    m = st.session_state.mesAtivo

    col_esq, col_dir = st.columns([1, 1], gap="large")

    # ── RECEITAS ──
    with col_esq:
        with st.container(border=True):
            card_titulo("💚","Receitas",f"Total: {fmt(rec_total(m))}")

            with st.expander("⚙  Salário e Vale Alimentação"):
                c1,c2 = st.columns(2)
                st.session_state.salario_mes[m] = c1.number_input("Salário (R$)", min_value=0.0, value=st.session_state.salario_mes.get(m,0.0), step=100.0, key="sal")
                st.session_state.vr_mes[m]       = c2.number_input("Vale Alimentação (R$)", min_value=0.0, value=st.session_state.vr_mes.get(m,0.0), step=50.0, key="vr")
                if st.button("Salvar ganhos fixos", use_container_width=True):
                    salvar(); st.toast("Salvo!", icon="✅")

            with st.expander("➕  Adicionar receita extra"):
                with st.form("f_rec", clear_on_submit=True):
                    n = st.text_input("Origem (ex: freelance, bônus)")
                    v = st.number_input("Valor (R$)", min_value=0.0, step=10.0)
                    if st.form_submit_button("Adicionar receita", use_container_width=True, type="primary"):
                        if n and v > 0:
                            nid = max([0]+[x['id'] for x in st.session_state.receitas_extras])+1
                            st.session_state.receitas_extras.append({"id":nid,"nome":n,"valor":v,"mes":m})
                            salvar(); st.rerun()

            with st.expander("✏  Editar / remover receita extra"):
                rec_m = [r for r in st.session_state.receitas_extras if r['mes']==m]
                if rec_m:
                    sel = st.selectbox("Receita", [r['id'] for r in rec_m],
                        format_func=lambda x: next(f"{r['nome']} ({fmt(r['valor'])})" for r in rec_m if r['id']==x))
                    idx = next(i for i,r in enumerate(st.session_state.receitas_extras) if r['id']==sel)
                    cur = st.session_state.receitas_extras[idx]
                    with st.form("f_erec"):
                        nn = st.text_input("Origem", value=cur['nome'])
                        nv = st.number_input("Valor", min_value=0.0, value=float(cur['valor']), step=10.0)
                        b1,b2 = st.columns(2)
                        if b1.form_submit_button("💾 Salvar", use_container_width=True):
                            st.session_state.receitas_extras[idx].update({'nome':nn,'valor':nv})
                            salvar(); st.rerun()
                        if b2.form_submit_button("🗑 Excluir", use_container_width=True):
                            st.session_state.receitas_extras.pop(idx)
                            salvar(); st.rerun()
                else:
                    st.caption("Nenhuma receita extra lançada.")

            # Tabela receitas
            linha_divisoria("resumo")
            
            # Cálculos de receitas (incluindo VR)
            salario_puro = st.session_state.salario_mes.get(m, 0.0)
            vr_puro      = st.session_state.vr_mes.get(m, 0.0)
            extras_puro  = rec_extra(m)
            total_receitas = salario_puro + extras_puro + vr_puro
            
            # 4 colunas de métricas
            mr1, mr2, mr3, mr4 = st.columns(4)
            mr1.metric("Salário", fmt(salario_puro))
            mr2.metric("Extra",   fmt(extras_puro))
            mr3.metric("VR",      fmt(vr_puro))
            mr4.metric("Total",   fmt(total_receitas))

            # Tabela visual de receitas extras
            rec_lista = [r for r in st.session_state.receitas_extras if r['mes']==m]
            if rec_lista:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                df_rec = pd.DataFrame([{"Origem": r['nome'], "Valor": r['valor']} for r in rec_lista])
                st.dataframe(df_rec, hide_index=True, use_container_width=True,
                             column_config={"Valor": st.column_config.NumberColumn(format="R$ %.2f")})
            else:
                st.markdown("<p style='color:#334155;font-size:.85rem;padding:8px 0'>Nenhuma receita extra lançada.</p>", unsafe_allow_html=True)

    # ── GASTOS ──
    with col_dir:
        with st.container(border=True):
            card_titulo("🔴","Gastos",f"Total: {fmt(gas_total(m))}")

            with st.expander("➕  Adicionar gasto"):
                with st.form("f_gas", clear_on_submit=True):
                    ng  = st.text_input("Descrição")
                    vg  = st.number_input("Valor (R$)", min_value=0.0, step=10.0)
                    cg  = st.selectbox("Categoria", CATEGORIAS, index=None, placeholder="Selecione…")
                    tipo_pg = st.radio("Tipo de pagamento", ["Avulso","🔄 Fixo","💠 PIX"], horizontal=True, key="tp_add")
                    if st.form_submit_button("Adicionar gasto", use_container_width=True, type="primary"):
                        if ng and vg > 0 and cg:
                            if cg=='📚 Educação': st.session_state.reservaFaculdade['usado'] += vg
                            nid = max([0]+[x['id'] for x in st.session_state.gastos])+1
                            fix = tipo_pg == "🔄 Fixo"
                            pix = tipo_pg == "💠 PIX"
                            st.session_state.gastos.append({"id":nid,"nome":ng,"valor":vg,"cat":cg,"mes":m,"fixo":fix,"pix":pix})
                            salvar(); st.rerun()

            with st.expander("✏  Editar / remover gasto"):
                gas_m = [g for g in st.session_state.gastos if g['mes']==m]
                if gas_m:
                    sel = st.selectbox("Gasto", [g['id'] for g in gas_m],
                        format_func=lambda x: next(f"{g['nome']} ({fmt(g['valor'])})" for g in gas_m if g['id']==x))
                    idx = next(i for i,g in enumerate(st.session_state.gastos) if g['id']==sel)
                    cur = st.session_state.gastos[idx]
                    with st.form("f_egas"):
                        nn  = st.text_input("Descrição", value=cur['nome'])
                        nv  = st.number_input("Valor", min_value=0.0, value=float(cur['valor']), step=10.0)
                        nc  = st.selectbox("Categoria", CATEGORIAS,
                                index=CATEGORIAS.index(cur['cat']) if cur['cat'] in CATEGORIAS else 0)
                        tipos_edit = ["Avulso","🔄 Fixo","💠 PIX"]
                        tipo_atual = "🔄 Fixo" if cur.get('fixo') else ("💠 PIX" if cur.get('pix') else "Avulso")
                        ntipo = st.radio("Tipo de pagamento", tipos_edit, index=tipos_edit.index(tipo_atual), horizontal=True, key="tp_edit")
                        b1,b2 = st.columns(2)
                        if b1.form_submit_button("💾 Salvar", use_container_width=True):
                            if cur['cat']=='📚 Educação': st.session_state.reservaFaculdade['usado'] -= cur['valor']
                            if nc=='📚 Educação': st.session_state.reservaFaculdade['usado'] += nv
                            nf = ntipo == "🔄 Fixo"
                            npix = ntipo == "💠 PIX"
                            st.session_state.gastos[idx].update({'nome':nn,'valor':nv,'cat':nc,'fixo':nf,'pix':npix})
                            salvar(); st.rerun()
                        if b2.form_submit_button("🗑 Excluir", use_container_width=True):
                            if cur['cat']=='📚 Educação': st.session_state.reservaFaculdade['usado'] -= cur['valor']
                            st.session_state.gastos.pop(idx); salvar(); st.rerun()
                else:
                    st.caption("Nenhum gasto lançado.")

            with st.expander("🔍  Filtrar gastos"):
                fc1,fc2 = st.columns(2)
                ftxt = fc1.text_input("Buscar", placeholder="Nome…", key="f_txt")
                fcat = fc2.selectbox("Categoria", ["Todas"]+CATEGORIAS, key="f_cat")
                ftipo= st.radio("Tipo", ["Todos","Fixos","Avulsos","PIX"], horizontal=True, key="f_tipo")
                gf   = [g for g in st.session_state.gastos if g['mes']==m]
                if ftxt: gf = [g for g in gf if ftxt.lower() in g['nome'].lower()]
                if fcat != "Todas": gf = [g for g in gf if g['cat']==fcat]
                if ftipo=="Fixos":  gf = [g for g in gf if g.get('fixo')]
                if ftipo=="Avulsos":gf = [g for g in gf if not g.get('fixo') and not g.get('pix')]
                if ftipo=="PIX":    gf = [g for g in gf if g.get('pix')]
                if gf:
                    st.dataframe(pd.DataFrame([{"Item":g['nome']+(" 🔄" if g.get('fixo') else "")+(" 💠" if g.get('pix') else ""),
                        "Cat.":g['cat'],"R$":g['valor']} for g in gf]),
                        hide_index=True, use_container_width=True,
                        column_config={"R$":st.column_config.NumberColumn(format="R$ %.2f")})
                    st.caption(f"Total filtrado: **{fmt(sum(g['valor'] for g in gf))}**")
                else:
                    st.caption("Nenhum gasto com esses filtros.")

            linha_divisoria("resumo")
            
            # Isola o VR completamente dos cálculos
            gastos_vr = sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g['cat']=='💳 Alimentação (VR)')
            
            # Garante que VR não entre em nenhuma categoria. PIX é mutuamente exclusivo com Fixo.
            fixos_sem_vr   = sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g.get('fixo') and g['cat'] != '💳 Alimentação (VR)')
            pix_sem_vr     = sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and g.get('pix')  and g['cat'] != '💳 Alimentação (VR)')
            avulsos_sem_vr = sum(g['valor'] for g in st.session_state.gastos if g['mes']==m and not g.get('fixo') and not g.get('pix') and g['cat'] != '💳 Alimentação (VR)')
            
            # Total é estritamente banco (Fixos + Avulsos + PIX)
            total_banco = fixos_sem_vr + avulsos_sem_vr + pix_sem_vr
            
            mg1,mg2,mg3,mg4,mg5 = st.columns(5)
            mg1.metric("Fixos",   fmt(fixos_sem_vr))
            mg2.metric("Avulsos", fmt(avulsos_sem_vr))
            mg3.metric("PIX",     fmt(pix_sem_vr))
            mg4.metric("No VR",   fmt(gastos_vr))
            mg5.metric("Total",   fmt(total_banco))

            gas_lista = [g for g in st.session_state.gastos if g['mes']==m]

            gas_lista = [g for g in st.session_state.gastos if g['mes']==m]
            if gas_lista:
                df2 = pd.DataFrame([{"Item":g['nome']+(" 🔄" if g.get('fixo') else "")+(" 💠" if g.get('pix') else ""),
                    "Categoria":g['cat'],"Valor":g['valor']} for g in gas_lista])
                tot = rec_total(m)
                df2["% Renda"] = (df2["Valor"]/tot*100).round(1) if tot>0 else 0.0
                st.dataframe(df2, hide_index=True, use_container_width=True,
                    column_config={"Valor":st.column_config.NumberColumn(format="R$ %.2f"),
                                   "% Renda":st.column_config.NumberColumn(format="%.1f %%")})
            else:
                st.markdown("<p style='color:#334155;font-size:.85rem;padding:8px 0'>Nenhum gasto lançado.</p>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
#  PÁGINA: RESERVAS
# ════════════════════════════════════════════════════════════
elif pag == "reservas":
    cabecalho_pagina("Reservas & Investimentos", f"Total acumulado: {fmt(total_reservas())}")
    m = st.session_state.mesAtivo

    k1,k2,k3 = st.columns(3)
    k1.metric("Total Guardado", fmt(total_reservas()))
    k2.metric("Qtd. Reservas",  str(len(st.session_state.investimentos)))
    k3.metric("Reserva Faculdade", fmt(max(0, st.session_state.reservaFaculdade['total']-st.session_state.reservaFaculdade['usado'])))

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([1,1], gap="large")

    with c1:
        with st.container(border=True):
            card_titulo("➕","Nova Reserva / Aporte")

            with st.expander("Criar nova reserva", expanded=True):
                with st.form("f_inv", clear_on_submit=True):
                    ni = st.text_input("Nome (ex: CDB, Viagem)")
                    vi = st.number_input("Aporte inicial (R$)", min_value=0.0, step=100.0)
                    ti = st.selectbox("Tipo", TIPOS_INV, index=None, placeholder="Selecione…")
                    if st.form_submit_button("Criar reserva", use_container_width=True, type="primary"):
                        if ni and vi > 0 and ti:
                            nid = max([0]+[x['id'] for x in st.session_state.investimentos])+1
                            ap  = {"mes":f"{MESES_C[m]}/{ANO_ATUAL}","valor":vi,"data":datetime.now().strftime("%d/%m/%Y")}
                            st.session_state.investimentos.append({"id":nid,"nome":ni,"tipo":ti,"aportes":[ap]})
                            salvar(); st.rerun()

            with st.expander("Adicionar aporte a reserva existente"):
                if st.session_state.investimentos:
                    with st.form("f_ap", clear_on_submit=True):
                        sel = st.selectbox("Reserva", [i['id'] for i in st.session_state.investimentos],
                            format_func=lambda x: next(f"{i['nome']} — {fmt(inv_valor(i))}" for i in st.session_state.investimentos if i['id']==x))
                        va = st.number_input("Valor do aporte (R$)", min_value=0.0, step=100.0)
                        if st.form_submit_button("Registrar aporte", use_container_width=True, type="primary"):
                            if va > 0:
                                idx = next(i for i,x in enumerate(st.session_state.investimentos) if x['id']==sel)
                                ap  = {"mes":f"{MESES_C[m]}/{ANO_ATUAL}","valor":va,"data":datetime.now().strftime("%d/%m/%Y")}
                                st.session_state.investimentos[idx]['aportes'].append(ap)
                                salvar(); st.rerun()
                else:
                    st.caption("Crie uma reserva primeiro.")

            with st.expander("✏  Editar / remover reserva"):
                if st.session_state.investimentos:
                    sel = st.selectbox("Reserva", [i['id'] for i in st.session_state.investimentos],
                        format_func=lambda x: next(f"{i['nome']} ({fmt(inv_valor(i))})" for i in st.session_state.investimentos if i['id']==x),
                        key="edit_inv_sel")
                    idx = next(i for i,x in enumerate(st.session_state.investimentos) if x['id']==sel)
                    cur = st.session_state.investimentos[idx]
                    with st.form("f_einv"):
                        nn = st.text_input("Nome", value=cur['nome'])
                        nt = st.selectbox("Tipo", TIPOS_INV, index=TIPOS_INV.index(cur['tipo']) if cur['tipo'] in TIPOS_INV else 0)
                        b1,b2 = st.columns(2)
                        if b1.form_submit_button("💾 Salvar", use_container_width=True):
                            st.session_state.investimentos[idx].update({'nome':nn,'tipo':nt})
                            salvar(); st.rerun()
                        if b2.form_submit_button("🗑 Excluir", use_container_width=True):
                            st.session_state.investimentos.pop(idx); salvar(); st.rerun()
                else:
                    st.caption("Nenhuma reserva cadastrada.")

    with c2:
        with st.container(border=True):
            card_titulo("📊","Composição do Patrimônio")

            dados_inv = []
            rf = st.session_state.reservaFaculdade
            if rf['total'] > 0:
                dados_inv.append({"Reserva":"📚 Faculdade","Valor":max(0,rf['total']-rf['usado'])})
            for i in st.session_state.investimentos:
                dados_inv.append({"Reserva":i['nome'],"Valor":inv_valor(i)})
            st.session_state._dados_inv_cache = dados_inv

            if dados_inv:
                df_inv = pd.DataFrame(dados_inv)
                tot = df_inv["Valor"].sum()
                df_inv["%"] = (df_inv["Valor"]/tot*100).round(1) if tot>0 else 0.0
                fig = go.Figure(go.Pie(
                    labels=df_inv["Reserva"], values=df_inv["Valor"],
                    hole=.5, textinfo="percent", textfont_size=11,
                    marker=dict(colors=["#3b82f6","#6366f1","#22c55e","#f59e0b","#a78bfa","#ec4899","#14b8a6"],
                                line=dict(color="#080c14",width=2))
                ))
                fig.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0,r=0,t=0,b=0), height=240,
                    legend=dict(font_size=11, font_color="#64748b", bgcolor="rgba(0,0,0,0)"),
                    font_family="Inter",
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
                st.dataframe(df_inv, hide_index=True, use_container_width=True,
                    column_config={"Valor":st.column_config.NumberColumn(format="R$ %.2f"),
                                   "%":st.column_config.NumberColumn(format="%.1f %%")})
            else:
                st.markdown("<p style='color:#334155;font-size:.85rem;padding:20px 0;text-align:center'>Nenhuma reserva cadastrada.</p>", unsafe_allow_html=True)

        with st.container(border=True):
            card_titulo("📈","Histórico de Aportes")
            if st.session_state.investimentos:
                sel = st.selectbox("Selecione a reserva", [i['id'] for i in st.session_state.investimentos],
                    format_func=lambda x: next(i['nome'] for i in st.session_state.investimentos if i['id']==x),
                    key="hist_sel")
                inv = next(i for i in st.session_state.investimentos if i['id']==sel)
                if inv.get('aportes'):
                    df_h = pd.DataFrame(inv['aportes'])
                    df_h.columns = ['Mês','Valor (R$)','Data']
                    st.dataframe(df_h, hide_index=True, use_container_width=True,
                        column_config={"Valor (R$)":st.column_config.NumberColumn(format="R$ %.2f")})
                    st.caption(f"**Total acumulado: {fmt(inv_valor(inv))}**")
            else:
                st.caption("Nenhuma reserva cadastrada.")

# ════════════════════════════════════════════════════════════
#  PÁGINA: DÍVIDAS
# ════════════════════════════════════════════════════════════
elif pag == "dividas":
    cabecalho_pagina("Dívidas & Parcelamentos", "Acompanhe o progresso das suas dívidas")
    m = st.session_state.mesAtivo

    div_total = sum(d['total'] for d in st.session_state.dividas)
    div_pago  = sum((d['total']/d['parcelas'])*parc_auto(d) for d in st.session_state.dividas)
    div_rest  = div_total - div_pago

    k1,k2,k3 = st.columns(3)
    k1.metric("Total em Dívidas", fmt(div_total))
    k2.metric("Total Pago",       fmt(div_pago))
    k3.metric("Restante",         fmt(div_rest))

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    col1, col2 = st.columns([1,1], gap="large")

    with col1:
        with st.container(border=True):
            card_titulo("➕","Cadastrar Nova Dívida")
            with st.form("f_div", clear_on_submit=True):
                nd = st.text_input("Nome da dívida")
                vd = st.number_input("Valor total (R$)", min_value=0.0, step=100.0)
                pd_ = st.number_input("Número de parcelas", min_value=1, step=1, value=12)
                di = st.text_input("Mês de início (AAAA-MM)", placeholder="2025-01")
                if st.form_submit_button("Cadastrar dívida", use_container_width=True, type="primary"):
                    if nd and vd > 0:
                        nid = max([0]+[x['id'] for x in st.session_state.dividas])+1
                        di_val = di.strip() or None
                        pa = 0
                        if di_val:
                            try:
                                ini = datetime.strptime(di_val,"%Y-%m")
                                h   = datetime.now()
                                pa  = min((h.year-ini.year)*12+(h.month-ini.month), int(pd_))
                                pa  = max(0, pa) # Trava de segurança para não ser negativo
                            except: pass
                        pg = (vd/pd_)*pa
                        st.session_state.dividas.append({"id":nid,"nome":nd,"total":vd,
                            "pago":pg,"parcelas":pd_,"parcPagas":pa,"comprovantes":[],"data_inicio":di_val})
                        salvar(); st.rerun()

        with st.container(border=True):
            card_titulo("✏","Editar / Remover Dívida")
            if st.session_state.dividas:
                sel = st.selectbox("Dívida", [d['id'] for d in st.session_state.dividas],
                    format_func=lambda x: next(f"{d['nome']} ({fmt(d['total'])})" for d in st.session_state.dividas if d['id']==x))
                idx = next(i for i,d in enumerate(st.session_state.dividas) if d['id']==sel)
                cur = st.session_state.dividas[idx]
                with st.form("f_ediv"):
                    nn = st.text_input("Nome", value=cur['nome'])
                    nv = st.number_input("Valor total", min_value=0.0, value=float(cur['total']), step=100.0)
                    np = st.number_input("Parcelas", min_value=1, value=int(cur['parcelas']), step=1)
                    nd_i = st.text_input("Início (AAAA-MM)", value=cur.get('data_inicio','') or '')
                    b1,b2 = st.columns(2)
                    if b1.form_submit_button("💾 Salvar", use_container_width=True):
                        st.session_state.dividas[idx].update({'nome':nn,'total':nv,'parcelas':np,'data_inicio':nd_i.strip() or None})
                        salvar(); st.rerun()
                    if b2.form_submit_button("🗑 Excluir", use_container_width=True):
                        st.session_state.dividas.pop(idx); salvar(); st.rerun()
            else:
                st.caption("Nenhuma dívida cadastrada.")

    with col2:
        for idx, d in enumerate(st.session_state.dividas):
            if 'comprovantes' not in d: st.session_state.dividas[idx]['comprovantes'] = []
            pa  = parc_auto(d)
            pago_v = (d['total']/d['parcelas'])*pa
            rest_v = d['total'] - pago_v
            
            # A nossa correção com a trava de segurança da barra de progresso
            pct = max(0.0, min(1.0, pa/d['parcelas']))

            with st.container(border=True):
                c1,c2 = st.columns([3,1])
                c1.markdown(f"**{d['nome']}**")
                if d.get('data_inicio'):
                    c2.caption("auto ✓")
                else:
                    if c2.button("Pagar parcela", key=f"pay_{idx}"):
                        if d['parcPagas'] < d['parcelas']:
                            st.session_state.dividas[idx]['parcPagas'] += 1
                            st.session_state.dividas[idx]['pago'] += d['total']/d['parcelas']
                            salvar(); st.rerun()

                st.progress(pct, text=f"{pa} / {d['parcelas']} parcelas · {pct*100:.0f}%")
                c3,c4,c5 = st.columns(3)
                c3.metric("Total",   fmt(d['total']))
                c4.metric("Pago",    fmt(pago_v))
                c5.metric("Restante",fmt(rest_v))

                with st.expander("📎 Comprovantes"):
                    arq = st.file_uploader("Anexar", type=['pdf','png','jpg','jpeg'], key=f"up_{idx}")
                    if arq and st.button("Salvar anexo", key=f"sv_{idx}"):
                        b64 = base64.b64encode(arq.read()).decode()
                        st.session_state.dividas[idx]['comprovantes'].append({"nome":arq.name,"tipo":arq.type,"dados":b64})
                        salvar(); st.rerun()
                    for comp in d['comprovantes']:
                        if isinstance(comp, dict):
                            with st.expander(f"👁 {comp['nome']}"):
                                if comp['tipo'].startswith('image'):
                                    st.image(base64.b64decode(comp['dados']))
                                else:
                                    st.download_button(f"⬇ {comp['nome']}", data=base64.b64decode(comp['dados']),
                                        file_name=comp['nome'], mime=comp['tipo'], key=f"dl_{idx}_{comp['nome']}")

# ════════════════════════════════════════════════════════════
#  PÁGINA: DASHBOARD
# ════════════════════════════════════════════════════════════
elif pag == "dashboard":
    cabecalho_pagina("Dashboard Analítico", f"{MESES_E[st.session_state.mesAtivo]} · {ANO_ATUAL}")
    m = st.session_state.mesAtivo

    receita  = rec_total(m)
    gasto    = gas_total(m)
    saldo    = receita - gasto
    reservas = total_reservas()
    div_rest = sum(d['total']-(d['total']/d['parcelas'])*parc_auto(d) for d in st.session_state.dividas)
    patrim   = reservas + saldo - div_rest
    comprm   = (gasto/receita*100) if receita > 0 else 0

    cor = "#22c55e" if comprm <= 70 else "#f59e0b" if comprm <= 90 else "#ef4444"
    msg = "Excelente controle! Menos de 70% comprometido." if comprm <= 70 else "Atenção: gastos elevados." if comprm <= 90 else "Alerta: quase toda a renda comprometida!"

    st.markdown(f"""<div style='background:{cor}12;border:1px solid {cor}30;border-left:3px solid {cor};
        border-radius:10px;padding:14px 18px;margin-bottom:24px;'>
        <strong style='color:{cor}'>{MESES_E[m]} / {ANO_ATUAL}</strong>
        <span style='color:#94a3b8;margin:0 8px'>·</span>
        <span style='color:#94a3b8;font-size:.88rem'>{msg} Comprometimento: <strong style='color:{cor}'>{comprm:.1f}%</strong></span>
    </div>""", unsafe_allow_html=True)

    k1,k2,k3,k4 = st.columns(4)
    k1.metric("Patrimônio Líq.",fmt(patrim))
    k2.metric("Total Reservas", fmt(reservas))
    k3.metric("Dívidas Rest.",  fmt(div_rest))
    k4.metric("Saldo do Mês",   fmt(saldo))

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    r1c1, r1c2 = st.columns(2, gap="large")

    with r1c1:
        with st.container(border=True):
            card_titulo("📈","Evolução Mensal")
            dados_hist = [(i, rec_total(i), gas_total(i)) for i in range(m+1)]
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Receita", x=MESES_C[:m+1],
                y=[r for _,r,_ in dados_hist], marker_color="rgba(34,197,94,0.27)",
                marker_line_color="#22c55e", marker_line_width=1))
            fig.add_trace(go.Bar(name="Gastos", x=MESES_C[:m+1],
                y=[g for _,_,g in dados_hist], marker_color="rgba(239,68,68,0.27)",
                marker_line_color="#ef4444", marker_line_width=1))
            fig.add_trace(go.Scatter(name="Saldo", x=MESES_C[:m+1],
                y=[r-g for _,r,g in dados_hist],
                line=dict(color="#3b82f6", width=2), mode="lines+markers",
                marker=dict(size=6)))
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                barmode="group", height=280,
                margin=dict(l=0,r=0,t=0,b=0),
                legend=dict(font_size=11,font_color="#64748b",bgcolor="rgba(0,0,0,0)",orientation="h",y=-0.15),
                xaxis=dict(showgrid=False,color="#475569",tickfont_size=11),
                yaxis=dict(showgrid=True,gridcolor="rgba(255,255,255,0.05)",color="#475569",tickfont_size=11),
                font_family="Inter",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})

    with r1c2:
        with st.container(border=True):
            card_titulo("🍩","Gastos por Categoria",MESES_E[m])
            gm = [g for g in st.session_state.gastos if g['mes']==m]
            if gm:
                df_c = pd.DataFrame(gm)
                fig2 = go.Figure(go.Pie(
                    labels=df_c['cat'].str.split(' ',n=1).str[-1],
                    values=df_c['valor'], hole=.52,
                    textinfo="percent+label", textfont_size=10,
                    marker=dict(colors=["#3b82f6","#6366f1","#22c55e","#f59e0b","#ef4444","#a78bfa","#ec4899","#14b8a6","#f97316"],
                                line=dict(color="#080c14",width=2))
                ))
                fig2.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",
                    height=280, margin=dict(l=0,r=0,t=0,b=0),
                    showlegend=False, font_family="Inter",
                )
                st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar":False})
            else:
                st.markdown("<p style='color:#334155;text-align:center;padding:60px 0'>Sem gastos neste mês.</p>", unsafe_allow_html=True)

    r2c1, r2c2 = st.columns(2, gap="large")

    with r2c1:
        with st.container(border=True):
            card_titulo("🏦","Composição do Patrimônio")
            dados_inv = st.session_state.get('_dados_inv_cache', [])
            if not dados_inv:
                rf = st.session_state.reservaFaculdade
                if rf['total']>0: dados_inv.append({"Reserva":"📚 Faculdade","Valor":max(0,rf['total']-rf['usado'])})
                for i in st.session_state.investimentos:
                    dados_inv.append({"Reserva":i['nome'],"Valor":inv_valor(i)})
            if dados_inv:
                df_i = pd.DataFrame(dados_inv)
                fig3 = go.Figure(go.Pie(
                    labels=df_i["Reserva"], values=df_i["Valor"], hole=.52,
                    textinfo="percent", textfont_size=11,
                    marker=dict(colors=["#3b82f6","#6366f1","#22c55e","#f59e0b","#a78bfa","#ec4899","#14b8a6"],
                                line=dict(color="#080c14",width=2))
                ))
                fig3.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",
                    height=280, margin=dict(l=0,r=0,t=0,b=0),
                    legend=dict(font_size=11,font_color="#64748b",bgcolor="rgba(0,0,0,0)"),
                    font_family="Inter",
                )
                st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar":False})
            else:
                st.markdown("<p style='color:#334155;text-align:center;padding:60px 0'>Sem reservas.</p>", unsafe_allow_html=True)

    with r2c2:
        with st.container(border=True):
            card_titulo("📋","Progresso de Dívidas")
            if st.session_state.dividas:
                dados_d = []
                for d in st.session_state.dividas:
                    pa   = parc_auto(d)
                    pg_v = (d['total']/d['parcelas'])*pa
                    dados_d.append({"Dívida":d['nome'],"Pago":pg_v,"Restante":d['total']-pg_v})
                df_d = pd.DataFrame(dados_d).melt(id_vars="Dívida",value_vars=["Pago","Restante"],var_name="Status",value_name="Valor")
                fig4 = px.bar(df_d, x="Valor", y="Dívida", color="Status", orientation='h',
                    color_discrete_map={"Pago":"#22c55e","Restante":"#ef4444"})
                fig4.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",
                    height=280, margin=dict(l=0,r=0,t=0,b=0),
                    legend=dict(font_size=11,font_color="#64748b",bgcolor="rgba(0,0,0,0)",orientation="h",y=-0.15),
                    xaxis=dict(showgrid=True,gridcolor="rgba(255,255,255,0.05)",color="#475569",tickfont_size=11),
                    yaxis=dict(showgrid=False,color="#475569",tickfont_size=11),
                    font_family="Inter",
                )
                st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar":False})
            else:
                st.markdown("<p style='color:#334155;text-align:center;padding:60px 0'>Sem dívidas cadastradas.</p>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
#  PÁGINA: ANÁLISE IA
# ════════════════════════════════════════════════════════════
elif pag == "ia":
    cabecalho_pagina("Análise com IA", "O Claude analisa sua situação financeira e gera recomendações personalizadas")
    m = st.session_state.mesAtivo

    receita_ia  = rec_total(m)
    gasto_ia    = gas_total(m)
    saldo_ia    = receita_ia - gasto_ia
    res_ia      = total_reservas()
    div_ia      = sum(d['total']-(d['total']/d['parcelas'])*parc_auto(d) for d in st.session_state.dividas)

    gastos_cat = {}
    for g in st.session_state.gastos:
        if g['mes']==m:
            c = g['cat'].split(' ',1)[-1]
            gastos_cat[c] = gastos_cat.get(c,0) + g['valor']

    hist = []
    for i in range(max(0,m-2), m+1):
        r,g = rec_total(i), gas_total(i)
        if r>0 or g>0:
            hist.append(f"{MESES_C[i]}: Receita {fmt(r)} | Gastos {fmt(g)} | Saldo {fmt(r-g)}")

    div_txt = [f"{d['nome']}: {fmt(d['total']-(d['total']/d['parcelas'])*parc_auto(d))} restantes" for d in st.session_state.dividas]
    inv_txt = [f"{i['nome']} ({i['tipo']}): {fmt(inv_valor(i))}" for i in st.session_state.investimentos]

    prompt = f"""Você é um consultor financeiro pessoal experiente. Analise os dados abaixo e forneça um feedback detalhado, prático e personalizado em português brasileiro.

=== SITUAÇÃO FINANCEIRA — {MESES_E[m].upper()} / {ANO_ATUAL} ===

RECEITAS:
- Salário: {fmt(st.session_state.salario_mes.get(m,0))}
- Vale Alimentação: {fmt(st.session_state.vr_mes.get(m,0))}
- Renda Extra: {fmt(rec_extra(m))}
- TOTAL: {fmt(receita_ia)}

GASTOS POR CATEGORIA:
{chr(10).join(f'- {c}: {fmt(v)} ({v/receita_ia*100:.1f}% da receita)' for c,v in gastos_cat.items()) if gastos_cat else '- Nenhum gasto lançado'}

SALDO: {fmt(saldo_ia)} ({saldo_ia/receita_ia*100 if receita_ia>0 else 0:.1f}% da receita)

RESERVAS/INVESTIMENTOS:
{chr(10).join('- '+r for r in inv_txt) if inv_txt else '- Nenhuma reserva'}
Total: {fmt(res_ia)}

DÍVIDAS:
{chr(10).join('- '+d for d in div_txt) if div_txt else '- Nenhuma dívida'}
Total restante: {fmt(div_ia)}

HISTÓRICO RECENTE:
{chr(10).join('- '+h for h in hist) if hist else '- Apenas o mês atual tem dados'}

=== ESTRUTURE SUA ANÁLISE ASSIM ===
1. **Nota de saúde financeira** (1-10) com justificativa em 1 linha
2. **Pontos positivos** (2-3 itens com bullet •)
3. **Alertas** (2-3 itens com bullet ⚠)
4. **Recomendações para o próximo mês** (3 ações concretas numeradas)
5. **Tendência** (análise do histórico se houver dados)
6. **Mensagem motivadora** (1-2 linhas)

Use os valores reais. Seja direto e específico. Máximo 450 palavras."""

    col_l, col_r = st.columns([1, 2], gap="large")

    with col_l:
        with st.container(border=True):
            card_titulo("📋","Resumo do Mês",MESES_E[m])
            st.metric("Receita",  fmt(receita_ia))
            st.metric("Gastos",   fmt(gasto_ia))
            st.metric("Saldo",    fmt(saldo_ia),
                delta=f"{saldo_ia/receita_ia*100:.1f}%" if receita_ia>0 else None)
            st.metric("Reservas", fmt(res_ia))
            st.metric("Dívidas",  fmt(div_ia))

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            if st.button("🤖  Gerar Análise com IA", type="primary", use_container_width=True):
                if receita_ia == 0 and gasto_ia == 0:
                    st.warning("Adicione receitas e gastos primeiro.")
                else:
                    with st.spinner("Analisando seus dados…"):
                        try:
                            client = anthropic.Anthropic()
                            msg_obj = client.messages.create(
                                model="claude-opus-4-5", max_tokens=1024,
                                messages=[{"role":"user","content":prompt}]
                            )
                            st.session_state.feedback_ia  = msg_obj.content[0].text
                            st.session_state.feedback_mes = m
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro na API: {e}")

    with col_r:
        if st.session_state.feedback_ia and st.session_state.feedback_mes == m:
            with st.container(border=True):
                card_titulo("🤖","Análise do Claude",f"Gerado para {MESES_E[m]}")
                st.markdown(f"""
                <div style='line-height:1.75;color:#cbd5e1;font-size:.9rem;'>
                    {st.session_state.feedback_ia.replace(chr(10),'<br>')}
                </div>""", unsafe_allow_html=True)
        elif st.session_state.feedback_ia:
            st.info(f"Análise do mês **{MESES_E[st.session_state.feedback_mes]}**. Clique em Gerar para atualizar.")
            st.markdown(st.session_state.feedback_ia)
        else:
            st.markdown("""
            <div style='display:flex;flex-direction:column;align-items:center;justify-content:center;
                        padding:80px 40px;border:1px solid rgba(255,255,255,0.07);border-radius:14px;
                        background:rgba(255,255,255,0.02);text-align:center;'>
                <div style='font-size:2.5rem;margin-bottom:16px;opacity:.4'>✦</div>
                <p style='color:#475569;margin:0;font-size:.9rem;max-width:280px;line-height:1.6'>
                    Clique em <strong style='color:#3b82f6'>Gerar Análise com IA</strong> para receber
                    um feedback personalizado sobre suas finanças.
                </p>
            </div>""", unsafe_allow_html=True)
