
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px

DB_PATH = Path("kreo_clienti.db")
LOGO_PATH = Path("assets/logo_kreo.png")
APP_PASSWORD = "kreo2026"

PACCHETTI = {
    "PACCHETTO LUXURY": 500,
    "PACCHETTO GOLD": 750,
    "PACCHETTO VIP": 900,
    "PACCHETTO COACHING IN SEDE": 150,
    "PACCHETTO PERSONALIZZATO": 0,
}
TIPOLOGIE_PAGAMENTO = ["MENSILE", "TRIMESTRALE", "SEMESTRALE", "ANNUALE", "UNICA SOLUZIONE"]
DURATA_MESI = {"MENSILE": 1, "TRIMESTRALE": 3, "SEMESTRALE": 6, "ANNUALE": 12, "UNICA SOLUZIONE": 12}
STATI_CLIENTE = ["ATTIVO", "SOSPESO", "CONCLUSO", "DA CONTATTARE"]
SI_NO = ["SI", "NO"]

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def get_conn():
    return sqlite3.connect(DB_PATH)

def norm(v):
    return "" if v is None else str(v).strip().lower()

def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, days[month - 1]))

def parse_date(value, default=None):
    if not value:
        return default or date.today()
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return default or date.today()

def format_date_it(value):
    if value in [None, ""] or pd.isna(value):
        return ""
    try:
        return pd.to_datetime(value).strftime("%d/%m/%Y")
    except Exception:
        return str(value)

def euro(value):
    try:
        return f"€ {float(value):,.0f}".replace(",", ".")
    except Exception:
        return "€ 0"

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clienti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            cellulare TEXT,
            email TEXT,
            codice_fiscale TEXT,
            pacchetto TEXT,
            tipologia_pagamento TEXT,
            numero_lezioni INTEGER,
            lezioni_utilizzate INTEGER DEFAULT 0,
            importo REAL,
            importo_pagato REAL,
            data_iscrizione TEXT,
            data_inizio_pacchetto TEXT,
            scadenza_abbonamento TEXT,
            certificato_medico TEXT,
            scadenza_certificato TEXT,
            consenso_foto_video TEXT,
            stato_cliente TEXT,
            note TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cronologia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            data_modifica TEXT,
            campo TEXT,
            valore_precedente TEXT,
            valore_nuovo TEXT,
            note TEXT
        )
    """)
    cur.execute("PRAGMA table_info(clienti)")
    existing = [r[1] for r in cur.fetchall()]
    migrations = {
        "lezioni_utilizzate": "ALTER TABLE clienti ADD COLUMN lezioni_utilizzate INTEGER DEFAULT 0",
        "scadenza_abbonamento": "ALTER TABLE clienti ADD COLUMN scadenza_abbonamento TEXT",
        "updated_at": "ALTER TABLE clienti ADD COLUMN updated_at TEXT",
    }
    for col, sql in migrations.items():
        if col not in existing:
            cur.execute(sql)
    conn.commit()
    conn.close()

def insert_history(cliente_id, campo, old, new, note=""):
    old = "" if old is None else str(old)
    new = "" if new is None else str(new)
    if old == new and campo != "CREAZIONE CLIENTE":
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cronologia (cliente_id, data_modifica, campo, valore_precedente, valore_nuovo, note)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (int(cliente_id), now_iso(), campo, old, new, note))
    conn.commit()
    conn.close()

def load_clienti():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clienti ORDER BY id DESC", conn)
    conn.close()
    if df.empty:
        return df
    for col in ["importo", "importo_pagato"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col in ["numero_lezioni", "lezioni_utilizzate"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["residuo"] = (df["importo"] - df["importo_pagato"]).clip(lower=0)
    df["stato_pagamento"] = df["residuo"].apply(lambda x: "PAGATO" if x <= 0 else "DA SALDARE")
    df["lezioni_residue"] = (df["numero_lezioni"] - df["lezioni_utilizzate"]).clip(lower=0)
    for c in ["data_iscrizione", "data_inizio_pacchetto", "scadenza_certificato", "scadenza_abbonamento"]:
        df[c + "_it"] = df[c].apply(format_date_it)
    return df

def get_cliente(cliente_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clienti WHERE id = ?", (int(cliente_id),))
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    conn.close()
    if not row:
        return None
    return dict(zip(cols, row))

def load_history(cliente_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT id, cliente_id, data_modifica, campo, valore_precedente, valore_nuovo, note
        FROM cronologia
        WHERE cliente_id = ?
        ORDER BY id DESC
    """, conn, params=(int(cliente_id),))
    conn.close()
    if not df.empty:
        df["data_modifica"] = df["data_modifica"].apply(lambda x: pd.to_datetime(x).strftime("%d/%m/%Y %H:%M:%S"))
    return df

def duplicate_keys_from_data(d):
    keys = []
    cf = norm(d.get("codice_fiscale"))
    email = norm(d.get("email"))
    cell = norm(d.get("cellulare"))
    nome = norm(d.get("nome"))
    cognome = norm(d.get("cognome"))
    if cf:
        keys.append(("codice_fiscale", cf))
    if email:
        keys.append(("email", email))
    if cell:
        keys.append(("cellulare", cell))
    if nome and cognome:
        keys.append(("nome_cognome", nome + "|" + cognome))
    return keys

def find_existing_clienti_for_data(data, exclude_id=None):
    df = load_clienti()
    if df.empty:
        return pd.DataFrame()
    if exclude_id is not None:
        df = df[df["id"] != int(exclude_id)]
    matches = pd.Series(False, index=df.index)
    cf = norm(data.get("codice_fiscale"))
    email = norm(data.get("email"))
    cell = norm(data.get("cellulare"))
    nome = norm(data.get("nome"))
    cognome = norm(data.get("cognome"))
    if cf:
        matches |= df["codice_fiscale"].fillna("").astype(str).str.strip().str.lower().eq(cf)
    if email:
        matches |= df["email"].fillna("").astype(str).str.strip().str.lower().eq(email)
    if cell:
        matches |= df["cellulare"].fillna("").astype(str).str.strip().str.lower().eq(cell)
    if nome and cognome:
        matches |= (
            df["nome"].fillna("").astype(str).str.strip().str.lower().eq(nome) &
            df["cognome"].fillna("").astype(str).str.strip().str.lower().eq(cognome)
        )
    return df[matches]

def insert_cliente(data):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO clienti (
            nome, cognome, cellulare, email, codice_fiscale, pacchetto,
            tipologia_pagamento, numero_lezioni, lezioni_utilizzate, importo, importo_pagato,
            data_iscrizione, data_inizio_pacchetto, scadenza_abbonamento, certificato_medico,
            scadenza_certificato, consenso_foto_video, stato_cliente, note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, data)
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    insert_history(cid, "CREAZIONE CLIENTE", "", f"{data[0]} {data[1]}", "Cliente inserito")
    return cid

def update_cliente(cliente_id, new_data):
    old = get_cliente(cliente_id)
    if not old:
        return
    fields = ["nome", "cognome", "cellulare", "email", "codice_fiscale", "pacchetto",
              "tipologia_pagamento", "numero_lezioni", "lezioni_utilizzate", "importo", "importo_pagato",
              "data_iscrizione", "data_inizio_pacchetto", "scadenza_abbonamento", "certificato_medico",
              "scadenza_certificato", "consenso_foto_video", "stato_cliente", "note"]
    conn = get_conn()
    cur = conn.cursor()
    set_clause = ", ".join([f"{f}=?" for f in fields] + ["updated_at=?"])
    values = [new_data.get(f) for f in fields] + [now_iso(), int(cliente_id)]
    cur.execute(f"UPDATE clienti SET {set_clause} WHERE id=?", values)
    conn.commit()
    conn.close()
    for f in fields:
        insert_history(cliente_id, f, old.get(f), new_data.get(f))

def delete_cliente(cliente_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM clienti WHERE id=?", (int(cliente_id),))
    conn.commit()
    conn.close()

def incrementa_lezioni(cliente_id, incremento=1):
    old = get_cliente(cliente_id)
    if not old:
        return
    old_val = int(old.get("lezioni_utilizzate") or 0)
    tot = int(old.get("numero_lezioni") or 0)
    new_val = min(old_val + incremento, tot) if tot > 0 else old_val + incremento
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE clienti SET lezioni_utilizzate=?, updated_at=? WHERE id=?", (new_val, now_iso(), int(cliente_id)))
    conn.commit()
    conn.close()
    insert_history(cliente_id, "lezioni_utilizzate", old_val, new_val, "Aggiornamento rapido lezioni")

def duplicate_group_key(row):
    cf = norm(row.get("codice_fiscale"))
    email = norm(row.get("email"))
    cell = norm(row.get("cellulare"))
    nome = norm(row.get("nome"))
    cognome = norm(row.get("cognome"))
    if cf:
        return "CF|" + cf
    if email:
        return "EMAIL|" + email
    if cell:
        return "CELL|" + cell
    return "NOME|" + nome + "|" + cognome

def find_duplicates(df):
    if df.empty:
        return df
    tmp = df.copy()
    tmp["dup_key"] = tmp.apply(duplicate_group_key, axis=1)
    dup_keys = tmp["dup_key"].value_counts()
    duplicated_keys = dup_keys[dup_keys > 1].index.tolist()
    return tmp[tmp["dup_key"].isin(duplicated_keys)].sort_values(["dup_key", "id"], ascending=[True, False])

def elimina_duplicati_tieni_ultimo():
    df = load_clienti()
    if df.empty:
        return 0
    tmp = df.copy()
    tmp["dup_key"] = tmp.apply(duplicate_group_key, axis=1)
    ids_to_delete = []
    for _, group in tmp.groupby("dup_key"):
        if len(group) > 1:
            keep_id = int(group["id"].max())
            ids_to_delete += [int(x) for x in group["id"].tolist() if int(x) != keep_id]
    conn = get_conn()
    cur = conn.cursor()
    for cid in ids_to_delete:
        cur.execute("DELETE FROM clienti WHERE id=?", (cid,))
        cur.execute("DELETE FROM cronologia WHERE cliente_id=?", (cid,))
    conn.commit()
    conn.close()
    return len(ids_to_delete)

def style():
    st.markdown("""
    <style>
        .stApp { background: linear-gradient(135deg, #f7f4ec 0%, #ffffff 45%, #f3ead8 100%); color:#111; }
        .block-container { padding-top: 1.4rem; max-width: 1280px; }
        h1,h2,h3 { color:#111!important; font-weight:800!important; }
        p,label,span,div { color:#111!important; }
        [data-testid="stSidebar"] { background:#111; }
        [data-testid="stSidebar"] * { color:#f7f1df!important; }
        div[data-testid="metric-container"] { background:#fff; border:1px solid rgba(181,139,47,.45); padding:18px; border-radius:18px; box-shadow:0 8px 25px rgba(0,0,0,.08); }
        input, textarea { background-color:#fff!important; color:#111!important; border:1px solid #c9b16a!important; border-radius:10px!important; }
        .stSelectbox div[data-baseweb="select"] > div, .stMultiSelect div[data-baseweb="select"] > div { background-color:#fff!important; color:#111!important; border-color:#c9b16a!important; border-radius:10px!important; }
        button { border-radius:12px!important; font-weight:700!important; }
        .alert-red { background:#fff0f0; border:1px solid #cc3333; padding:14px; border-radius:14px; margin-bottom:10px; }
        .alert-gold { background:#fff8df; border:1px solid #c9a227; padding:14px; border-radius:14px; margin-bottom:10px; }
        .alert-green { background:#eefaf0; border:1px solid #2d9b4b; padding:14px; border-radius:14px; margin-bottom:10px; }
    </style>
    """, unsafe_allow_html=True)

def show_logo():
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=260)
    else:
        st.markdown("## KREO Your Place")

def login_gate():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if st.session_state.logged_in:
        return True
    st.title("Accesso gestionale KREO")
    pw = st.text_input("Password", type="password")
    if st.button("Entra"):
        if pw == APP_PASSWORD:
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Password errata.")
    return False

def get_cliente_alerts(cliente):
    alerts = {}
    today = date.today()
    five = today + timedelta(days=5)
    thirty = today + timedelta(days=30)
    residuo = max(float(cliente.get("importo") or 0) - float(cliente.get("importo_pagato") or 0), 0)
    if residuo > 0:
        alerts["IMPORTO_NON_SALDATO"] = ("ALTA", f"Importo non saldato: residuo {euro(residuo)}.")
    cert = parse_date(cliente.get("scadenza_certificato"))
    if cliente.get("certificato_medico") != "SI":
        alerts["CERTIFICATO_MANCANTE"] = ("ALTA", "Certificato medico mancante/non consegnato.")
    elif cert < today:
        alerts["CERTIFICATO_SCADUTO"] = ("ALTA", f"Certificato medico scaduto il {format_date_it(cert)}.")
    elif cert <= five:
        alerts["CERTIFICATO_5_GG"] = ("ALTA", f"Certificato medico in scadenza entro 5 giorni: {format_date_it(cert)}.")
    elif cert <= thirty:
        alerts["CERTIFICATO_30_GG"] = ("MEDIA", f"Certificato medico in scadenza entro 30 giorni: {format_date_it(cert)}.")
    abb = parse_date(cliente.get("scadenza_abbonamento"))
    if abb < today:
        alerts["ABBONAMENTO_SCADUTO"] = ("ALTA", f"Abbonamento/prossima rata scaduto il {format_date_it(abb)}.")
    elif abb <= five:
        alerts["ABBONAMENTO_5_GG"] = ("ALTA", f"Abbonamento/prossima rata in scadenza entro 5 giorni: {format_date_it(abb)}.")
    elif abb <= thirty:
        alerts["ABBONAMENTO_30_GG"] = ("MEDIA", f"Abbonamento/prossima rata in scadenza entro 30 giorni: {format_date_it(abb)}.")
    if residuo > 0 and abb <= five:
        alerts["RATA_DA_INCASSARE_5_GG"] = ("ALTA", f"Rata/importo da incassare entro la scadenza periodo: {euro(residuo)}.")
    lezioni_tot = int(cliente.get("numero_lezioni") or 0)
    lezioni_usate = int(cliente.get("lezioni_utilizzate") or 0)
    if lezioni_tot > 0 and lezioni_usate >= lezioni_tot:
        alerts["LEZIONI_TERMINATE"] = ("MEDIA", f"Lezioni terminate: {lezioni_usate}/{lezioni_tot} utilizzate.")
    return alerts

def render_alerts(alerts):
    if not alerts:
        st.markdown("<div class='alert-green'><b>Nessun alert critico.</b></div>", unsafe_allow_html=True)
        return
    for _, (priorita, msg) in alerts.items():
        cls = "alert-red" if priorita == "ALTA" else "alert-gold"
        icon = "🚨" if priorita == "ALTA" else "⚠️"
        st.markdown(f"<div class='{cls}'>{icon} <b>{msg}</b></div>", unsafe_allow_html=True)

def build_alert_dashboard(df):
    rows, seen = [], set()
    for _, r in df.iterrows():
        for key, (priorita, msg) in get_cliente_alerts(r.to_dict()).items():
            uniq = (int(r["id"]), key)
            if uniq in seen:
                continue
            seen.add(uniq)
            rows.append({
                "Priorità": priorita, "ID": int(r["id"]),
                "Cliente": f"{r.get('nome','')} {r.get('cognome','')}",
                "Cellulare": r.get("cellulare", ""), "Pacchetto": r.get("pacchetto", ""),
                "Alert": msg, "Scadenza abbonamento": r.get("scadenza_abbonamento_it", ""),
                "Scadenza certificato": r.get("scadenza_certificato_it", ""), "Residuo": euro(r.get("residuo", 0)),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["sort"] = out["Priorità"].map({"ALTA": 0, "MEDIA": 1})
        out = out.sort_values(["sort", "Cliente"]).drop(columns=["sort"])
    return out

def cliente_form(prefix, defaults=None, unique_suffix=""):
    defaults = defaults or {}
    k = lambda name: f"{prefix}_{unique_suffix}_{name}"
    st.subheader("Dati anagrafici")
    c1, c2 = st.columns(2)
    with c1:
        nome = st.text_input("Nome *", value=defaults.get("nome", ""), key=k("nome"))
        cognome = st.text_input("Cognome *", value=defaults.get("cognome", ""), key=k("cognome"))
        cellulare = st.text_input("Cellulare", value=defaults.get("cellulare", ""), key=k("cellulare"))
    with c2:
        email = st.text_input("Email", value=defaults.get("email", ""), key=k("email"))
        codice_fiscale = st.text_input("Codice fiscale", value=defaults.get("codice_fiscale", ""), key=k("cf"))
    st.subheader("Pacchetto e pagamento")
    c3, c4 = st.columns(2)
    with c3:
        pac_def = defaults.get("pacchetto", "PACCHETTO LUXURY")
        pacchetto = st.selectbox("Pacchetto", list(PACCHETTI.keys()), index=list(PACCHETTI.keys()).index(pac_def) if pac_def in PACCHETTI else 0, key=k("pacchetto"))
        tip_def = defaults.get("tipologia_pagamento", "MENSILE")
        tipologia = st.selectbox("Tipologia pagamento", TIPOLOGIE_PAGAMENTO, index=TIPOLOGIE_PAGAMENTO.index(tip_def) if tip_def in TIPOLOGIE_PAGAMENTO else 0, key=k("tipologia"))
        numero_lezioni = st.number_input("Numero lezioni totali", min_value=0, step=1, value=int(defaults.get("numero_lezioni") or 0), key=k("num_lez"))
        lezioni_utilizzate = st.number_input("Lezioni già utilizzate", min_value=0, step=1, value=int(defaults.get("lezioni_utilizzate") or 0), key=k("lez_usate"))
    with c4:
        default_importo = float(defaults.get("importo") if defaults.get("importo") not in [None, ""] else PACCHETTI[pacchetto])
        if prefix == "new" and pacchetto != "PACCHETTO PERSONALIZZATO":
            default_importo = float(PACCHETTI[pacchetto])
        importo = st.number_input("Importo contratto / periodo (€)", min_value=0.0, step=10.0, value=default_importo, key=k("importo"))
        importo_pagato = st.number_input("Importo pagato (€)", min_value=0.0, step=10.0, value=float(defaults.get("importo_pagato") or 0), key=k("pagato"))
        st.success(f"Residuo aggiornato: {euro(max(importo - importo_pagato, 0))}")
        st.info(f"Lezioni residue: {max(int(numero_lezioni) - int(lezioni_utilizzate), 0)}")
    st.subheader("Date e documenti")
    data_iscr_default = parse_date(defaults.get("data_iscrizione"), date.today())
    data_inizio_default = parse_date(defaults.get("data_inizio_pacchetto"), date.today())
    c5, c6, c7 = st.columns(3)
    with c5:
        data_iscrizione = st.date_input("Data iscrizione", value=data_iscr_default, format="DD/MM/YYYY", key=k("data_iscr"))
        data_inizio = st.date_input("Data inizio pacchetto", value=data_inizio_default, format="DD/MM/YYYY", key=k("data_inizio"))
    with c6:
        cert_def = defaults.get("certificato_medico", "NO")
        certificato = st.selectbox("Certificato medico consegnato", SI_NO, index=SI_NO.index(cert_def) if cert_def in SI_NO else 1, key=k("cert"))
        scadenza_certificato = st.date_input("Scadenza certificato", value=parse_date(defaults.get("scadenza_certificato"), date.today()+timedelta(days=365)), format="DD/MM/YYYY", key=k("scad_cert"))
    with c7:
        cons_def = defaults.get("consenso_foto_video", "NO")
        consenso = st.selectbox("Consenso foto/video", SI_NO, index=SI_NO.index(cons_def) if cons_def in SI_NO else 1, key=k("consenso"))
        stato_def = defaults.get("stato_cliente", "ATTIVO")
        stato = st.selectbox("Stato cliente", STATI_CLIENTE, index=STATI_CLIENTE.index(stato_def) if stato_def in STATI_CLIENTE else 0, key=k("stato"))
    scadenza_auto = add_months(data_iscrizione, DURATA_MESI.get(tipologia, 1))
    scadenza_abbonamento = st.date_input("Scadenza abbonamento / prossima rata", value=parse_date(defaults.get("scadenza_abbonamento"), scadenza_auto) if prefix != "new" else scadenza_auto, format="DD/MM/YYYY", key=k("scad_abb"))
    note = st.text_area("Note", value=defaults.get("note", ""), key=k("note"))
    return {
        "nome": nome.strip(), "cognome": cognome.strip(), "cellulare": cellulare.strip(), "email": email.strip(), "codice_fiscale": codice_fiscale.strip(),
        "pacchetto": pacchetto, "tipologia_pagamento": tipologia, "numero_lezioni": int(numero_lezioni), "lezioni_utilizzate": int(lezioni_utilizzate),
        "importo": float(importo), "importo_pagato": float(importo_pagato), "data_iscrizione": str(data_iscrizione), "data_inizio_pacchetto": str(data_inizio),
        "scadenza_abbonamento": str(scadenza_abbonamento), "certificato_medico": certificato, "scadenza_certificato": str(scadenza_certificato),
        "consenso_foto_video": consenso, "stato_cliente": stato, "note": note.strip()
    }

def main():
    st.set_page_config(page_title="KREO Gestionale Clienti", page_icon="✨", layout="wide")
    init_db(); style()
    if not login_gate(): return
    col_logo, col_title = st.columns([1, 3])
    with col_logo: show_logo()
    with col_title:
        st.title("Gestionale Clienti")
        st.caption("Iscrizioni, pagamenti, lezioni, scadenze, alert e cronologia")
    menu = st.sidebar.radio("Navigazione", ["➕ Nuovo cliente", "✏️ Modifica cliente", "🚨 Alert clienti", "📋 Database clienti", "📊 Dashboard", "🧹 Pulizia duplicati", "🕘 Cronologia", "⬇️ Export Excel"])
    df = load_clienti()
    if menu == "➕ Nuovo cliente":
        st.header("Nuova iscrizione cliente")
        with st.form("nuovo_cliente"):
            data = cliente_form("new", unique_suffix="form")
            allow_duplicate = st.checkbox("Consenti duplicato intenzionale", value=False)
            if st.form_submit_button("Salva cliente"):
                if not data["nome"] or not data["cognome"]:
                    st.error("Nome e cognome sono obbligatori.")
                else:
                    existing = find_existing_clienti_for_data(data)
                    if not existing.empty and not allow_duplicate:
                        st.error("Cliente già presente. Non creo un duplicato. Vai in 'Modifica cliente' per aggiornarlo.")
                        st.dataframe(existing[["id","nome","cognome","cellulare","email","codice_fiscale","pacchetto","created_at"]], use_container_width=True, hide_index=True)
                    else:
                        cid = insert_cliente((data["nome"], data["cognome"], data["cellulare"], data["email"], data["codice_fiscale"], data["pacchetto"], data["tipologia_pagamento"], data["numero_lezioni"], data["lezioni_utilizzate"], data["importo"], data["importo_pagato"], data["data_iscrizione"], data["data_inizio_pacchetto"], data["scadenza_abbonamento"], data["certificato_medico"], data["scadenza_certificato"], data["consenso_foto_video"], data["stato_cliente"], data["note"], now_iso(), now_iso()))
                        st.success(f"Cliente salvato correttamente. ID: {cid}")
    elif menu == "✏️ Modifica cliente":
        st.header("Modifica cliente / aggiorna lezioni")
        if df.empty: st.info("Nessun cliente inserito.")
        else:
            df_sorted = df.sort_values("id", ascending=True).copy()
            labels = (df_sorted["id"].astype(str) + " - " + df_sorted["nome"] + " " + df_sorted["cognome"]).tolist()
            selected = st.selectbox("Seleziona cliente", labels, key="selected_cliente_label")
            cliente_id = int(selected.split(" - ")[0])
            cliente = get_cliente(cliente_id)
            st.subheader(f"Cliente selezionato: ID {cliente_id} - {cliente.get('nome')} {cliente.get('cognome')}")
            st.subheader("Alert cliente")
            render_alerts(get_cliente_alerts(cliente))
            st.markdown("### Aggiornamento rapido lezioni")
            c1,c2,c3 = st.columns(3)
            c1.metric("Lezioni totali", int(cliente.get("numero_lezioni") or 0))
            c2.metric("Lezioni usate", int(cliente.get("lezioni_utilizzate") or 0))
            c3.metric("Lezioni residue", max(int(cliente.get("numero_lezioni") or 0)-int(cliente.get("lezioni_utilizzate") or 0), 0))
            if st.button("Aggiungi 1 lezione utilizzata", key=f"add_lesson_{cliente_id}"):
                incrementa_lezioni(cliente_id, 1); st.success("Lezione aggiornata."); st.rerun()
            st.markdown("---")
            with st.form(f"modifica_cliente_{cliente_id}"):
                data = cliente_form("edit", cliente, unique_suffix=str(cliente_id))
                if st.form_submit_button("Salva modifiche"):
                    existing = find_existing_clienti_for_data(data, exclude_id=cliente_id)
                    if not existing.empty:
                        st.error("Attenzione: i dati coincidono con un altro cliente già presente. Modifica bloccata per evitare duplicati.")
                        st.dataframe(existing[["id","nome","cognome","cellulare","email","codice_fiscale"]], use_container_width=True, hide_index=True)
                    else:
                        update_cliente(cliente_id, data); st.success("Cliente aggiornato correttamente."); st.rerun()
    elif menu == "🚨 Alert clienti":
        st.header("Alert clienti")
        if df.empty: st.info("Nessun cliente inserito.")
        else:
            alert_df = build_alert_dashboard(df)
            if alert_df.empty: st.success("Nessun alert presente.")
            else:
                c1,c2,c3 = st.columns(3)
                c1.metric("Alert totali", len(alert_df))
                c2.metric("Priorità alta", int((alert_df["Priorità"]=="ALTA").sum()))
                c3.metric("Priorità media", int((alert_df["Priorità"]=="MEDIA").sum()))
                priorita = st.multiselect("Filtra priorità", ["ALTA","MEDIA"], default=["ALTA","MEDIA"])
                st.dataframe(alert_df[alert_df["Priorità"].isin(priorita)], use_container_width=True, hide_index=True)
    elif menu == "📋 Database clienti":
        st.header("Database clienti")
        if df.empty: st.info("Nessun cliente inserito.")
        else:
            cols = ["id","nome","cognome","cellulare","email","pacchetto","tipologia_pagamento","numero_lezioni","lezioni_utilizzate","lezioni_residue","importo","importo_pagato","residuo","stato_pagamento","data_iscrizione_it","scadenza_abbonamento_it","certificato_medico","scadenza_certificato_it","consenso_foto_video","stato_cliente","note"]
            st.dataframe(df[[c for c in cols if c in df.columns]], use_container_width=True, hide_index=True)
            with st.expander("Elimina cliente"):
                cliente_id = st.number_input("ID cliente da eliminare", min_value=1, step=1)
                if st.button("Elimina definitivamente"):
                    delete_cliente(cliente_id); st.warning("Cliente eliminato."); st.rerun()
    elif menu == "📊 Dashboard":
        st.header("Dashboard")
        if df.empty: st.info("Inserisci almeno un cliente.")
        else:
            alert_df = build_alert_dashboard(df)
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Clienti attivi", int((df["stato_cliente"]=="ATTIVO").sum()))
            c2.metric("Valore contratti", euro(df["importo"].sum()))
            c3.metric("Incassato", euro(df["importo_pagato"].sum()))
            c4.metric("Residuo", euro(df["residuo"].sum()))
            c5.metric("Alert", len(alert_df))
            if not alert_df.empty: st.subheader("Alert principali"); st.dataframe(alert_df, use_container_width=True, hide_index=True)
            c6,c7=st.columns(2)
            with c6:
                pac=df.groupby("pacchetto",as_index=False)["id"].count().rename(columns={"id":"clienti"})
                st.plotly_chart(px.bar(pac,x="pacchetto",y="clienti",title="Clienti per pacchetto"),use_container_width=True)
            with c7:
                pag=df.groupby("stato_pagamento",as_index=False)["residuo"].sum()
                st.plotly_chart(px.pie(pag,names="stato_pagamento",values="residuo",title="Residui per stato pagamento"),use_container_width=True)
    elif menu == "🧹 Pulizia duplicati":
        st.header("Pulizia clienti duplicati")
        if df.empty: st.info("Nessun cliente inserito.")
        else:
            dups=find_duplicates(df)
            if dups.empty: st.success("Nessun duplicato rilevato.")
            else:
                st.warning("Duplicati rilevati. La logica usa prima Codice Fiscale, poi Email, poi Cellulare, poi Nome+Cognome.")
                st.dataframe(dups[["id","nome","cognome","cellulare","email","codice_fiscale","pacchetto","created_at","updated_at"]], use_container_width=True, hide_index=True)
                if st.button("Elimina duplicati tenendo solo l'ultimo ID"):
                    n=elimina_duplicati_tieni_ultimo(); st.success(f"Eliminati {n} duplicati."); st.rerun()
    elif menu == "🕘 Cronologia":
        st.header("Cronologia modifiche per cliente")
        if df.empty: st.info("Nessun cliente inserito.")
        else:
            df_sorted=df.sort_values("id",ascending=True).copy()
            labels=(df_sorted["id"].astype(str)+" - "+df_sorted["nome"]+" "+df_sorted["cognome"]).tolist()
            selected=st.selectbox("Seleziona cliente", labels, key="history_client")
            cliente_id=int(selected.split(" - ")[0])
            hist=load_history(cliente_id)
            if hist.empty: st.info("Nessuna modifica registrata.")
            else: st.dataframe(hist, use_container_width=True, hide_index=True)
    elif menu == "⬇️ Export Excel":
        st.header("Export Excel")
        if df.empty: st.info("Nessun dato da esportare.")
        else:
            export_path="export_kreo_clienti.xlsx"
            df.to_excel(export_path,index=False)
            with open(export_path,"rb") as f:
                st.download_button("Scarica database clienti in Excel", data=f, file_name="export_kreo_clienti.xlsx")

if __name__ == "__main__":
    main()
