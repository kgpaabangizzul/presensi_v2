from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os, math, json, io, re, random, string, smtplib, ssl, urllib.request as _urllib_req
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from collections import OrderedDict
import psycopg2
import psycopg2.extras
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm
from lupa_password import lupa_pw_bp, init_reset_table

app = Flask(__name__)
app.register_blueprint(lupa_pw_bp)
app.secret_key = 'absensi-secret-key-2024'

@app.before_request
def load_global_settings():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM settings WHERE id=1")
        row = cur.fetchone()
        g.settings = dict(row) if row else {}
        cur.close(); conn.close()
    except Exception:
        g.settings = {}
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'photos')
app.config['DOSIR_FOLDER']  = os.path.join('static', 'uploads', 'dosir')
app.config['SURAT_FOLDER']  = os.path.join('static', 'uploads', 'surat')
app.config['TTD_FOLDER']    = os.path.join('static', 'uploads', 'ttd')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_LAMPIRAN   = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
ALLOWED_DOSIR      = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

# ── PostgreSQL config ─────────────────────────────────────────────────────────
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'presensi')
DB_USER = os.environ.get('DB_USER', 'presensi')
DB_PASS = os.environ.get('DB_PASS', 'presensi123')

def get_db():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )
    conn.autocommit = False
    return conn

def fetchone(cur):
    row = cur.fetchone()
    return dict(row) if row else None

def fetchall(cur):
    return [dict(r) for r in cur.fetchall()]

# ══════════════════════════════════════════════════════════════════════════════
# ██  AUDIT LOG SYSTEM  ████████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════════════

AKSI_LABELS = {
    'LOGIN'         : ('🔐', 'Login'),
    'LOGOUT'        : ('🚪', 'Logout'),
    'LOGIN_GAGAL'   : ('❌', 'Login Gagal'),
    'REGISTER'      : ('📝', 'Registrasi'),
    'CREATE'        : ('➕', 'Tambah Data'),
    'UPDATE'        : ('✏️',  'Ubah Data'),
    'DELETE'        : ('🗑️',  'Hapus Data'),
    'APPROVE'       : ('✅', 'Setujui'),
    'REJECT'        : ('🚫', 'Tolak'),
    'ABSEN_MASUK'   : ('🟢', 'Absen Masuk'),
    'ABSEN_KELUAR'  : ('🔴', 'Absen Keluar'),
    'EXPORT'        : ('📥', 'Export Data'),
    'UPLOAD'        : ('📤', 'Upload File'),
    'SETTING'       : ('⚙️',  'Ubah Pengaturan'),
    'VIEW'          : ('👁️',  'Lihat Data'),
    'PASSWORD'      : ('🔑', 'Ubah Password'),
    'VALIDASI'      : ('🪪', 'Validasi Akun'),
    'LUPA_ABSEN'    : ('⏱️',  'Lupa Absen'),
    'NOTA_DINAS'    : ('📄', 'Nota Dinas'),
    'SURAT'         : ('📃', 'Surat Perintah'),
    'IZIN'          : ('📋', 'Izin'),
    'OTP_KIRIM'     : ('📨', 'Kirim OTP'),
    'OTP_VERIF'     : ('🔏', 'Verifikasi OTP'),
    'RESET_PW'      : ('🔑', 'Reset Password'),
}

MODUL_LABELS = {
    'auth'          : 'Autentikasi',
    'absensi'       : 'Absensi',
    'izin'          : 'Perizinan',
    'pegawai'       : 'Data Pegawai',
    'departemen'    : 'Departemen',
    'shift'         : 'Shift',
    'settings'      : 'Pengaturan Sistem',
    'laporan'       : 'Laporan',
    'nota_dinas'    : 'Nota Dinas',
    'surat'         : 'Surat Perintah',
    'dosir'         : 'E-Dosir',
    'profil'        : 'Profil',
    'role'          : 'Manajemen Role',
    'permission'    : 'Hak Akses',
    'notifikasi'    : 'Notifikasi',
    'approval'      : 'Approval',
    'sistem'        : 'Sistem',
}


def _init_audit_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          BIGSERIAL PRIMARY KEY,
            waktu       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id     INTEGER,
            user_nama   TEXT,
            user_role   TEXT,
            aksi        TEXT NOT NULL,
            modul       TEXT NOT NULL,
            deskripsi   TEXT,
            data_lama   JSONB,
            data_baru   JSONB,
            ref_id      INTEGER,
            ref_table   TEXT,
            ip_address  TEXT,
            user_agent  TEXT,
            status      TEXT DEFAULT 'success',
            pesan_error TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_waktu ON audit_log(waktu DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_user  ON audit_log(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_modul ON audit_log(modul)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_aksi  ON audit_log(aksi)")


def log_audit(conn, aksi, modul, deskripsi=None,
              data_lama=None, data_baru=None,
              ref_id=None, ref_table=None,
              status='success', pesan_error=None,
              user_id=None, user_nama=None, user_role=None):
    """Catat satu baris audit log. Aman dipanggil dari mana saja."""
    try:
        if user_id   is None: user_id   = session.get('user_id')
        if user_nama is None: user_nama = session.get('nama', 'System')
        if user_role is None: user_role = session.get('role', '-')
        try:
            ip = request.headers.get('X-Forwarded-For', request.remote_addr) or '-'
            ua = (request.user_agent.string or '-')[:300]
        except RuntimeError:
            ip, ua = 'system', 'system'

        def _sanitize(d):
            if not isinstance(d, dict): return d
            skip = {'password', 'password_hash', 'token', 'secret', 'otp_code'}
            return {k: '***' if k in skip else v for k, v in d.items()}

        dl = json.dumps(_sanitize(data_lama), default=str) if data_lama else None
        db_ = json.dumps(_sanitize(data_baru), default=str) if data_baru else None

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_log
              (user_id,user_nama,user_role,aksi,modul,deskripsi,
               data_lama,data_baru,ref_id,ref_table,
               ip_address,user_agent,status,pesan_error)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (user_id, user_nama, user_role,
              aksi, modul, deskripsi,
              dl, db_, ref_id, ref_table,
              ip, ua, status, pesan_error))
        conn.commit()
        cur.close()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass


def log_error(conn, aksi, modul, pesan_error, deskripsi=None, ref_id=None):
    log_audit(conn, aksi, modul, deskripsi=deskripsi,
              ref_id=ref_id, status='error', pesan_error=str(pesan_error))


# ══════════════════════════════════════════════════════════════════════════════
# ██  LUPA PASSWORD — OTP via Email & WhatsApp  ████████████████████████████████
# ══════════════════════════════════════════════════════════════════════════════

# ── Konfigurasi Notifikasi ────────────────────────────────────────────────────
def _get_notif_config(conn=None):
    cfg = {
        'smtp_host'      : os.environ.get('SMTP_HOST', ''),
        'smtp_port'      : int(os.environ.get('SMTP_PORT', 587)),
        'smtp_user'      : os.environ.get('SMTP_USER', ''),
        'smtp_pass'      : os.environ.get('SMTP_PASS', ''),
        'smtp_from_name' : os.environ.get('SMTP_FROM_NAME', 'Presensi Digital'),
        'smtp_tls'       : os.environ.get('SMTP_TLS', 'true').lower() == 'true',
        'fonnte_token'   : os.environ.get('FONNTE_TOKEN', ''),
        'fonnte_url'     : 'https://api.fonnte.com/send',
        'otp_expire'     : int(os.environ.get('OTP_EXPIRE_MENIT', 10)),
        'otp_length'     : int(os.environ.get('OTP_LENGTH', 6)),
        'nama_perusahaan': 'Presensi Digital',
    }
    try:
        _conn = conn or get_db()
        cur2 = _conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute("SELECT * FROM settings WHERE id=1")
        row = cur2.fetchone()
        if row:
            cfg['nama_perusahaan'] = row.get('nama_perusahaan', cfg['nama_perusahaan'])
            for k in ['smtp_host','smtp_port','smtp_user','smtp_pass',
                      'smtp_from_name','fonnte_token']:
                if row.get(k): cfg[k] = row[k]
        cur2.close()
        if not conn: _conn.close()
    except Exception: pass
    return cfg


def _init_reset_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_otp (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            otp_code   TEXT NOT NULL,
            metode     TEXT NOT NULL DEFAULT 'email',
            tujuan     TEXT NOT NULL,
            kadaluarsa TIMESTAMP NOT NULL,
            digunakan  BOOLEAN DEFAULT FALSE,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_user ON password_reset_otp(user_id,digunakan)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_otp_kode ON password_reset_otp(otp_code,digunakan)")
    for kolom, tipe in [
        ('smtp_host',      "TEXT DEFAULT ''"),
        ('smtp_port',      "INTEGER DEFAULT 587"),
        ('smtp_user',      "TEXT DEFAULT ''"),
        ('smtp_pass',      "TEXT DEFAULT ''"),
        ('smtp_from_name', "TEXT DEFAULT 'Presensi Digital'"),
        ('smtp_tls',       "BOOLEAN DEFAULT TRUE"),
        ('fonnte_token',   "TEXT DEFAULT ''"),
    ]:
        try: cur.execute(f"ALTER TABLE settings ADD COLUMN IF NOT EXISTS {kolom} {tipe}")
        except Exception: pass


def _generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))


def _simpan_otp(conn, user_id, otp_code, metode, tujuan, expire_menit=10):
    cur = conn.cursor()
    cur.execute("UPDATE password_reset_otp SET digunakan=TRUE WHERE user_id=%s AND digunakan=FALSE", (user_id,))
    kadaluarsa = datetime.now() + timedelta(minutes=expire_menit)
    try: ip = request.remote_addr
    except RuntimeError: ip = 'system'
    cur.execute("""INSERT INTO password_reset_otp (user_id,otp_code,metode,tujuan,kadaluarsa,ip_address)
        VALUES (%s,%s,%s,%s,%s,%s)""", (user_id, otp_code, metode, tujuan, kadaluarsa, ip))
    conn.commit(); cur.close()


def _verifikasi_otp(conn, user_id, otp_input):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT * FROM password_reset_otp
        WHERE user_id=%s AND otp_code=%s AND digunakan=FALSE AND kadaluarsa>NOW()
        ORDER BY created_at DESC LIMIT 1""", (user_id, otp_input.strip()))
    row = cur.fetchone(); cur.close()
    return dict(row) if row else None


def _tandai_otp_digunakan(conn, otp_id):
    cur = conn.cursor()
    cur.execute("UPDATE password_reset_otp SET digunakan=TRUE WHERE id=%s", (otp_id,))
    conn.commit(); cur.close()


def _kirim_email_otp(cfg, tujuan_email, nama_user, otp_code):
    if not cfg['smtp_host'] or not cfg['smtp_user']:
        return False, "Konfigurasi SMTP belum diisi. Hubungi administrator."
    subject = f"[{cfg['nama_perusahaan']}] Kode OTP Reset Password"
    expire  = cfg['otp_expire']
    html_body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f8fafc;margin:0;padding:20px">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;
              box-shadow:0 2px 12px rgba(0,0,0,.08);overflow:hidden">
    <div style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 32px">
      <h2 style="color:#fff;margin:0;font-size:20px">🔐 Reset Password</h2>
      <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:13px">{cfg['nama_perusahaan']}</p>
    </div>
    <div style="padding:32px">
      <p style="color:#1e293b;margin:0 0 16px">Halo <strong>{nama_user}</strong>,</p>
      <p style="color:#475569;font-size:14px;margin:0 0 24px">
        Kami menerima permintaan reset password. Gunakan kode OTP berikut:
      </p>
      <div style="background:#f1f5f9;border:2px dashed #cbd5e1;border-radius:10px;
                  padding:20px;text-align:center;margin:0 0 24px">
        <div style="font-size:38px;font-weight:700;letter-spacing:10px;
                    color:#2563eb;font-family:monospace">{otp_code}</div>
        <div style="color:#94a3b8;font-size:12px;margin-top:8px">
          ⏱ Berlaku selama <strong>{expire} menit</strong>
        </div>
      </div>
      <div style="background:#fef9c3;border-left:4px solid #eab308;
                  padding:12px 16px;border-radius:0 8px 8px 0;margin:0 0 24px">
        <p style="margin:0;font-size:13px;color:#713f12">
          ⚠️ <strong>Jangan bagikan kode ini</strong> kepada siapapun.
          Jika tidak merasa meminta reset, abaikan email ini.
        </p>
      </div>
    </div>
  </div>
</body></html>"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"{cfg['smtp_from_name']} <{cfg['smtp_user']}>"
        msg['To']      = tujuan_email
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        port = int(cfg['smtp_port'])
        if cfg['smtp_tls']:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg['smtp_host'], port, timeout=15) as srv:
                srv.ehlo(); srv.starttls(context=ctx)
                srv.login(cfg['smtp_user'], cfg['smtp_pass'])
                srv.sendmail(cfg['smtp_user'], tujuan_email, msg.as_string())
        else:
            with smtplib.SMTP_SSL(cfg['smtp_host'], port, timeout=15) as srv:
                srv.login(cfg['smtp_user'], cfg['smtp_pass'])
                srv.sendmail(cfg['smtp_user'], tujuan_email, msg.as_string())
        return True, ''
    except smtplib.SMTPAuthenticationError:
        return False, "Autentikasi SMTP gagal. Periksa email & App Password."
    except Exception as e:
        return False, f"Gagal kirim email: {str(e)}"


def _kirim_wa_otp(cfg, no_hp, nama_user, otp_code):
    if not cfg['fonnte_token']:
        return False, "Token Fonnte WhatsApp belum dikonfigurasi. Hubungi administrator."
    nomor = re.sub(r'\D', '', no_hp)
    if nomor.startswith('0'): nomor = '62' + nomor[1:]
    elif not nomor.startswith('62'): nomor = '62' + nomor
    expire = cfg['otp_expire']
    pesan = (f"🔐 *Reset Password — {cfg['nama_perusahaan']}*\n\n"
             f"Halo *{nama_user}*,\n\n"
             f"Kode OTP reset password Anda:\n\n"
             f"*{otp_code}*\n\n"
             f"⏱ Berlaku {expire} menit.\n\n"
             f"⚠️ Jangan bagikan kode ini kepada siapapun.")
    try:
        payload = json.dumps({'target':nomor,'message':pesan,'countryCode':'62'}).encode('utf-8')
        req = _urllib_req.Request(cfg['fonnte_url'], data=payload,
            headers={'Authorization':cfg['fonnte_token'],'Content-Type':'application/json'},
            method='POST')
        with _urllib_req.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get('status') in (True, 'true'): return True, ''
            return False, f"Fonnte: {result.get('reason') or result.get('message') or str(result)}"
    except Exception as e:
        return False, f"Gagal kirim WhatsApp: {str(e)}"


def _mask_tujuan(value, metode):
    if not value: return '***'
    if metode == 'email':
        parts = value.split('@')
        if len(parts) == 2:
            name, domain = parts
            return name[:2] + '*'*max(1,len(name)-2) + '@' + domain
        return value[:3] + '***'
    digits = re.sub(r'\D', '', value)
    return digits[:4]+'****'+digits[-3:] if len(digits)>=8 else '****'



def init_db():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS departemen (
            id SERIAL PRIMARY KEY,
            nama TEXT UNIQUE NOT NULL,
            kode TEXT UNIQUE NOT NULL,
            deskripsi TEXT,
            warna TEXT DEFAULT '#3b82f6',
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shift (
            id SERIAL PRIMARY KEY,
            nama TEXT NOT NULL UNIQUE,
            jam_masuk TEXT NOT NULL,
            jam_keluar TEXT NOT NULL,
            toleransi_menit INTEGER DEFAULT 15,
            deskripsi TEXT,
            warna TEXT DEFAULT '#10b981',
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Tambahkan UNIQUE constraint pada kolom nama jika belum ada (untuk DB yang sudah ada)
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS shift_nama_unique ON shift(nama)")
        conn.commit()
    except Exception:
        conn.rollback()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS departemen_shift (
            id SERIAL PRIMARY KEY,
            departemen_id INTEGER NOT NULL REFERENCES departemen(id),
            shift_id INTEGER NOT NULL REFERENCES shift(id),
            UNIQUE(departemen_id, shift_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            nik TEXT UNIQUE NOT NULL,
            nama TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            jabatan TEXT,
            departemen TEXT,
            departemen_id INTEGER REFERENCES departemen(id),
            shift_id INTEGER REFERENCES shift(id),
            no_hp TEXT,
            alamat TEXT,
            tanggal_lahir TEXT,
            jenis_kelamin TEXT,
            foto TEXT,
            role TEXT DEFAULT 'user',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS absensi (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            tanggal DATE NOT NULL,
            jam_masuk TEXT,
            jam_keluar TEXT,
            foto_masuk TEXT,
            foto_keluar TEXT,
            lat_masuk REAL,
            lng_masuk REAL,
            lat_keluar REAL,
            lng_keluar REAL,
            jarak_masuk REAL,
            jarak_keluar REAL,
            shift_id INTEGER,
            status TEXT DEFAULT 'hadir',
            keterangan TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS izin (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            tanggal_mulai DATE NOT NULL,
            tanggal_selesai DATE NOT NULL,
            jenis TEXT NOT NULL,
            alasan TEXT,
            lampiran TEXT,
            status TEXT DEFAULT 'pending',
            catatan_admin TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            nama_perusahaan TEXT DEFAULT 'PT. Absensi Digital',
            jam_masuk TEXT DEFAULT '08:00',
            jam_keluar TEXT DEFAULT '17:00',
            office_lat REAL DEFAULT -6.2088,
            office_lng REAL DEFAULT 106.8456,
            max_distance INTEGER DEFAULT 100
        )
    """)

    cur.execute("INSERT INTO settings (id, nama_perusahaan) VALUES (1, 'PT. Absensi Digital') ON CONFLICT DO NOTHING")

    # ── MASTER ROLE ───────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS master_role (
            id SERIAL PRIMARY KEY,
            kode TEXT UNIQUE NOT NULL,
            nama TEXT NOT NULL,
            deskripsi TEXT,
            aktif INTEGER DEFAULT 1,
            urutan INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Seed default roles
    default_roles = [
        ('admin',    'Administrator',  'Akses penuh ke semua fitur', 0),
        ('user',     'Pegawai',        'Akses standar pegawai',      1),
        ('manajer',  'Manajer',        'Akses laporan dan approval', 2),
        ('dokter',   'Dokter',         'Tenaga medis dokter',        3),
        ('perawat',  'Perawat',        'Tenaga medis perawat',       4),
        ('apoteker', 'Apoteker',       'Tenaga farmasi',             5),
        ('bidan',    'Bidan',          'Tenaga kebidanan',           6),
        ('teknisi',  'Teknisi',        'Teknisi dan IT',             7),
        ('security', 'Security',       'Petugas keamanan',           8),
        ('staf',     'Staf Admin',     'Staf administrasi',          9),
    ]
    for kode, nama, desk, urut in default_roles:
        cur.execute("""INSERT INTO master_role (kode,nama,deskripsi,urutan)
            VALUES (%s,%s,%s,%s) ON CONFLICT (kode) DO NOTHING""",
            (kode, nama, desk, urut))

    # ── KOLOM NIP DI USERS ────────────────────────────────────────────────────
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS nip TEXT")
        conn.commit()
    except Exception:
        conn.rollback()

    # ── SURAT PERINTAH & NOTA DINAS ───────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS surat_template (
            id SERIAL PRIMARY KEY,
            nama TEXT NOT NULL,
            jenis TEXT NOT NULL DEFAULT 'surat_perintah',
            konten TEXT NOT NULL,
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS surat_perintah (
            id SERIAL PRIMARY KEY,
            nomor TEXT UNIQUE,
            template_id INTEGER REFERENCES surat_template(id),
            judul TEXT NOT NULL,
            isi TEXT NOT NULL,
            dibuat_oleh INTEGER REFERENCES users(id),
            tanggal DATE DEFAULT CURRENT_DATE,
            status TEXT DEFAULT 'aktif',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS surat_penerima (
            id SERIAL PRIMARY KEY,
            surat_id INTEGER NOT NULL REFERENCES surat_perintah(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            dibaca INTEGER DEFAULT 0,
            dibaca_at TIMESTAMP,
            UNIQUE(surat_id, user_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nota_dinas (
            id SERIAL PRIMARY KEY,
            nomor TEXT UNIQUE,
            judul TEXT NOT NULL,
            isi TEXT NOT NULL,
            perihal TEXT,
            dari_user INTEGER NOT NULL REFERENCES users(id),
            kepada TEXT,
            tanggal DATE DEFAULT CURRENT_DATE,
            status TEXT DEFAULT 'draft',
            lampiran TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Tambah kolom dasar jika belum ada
    try:
        cur.execute("ALTER TABLE nota_dinas ADD COLUMN IF NOT EXISTS dasar TEXT")
        conn.commit()
    except Exception:
        conn.rollback()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS nota_approval (
            id SERIAL PRIMARY KEY,
            nota_id INTEGER NOT NULL REFERENCES nota_dinas(id) ON DELETE CASCADE,
            level INTEGER NOT NULL,
            role_label TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'pending',
            catatan TEXT,
            ttd_file TEXT,
            approved_at TIMESTAMP,
            urutan INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifikasi (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            judul TEXT NOT NULL,
            pesan TEXT,
            tipe TEXT DEFAULT 'info',
            ref_id INTEGER,
            ref_type TEXT,
            dibaca INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Seed template surat awal — pakai kolom kode (UNIQUE) agar tidak duplikat saat restart
    cur.execute("""
        INSERT INTO surat_template (nama, jenis, kode, konten) VALUES
        ('Surat Perintah Tugas', 'surat_perintah', 'SPT_DEFAULT',
         'Diperintahkan kepada:

Nama    : {{nama}}
Jabatan : {{jabatan}}
Unit    : {{departemen}}

Untuk melaksanakan tugas:
{{isi}}

Dilaksanakan mulai tanggal {{tanggal}} s.d. selesai.')
        ON CONFLICT (kode) DO NOTHING
    """)
    # Tambah kolom logo jika belum ada
    try:
        cur.execute("ALTER TABLE settings ADD COLUMN IF NOT EXISTS logo TEXT")
    except Exception:
        pass

    # ── E-DOSIR ──────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dosir_jenis (
            id SERIAL PRIMARY KEY,
            nama TEXT NOT NULL,
            deskripsi TEXT,
            wajib INTEGER DEFAULT 1,
            departemen_id INTEGER REFERENCES departemen(id) ON DELETE CASCADE,
            urutan INTEGER DEFAULT 0,
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dosir_file (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            jenis_id INTEGER NOT NULL REFERENCES dosir_jenis(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            original_name TEXT,
            keterangan TEXT,
            status TEXT DEFAULT 'pending',
            catatan_admin TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_at TIMESTAMP,
            UNIQUE(user_id, jenis_id)
        )
    """)

    # Migration: tambah kolom tanggal_expired jika DB sudah ada sebelumnya
    try:
        cur.execute("ALTER TABLE dosir_file ADD COLUMN IF NOT EXISTS tanggal_expired DATE")
        conn.commit()
    except Exception:
        conn.rollback()

    admin_pass = generate_password_hash('admin123')
    cur.execute("""INSERT INTO users (nik,nama,email,password,jabatan,departemen,role,status)
        VALUES ('ADMIN001','Administrator','admin@absensi.com',%s,'System Administrator','IT','admin','active')
        ON CONFLICT DO NOTHING""", (admin_pass,))

    depts = [('IT','IT','Information Technology','#3b82f6'),
             ('HR','HR','Human Resources','#8b5cf6'),
             ('Finance','FIN','Keuangan','#10b981'),
             ('Marketing','MKT','Pemasaran','#f59e0b'),
             ('Operations','OPS','Operasional','#ef4444'),
             ('Sales','SLS','Penjualan','#06b6d4')]
    for d in depts:
        cur.execute("INSERT INTO departemen (nama,kode,deskripsi,warna) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", d)

    shifts = [('Shift Pagi','08:00','17:00',15,'Shift normal pagi','#10b981'),
              ('Shift Siang','13:00','21:00',15,'Shift siang','#f59e0b'),
              ('Shift Malam','21:00','06:00',15,'Shift malam','#6366f1'),
              ('Shift Fleksibel','07:00','16:00',30,'Jam fleksibel','#06b6d4')]
    for s in shifts:
        cur.execute("INSERT INTO shift (nama,jam_masuk,jam_keluar,toleransi_menit,deskripsi,warna) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (nama) DO NOTHING", s)


    # ── MODUL SURAT & NOTA DINAS ─────────────────────────────────────────────

    # Template surat
    cur.execute("""
        CREATE TABLE IF NOT EXISTS surat_template (
            id SERIAL PRIMARY KEY,
            nama TEXT NOT NULL,
            jenis TEXT NOT NULL DEFAULT 'surat_perintah',
            kode TEXT UNIQUE,
            konten TEXT NOT NULL,
            deskripsi TEXT,
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Surat Perintah
    cur.execute("""
        CREATE TABLE IF NOT EXISTS surat_perintah (
            id SERIAL PRIMARY KEY,
            nomor_surat TEXT UNIQUE NOT NULL,
            template_id INTEGER REFERENCES surat_template(id),
            judul TEXT NOT NULL,
            dasar TEXT,
            isi TEXT NOT NULL,
            tanggal_surat DATE NOT NULL,
            tanggal_mulai DATE,
            tanggal_selesai DATE,
            pembuat_id INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'aktif',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Penerima surat perintah
    cur.execute("""
        CREATE TABLE IF NOT EXISTS surat_penerima (
            id SERIAL PRIMARY KEY,
            surat_id INTEGER NOT NULL REFERENCES surat_perintah(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            dibaca INTEGER DEFAULT 0,
            dibaca_at TIMESTAMP,
            UNIQUE(surat_id, user_id)
        )
    """)

    # Nota Dinas
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nota_dinas (
            id SERIAL PRIMARY KEY,
            nomor_nota TEXT UNIQUE NOT NULL,
            template_id INTEGER REFERENCES surat_template(id),
            pengaju_id INTEGER NOT NULL REFERENCES users(id),
            perihal TEXT NOT NULL,
            isi TEXT NOT NULL,
            tanggal_nota DATE NOT NULL,
            status TEXT DEFAULT 'draft',
            current_step INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Alur TTD nota dinas
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nota_approval (
            id SERIAL PRIMARY KEY,
            nota_id INTEGER NOT NULL REFERENCES nota_dinas(id) ON DELETE CASCADE,
            step INTEGER NOT NULL,
            role_label TEXT NOT NULL,
            approver_id INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'pending',
            catatan TEXT,
            ttd_image TEXT,
            approved_at TIMESTAMP,
            UNIQUE(nota_id, step)
        )
    """)

    # Notifikasi
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifikasi (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            judul TEXT NOT NULL,
            pesan TEXT,
            tipe TEXT DEFAULT 'info',
            ref_id INTEGER,
            ref_type TEXT,
            dibaca INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Default TTD workflow roles
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS jabatan_kode TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ttd_image TEXT")
    except Exception:
        pass

    # ── Tabel konfigurasi level approval nota dinas ───────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS approval_config (
            id SERIAL PRIMARY KEY,
            level INTEGER UNIQUE NOT NULL,
            label TEXT NOT NULL,
            aktif INTEGER DEFAULT 1,
            urutan INTEGER DEFAULT 0
        )
    """)
    # Seed default jika belum ada
    cur.execute("SELECT COUNT(*) FROM approval_config")
    if cur.fetchone()[0] == 0:
        defaults = [
            (1, 'Kepala TUUD', 1),
            (2, 'Waka Rumkit', 2),
            (3, 'Karumkit', 3),
            (4, 'Pejabat Pengadaan', 4),
        ]
        for lv, lb, ur in defaults:
            cur.execute("INSERT INTO approval_config (level,label,urutan) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (lv, lb, ur))

    # ── Template nota dinas ───────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nota_template (
            id SERIAL PRIMARY KEY,
            nama TEXT NOT NULL UNIQUE,
            header TEXT,
            footer TEXT,
            font_size INTEGER DEFAULT 11,
            margin_top REAL DEFAULT 2.0,
            margin_left REAL DEFAULT 3.0,
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Tambah UNIQUE constraint jika tabel sudah ada sebelumnya (DB lama)
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS nota_template_nama_unique ON nota_template(nama)")
        conn.commit()
    except Exception:
        conn.rollback()
    cur.execute("INSERT INTO nota_template (nama,header,footer) VALUES ('Default','','') ON CONFLICT (nama) DO NOTHING")

    # ── HAK AKSES ROLE ────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS role_permission (
            id SERIAL PRIMARY KEY,
            role_kode TEXT NOT NULL,
            modul_kode TEXT NOT NULL,
            modul_nama TEXT NOT NULL,
            grup TEXT NOT NULL DEFAULT 'Lainnya',
            aktif INTEGER DEFAULT 1,
            UNIQUE(role_kode, modul_kode)
        )
    """)

    SEMUA_MODUL = [
        ('dashboard',         'Dashboard',                 'Dashboard & Profil'),
        ('profil',            'Profil & Ubah Password',    'Dashboard & Profil'),
        ('riwayat',           'Riwayat Absensi',           'Dashboard & Profil'),
        ('absen',             'Absen Masuk / Keluar',      'Absensi'),
        ('lupa_absen',        'Lapor Lupa Absen',          'Absensi'),
        ('izin',              'Pengajuan Izin',            'Absensi'),
        ('nota_dinas',        'Lihat Nota Dinas',          'Nota Dinas'),
        ('nota_dinas_buat',   'Buat Nota Dinas',           'Nota Dinas'),
        ('nota_dinas_pdf',    'Unduh PDF Nota Dinas',      'Nota Dinas'),
        ('dosir',             'E-Dosir (Upload Dokumen)',  'E-Dosir'),
        ('surat_perintah',    'Lihat Surat Perintah',      'Surat Perintah'),
        ('admin_dashboard',   'Dashboard Admin',           'Admin — Umum'),
        ('admin_pegawai',     'Kelola Pegawai',            'Admin — Umum'),
        ('admin_validasi',    'Validasi Registrasi',       'Admin — Umum'),
        ('admin_settings',    'Pengaturan Sistem',         'Admin — Umum'),
        ('admin_absensi',     'Monitor Absensi',           'Admin — Absensi'),
        ('admin_izin',        'Kelola Izin',               'Admin — Absensi'),
        ('admin_laporan',     'Laporan & Export',          'Admin — Absensi'),
        ('admin_grafik',      'Grafik Statistik',          'Admin — Absensi'),
        ('admin_departemen',  'Kelola Departemen',         'Admin — Master Data'),
        ('admin_shift',       'Kelola Shift',              'Admin — Master Data'),
        ('admin_master_role', 'Kelola Role',               'Admin — Master Data'),
        ('admin_role_perm',   'Kelola Hak Akses',          'Admin — Master Data'),
        ('admin_surat',       'Kelola Surat Perintah',     'Admin — Surat & Nota'),
        ('admin_nota_dinas',  'Monitor Nota Dinas',        'Admin — Surat & Nota'),
        ('admin_approval_cfg','Konfigurasi Approval',      'Admin — Surat & Nota'),
        ('admin_nota_tmpl',   'Template Nota Dinas',       'Admin — Surat & Nota'),
        ('admin_pejabat_ttd', 'Pejabat TTD',               'Admin — Surat & Nota'),
        ('admin_dosir',       'Kelola E-Dosir',            'Admin — E-Dosir'),
        ('admin_dosir_jenis', 'Jenis Dokumen Dosir',       'Admin — E-Dosir'),
    ]

    DEFAULT_PERMS = {
        'admin':    [m[0] for m in SEMUA_MODUL],
        'user':     ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'nota_dinas','nota_dinas_buat','nota_dinas_pdf','dosir','surat_perintah'],
        'manajer':  ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'nota_dinas','nota_dinas_buat','nota_dinas_pdf','dosir','surat_perintah',
                     'admin_dashboard','admin_absensi','admin_laporan','admin_grafik',
                     'admin_izin','admin_nota_dinas'],
        'dokter':   ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'nota_dinas','nota_dinas_buat','nota_dinas_pdf','dosir','surat_perintah'],
        'perawat':  ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'dosir','surat_perintah'],
        'apoteker': ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'dosir','surat_perintah'],
        'bidan':    ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'dosir','surat_perintah'],
        'teknisi':  ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'dosir','surat_perintah'],
        'security': ['dashboard','profil','riwayat','absen','lupa_absen','izin'],
        'staf':     ['dashboard','profil','riwayat','absen','lupa_absen','izin',
                     'nota_dinas','nota_dinas_buat','nota_dinas_pdf','dosir','surat_perintah'],
    }

    for kode, nama, grup in SEMUA_MODUL:
        for role_kode, allowed in DEFAULT_PERMS.items():
            aktif = 1 if kode in allowed else 0
            cur.execute("""INSERT INTO role_permission (role_kode,modul_kode,modul_nama,grup,aktif)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (role_kode,modul_kode) DO NOTHING""",
                (role_kode, kode, nama, grup, aktif))

    # ── AUDIT LOG TABLE ───────────────────────────────────────────
    _init_audit_table(cur)
    # ── OTP RESET PASSWORD TABLE ──────────────────────────────────
    _init_reset_table(cur)
    # ─────────────────────────────────────────────────────────────

    conn.commit()
    cur.close()
    conn.close()
    print("Database initialized.")

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_lampiran(fn):
    """FIX: cek ekstensi untuk lampiran izin (termasuk PDF)"""
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED_LAMPIRAN

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def get_user_shift(uid, conn):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if user and user['shift_id']:
        cur.execute("SELECT * FROM shift WHERE id=%s AND aktif=1", (user['shift_id'],))
        s = cur.fetchone()
        if s: cur.close(); return dict(s)
    if user and user['departemen_id']:
        cur.execute("""SELECT s.* FROM shift s JOIN departemen_shift ds ON s.id=ds.shift_id
            WHERE ds.departemen_id=%s AND s.aktif=1 LIMIT 1""", (user['departemen_id'],))
        s = cur.fetchone()
        if s: cur.close(); return dict(s)
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()
    return {'jam_masuk': settings['jam_masuk'] if settings else '08:00',
            'jam_keluar': settings['jam_keluar'] if settings else '17:00',
            'toleransi_menit': 15, 'nama': 'Default', 'id': None}

def get_active_shift(uid, conn):
    """Deteksi shift yang sedang berjalan berdasarkan jam sekarang."""
    now = datetime.now().strftime('%H:%M')
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if user and user['departemen_id']:
        cur.execute("""SELECT s.* FROM shift s
            JOIN departemen_shift ds ON s.id=ds.shift_id
            WHERE ds.departemen_id=%s AND s.aktif=1 ORDER BY s.jam_masuk""", (user['departemen_id'],))
        shifts = cur.fetchall()
    else:
        cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
        shifts = cur.fetchall()
    if not shifts:
        cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
        shifts = cur.fetchall()
    for s in shifts:
        jm, jk = s['jam_masuk'], s['jam_keluar']
        if jm <= jk:
            if jm <= now <= jk:
                cur.close(); return dict(s)
        else:
            if now >= jm or now <= jk:
                cur.close(); return dict(s)
    upcoming = next((s for s in shifts if s['jam_masuk'] > now), None)
    if upcoming:
        cur.close(); return dict(upcoming)
    if shifts:
        cur.close(); return dict(shifts[0])
    cur.close()
    return {'jam_masuk':'08:00','jam_keluar':'17:00','toleransi_menit':15,'nama':'Default','id':None}


def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Akses ditolak!', 'error')
            return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return dec

def q(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# ── AUTH ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        conn = get_db(); cur = q(conn)
        cur.execute("SELECT * FROM users WHERE email=%s", (request.form.get('email','').strip(),))
        user = cur.fetchone()
        cur.close()
        if user and check_password_hash(user['password'], request.form.get('password','')):
            if user['status'] == 'pending':
                flash('Akun belum divalidasi admin.', 'warning')
                log_audit(conn, 'LOGIN_GAGAL', 'auth',
                    deskripsi=f'Login ditolak — akun pending: {user["email"]}',
                    ref_id=user['id'], ref_table='users', status='error',
                    user_id=user['id'], user_nama=user['nama'], user_role=user['role'])
            elif user['status'] == 'rejected':
                flash('Akun ditolak. Hubungi admin.', 'error')
                log_audit(conn, 'LOGIN_GAGAL', 'auth',
                    deskripsi=f'Login ditolak — akun rejected: {user["email"]}',
                    ref_id=user['id'], ref_table='users', status='error',
                    user_id=user['id'], user_nama=user['nama'], user_role=user['role'])
            else:
                session.update({'user_id':user['id'],'nama':user['nama'],'role':user['role'],'foto':user['foto']})
                log_audit(conn, 'LOGIN', 'auth',
                    deskripsi=f'Login berhasil: {user["nama"]} ({user["role"]})',
                    ref_id=user['id'], ref_table='users',
                    user_id=user['id'], user_nama=user['nama'], user_role=user['role'])
                conn.close()
                return redirect(url_for('dashboard'))
        else:
            email_input = request.form.get('email','')
            log_audit(conn, 'LOGIN_GAGAL', 'auth',
                deskripsi=f'Password salah atau email tidak ditemukan: {email_input}',
                status='error', user_id=None, user_nama=email_input, user_role='-')
            flash('Email atau password salah.', 'error')
        conn.close()
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    if request.method == 'POST':
        dept_id = request.form.get('departemen_id') or None
        dept_nama = ''
        if dept_id:
            cur.execute("SELECT nama FROM departemen WHERE id=%s", (dept_id,))
            d = cur.fetchone()
            if d: dept_nama = d['nama']
        foto_path = None
        if 'foto' in request.files:
            f = request.files['foto']
            if f and f.filename and allowed_file(f.filename):
                nik = request.form.get('nik', 'new')
                fn = secure_filename(f"{nik}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{f.filename.rsplit('.',1)[1].lower()}")
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                foto_path = fn
        try:
            cur.execute("""INSERT INTO users (nik,nip,nama,email,password,jabatan,departemen,departemen_id,no_hp,alamat,tanggal_lahir,jenis_kelamin,foto)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (request.form['nik'].strip(), request.form.get('nip','').strip(),
                 request.form['nama'].strip(), request.form['email'].strip(),
                 generate_password_hash(request.form['password']), request.form.get('jabatan','').strip(),
                 dept_nama, dept_id, request.form.get('no_hp','').strip(), request.form.get('alamat','').strip(),
                 request.form.get('tanggal_lahir',''), request.form.get('jenis_kelamin',''), foto_path))
            conn.commit()
            flash('Registrasi berhasil! Tunggu validasi admin.', 'success')
            cur.close(); conn.close()
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash('NIK atau Email sudah terdaftar.', 'error')
    cur.close(); conn.close()
    return render_template('register.html', depts=depts)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        conn = get_db()
        log_audit(conn, 'LOGOUT', 'auth', deskripsi=f'Logout: {session.get("nama")}')
        conn.close()
    session.clear()
    return redirect(url_for('login'))

# ── USER ──────────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('role') == 'admin': return redirect(url_for('admin_dashboard'))
    uid = session['user_id']; today = date.today().isoformat()
    conn = get_db(); cur = q(conn)

    cur.execute("SELECT * FROM absensi WHERE user_id=%s AND tanggal=%s", (uid, today))
    absen_today = cur.fetchone()

    bulan = date.today().strftime('%Y-%m')
    cur.execute("""SELECT
        SUM(CASE WHEN status='hadir' THEN 1 ELSE 0 END) as hadir,
        SUM(CASE WHEN status='telat' THEN 1 ELSE 0 END) as telat,
        SUM(CASE WHEN status='izin' THEN 1 ELSE 0 END) as izin,
        COUNT(*) as total
        FROM absensi WHERE user_id=%s AND TO_CHAR(tanggal,'YYYY-MM')=%s""", (uid, bulan))
    stats = cur.fetchone()

    cur.execute("""SELECT a.tanggal,a.status,a.jam_masuk,a.jam_keluar,a.jarak_masuk,s.nama as shift_nama
        FROM absensi a LEFT JOIN shift s ON a.shift_id=s.id
        WHERE a.user_id=%s ORDER BY a.tanggal DESC LIMIT 30""", (uid,))
    riwayat = cur.fetchall()

    cur.execute("""SELECT u.*,d.nama as dept_nama,d.warna as dept_warna,
        s.nama as shift_nama,s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()

    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()

    user_shift = get_active_shift(uid, conn)  # otomatis deteksi shift berjalan

    # Ambil daftar shift tersedia untuk user (dari departemen atau semua shift aktif)
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    u_raw = cur.fetchone()
    if u_raw and u_raw['departemen_id']:
        cur.execute("""SELECT s.* FROM shift s
            JOIN departemen_shift ds ON s.id=ds.shift_id
            WHERE ds.departemen_id=%s AND s.aktif=1 ORDER BY s.jam_masuk""", (u_raw['departemen_id'],))
        available_shifts = cur.fetchall()
        if not available_shifts:
            cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
            available_shifts = cur.fetchall()
    else:
        cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
        available_shifts = cur.fetchall()

    cur.close(); conn.close()

    if not user:
        session.clear()
        flash('Sesi tidak valid, silakan login kembali.', 'warning')
        return redirect(url_for('login'))

    return render_template('dashboard.html', absen_today=absen_today, stats=stats,
        riwayat=[dict(r) for r in riwayat], user=user, settings=settings,
        today=today, user_shift=user_shift, available_shifts=available_shifts)

@app.route('/absen', methods=['POST'])
@login_required
def absen():
    uid = session['user_id']; today = date.today().isoformat()
    now = datetime.now().strftime('%H:%M:%S')
    lat = request.form.get('lat', type=float)
    lng = request.form.get('lng', type=float)
    tipe = request.form.get('tipe')
    shift_id_form = request.form.get('shift_id') or None
    conn = get_db(); cur = q(conn)

    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    off_lat = settings['office_lat'] if settings else -6.2088
    off_lng = settings['office_lng'] if settings else 106.8456
    max_dist = settings['max_distance'] if settings else 100

    jarak = haversine(lat, lng, off_lat, off_lng) if lat and lng else None

    if jarak is not None and jarak > max_dist:
        cur.close(); conn.close()
        flash(f'Absen ditolak! Anda berada {jarak:.0f}m dari kantor. Batas maksimal {max_dist}m.', 'error_radius')
        return redirect(url_for('dashboard'))

    foto_path = None
    if 'foto' in request.files:
        f = request.files['foto']
        if f and f.filename:
            ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else 'jpg'
            fn = secure_filename(f"{uid}_{today}_{tipe}.{ext}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
            foto_path = fn

    cur.execute("SELECT * FROM absensi WHERE user_id=%s AND tanggal=%s", (uid, today))
    absen_today = cur.fetchone()

    if tipe == 'masuk':
        if absen_today:
            flash('Sudah absen masuk hari ini!', 'warning')
        else:
            # Gunakan shift yang dipilih user, atau fallback ke shift aktif
            shift_id = shift_id_form
            if shift_id:
                cur.execute("SELECT * FROM shift WHERE id=%s AND aktif=1", (shift_id,))
                chosen_shift = cur.fetchone()
            else:
                chosen_shift = get_active_shift(uid, conn)
                shift_id = chosen_shift.get('id') if chosen_shift else None

            # Cek telat berdasarkan shift yang dipilih
            status = 'hadir'
            if chosen_shift:
                from datetime import time as dtime
                h, m = map(int, chosen_shift['jam_masuk'].split(':'))
                toleransi = chosen_shift.get('toleransi_menit', 15)
                batas = datetime.combine(date.today(), dtime(h, m)) + timedelta(minutes=toleransi)
                if datetime.now() > batas: status = 'telat'

            cur.execute("""INSERT INTO absensi (user_id,tanggal,jam_masuk,foto_masuk,lat_masuk,lng_masuk,jarak_masuk,shift_id,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (uid, today, now, foto_path, lat, lng, jarak, shift_id, status))
            conn.commit()
            log_audit(conn, 'ABSEN_MASUK', 'absensi',
                deskripsi=f'Absen masuk — {session.get("nama")} | Jarak: {jarak:.0f}m | Status: {status}' if jarak else f'Absen masuk — {session.get("nama")} | Status: {status}',
                data_baru={'tanggal':today,'jam':now,'jarak':jarak,'shift_id':shift_id,'status':status},
                ref_id=uid, ref_table='users')
            flash(f'Absen masuk berhasil! Jarak: {jarak:.0f}m' if jarak else 'Absen masuk berhasil!', 'success')

    elif tipe == 'keluar':
        if not absen_today:
            flash('Belum absen masuk!', 'warning')
        elif absen_today['jam_keluar']:
            flash('Sudah absen keluar!', 'warning')
        else:
            # LOCK shift keluar = shift masuk, abaikan pilihan user
            shift_id = absen_today['shift_id']
            cur.execute("""UPDATE absensi SET jam_keluar=%s,foto_keluar=%s,lat_keluar=%s,lng_keluar=%s,jarak_keluar=%s,shift_id=%s
                WHERE user_id=%s AND tanggal=%s""", (now, foto_path, lat, lng, jarak, shift_id, uid, today))
            conn.commit()
            log_audit(conn, 'ABSEN_KELUAR', 'absensi',
                deskripsi=f'Absen keluar — {session.get("nama")} | Jarak: {jarak:.0f}m' if jarak else f'Absen keluar — {session.get("nama")}',
                data_baru={'tanggal':today,'jam':now,'jarak':jarak},
                ref_id=uid, ref_table='users')
            flash('Absen keluar berhasil!', 'success')

    cur.close(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/lupa-absen', methods=['POST'])
@login_required
def lupa_absen():
    """User lapor lupa absen pulang — admin yang approve."""
    uid = session['user_id']
    tanggal = request.form.get('tanggal', date.today().isoformat())
    alasan = request.form.get('alasan', 'Lupa absen pulang')
    jam_keluar_manual = request.form.get('jam_keluar_manual', '').strip()
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM absensi WHERE user_id=%s AND tanggal=%s", (uid, tanggal))
    absen = cur.fetchone()
    if not absen:
        flash('Tidak ada data absen masuk pada tanggal tersebut.', 'error')
    elif absen['jam_keluar']:
        flash('Absen pulang sudah tercatat.', 'warning')
    else:
        # Simpan sebagai izin dengan jenis khusus "Lupa Absen Pulang"
        cur.execute("""INSERT INTO izin (user_id,tanggal_mulai,tanggal_selesai,jenis,alasan,status)
            VALUES (%s,%s,%s,%s,%s,'pending')""",
            (uid, tanggal, tanggal, 'Lupa Absen Pulang',
             f"{alasan} | Jam keluar: {jam_keluar_manual if jam_keluar_manual else 'tidak diisi'}"))
        conn.commit()
        flash('Laporan lupa absen pulang berhasil dikirim. Tunggu konfirmasi admin.', 'success')
    cur.close(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/admin/izin/<int:iid>/approve-lupa-absen', methods=['POST'])
@admin_required
def approve_lupa_absen(iid):
    """Admin setujui lupa absen pulang — isi jam keluar manual."""
    jam_keluar = request.form.get('jam_keluar', '17:00') + ':00'
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM izin WHERE id=%s", (iid,))
    iz = cur.fetchone()
    if iz:
        cur.execute("UPDATE izin SET status='approved',catatan_admin=%s WHERE id=%s",
            (f'Disetujui admin, jam keluar: {jam_keluar}', iid))
        cur.execute("""UPDATE absensi SET jam_keluar=%s,keterangan='Lupa absen pulang — disetujui admin'
            WHERE user_id=%s AND tanggal=%s AND jam_keluar IS NULL""",
            (jam_keluar, iz['user_id'], str(iz['tanggal_mulai'])))
        conn.commit()
        flash(f'Lupa absen pulang disetujui. Jam keluar: {jam_keluar}', 'success')
    cur.close(); conn.close()
    return redirect(url_for('admin_izin'))

@app.route('/riwayat')
@login_required
def riwayat():
    uid = session['user_id']
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT a.*,s.nama as shift_nama,s.jam_masuk as shift_masuk
        FROM absensi a LEFT JOIN shift s ON a.shift_id=s.id
        WHERE a.user_id=%s AND TO_CHAR(a.tanggal,'YYYY-MM')=%s ORDER BY a.tanggal DESC""", (uid, bulan))
    data = cur.fetchall()
    cur.close(); conn.close()
    return render_template('riwayat.html', data=data, bulan=bulan)

# ── FIX: Route izin dengan allowed_lampiran ───────────────────────────────────
@app.route('/izin', methods=['GET','POST'])
@login_required
def izin():
    uid = session['user_id']
    if request.method == 'POST':
        conn = get_db(); cur = q(conn)
        lamp = None

        if 'lampiran' in request.files:
            f = request.files['lampiran']
            if f and f.filename:
                if allowed_lampiran(f.filename):
                    ext = f.filename.rsplit('.', 1)[-1].lower()
                    fn = secure_filename(f"{uid}_izin_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                    lamp = fn
                else:
                    flash('Format file tidak didukung. Gunakan JPG, PNG, atau PDF.', 'error')
                    cur.close(); conn.close()
                    return redirect(url_for('izin'))

        cur.execute("""INSERT INTO izin (user_id,tanggal_mulai,tanggal_selesai,jenis,alasan,lampiran)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (uid, request.form['tanggal_mulai'], request.form['tanggal_selesai'],
             request.form['jenis'], request.form['alasan'], lamp))
        conn.commit(); cur.close(); conn.close()
        flash('Permohonan izin berhasil dikirim!', 'success')
        return redirect(url_for('izin'))

    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM izin WHERE user_id=%s ORDER BY created_at DESC", (uid,))
    data = cur.fetchall()
    cur.close(); conn.close()
    return render_template('izin.html', data=data)

@app.route('/profil', methods=['GET','POST'])
@login_required
def profil():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    if request.method == 'POST':
        foto_path = None
        if 'foto' in request.files:
            f = request.files['foto']
            if f and f.filename and allowed_file(f.filename):
                fn = secure_filename(f"user_{uid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{f.filename.rsplit('.',1)[-1].lower()}")
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                foto_path = fn
        dept_id = request.form.get('departemen_id') or None
        # Ambil nama departemen untuk disimpan di kolom departemen (teks)
        dept_nama = None
        if dept_id:
            cur.execute("SELECT nama FROM departemen WHERE id=%s AND aktif=1", (dept_id,))
            d_row = cur.fetchone()
            if d_row:
                dept_nama = d_row['nama']
        if foto_path:
            cur.execute("UPDATE users SET no_hp=%s,alamat=%s,foto=%s,departemen_id=%s,departemen=%s WHERE id=%s",
                (request.form.get('no_hp',''), request.form.get('alamat',''), foto_path, dept_id, dept_nama, uid))
            session['foto'] = foto_path
        else:
            cur.execute("UPDATE users SET no_hp=%s,alamat=%s,departemen_id=%s,departemen=%s WHERE id=%s",
                (request.form.get('no_hp',''), request.form.get('alamat',''), dept_id, dept_nama, uid))
        conn.commit()
        flash('Profil berhasil diperbarui!', 'success')

    cur.execute("""SELECT u.*,d.nama as dept_nama,d.warna as dept_warna,
        s.nama as shift_nama,s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()
    cur.execute("SELECT id, nama FROM departemen WHERE aktif=1 ORDER BY nama")
    daftar_departemen = cur.fetchall()
    cur.close(); conn.close()
    if not user:
        session.clear()
        flash('Sesi tidak valid, silakan login kembali.', 'warning')
        return redirect(url_for('login'))
    return render_template('profil.html', user=user, daftar_departemen=daftar_departemen)

# ── ADMIN DASHBOARD ───────────────────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db(); cur = q(conn)
    today = date.today().isoformat()

    cur.execute("SELECT COUNT(*) as c FROM users WHERE role='user' AND status='active'")
    total_user = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM users WHERE status='pending'")
    pending = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM absensi WHERE tanggal=%s AND status IN ('hadir','telat')", (today,))
    hadir_today = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM absensi WHERE tanggal=%s AND status='telat'", (today,))
    telat_today = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM izin WHERE status='pending'")
    izin_pending = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM departemen WHERE aktif=1")
    total_dept = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM shift WHERE aktif=1")
    total_shift = cur.fetchone()['c']

    chart_data = []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        cur.execute("SELECT COUNT(*) as c FROM absensi WHERE tanggal=%s AND status IN ('hadir','telat')", (d,))
        h = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) as c FROM absensi WHERE tanggal=%s AND status='telat'", (d,))
        t = cur.fetchone()['c']
        chart_data.append({'tanggal': d, 'hadir': h, 'telat': t})

    cur.execute("""SELECT d.nama as departemen, d.warna, d.kode,
        COUNT(DISTINCT u.id) as total_pegawai,
        SUM(CASE WHEN a.tanggal=%s AND a.status IN ('hadir','telat') THEN 1 ELSE 0 END) as hadir_today
        FROM departemen d
        LEFT JOIN users u ON u.departemen_id=d.id AND u.status='active' AND u.role='user'
        LEFT JOIN absensi a ON u.id=a.user_id AND a.tanggal=%s
        WHERE d.aktif=1 GROUP BY d.id,d.nama,d.warna,d.kode ORDER BY total_pegawai DESC""", (today, today))
    dept_stats = cur.fetchall()

    cur.execute("""SELECT a.*,u.nama,u.jabatan,u.foto,u.departemen,s.nama as shift_nama
        FROM absensi a JOIN users u ON a.user_id=u.id LEFT JOIN shift s ON a.shift_id=s.id
        WHERE a.tanggal=%s ORDER BY a.jam_masuk DESC LIMIT 10""", (today,))
    recent = cur.fetchall()

    cur.execute("""SELECT d.*,(SELECT COUNT(*) FROM users WHERE departemen_id=d.id AND status='active') as jml
        FROM departemen d WHERE aktif=1 ORDER BY nama""")
    recent_depts = cur.fetchall()

    cur.execute("""SELECT s.*,(SELECT COUNT(*) FROM users WHERE shift_id=s.id AND status='active') as jml
        FROM shift s WHERE aktif=1 ORDER BY jam_masuk""")
    recent_shifts = cur.fetchall()

    cur.close(); conn.close()
    return render_template('admin/dashboard.html',
        total_user=total_user, pending=pending, hadir_today=hadir_today,
        telat_today=telat_today, izin_pending=izin_pending,
        total_dept=total_dept, total_shift=total_shift,
        chart_data=json.dumps(chart_data), dept_stats=dept_stats,
        recent=recent, recent_depts=recent_depts, recent_shifts=recent_shifts, today=today)

# ── ADMIN DEPARTEMEN ──────────────────────────────────────────────────────────
@app.route('/admin/departemen')
@admin_required
def admin_departemen():
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT d.*,
        COUNT(DISTINCT u.id) as total_pegawai,
        COUNT(DISTINCT ds.shift_id) as total_shift
        FROM departemen d
        LEFT JOIN users u ON u.departemen_id=d.id AND u.status='active' AND u.role='user'
        LEFT JOIN departemen_shift ds ON ds.departemen_id=d.id
        GROUP BY d.id ORDER BY d.nama""")
    depts = cur.fetchall()
    cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
    shifts = cur.fetchall()
    cur.execute("SELECT * FROM departemen_shift")
    dept_shifts = {}
    for ds in cur.fetchall():
        dept_shifts.setdefault(str(ds['departemen_id']), []).append(str(ds['shift_id']))
    cur.close(); conn.close()
    return render_template('admin/departemen.html', depts=depts, shifts=shifts, dept_shifts=dept_shifts)

@app.route('/admin/departemen/tambah', methods=['POST'])
@admin_required
def tambah_departemen():
    conn = get_db(); cur = q(conn)
    try:
        cur.execute("INSERT INTO departemen (nama,kode,deskripsi,warna) VALUES (%s,%s,%s,%s)",
            (request.form['nama'], request.form['kode'].upper(),
             request.form.get('deskripsi',''), request.form.get('warna','#3b82f6')))
        conn.commit()
        flash(f'Departemen "{request.form["nama"]}" ditambahkan!', 'success')
    except:
        conn.rollback(); flash('Nama atau kode sudah ada!', 'error')
    cur.close(); conn.close()
    return redirect(url_for('admin_departemen'))

@app.route('/admin/departemen/edit/<int:did>', methods=['POST'])
@admin_required
def edit_departemen(did):
    conn = get_db(); cur = q(conn)
    try:
        cur.execute("UPDATE departemen SET nama=%s,kode=%s,deskripsi=%s,warna=%s,aktif=%s WHERE id=%s",
            (request.form['nama'], request.form['kode'].upper(), request.form.get('deskripsi',''),
             request.form.get('warna','#3b82f6'), 1 if request.form.get('aktif') else 0, did))
        conn.commit(); flash('Departemen diperbarui!', 'success')
    except Exception as e:
        conn.rollback(); flash('Gagal: '+str(e), 'error')
    cur.close(); conn.close()
    return redirect(url_for('admin_departemen'))

@app.route('/admin/departemen/hapus/<int:did>', methods=['POST'])
@admin_required
def hapus_departemen(did):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT COUNT(*) as c FROM users WHERE departemen_id=%s", (did,))
    peg = cur.fetchone()['c']
    if peg > 0:
        flash(f'Tidak bisa hapus: masih ada {peg} pegawai!', 'error')
    else:
        cur.execute("DELETE FROM departemen_shift WHERE departemen_id=%s", (did,))
        cur.execute("DELETE FROM departemen WHERE id=%s", (did,))
        conn.commit(); flash('Departemen dihapus!', 'success')
    cur.close(); conn.close()
    return redirect(url_for('admin_departemen'))

@app.route('/admin/departemen/<int:did>/shift', methods=['POST'])
@admin_required
def atur_shift_departemen(did):
    conn = get_db(); cur = q(conn)
    try:
        cur.execute("DELETE FROM departemen_shift WHERE departemen_id=%s", (did,))
        for sid in request.form.getlist('shift_ids'):
            try:
                cur.execute("INSERT INTO departemen_shift (departemen_id,shift_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (did, int(sid)))
            except (ValueError, TypeError):
                pass
        conn.commit()
        flash('Shift departemen diperbarui!', 'success')
    except Exception as e:
        conn.rollback()
        flash('Gagal memperbarui shift: ' + str(e), 'error')
    cur.close(); conn.close()
    return redirect(url_for('admin_departemen'))

# ── ADMIN SHIFT ───────────────────────────────────────────────────────────────
@app.route('/admin/shift')
@admin_required
def admin_shift():
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT s.*,
        COUNT(DISTINCT u.id) as total_pegawai,
        COUNT(DISTINCT ds.departemen_id) as total_dept
        FROM shift s
        LEFT JOIN users u ON u.shift_id=s.id AND u.status='active'
        LEFT JOIN departemen_shift ds ON ds.shift_id=s.id
        GROUP BY s.id ORDER BY s.jam_masuk""")
    shifts = cur.fetchall()
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/shift.html', shifts=shifts, depts=depts)

@app.route('/admin/shift/tambah', methods=['POST'])
@admin_required
def tambah_shift():
    conn = get_db(); cur = q(conn)
    nama = request.form.get('nama', '').strip()
    if not nama:
        flash('Nama shift tidak boleh kosong.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('admin_shift'))
    cur.execute("SELECT id FROM shift WHERE LOWER(nama)=LOWER(%s)", (nama,))
    if cur.fetchone():
        flash(f'Shift "{nama}" sudah ada, tidak bisa duplikat.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('admin_shift'))
    try:
        cur.execute("INSERT INTO shift (nama,jam_masuk,jam_keluar,toleransi_menit,deskripsi,warna) VALUES (%s,%s,%s,%s,%s,%s)",
            (nama, request.form['jam_masuk'], request.form['jam_keluar'],
             int(request.form.get('toleransi_menit', 15)), request.form.get('deskripsi',''),
             request.form.get('warna','#10b981')))
        conn.commit(); flash(f'Shift "{nama}" ditambahkan!', 'success')
    except Exception as e:
        conn.rollback(); flash('Gagal: '+str(e), 'error')
    cur.close(); conn.close()
    return redirect(url_for('admin_shift'))

@app.route('/admin/shift/edit/<int:sid>', methods=['POST'])
@admin_required
def edit_shift(sid):
    conn = get_db(); cur = q(conn)
    cur.execute("UPDATE shift SET nama=%s,jam_masuk=%s,jam_keluar=%s,toleransi_menit=%s,deskripsi=%s,warna=%s,aktif=%s WHERE id=%s",
        (request.form['nama'], request.form['jam_masuk'], request.form['jam_keluar'],
         int(request.form.get('toleransi_menit', 15)), request.form.get('deskripsi',''),
         request.form.get('warna','#10b981'), 1 if request.form.get('aktif') else 0, sid))
    conn.commit(); cur.close(); conn.close()
    flash('Shift diperbarui!', 'success')
    return redirect(url_for('admin_shift'))

@app.route('/admin/shift/hapus/<int:sid>', methods=['POST'])
@admin_required
def hapus_shift(sid):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT COUNT(*) as c FROM users WHERE shift_id=%s", (sid,))
    peg = cur.fetchone()['c']
    if peg > 0:
        flash(f'Tidak bisa hapus: {peg} pegawai masih menggunakan shift ini!', 'error')
    else:
        cur.execute("DELETE FROM departemen_shift WHERE shift_id=%s", (sid,))
        cur.execute("DELETE FROM shift WHERE id=%s", (sid,))
        conn.commit(); flash('Shift dihapus!', 'success')
    cur.close(); conn.close()
    return redirect(url_for('admin_shift'))

# ── ADMIN PEGAWAI ─────────────────────────────────────────────────────────────
@app.route('/admin/pegawai')
@admin_required
def admin_pegawai():
    conn = get_db(); cur = q(conn)
    qstr = request.args.get('q',''); sf = request.args.get('status',''); df = request.args.get('dept','')
    sql = """SELECT u.*,d.nama as dept_nama,d.warna as dept_warna,
        s.nama as shift_nama,s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.role='user'"""
    params = []
    if qstr:
        sql += " AND (u.nama ILIKE %s OR u.nik ILIKE %s OR u.email ILIKE %s)"
        params.extend([f'%{qstr}%']*3)
    if sf: sql += " AND u.status=%s"; params.append(sf)
    if df: sql += " AND u.departemen_id=%s"; params.append(df)
    sql += " ORDER BY u.created_at DESC"
    cur.execute(sql, params)
    users = cur.fetchall()
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
    shifts = cur.fetchall()
    stats = {'total': len(users),
             'active': sum(1 for u in users if u['status']=='active'),
             'pending': sum(1 for u in users if u['status']=='pending')}
    cur.close(); conn.close()
    return render_template('admin/pegawai.html', users=users, q=qstr,
        status_filter=sf, dept_filter=df, depts=depts, shifts=shifts, stats=stats)

@app.route('/admin/pegawai/tambah', methods=['POST'])
@admin_required
def tambah_pegawai():
    conn = get_db(); cur = q(conn)
    dept_id = request.form.get('departemen_id') or None; dept_nama = ''
    if dept_id:
        cur.execute("SELECT nama FROM departemen WHERE id=%s", (dept_id,))
        d = cur.fetchone()
        if d: dept_nama = d['nama']
    foto_path = None
    if 'foto' in request.files:
        f = request.files['foto']
        if f and f.filename and allowed_file(f.filename):
            fn = secure_filename(f"{request.form.get('nik','new')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{f.filename.rsplit('.',1)[-1].lower()}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); foto_path = fn
    try:
        cur.execute("""INSERT INTO users (nik,nama,email,password,jabatan,departemen,departemen_id,shift_id,
            no_hp,alamat,tanggal_lahir,jenis_kelamin,foto,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (request.form['nik'], request.form['nama'], request.form['email'],
             generate_password_hash(request.form['password']), request.form.get('jabatan',''),
             dept_nama, dept_id, request.form.get('shift_id') or None,
             request.form.get('no_hp',''), request.form.get('alamat',''),
             request.form.get('tanggal_lahir',''), request.form.get('jenis_kelamin',''),
             foto_path, request.form.get('status','active')))
        conn.commit(); flash('Pegawai berhasil ditambahkan!', 'success')
    except Exception as e:
        conn.rollback(); flash('NIK atau Email sudah ada: '+str(e), 'error')
    cur.close(); conn.close()
    return redirect(url_for('admin_pegawai'))

@app.route('/admin/pegawai/edit/<int:uid>', methods=['GET','POST'])
@admin_required
def edit_pegawai(uid):
    conn = get_db(); cur = q(conn)
    if request.method == 'POST':
        dept_id = int(request.form.get('departemen_id')) if request.form.get('departemen_id') else None
        dept_nama = ''
        if dept_id:
            cur.execute("SELECT nama FROM departemen WHERE id=%s", (dept_id,))
            d = cur.fetchone()
            if d: dept_nama = d['nama']
        shift_id = int(request.form.get('shift_id')) if request.form.get('shift_id') else None
        foto_path = None
        if 'foto' in request.files:
            f = request.files['foto']
            if f and f.filename and allowed_file(f.filename):
                fn = secure_filename(f"user_{uid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{f.filename.rsplit('.',1)[-1].lower()}")
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); foto_path = fn
        # Cek apakah kolom nip ada di tabel users
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='nip'")
        has_nip = cur.fetchone() is not None
        fields = ["nik=%s","nama=%s","email=%s","jabatan=%s","departemen=%s","departemen_id=%s",
                  "shift_id=%s","no_hp=%s","alamat=%s","tanggal_lahir=%s","jenis_kelamin=%s","status=%s","role=%s"]
        params = [request.form['nik'],
                  request.form['nama'], request.form['email'],
                  request.form.get('jabatan',''), dept_nama, dept_id,
                  shift_id, request.form.get('no_hp',''),
                  request.form.get('alamat',''), request.form.get('tanggal_lahir',''),
                  request.form.get('jenis_kelamin',''), request.form.get('status','active'),
                  request.form.get('role','user')]
        if has_nip:
            fields.insert(1, "nip=%s")
            params.insert(1, request.form.get('nip','').strip())
        if foto_path: fields.append("foto=%s"); params.append(foto_path)
        if request.form.get('password'): fields.append("password=%s"); params.append(generate_password_hash(request.form['password']))
        params.append(uid)
        try:
            cur.execute(f"UPDATE users SET {','.join(fields)} WHERE id=%s", params)
            conn.commit()
            flash('Data pegawai diperbarui!', 'success')
        except Exception as e:
            conn.rollback()
            flash('Gagal memperbarui data: ' + str(e), 'error')
        cur.close(); conn.close()
        return redirect(url_for('admin_pegawai'))
    cur.execute("""SELECT u.*,d.nama as dept_nama,s.nama as shift_nama
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
    shifts = cur.fetchall()
    cur.execute("SELECT * FROM master_role WHERE aktif=1 ORDER BY urutan")
    roles = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/edit_pegawai.html', user=user, depts=depts, shifts=shifts, roles=roles)

@app.route('/admin/pegawai/hapus/<int:uid>', methods=['POST'])
@admin_required
def hapus_pegawai(uid):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT COUNT(*) as c FROM absensi WHERE user_id=%s", (uid,))
    cnt = cur.fetchone()['c']
    if cnt > 0:
        cur.execute("UPDATE users SET status='rejected' WHERE id=%s", (uid,))
        conn.commit(); flash('Pegawai dinonaktifkan (ada data absensi).', 'warning')
    else:
        cur.execute("DELETE FROM izin WHERE user_id=%s", (uid,))
        cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        conn.commit(); flash('Pegawai dihapus!', 'success')
    cur.close(); conn.close()
    return redirect(url_for('admin_pegawai'))

@app.route('/admin/validasi/<int:uid>/<action>')
@admin_required
def validasi_user(uid, action):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT nama,status FROM users WHERE id=%s", (uid,))
    target = cur.fetchone()
    status_lama = target['status'] if target else '-'
    status_baru = 'active' if action=='approve' else 'rejected'
    cur.execute("UPDATE users SET status=%s WHERE id=%s", (status_baru, uid))
    conn.commit()
    log_audit(conn, 'VALIDASI', 'pegawai',
        deskripsi=f'Validasi akun {target["nama"] if target else uid}: {status_lama} → {status_baru}',
        data_lama={'status':status_lama}, data_baru={'status':status_baru},
        ref_id=uid, ref_table='users')
    cur.close(); conn.close()
    flash('Akun disetujui!' if action=='approve' else 'Akun ditolak!',
          'success' if action=='approve' else 'info')
    return redirect(url_for('admin_pegawai'))

# ── ADMIN ABSENSI ─────────────────────────────────────────────────────────────
@app.route('/admin/absensi')
@admin_required
def admin_absensi():
    conn = get_db(); cur = q(conn)
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))
    dept = request.args.get('dept','')
    sql = """SELECT a.*,u.nama,u.nik,u.jabatan,u.departemen,u.foto,s.nama as shift_nama
        FROM absensi a JOIN users u ON a.user_id=u.id LEFT JOIN shift s ON a.shift_id=s.id
        WHERE TO_CHAR(a.tanggal,'YYYY-MM')=%s"""
    params = [bulan]
    if dept: sql += " AND u.departemen_id=%s"; params.append(dept)
    sql += " ORDER BY a.tanggal DESC,a.jam_masuk DESC"
    cur.execute(sql, params)
    data = cur.fetchall()
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/absensi.html', data=data, bulan=bulan, dept=dept, depts=depts)

# ── ADMIN IZIN ────────────────────────────────────────────────────────────────
@app.route('/admin/izin')
@admin_required
def admin_izin():
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT i.*,u.nama,u.nik,u.departemen FROM izin i JOIN users u ON i.user_id=u.id ORDER BY i.created_at DESC")
    data = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/izin.html', data=data)

@app.route('/admin/izin/<int:iid>/<action>', methods=['GET','POST'])
@admin_required
def proses_izin(iid, action):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM izin WHERE id=%s", (iid,))
    iz = cur.fetchone()
    if iz and action in ['approve','reject']:
        cur.execute("UPDATE izin SET status=%s WHERE id=%s",
            ('approved' if action=='approve' else 'rejected', iid))

        if action == 'approve':
            if iz['jenis'] == 'Lupa Absen Pulang':
                # Ambil jam keluar dari form (admin input) atau dari alasan
                jam_keluar_input = request.form.get('jam_keluar', '').strip()
                if jam_keluar_input:
                    jam_keluar = jam_keluar_input + ':00' if len(jam_keluar_input) == 5 else jam_keluar_input
                else:
                    # Fallback: ekstrak dari alasan
                    import re
                    alasan = iz['alasan'] or ''
                    m2 = re.search(r'Jam keluar[:\s]+(\d{1,2}:\d{2})', alasan)
                    jam_keluar = (m2.group(1) + ':00') if m2 else '17:00:00'

                tanggal = str(iz['tanggal_mulai'])
                cur.execute("""UPDATE absensi SET jam_keluar=%s,
                    keterangan='Lupa absen pulang — disetujui admin'
                    WHERE user_id=%s AND tanggal=%s AND (jam_keluar IS NULL OR jam_keluar='')""",
                    (jam_keluar, iz['user_id'], tanggal))
                cur.execute("UPDATE izin SET catatan_admin=%s WHERE id=%s",
                    (f'Jam keluar diisi: {jam_keluar}', iid))
                flash(f'Lupa absen pulang disetujui. Jam keluar: {jam_keluar}', 'success')
            else:
                d1 = datetime.strptime(str(iz['tanggal_mulai']), '%Y-%m-%d')
                d2 = datetime.strptime(str(iz['tanggal_selesai']), '%Y-%m-%d')
                cur2 = conn.cursor()
                cur_date = d1
                while cur_date <= d2:
                    cur2.execute("""INSERT INTO absensi (user_id,tanggal,status,keterangan)
                        VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (iz['user_id'], cur_date.date().isoformat(), 'izin', iz['jenis']))
                    cur_date += timedelta(days=1)
                cur2.close()
                flash('Izin disetujui!', 'success')
        else:
            flash('Izin ditolak!', 'info')

        log_audit(conn,
            'APPROVE' if action=='approve' else 'REJECT', 'izin',
            deskripsi=f'{"Setujui" if action=="approve" else "Tolak"} izin ID {iid} — {iz["jenis"]} milik user_id {iz["user_id"]}',
            data_lama={'status':'pending'},
            data_baru={'status':'approved' if action=="approve" else 'rejected'},
            ref_id=iid, ref_table='izin')
        conn.commit()
    cur.close(); conn.close()
    return redirect(url_for('admin_izin'))

# ── ADMIN LAPORAN ─────────────────────────────────────────────────────────────
@app.route('/admin/laporan')
@admin_required
def admin_laporan():
    conn = get_db(); cur = q(conn)
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))
    cur.execute("""SELECT u.*,d.nama as dept_nama,s.nama as shift_nama FROM users u
        LEFT JOIN departemen d ON u.departemen_id=d.id LEFT JOIN shift s ON u.shift_id=s.id
        WHERE u.role='user' AND u.status='active' ORDER BY u.nama""")
    users = cur.fetchall()
    rekap = []
    for u in users:
        cur.execute("""SELECT
            SUM(CASE WHEN status='hadir' THEN 1 ELSE 0 END) as hadir,
            SUM(CASE WHEN status='telat' THEN 1 ELSE 0 END) as telat,
            SUM(CASE WHEN status='izin' THEN 1 ELSE 0 END) as izin,
            COUNT(*) as total
            FROM absensi WHERE user_id=%s AND TO_CHAR(tanggal,'YYYY-MM')=%s""", (u['id'], bulan))
        rekap.append({'user': u, 'stats': cur.fetchone()})
    cur.close(); conn.close()
    return render_template('admin/laporan.html', rekap=rekap, bulan=bulan)

@app.route('/admin/export/excel')
@admin_required
def export_excel():
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))
    conn = get_db()
    log_audit(conn, 'EXPORT', 'laporan', deskripsi=f'Export Excel laporan bulan {bulan}')
    conn.close()
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT a.tanggal,u.nik,u.nama,u.departemen,u.jabatan,a.jam_masuk,a.jam_keluar,
        a.jarak_masuk,a.status,a.keterangan,s.nama as shift_nama
        FROM absensi a JOIN users u ON a.user_id=u.id LEFT JOIN shift s ON a.shift_id=s.id
        WHERE TO_CHAR(a.tanggal,'YYYY-MM')=%s ORDER BY a.tanggal,u.nama""", (bulan,))
    data = cur.fetchall()
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = f"Absensi {bulan}"
    for col,w in zip('ABCDEFGHIJK',[12,14,22,18,20,12,12,14,10,15,20]):
        ws.column_dimensions[col].width = w
    ws.merge_cells('A1:K1')
    ws['A1'] = f"LAPORAN ABSENSI - {settings['nama_perusahaan'] if settings else 'PT Absensi'}"
    ws['A1'].font = Font(bold=True,size=14); ws['A1'].alignment = Alignment(horizontal='center')
    ws.merge_cells('A2:K2'); ws['A2'] = f"Periode: {bulan}"
    ws['A2'].alignment = Alignment(horizontal='center')
    for col,h in enumerate(['Tanggal','NIK','Nama','Departemen','Jabatan','Jam Masuk','Jam Keluar','Jarak (m)','Status','Shift','Keterangan'],1):
        cell = ws.cell(4,col,h); cell.font = Font(bold=True,color='FFFFFF')
        cell.fill = PatternFill(fill_type='solid',fgColor='1E3A5F')
        cell.alignment = Alignment(horizontal='center')
    sc = {'hadir':'C8E6C9','telat':'FFE082','izin':'BBDEFB','alpha':'FFCDD2'}
    for ri,row in enumerate(data,5):
        for col,val in enumerate([str(row['tanggal']),row['nik'],row['nama'],
            row['departemen'] or '-',row['jabatan'] or '-',str(row['jam_masuk'] or '-'),
            str(row['jam_keluar'] or '-'),f"{row['jarak_masuk']:.0f}" if row['jarak_masuk'] else '-',
            row['status'],row['shift_nama'] or '-',row['keterangan'] or ''],1):
            cell = ws.cell(ri,col,val)
            cell.fill = PatternFill(fill_type='solid',fgColor=sc.get(row['status'],'FFFFFF'))
    out = io.BytesIO(); wb.save(out); out.seek(0)
    return send_file(out,as_attachment=True,download_name=f"absensi_{bulan}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/admin/export/pdf')
@admin_required
def export_pdf():
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT a.tanggal,u.nik,u.nama,u.departemen,a.jam_masuk,a.jam_keluar,
        a.jarak_masuk,a.status,s.nama as shift_nama
        FROM absensi a JOIN users u ON a.user_id=u.id LEFT JOIN shift s ON a.shift_id=s.id
        WHERE TO_CHAR(a.tanggal,'YYYY-MM')=%s ORDER BY a.tanggal,u.nama""", (bulan,))
    data = cur.fetchall()
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    out = io.BytesIO()
    doc = SimpleDocTemplate(out,pagesize=landscape(A4),rightMargin=1*cm,leftMargin=1*cm,topMargin=2*cm,bottomMargin=1*cm)
    el = [Paragraph(f"LAPORAN ABSENSI - {settings['nama_perusahaan'] if settings else 'PT Absensi'}",
              ParagraphStyle('T',fontSize=14,spaceAfter=4,fontName='Helvetica-Bold',alignment=1)),
          Paragraph(f"Periode: {bulan}", ParagraphStyle('S',fontSize=10,spaceAfter=10,alignment=1)),
          Spacer(1,0.3*cm)]
    td = [['No','Tanggal','NIK','Nama','Dept','Shift','Masuk','Keluar','Jarak','Status']]
    for i,row in enumerate(data,1):
        td.append([i,str(row['tanggal']),row['nik'],row['nama'],row['departemen'] or '-',
            row['shift_nama'] or '-',str(row['jam_masuk'] or '-'),str(row['jam_keluar'] or '-'),
            f"{row['jarak_masuk']:.0f}m" if row['jarak_masuk'] else '-',row['status']])
    t = Table(td,colWidths=[0.8*cm,2.2*cm,2.2*cm,3.5*cm,2.5*cm,2.5*cm,2*cm,2*cm,1.8*cm,1.8*cm])
    sc2 = {'hadir':colors.HexColor('#C8E6C9'),'telat':colors.HexColor('#FFE082'),'izin':colors.HexColor('#BBDEFB')}
    sty = [('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1E3A5F')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
           ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),
           ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F5F5F5')]),
           ('GRID',(0,0),(-1,-1),0.5,colors.grey),('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]
    for i,row in enumerate(data,1):
        c = sc2.get(row['status'])
        if c: sty.append(('BACKGROUND',(9,i),(9,i),c))
    t.setStyle(TableStyle(sty)); el.append(t); doc.build(el); out.seek(0)
    return send_file(out,as_attachment=True,download_name=f"absensi_{bulan}.pdf",mimetype='application/pdf')

# ── LAPORAN PER PEGAWAI ───────────────────────────────────────────────────────
@app.route('/admin/laporan/pegawai')
@admin_required
def laporan_per_pegawai():
    conn = get_db(); cur = q(conn)
    bulan     = request.args.get('bulan', date.today().strftime('%Y-%m'))
    dept_id   = request.args.get('dept_id', '')
    status_f  = request.args.get('status_filter', '')

    # Daftar departemen untuk filter
    cur.execute("SELECT id, nama FROM departemen WHERE aktif=1 ORDER BY nama")
    daftar_dept = cur.fetchall()

    # Query pegawai
    where = ["u.role='user'", "u.status='active'"]
    params = []
    if dept_id:
        where.append("u.departemen_id=%s"); params.append(dept_id)
    cur.execute(f"""SELECT u.id,u.nik,u.nama,u.jabatan,u.departemen,u.foto,
        d.nama as dept_nama, s.nama as shift_nama, s.jam_masuk as shift_masuk, s.jam_keluar as shift_keluar
        FROM users u
        LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id
        WHERE {' AND '.join(where)} ORDER BY u.nama""", params)
    users = cur.fetchall()

    # Hitung hari kerja dalam bulan (Senin-Sabtu kecuali Minggu)
    y, m   = map(int, bulan.split('-'))
    import calendar
    total_hari_kerja = sum(
        1 for d2 in range(1, calendar.monthrange(y, m)[1]+1)
        if date(y, m, d2).weekday() < 6  # 0=Senin..5=Sabtu, 6=Minggu
    )

    rekap = []
    for u in users:
        cur.execute("""
            SELECT tanggal, jam_masuk, jam_keluar, status, keterangan,
                   jarak_masuk, shift_id
            FROM absensi
            WHERE user_id=%s AND TO_CHAR(tanggal,'YYYY-MM')=%s
            ORDER BY tanggal
        """, (u['id'], bulan))
        absensi_list = cur.fetchall()

        hadir  = sum(1 for a in absensi_list if a['status'] == 'hadir')
        telat  = sum(1 for a in absensi_list if a['status'] == 'telat')
        izin   = sum(1 for a in absensi_list if a['status'] == 'izin')
        alpha  = sum(1 for a in absensi_list if a['status'] == 'alpha')
        total_masuk = hadir + telat
        pct    = round(total_masuk / total_hari_kerja * 100) if total_hari_kerja else 0
        alpha_real = max(0, total_hari_kerja - hadir - telat - izin - alpha)

        row = {
            'user'        : u,
            'hadir'       : hadir,
            'telat'       : telat,
            'izin'        : izin,
            'alpha'       : alpha + alpha_real,
            'total_masuk' : total_masuk,
            'pct'         : pct,
            'hari_kerja'  : total_hari_kerja,
            'absensi'     : absensi_list,
        }
        if status_f == 'baik'   and pct <  90: continue
        if status_f == 'cukup'  and not (75 <= pct < 90): continue
        if status_f == 'kurang' and pct >= 75: continue
        rekap.append(row)

    cur.close(); conn.close()
    return render_template('admin/laporan_pegawai.html',
        rekap=rekap, bulan=bulan, daftar_dept=daftar_dept,
        dept_id=dept_id, status_filter=status_f,
        total_hari_kerja=total_hari_kerja)


@app.route('/admin/laporan/pegawai/<int:uid>')
@admin_required
def laporan_detail_pegawai(uid):
    conn = get_db(); cur = q(conn)
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))

    cur.execute("""SELECT u.*,d.nama as dept_nama,s.nama as shift_nama,
        s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar,s.toleransi_menit
        FROM users u
        LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id
        WHERE u.id=%s""", (uid,))
    user = cur.fetchone()
    if not user:
        cur.close(); conn.close()
        flash('Pegawai tidak ditemukan', 'error')
        return redirect(url_for('laporan_per_pegawai'))

    cur.execute("""
        SELECT a.*, s.nama as shift_nama, s.jam_masuk as sft_masuk, s.jam_keluar as sft_keluar
        FROM absensi a
        LEFT JOIN shift s ON a.shift_id=s.id
        WHERE a.user_id=%s AND TO_CHAR(a.tanggal,'YYYY-MM')=%s
        ORDER BY a.tanggal
    """, (uid, bulan))
    absensi_list = cur.fetchall()

    # Izin bulan ini
    cur.execute("""SELECT * FROM izin WHERE user_id=%s
        AND TO_CHAR(tanggal_mulai,'YYYY-MM')=%s ORDER BY tanggal_mulai""",
        (uid, bulan))
    izin_list = cur.fetchall()

    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()

    # Statistik
    hadir  = sum(1 for a in absensi_list if a['status'] == 'hadir')
    telat  = sum(1 for a in absensi_list if a['status'] == 'telat')
    izin_c = sum(1 for a in absensi_list if a['status'] == 'izin')
    alpha  = sum(1 for a in absensi_list if a['status'] == 'alpha')

    import calendar
    y, m = map(int, bulan.split('-'))
    total_hari_kerja = sum(
        1 for d2 in range(1, calendar.monthrange(y, m)[1]+1)
        if date(y, m, d2).weekday() < 6
    )
    total_masuk = hadir + telat
    pct = round(total_masuk / total_hari_kerja * 100) if total_hari_kerja else 0

    # Build kalender
    cal_data = {}
    for a in absensi_list:
        cal_data[str(a['tanggal'])] = a

    # Buat list hari dalam bulan
    bulan_days = []
    for d2 in range(1, calendar.monthrange(y, m)[1]+1):
        tgl = date(y, m, d2)
        tgl_str = tgl.isoformat()
        bulan_days.append({
            'tanggal' : tgl,
            'hari'    : tgl.strftime('%a'),
            'is_minggu': tgl.weekday() == 6,
            'absensi' : cal_data.get(tgl_str),
        })

    return render_template('admin/laporan_detail_pegawai.html',
        user=user, bulan=bulan, absensi_list=absensi_list,
        izin_list=izin_list, hadir=hadir, telat=telat,
        izin_c=izin_c, alpha=alpha,
        total_masuk=total_masuk, total_hari_kerja=total_hari_kerja,
        pct=pct, bulan_days=bulan_days, settings=settings)


@app.route('/admin/laporan/pegawai/<int:uid>/export-excel')
@admin_required
def laporan_pegawai_export_excel(uid):
    conn = get_db(); cur = q(conn)
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))

    cur.execute("""SELECT u.*,d.nama as dept_nama,s.nama as shift_nama,
        s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()

    cur.execute("""SELECT a.*,s.nama as shift_nama,s.jam_masuk as sft_masuk
        FROM absensi a LEFT JOIN shift s ON a.shift_id=s.id
        WHERE a.user_id=%s AND TO_CHAR(a.tanggal,'YYYY-MM')=%s
        ORDER BY a.tanggal""", (uid, bulan))
    rows = cur.fetchall()

    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()

    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = f"Absensi {user['nama']}"

    # Column widths
    for col, w in zip('ABCDEFGHI', [12,10,12,12,14,14,14,12,25]):
        ws.column_dimensions[col].width = w

    navy  = 'FF1E3A5F'
    green = 'FFC8E6C9'; yellow = 'FFFFE082'; blue = 'FFBBDEFB'; red = 'FFFFCDD2'; grey = 'FFF5F5F5'

    def cell_style(cell, bold=False, bg=None, align='left', color='FF000000', size=10):
        cell.font = Font(bold=bold, size=size, color=color)
        if bg: cell.fill = PatternFill(fill_type='solid', fgColor=bg)
        cell.alignment = Alignment(horizontal=align, vertical='center', wrap_text=True)

    instansi = settings['nama_perusahaan'] if settings else 'RST Slamet Riyadi'

    ws.merge_cells('A1:I1'); ws['A1'] = instansi.upper()
    cell_style(ws['A1'], bold=True, bg=navy, align='center', color='FFFFFFFF', size=12)
    ws.row_dimensions[1].height = 22

    ws.merge_cells('A2:I2'); ws['A2'] = f'LAPORAN ABSENSI PEGAWAI - {bulan}'
    cell_style(ws['A2'], bold=True, align='center', bg='FFE8EFF8', size=11)

    ws.merge_cells('A3:I3'); ws['A3'] = ''
    ws.row_dimensions[3].height = 6

    # Info pegawai
    info = [
        ('Nama', user['nama']),  ('NIK/NRP', user['nik'] or '-'),
        ('Jabatan', user['jabatan'] or '-'), ('Departemen', user['dept_nama'] or '-'),
        ('Shift', f"{user['shift_nama'] or '-'} ({user['shift_masuk'] or '-'} - {user['shift_keluar'] or '-'})"),
        ('Periode', bulan),
    ]
    for i, (lbl, val) in enumerate(info, 4):
        ws[f'A{i}'] = lbl; ws[f'B{i}'] = ':'
        ws.merge_cells(f'C{i}:I{i}'); ws[f'C{i}'] = val
        cell_style(ws[f'A{i}'], bold=True)
        cell_style(ws[f'C{i}'])
    ws.row_dimensions[9].height = 6

    # Header tabel
    headers = ['Tanggal', 'Hari', 'Jam Masuk', 'Jam Keluar', 'Shift', 'Jarak (m)', 'Status', 'Keterangan']
    for col, h in enumerate(headers, 1):
        c = ws.cell(10, col, h)
        cell_style(c, bold=True, bg=navy, align='center', color='FFFFFFFF')
    ws.row_dimensions[10].height = 18

    # Data
    sc = {'hadir': green, 'telat': yellow, 'izin': blue, 'alpha': red}
    for ri, row in enumerate(rows, 11):
        tgl = row['tanggal']
        hari = tgl.strftime('%A') if hasattr(tgl, 'strftime') else '-'
        bg_row = sc.get(row['status'], 'FFFFFFFF')
        vals = [
            str(tgl), hari,
            str(row['jam_masuk'] or '-'), str(row['jam_keluar'] or '-'),
            row['shift_nama'] or '-',
            f"{row['jarak_masuk']:.0f}" if row['jarak_masuk'] else '-',
            (row['status'] or '-').upper(), row['keterangan'] or '-'
        ]
        for col, val in enumerate(vals, 1):
            c = ws.cell(ri, col, val)
            cell_style(c, bg=bg_row if col in (7,) else grey if ri % 2 == 0 else None,
                       align='center' if col in (1,2,3,4,6,7) else 'left')

    # Statistik
    hadir  = sum(1 for r in rows if r['status']=='hadir')
    telat  = sum(1 for r in rows if r['status']=='telat')
    izin   = sum(1 for r in rows if r['status']=='izin')
    alpha  = sum(1 for r in rows if r['status']=='alpha')

    sr = len(rows) + 12
    ws.row_dimensions[sr].height = 6
    stats = [
        ('Hadir', hadir, green), ('Telat', telat, yellow),
        ('Izin', izin, blue),  ('Alpha', alpha, red),
        ('Total Hadir+Telat', hadir+telat, 'FFFFFFFF'),
    ]
    for i, (lbl, val, bg) in enumerate(stats):
        r = sr + 1 + i
        ws[f'A{r}'] = lbl; ws[f'B{r}'] = val
        cell_style(ws[f'A{r}'], bold=True, bg=bg)
        cell_style(ws[f'B{r}'], bold=True, align='center', bg=bg)

    out = io.BytesIO(); wb.save(out); out.seek(0)
    safe_name = re.sub(r'[^\w]', '_', user['nama'])
    log_audit(conn if False else get_db(), 'EXPORT', 'laporan',
              deskripsi=f'Export Excel laporan pegawai {user["nama"]} bulan {bulan}')
    return send_file(out, as_attachment=True,
        download_name=f"absensi_{safe_name}_{bulan}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/admin/laporan/pegawai/<int:uid>/export-pdf')
@admin_required
def laporan_pegawai_export_pdf(uid):
    conn = get_db(); cur = q(conn)
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))

    cur.execute("""SELECT u.*,d.nama as dept_nama,s.nama as shift_nama,
        s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()

    cur.execute("""SELECT a.*,s.nama as shift_nama
        FROM absensi a LEFT JOIN shift s ON a.shift_id=s.id
        WHERE a.user_id=%s AND TO_CHAR(a.tanggal,'YYYY-MM')=%s
        ORDER BY a.tanggal""", (uid, bulan))
    rows = cur.fetchall()

    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()

    hadir = sum(1 for r in rows if r['status']=='hadir')
    telat = sum(1 for r in rows if r['status']=='telat')
    izin  = sum(1 for r in rows if r['status']=='izin')
    alpha = sum(1 for r in rows if r['status']=='alpha')

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=2*cm, bottomMargin=1.5*cm)

    navy   = colors.HexColor('#1E3A5F')
    c_green= colors.HexColor('#C8E6C9')
    c_yell = colors.HexColor('#FFE082')
    c_blue = colors.HexColor('#BBDEFB')
    c_red  = colors.HexColor('#FFCDD2')
    c_grey = colors.HexColor('#F5F5F5')

    instansi = settings['nama_perusahaan'] if settings else 'RST Slamet Riyadi'

    el = []
    el.append(Paragraph(instansi.upper(),
        ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=13, alignment=1,
                       textColor=navy, spaceAfter=2)))
    el.append(Paragraph(f'LAPORAN ABSENSI PEGAWAI',
        ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=11, alignment=1, spaceAfter=2)))
    el.append(Paragraph(f'Periode: {bulan}',
        ParagraphStyle('H3', fontName='Helvetica', fontSize=9, alignment=1, spaceAfter=8,
                       textColor=colors.grey)))

    # Info pegawai
    info_data = [
        ['Nama', ':', user['nama'], 'NIK/NRP', ':', user['nik'] or '-'],
        ['Jabatan', ':', user['jabatan'] or '-', 'Departemen', ':', user['dept_nama'] or '-'],
        ['Shift', ':', f"{user['shift_nama'] or '-'} ({user['shift_masuk'] or '-'} - {user['shift_keluar'] or '-'})", '', '', ''],
    ]
    info_tbl = Table(info_data, colWidths=[2.2*cm,0.4*cm,5*cm,2.2*cm,0.4*cm,5*cm])
    info_tbl.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,-1),'Helvetica'),
        ('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),
        ('FONTNAME',(3,0),(3,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),
        ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#F0F4F8')),
        ('BOX',(0,0),(-1,-1),0.5,colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.HexColor('#F0F4F8'), colors.HexColor('#E8EFF8')]),
    ]))
    el.append(info_tbl); el.append(Spacer(1, 0.4*cm))

    # Tabel absensi
    td = [['No','Tanggal','Hari','Jam Masuk','Jam Keluar','Shift','Jarak','Status','Keterangan']]
    for i, row in enumerate(rows, 1):
        tgl = row['tanggal']
        hari = tgl.strftime('%a') if hasattr(tgl, 'strftime') else '-'
        td.append([
            str(i), str(tgl), hari,
            str(row['jam_masuk'] or '-'), str(row['jam_keluar'] or '-'),
            row['shift_nama'] or '-',
            f"{row['jarak_masuk']:.0f}m" if row['jarak_masuk'] else '-',
            (row['status'] or '-').upper(),
            row['keterangan'] or '-'
        ])

    col_w = [0.7*cm,2.3*cm,1.3*cm,2.1*cm,2.1*cm,2.5*cm,1.4*cm,1.6*cm,3*cm]
    t = Table(td, colWidths=col_w, repeatRows=1)
    sty = [
        ('BACKGROUND',(0,0),(-1,0), navy),
        ('TEXTCOLOR',(0,0),(-1,0), colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),7.5),
        ('ALIGN',(0,0),(-1,0),'CENTER'),
        ('ALIGN',(0,1),(7,-1),'CENTER'),
        ('ALIGN',(8,1),(8,-1),'LEFT'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('GRID',(0,0),(-1,-1),0.4, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, c_grey]),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('TOPPADDING',(0,0),(-1,-1),4),
    ]
    sc_map = {'hadir': c_green, 'telat': c_yell, 'izin': c_blue, 'alpha': c_red}
    for i, row in enumerate(rows, 1):
        c = sc_map.get(row['status'])
        if c: sty.append(('BACKGROUND',(7,i),(7,i), c))
    t.setStyle(TableStyle(sty))
    el.append(t); el.append(Spacer(1, 0.4*cm))

    # Rekap statistik
    stat_data = [
        ['Hadir', str(hadir), 'Telat', str(telat), 'Izin', str(izin), 'Alpha', str(alpha)],
    ]
    st = Table(stat_data, colWidths=[2*cm,1.2*cm,2*cm,1.2*cm,2*cm,1.2*cm,2*cm,1.2*cm])
    st.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,-1),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),9),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BACKGROUND',(0,0),(1,0), c_green),
        ('BACKGROUND',(2,0),(3,0), c_yell),
        ('BACKGROUND',(4,0),(5,0), c_blue),
        ('BACKGROUND',(6,0),(7,0), c_red),
        ('BOX',(0,0),(-1,-1),0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID',(0,0),(-1,-1),0.3, colors.HexColor('#CBD5E1')),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('TOPPADDING',(0,0),(-1,-1),5),
    ]))
    el.append(st)
    doc.build(el); out.seek(0)

    safe_name = re.sub(r'[^\w]', '_', user['nama'])
    return send_file(out, as_attachment=True,
        download_name=f"absensi_{safe_name}_{bulan}.pdf",
        mimetype='application/pdf')


# ── ADMIN GRAFIK ──────────────────────────────────────────────────────────────
@app.route('/admin/grafik')
@admin_required
def admin_grafik():
    conn = get_db(); cur = q(conn)
    bulan = request.args.get('bulan', date.today().strftime('%Y-%m'))
    cur.execute("""SELECT tanggal::text,
        SUM(CASE WHEN status='hadir' THEN 1 ELSE 0 END) as hadir,
        SUM(CASE WHEN status='telat' THEN 1 ELSE 0 END) as telat,
        SUM(CASE WHEN status='izin' THEN 1 ELSE 0 END) as izin
        FROM absensi WHERE TO_CHAR(tanggal,'YYYY-MM')=%s
        GROUP BY tanggal ORDER BY tanggal""", (bulan,))
    harian = cur.fetchall()
    cur.execute("""SELECT d.nama as departemen,d.warna,
        SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir,
        SUM(CASE WHEN a.status='telat' THEN 1 ELSE 0 END) as telat,
        SUM(CASE WHEN a.status='izin' THEN 1 ELSE 0 END) as izin,
        COUNT(a.id) as total
        FROM departemen d
        LEFT JOIN users u ON u.departemen_id=d.id AND u.role='user' AND u.status='active'
        LEFT JOIN absensi a ON u.id=a.user_id AND TO_CHAR(a.tanggal,'YYYY-MM')=%s
        WHERE d.aktif=1 GROUP BY d.id,d.nama,d.warna""", (bulan,))
    dept = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/grafik.html',
        harian=json.dumps([dict(r) for r in harian]),
        dept=json.dumps([dict(r) for r in dept]), bulan=bulan)

# ── ADMIN SETTINGS ────────────────────────────────────────────────────────────
@app.route('/admin/settings', methods=['GET','POST'])
@admin_required
def admin_settings():
    conn = get_db(); cur = q(conn)
    if request.method == 'POST':
        # Handle logo upload
        logo_filename = None
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            ext = logo_file.filename.rsplit('.', 1)[-1].lower() if '.' in logo_file.filename else ''
            if ext in {'png', 'jpg', 'jpeg', 'svg', 'gif', 'webp'}:
                logo_dir = os.path.join('static', 'uploads', 'logo')
                os.makedirs(logo_dir, exist_ok=True)
                logo_filename = secure_filename(f"logo.{ext}")
                logo_file.save(os.path.join(logo_dir, logo_filename))

        if logo_filename:
            cur.execute("""UPDATE settings SET nama_perusahaan=%s,
                office_lat=%s,office_lng=%s,max_distance=%s,logo=%s WHERE id=1""",
                (request.form['nama_perusahaan'],
                 float(request.form['office_lat']), float(request.form['office_lng']),
                 int(request.form['max_distance']), logo_filename))
        else:
            cur.execute("""UPDATE settings SET nama_perusahaan=%s,
                office_lat=%s,office_lng=%s,max_distance=%s WHERE id=1""",
                (request.form['nama_perusahaan'],
                 float(request.form['office_lat']), float(request.form['office_lng']),
                 int(request.form['max_distance'])))
        conn.commit()
        log_audit(conn, 'SETTING', 'settings', deskripsi='Update pengaturan sistem',
            data_baru={'nama_perusahaan':request.form.get('nama_perusahaan'),
                       'office_lat':request.form.get('office_lat'),
                       'office_lng':request.form.get('office_lng'),
                       'max_distance':request.form.get('max_distance')})
        flash('Settings disimpan!', 'success')
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    return render_template('admin/settings.html', settings=settings)

@app.route('/admin/settings/ganti-password', methods=['POST'])
@admin_required
def admin_ganti_password_sendiri():
    uid = session['user_id']
    pw_lama     = request.form.get('password_lama', '')
    pw_baru     = request.form.get('password_baru', '')
    pw_konfirm  = request.form.get('password_konfirm', '')
    if not pw_baru or len(pw_baru) < 6:
        flash('Password baru minimal 6 karakter.', 'error')
        return redirect(url_for('admin_settings') + '#keamanan')
    if pw_baru != pw_konfirm:
        flash('Konfirmasi password tidak cocok.', 'error')
        return redirect(url_for('admin_settings') + '#keamanan')
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT password FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user or not check_password_hash(user['password'], pw_lama):
        flash('Password lama salah.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('admin_settings') + '#keamanan')
    cur.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(pw_baru), uid))
    conn.commit()
    log_audit(conn, 'PASSWORD', 'settings',
        deskripsi=f'Admin ganti password: {session.get("nama")}',
        ref_id=uid, ref_table='users')
    cur.close(); conn.close()
    flash('Password admin berhasil diubah!', 'success')
    return redirect(url_for('admin_settings') + '#keamanan')

@app.route('/admin/settings/hapus-logo', methods=['POST'])
@admin_required
def hapus_logo():
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT logo FROM settings WHERE id=1")
    s = cur.fetchone()
    if s and s['logo']:
        path = os.path.join('static', 'uploads', 'logo', s['logo'])
        if os.path.exists(path):
            os.remove(path)
        cur.execute("UPDATE settings SET logo=NULL WHERE id=1")
        conn.commit()
        flash('Logo berhasil dihapus.', 'success')
    cur.close(); conn.close()
    return redirect(url_for('admin_settings'))

# ── API ───────────────────────────────────────────────────────────────────────
@app.route('/api/shift-by-dept/<int:dept_id>')
@login_required
def api_shift_by_dept(dept_id):
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT s.* FROM shift s JOIN departemen_shift ds ON s.id=ds.shift_id
        WHERE ds.departemen_id=%s AND s.aktif=1""", (dept_id,))
    shifts = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(s) for s in shifts])

# ── UBAH PASSWORD ─────────────────────────────────────────────────────────────

@app.route('/ubah-password', methods=['POST'])
@login_required
def ubah_password():
    uid = session['user_id']
    pw_lama = request.form.get('password_lama','')
    pw_baru = request.form.get('password_baru','')
    pw_konfirm = request.form.get('password_konfirm','')
    if not pw_baru or len(pw_baru) < 6:
        flash('Password baru minimal 6 karakter.', 'error')
        return redirect(url_for('profil'))
    if pw_baru != pw_konfirm:
        flash('Konfirmasi password tidak cocok.', 'error')
        return redirect(url_for('profil'))
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT password FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user or not check_password_hash(user['password'], pw_lama):
        flash('Password lama salah.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('profil'))
    cur.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(pw_baru), uid))
    conn.commit()
    log_audit(conn, 'PASSWORD', 'profil',
        deskripsi=f'Ubah password: {session.get("nama")}',
        ref_id=uid, ref_table='users')
    cur.close(); conn.close()
    flash('Password berhasil diubah!', 'success')
    return redirect(url_for('profil'))

@app.route('/admin/pegawai/<int:uid>/ubah-password', methods=['POST'])
@admin_required
def admin_ubah_password(uid):
    pw_baru = request.form.get('password_baru','')
    pw_konfirm = request.form.get('password_konfirm','')
    if not pw_baru or len(pw_baru) < 6:
        flash('Password baru minimal 6 karakter.', 'error')
        return redirect(url_for('edit_pegawai', uid=uid))
    if pw_baru != pw_konfirm:
        flash('Konfirmasi password tidak cocok.', 'error')
        return redirect(url_for('edit_pegawai', uid=uid))
    conn = get_db(); cur = q(conn)
    cur.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(pw_baru), uid))
    conn.commit(); cur.close(); conn.close()
    flash('Password pegawai berhasil diubah!', 'success')
    return redirect(url_for('edit_pegawai', uid=uid))

# ── PEJABAT TTD ───────────────────────────────────────────────────────────────

@app.route('/admin/pejabat-ttd')
@admin_required
def admin_pejabat_ttd():
    conn = get_db(); cur = q(conn)
    # Buat tabel jika belum ada
    cur2 = conn.cursor()
    cur2.execute("""CREATE TABLE IF NOT EXISTS pejabat_ttd (
        id SERIAL PRIMARY KEY, nama TEXT NOT NULL, jabatan TEXT NOT NULL,
        nip TEXT, departemen_id INTEGER REFERENCES departemen(id) ON DELETE SET NULL,
        level_approval INTEGER NOT NULL DEFAULT 1, role_label TEXT NOT NULL DEFAULT 'Pejabat',
        ttd_file TEXT, aktif INTEGER DEFAULT 1, urutan INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); cur2.close()
    cur.execute("""SELECT p.*, d.nama as nama_dept FROM pejabat_ttd p
        LEFT JOIN departemen d ON p.departemen_id=d.id ORDER BY p.level_approval, p.urutan""")
    pejabat_list = cur.fetchall()
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/pejabat_ttd.html', pejabat_list=pejabat_list, depts=depts)

@app.route('/admin/pejabat-ttd/tambah', methods=['POST'])
@admin_required
def admin_pejabat_ttd_tambah():
    nama=request.form.get('nama','').strip(); jabatan=request.form.get('jabatan','').strip()
    nip=request.form.get('nip','').strip(); dept_id=request.form.get('departemen_id') or None
    level=int(request.form.get('level_approval',1)); role_label=request.form.get('role_label','').strip() or jabatan
    urutan=int(request.form.get('urutan',0))
    ttd_file=None; f=request.files.get('ttd_file')
    if f and f.filename:
        ext=f.filename.rsplit('.',1)[-1].lower()
        if ext in {'png','jpg','jpeg'}:
            os.makedirs(app.config['TTD_FOLDER'],exist_ok=True)
            fn=secure_filename(f"pjb_{nama.replace(' ','_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
            f.save(os.path.join(app.config['TTD_FOLDER'],fn)); ttd_file=fn
    conn=get_db(); cur=q(conn)
    cur.execute("""INSERT INTO pejabat_ttd (nama,jabatan,nip,departemen_id,level_approval,role_label,ttd_file,urutan)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", (nama,jabatan,nip,dept_id,level,role_label,ttd_file,urutan))
    conn.commit(); cur.close(); conn.close()
    flash(f'Pejabat {nama} berhasil ditambahkan.','success')
    return redirect(url_for('admin_pejabat_ttd'))

@app.route('/admin/pejabat-ttd/<int:pid>/edit', methods=['POST'])
@admin_required
def admin_pejabat_ttd_edit(pid):
    nama=request.form.get('nama','').strip(); jabatan=request.form.get('jabatan','').strip()
    nip=request.form.get('nip','').strip(); dept_id=request.form.get('departemen_id') or None
    level=int(request.form.get('level_approval',1)); role_label=request.form.get('role_label','').strip() or jabatan
    urutan=int(request.form.get('urutan',0)); aktif=int(request.form.get('aktif',1))
    conn=get_db(); cur=q(conn)
    f=request.files.get('ttd_file')
    if f and f.filename:
        ext=f.filename.rsplit('.',1)[-1].lower()
        if ext in {'png','jpg','jpeg'}:
            os.makedirs(app.config['TTD_FOLDER'],exist_ok=True)
            fn=secure_filename(f"pjb_{pid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
            f.save(os.path.join(app.config['TTD_FOLDER'],fn))
            cur.execute("""UPDATE pejabat_ttd SET nama=%s,jabatan=%s,nip=%s,departemen_id=%s,
                level_approval=%s,role_label=%s,ttd_file=%s,urutan=%s,aktif=%s WHERE id=%s""",
                (nama,jabatan,nip,dept_id,level,role_label,fn,urutan,aktif,pid))
        else:
            cur.execute("""UPDATE pejabat_ttd SET nama=%s,jabatan=%s,nip=%s,departemen_id=%s,
                level_approval=%s,role_label=%s,urutan=%s,aktif=%s WHERE id=%s""",
                (nama,jabatan,nip,dept_id,level,role_label,urutan,aktif,pid))
    else:
        cur.execute("""UPDATE pejabat_ttd SET nama=%s,jabatan=%s,nip=%s,departemen_id=%s,
            level_approval=%s,role_label=%s,urutan=%s,aktif=%s WHERE id=%s""",
            (nama,jabatan,nip,dept_id,level,role_label,urutan,aktif,pid))
    conn.commit(); cur.close(); conn.close()
    flash('Data pejabat berhasil diperbarui.','success')
    return redirect(url_for('admin_pejabat_ttd'))

@app.route('/admin/pejabat-ttd/<int:pid>/hapus', methods=['POST'])
@admin_required
def admin_pejabat_ttd_hapus(pid):
    conn=get_db(); cur=q(conn)
    cur.execute("DELETE FROM pejabat_ttd WHERE id=%s",(pid,))
    conn.commit(); cur.close(); conn.close()
    flash('Pejabat berhasil dihapus.','success')
    return redirect(url_for('admin_pejabat_ttd'))

@app.route('/api/pejabat-ttd')
@login_required
def api_pejabat_ttd():
    level=request.args.get('level',type=int)
    conn=get_db(); cur=q(conn)
    if level:
        cur.execute("""SELECT id,nama,jabatan,role_label,ttd_file FROM pejabat_ttd
            WHERE aktif=1 AND level_approval=%s ORDER BY urutan""",(level,))
    else:
        cur.execute("""SELECT id,nama,jabatan,role_label,level_approval,ttd_file
            FROM pejabat_ttd WHERE aktif=1 ORDER BY level_approval,urutan""")
    data=cur.fetchall(); cur.close(); conn.close()
    return jsonify(data)



# ══════════════════════════════════════════════════════════════════════════════
# ── E-DOSIR USER ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/dosir')
@login_required
def dosir():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    dept_id = user['departemen_id'] if user else None

    # Jenis dokumen yang perlu diupload (global + dept)
    if dept_id:
        cur.execute("""SELECT * FROM dosir_jenis
            WHERE aktif=1 AND (departemen_id IS NULL OR departemen_id=%s)
            ORDER BY urutan, nama""", (dept_id,))
    else:
        cur.execute("SELECT * FROM dosir_jenis WHERE aktif=1 AND departemen_id IS NULL ORDER BY urutan, nama")
    jenis_list = cur.fetchall()

    # File yang sudah diupload user
    cur.execute("SELECT * FROM dosir_file WHERE user_id=%s", (uid,))
    uploads = {r['jenis_id']: dict(r) for r in cur.fetchall()}

    cur.close(); conn.close()
    return render_template('dosir.html', jenis_list=jenis_list, uploads=uploads, user=user, today=date.today())


@app.route('/dosir/upload/<int:jid>', methods=['POST'])
@login_required
def dosir_upload(jid):
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM dosir_jenis WHERE id=%s AND aktif=1", (jid,))
    jenis = cur.fetchone()
    if not jenis:
        flash('Jenis dokumen tidak ditemukan.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('dosir'))

    f = request.files.get('file')
    keterangan = request.form.get('keterangan', '').strip()
    tgl_expired_raw = request.form.get('tanggal_expired', '').strip()
    tanggal_expired = tgl_expired_raw if tgl_expired_raw else None
    if not f or not f.filename:
        flash('Pilih file terlebih dahulu.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('dosir'))

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_DOSIR:
        flash('Format file tidak diizinkan. Gunakan PDF, JPG, atau PNG.', 'error')
        cur.close(); conn.close()
        return redirect(url_for('dosir'))

    dosir_folder = app.config['DOSIR_FOLDER']
    os.makedirs(dosir_folder, exist_ok=True)
    original = f.filename
    fn = secure_filename(f"dosir_{uid}_{jid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
    f.save(os.path.join(dosir_folder, fn))

    cur.execute("""INSERT INTO dosir_file (user_id, jenis_id, filename, original_name, keterangan, tanggal_expired, status)
        VALUES (%s,%s,%s,%s,%s,%s,'pending')
        ON CONFLICT (user_id, jenis_id) DO UPDATE
        SET filename=EXCLUDED.filename, original_name=EXCLUDED.original_name,
            keterangan=EXCLUDED.keterangan, tanggal_expired=EXCLUDED.tanggal_expired,
            status='pending', catatan_admin=NULL, uploaded_at=CURRENT_TIMESTAMP, verified_at=NULL""",
        (uid, jid, fn, original, keterangan, tanggal_expired))
    conn.commit()
    cur.close(); conn.close()
    flash(f'Dokumen "{jenis["nama"]}" berhasil diupload. Menunggu verifikasi admin.', 'success')
    return redirect(url_for('dosir'))


@app.route('/dosir/file/<int:fid>')
@login_required
def dosir_view(fid):
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM dosir_file WHERE id=%s AND user_id=%s", (fid, uid))
    df = cur.fetchone()
    cur.close(); conn.close()
    if not df:
        flash('File tidak ditemukan.', 'error')
        return redirect(url_for('dosir'))
    path = os.path.join(app.config['DOSIR_FOLDER'], df['filename'])
    return send_file(path, as_attachment=False)


# ══════════════════════════════════════════════════════════════════════════════
# ── E-DOSIR ADMIN ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/dosir')
@admin_required
def admin_dosir():
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.execute("""SELECT dj.*, d.nama as dept_nama
        FROM dosir_jenis dj LEFT JOIN departemen d ON dj.departemen_id=d.id
        WHERE dj.aktif=1 ORDER BY dj.urutan, dj.nama""")
    jenis_list = cur.fetchall()
    # Statistik upload per jenis
    try:
        cur.execute("""SELECT jenis_id,
            COUNT(*) as total,
            SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) as verified,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected,
            SUM(CASE WHEN tanggal_expired IS NOT NULL AND tanggal_expired < CURRENT_DATE THEN 1 ELSE 0 END) as expired
            FROM dosir_file GROUP BY jenis_id""")
    except Exception:
        conn.rollback()
        cur.execute("""SELECT jenis_id,
            COUNT(*) as total,
            SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) as verified,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected,
            0 as expired
            FROM dosir_file GROUP BY jenis_id""")
    stats = {r['jenis_id']: dict(r) for r in cur.fetchall()}
    cur.close(); conn.close()
    return render_template('admin/dosir.html', depts=depts, jenis_list=jenis_list, stats=stats)


@app.route('/admin/dosir/jenis/tambah', methods=['POST'])
@admin_required
def admin_dosir_tambah():
    nama = request.form.get('nama','').strip()
    deskripsi = request.form.get('deskripsi','').strip()
    wajib = 1 if request.form.get('wajib') else 0
    dept_id = request.form.get('departemen_id') or None
    urutan = request.form.get('urutan', 0)
    if not nama:
        flash('Nama dokumen tidak boleh kosong.', 'error')
        return redirect(url_for('admin_dosir'))
    conn = get_db(); cur = q(conn)
    cur.execute("""INSERT INTO dosir_jenis (nama,deskripsi,wajib,departemen_id,urutan)
        VALUES (%s,%s,%s,%s,%s)""", (nama, deskripsi, wajib, dept_id, urutan))
    conn.commit(); cur.close(); conn.close()
    flash(f'Jenis dokumen "{nama}" berhasil ditambahkan.', 'success')
    return redirect(url_for('admin_dosir'))


@app.route('/admin/dosir/jenis/edit/<int:jid>', methods=['POST'])
@admin_required
def admin_dosir_edit(jid):
    nama = request.form.get('nama','').strip()
    deskripsi = request.form.get('deskripsi','').strip()
    wajib = 1 if request.form.get('wajib') else 0
    dept_id = request.form.get('departemen_id') or None
    urutan = request.form.get('urutan', 0)
    conn = get_db(); cur = q(conn)
    cur.execute("""UPDATE dosir_jenis SET nama=%s,deskripsi=%s,wajib=%s,departemen_id=%s,urutan=%s
        WHERE id=%s""", (nama, deskripsi, wajib, dept_id, urutan, jid))
    conn.commit(); cur.close(); conn.close()
    flash('Jenis dokumen berhasil diperbarui.', 'success')
    return redirect(url_for('admin_dosir'))


@app.route('/admin/dosir/jenis/hapus/<int:jid>', methods=['POST'])
@admin_required
def admin_dosir_hapus(jid):
    conn = get_db(); cur = q(conn)
    cur.execute("UPDATE dosir_jenis SET aktif=0 WHERE id=%s", (jid,))
    conn.commit(); cur.close(); conn.close()
    flash('Jenis dokumen berhasil dihapus.', 'success')
    return redirect(url_for('admin_dosir'))


@app.route('/admin/dosir/files')
@admin_required
def admin_dosir_files():
    conn = get_db(); cur = q(conn)
    dept_id = request.args.get('dept_id')
    status_filter = request.args.get('status', '')
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    params = []
    where = " WHERE 1=1"
    if dept_id:
        where += " AND u.departemen_id=%s"; params.append(dept_id)
    if status_filter == 'expired':
        where += " AND df.tanggal_expired IS NOT NULL AND df.tanggal_expired < CURRENT_DATE"
    elif status_filter:
        where += " AND df.status=%s"; params.append(status_filter)
    try:
        query = """SELECT df.*,
            u.nama as user_nama, u.nik, d.nama as dept_nama,
            dj.nama as jenis_nama, dj.wajib,
            CASE WHEN df.tanggal_expired IS NOT NULL AND df.tanggal_expired < CURRENT_DATE THEN TRUE ELSE FALSE END as is_expired
            FROM dosir_file df
            JOIN users u ON df.user_id=u.id
            LEFT JOIN departemen d ON u.departemen_id=d.id
            JOIN dosir_jenis dj ON df.jenis_id=dj.id""" + where + " ORDER BY df.uploaded_at DESC"
        cur.execute(query, params)
    except Exception:
        conn.rollback()
        query = """SELECT df.*,
            u.nama as user_nama, u.nik, d.nama as dept_nama,
            dj.nama as jenis_nama, dj.wajib,
            FALSE as is_expired
            FROM dosir_file df
            JOIN users u ON df.user_id=u.id
            LEFT JOIN departemen d ON u.departemen_id=d.id
            JOIN dosir_jenis dj ON df.jenis_id=dj.id""" + where + " ORDER BY df.uploaded_at DESC"
        cur.execute(query, params)
    files = cur.fetchall()
    cur.close(); conn.close()

    # Build stats dict keyed by jenis_nama so the template can sum verified counts
    stats = {}
    for f in files:
        key = f['jenis_nama'] or 'Lainnya'
        if key not in stats:
            stats[key] = {'total': 0, 'verified': 0, 'pending': 0, 'rejected': 0}
        stats[key]['total'] += 1
        status_val = f.get('status', '')
        if status_val == 'verified':
            stats[key]['verified'] += 1
        elif status_val == 'rejected':
            stats[key]['rejected'] += 1
        else:
            stats[key]['pending'] += 1

    return render_template('admin/dosir_files.html', files=files, depts=depts,
        dept_id=dept_id, status_filter=status_filter, today=date.today(), stats=stats)


@app.route('/admin/dosir/verify/<int:fid>/<action>', methods=['POST'])
@admin_required
def admin_dosir_verify(fid, action):
    catatan = request.form.get('catatan','').strip()
    tgl_expired_raw = request.form.get('tanggal_expired','').strip()
    tanggal_expired = tgl_expired_raw if tgl_expired_raw else None
    conn = get_db(); cur = q(conn)
    if action == 'verify':
        cur.execute("""UPDATE dosir_file SET status='verified', catatan_admin=%s,
            tanggal_expired=COALESCE(%s::DATE, tanggal_expired),
            verified_at=CURRENT_TIMESTAMP WHERE id=%s""", (catatan, tanggal_expired, fid))
        flash('Dokumen berhasil diverifikasi.', 'success')
    elif action == 'reject':
        cur.execute("""UPDATE dosir_file SET status='rejected', catatan_admin=%s,
            tanggal_expired=COALESCE(%s::DATE, tanggal_expired),
            verified_at=CURRENT_TIMESTAMP WHERE id=%s""", (catatan, tanggal_expired, fid))
        flash('Dokumen ditolak.', 'info')
    conn.commit(); cur.close(); conn.close()
    return redirect(url_for('admin_dosir_files', **request.args))


@app.route('/admin/dosir/file/<int:fid>')
@admin_required
def admin_dosir_view(fid):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM dosir_file WHERE id=%s", (fid,))
    df = cur.fetchone()
    cur.close(); conn.close()
    if not df:
        flash('File tidak ditemukan.', 'error')
        return redirect(url_for('admin_dosir_files'))
    path = os.path.join(app.config['DOSIR_FOLDER'], df['filename'])
    return send_file(path, as_attachment=False)


# ══════════════════════════════════════════════════════════════════════════════
# ── HELPER NOTIFIKASI ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def kirim_notif(conn, user_id, judul, pesan, tipe='info', ref_id=None, ref_type=None):
    cur = conn.cursor()
    cur.execute("""INSERT INTO notifikasi (user_id,judul,pesan,tipe,ref_id,ref_type)
        VALUES (%s,%s,%s,%s,%s,%s)""", (user_id, judul, pesan, tipe, ref_id, ref_type))
    cur.close()

@app.route('/api/notifikasi')
@login_required
def api_notifikasi():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT * FROM notifikasi WHERE user_id=%s ORDER BY created_at DESC LIMIT 20""", (uid,))
    notifs = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) as c FROM notifikasi WHERE user_id=%s AND dibaca=0", (uid,))
    unread = cur.fetchone()['c']
    cur.close(); conn.close()
    return jsonify({'notifs': notifs, 'unread': unread})

@app.route('/notifikasi/baca/<int:nid>', methods=['POST'])
@login_required
def baca_notif(nid):
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("UPDATE notifikasi SET dibaca=1 WHERE id=%s AND user_id=%s", (nid, uid))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/notifikasi/baca-semua', methods=['POST'])
@login_required
def baca_semua_notif():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("UPDATE notifikasi SET dibaca=1 WHERE user_id=%s", (uid,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

@app.route('/notifikasi')
@login_required
def halaman_notifikasi():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT * FROM notifikasi WHERE user_id=%s ORDER BY created_at DESC LIMIT 50""", (uid,))
    notifs = [dict(r) for r in cur.fetchall()]
    # Tandai semua sebagai dibaca saat halaman dibuka
    cur.execute("UPDATE notifikasi SET dibaca=1 WHERE user_id=%s", (uid,))
    conn.commit(); cur.close(); conn.close()
    return render_template('notifikasi.html', notifs=notifs)

# ══════════════════════════════════════════════════════════════════════════════
# ── SURAT PERINTAH ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/surat')
@login_required
def surat_user():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT sp.*, u.nama as pembuat, sp2.dibaca
        FROM surat_penerima sp2
        JOIN surat_perintah sp ON sp.id=sp2.surat_id
        JOIN users u ON sp.dibuat_oleh=u.id
        WHERE sp2.user_id=%s ORDER BY sp.created_at DESC""", (uid,))
    surat_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template('surat_user.html', surat_list=surat_list)

@app.route('/surat/<int:sid>')
@login_required
def surat_detail(sid):
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    # Tandai sudah dibaca
    cur.execute("""UPDATE surat_penerima SET dibaca=1, dibaca_at=CURRENT_TIMESTAMP
        WHERE surat_id=%s AND user_id=%s""", (sid, uid))
    cur.execute("""SELECT sp.*, u.nama as pembuat, u.jabatan as pembuat_jabatan
        FROM surat_perintah sp JOIN users u ON sp.dibuat_oleh=u.id WHERE sp.id=%s""", (sid,))
    surat = cur.fetchone()
    cur.execute("""SELECT u.nama, u.jabatan, sp2.dibaca, sp2.dibaca_at
        FROM surat_penerima sp2 JOIN users u ON sp2.user_id=u.id
        WHERE sp2.surat_id=%s""", (sid,))
    penerima = cur.fetchall()
    conn.commit(); cur.close(); conn.close()
    if not surat:
        flash('Surat tidak ditemukan.', 'error')
        return redirect(url_for('surat_user'))
    return render_template('surat_detail.html', surat=surat, penerima=penerima)

@app.route('/surat/<int:sid>/pdf')
@login_required
def surat_pdf(sid):
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT sp.*,u.nama as pembuat,u.jabatan as pembuat_jabatan
        FROM surat_perintah sp JOIN users u ON sp.dibuat_oleh=u.id WHERE sp.id=%s""", (sid,))
    surat = cur.fetchone()
    cur.execute("""SELECT u.* FROM surat_penerima sp2
        JOIN users u ON sp2.user_id=u.id WHERE sp2.surat_id=%s AND sp2.user_id=%s""", (sid, uid))
    penerima_user = cur.fetchone()
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    if not surat:
        flash('Surat tidak ditemukan.', 'error')
        return redirect(url_for('surat_user'))
    # Generate PDF
    buf = io.BytesIO()
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    styles = getSampleStyleSheet()
    instansi = settings['nama_perusahaan'] if settings else 'RS Slamet Riyadi'
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=3*cm, rightMargin=2*cm)
    elems = []
    # Header
    elems.append(Paragraph(f"<b>{instansi.upper()}</b>", ParagraphStyle('h',fontSize=14,alignment=TA_CENTER,spaceAfter=4)))
    elems.append(Paragraph("Jl. Adisucipto No. 1, Surakarta", ParagraphStyle('sub',fontSize=10,alignment=TA_CENTER,spaceAfter=2)))
    elems.append(Spacer(1, 0.3*cm))
    from reportlab.platypus import HRFlowable
    elems.append(HRFlowable(width="100%", thickness=2, color=colors.black))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=10))
    elems.append(Spacer(1, 0.3*cm))
    elems.append(Paragraph(f"<b>{surat['judul'].upper()}</b>", ParagraphStyle('title',fontSize=13,alignment=TA_CENTER,spaceAfter=4)))
    nomor = surat['nomor'] or f"SP/{sid}/{date.today().year}"
    elems.append(Paragraph(f"Nomor: {nomor}", ParagraphStyle('nomor',fontSize=11,alignment=TA_CENTER,spaceAfter=16)))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=12))
    # Isi surat
    isi = surat['isi']
    if penerima_user:
        isi = isi.replace('{{nama}}', penerima_user['nama'] or '')
        isi = isi.replace('{{jabatan}}', penerima_user['jabatan'] or '')
        isi = isi.replace('{{departemen}}', penerima_user['departemen'] or '')
    isi = isi.replace('{{tanggal}}', str(surat['tanggal']))
    for line in isi.split('\n'):
        elems.append(Paragraph(line or '&nbsp;', ParagraphStyle('body',fontSize=11,leading=16,alignment=TA_JUSTIFY,spaceAfter=4)))
    elems.append(Spacer(1, 1*cm))
    # TTD
    tgl = surat['tanggal'].strftime('%d %B %Y') if hasattr(surat['tanggal'], 'strftime') else str(surat['tanggal'])
    ttd_data = [
        ['', f'Surakarta, {tgl}'],
        ['', f'{surat["pembuat_jabatan"] or "Pimpinan"}'],
        ['', ''],['', ''],['', ''],
        ['', f'<b>{surat["pembuat"]}</b>'],
    ]
    ttd_table = Table(ttd_data, colWidths=[10*cm, 7*cm])
    ttd_table.setStyle(TableStyle([('FONTNAME',  (0,0), (-1,-1), 'Helvetica'),
                                   ('FONTSIZE',  (0,0), (-1,-1), 11),
                                   ('ALIGN',     (1,0), (1,-1), 'CENTER'),]))
    elems.append(ttd_table)
    doc.build(elems)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf',
                     download_name=f"surat_{nomor.replace('/','_')}.pdf", as_attachment=False)

# ── ADMIN SURAT ───────────────────────────────────────────────────────────────

@app.route('/admin/surat')
@admin_required
def admin_surat():
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT sp.*, u.nama as pembuat,
        (SELECT COUNT(*) FROM surat_penerima WHERE surat_id=sp.id) as total_penerima,
        (SELECT COUNT(*) FROM surat_penerima WHERE surat_id=sp.id AND dibaca=1) as sudah_baca
        FROM surat_perintah sp JOIN users u ON sp.dibuat_oleh=u.id
        ORDER BY sp.created_at DESC""")
    surat_list = cur.fetchall()
    cur.execute("SELECT * FROM surat_template WHERE aktif=1 ORDER BY nama")
    templates = cur.fetchall()
    cur.execute("SELECT id,nama,jabatan,departemen FROM users WHERE role='user' AND status='active' ORDER BY nama")
    users = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/surat.html', surat_list=surat_list, templates=templates, users=users)

@app.route('/admin/surat/buat', methods=['POST'])
@admin_required
def admin_surat_buat():
    conn = get_db(); cur = q(conn)
    judul = request.form.get('judul','').strip()
    isi = request.form.get('isi','').strip()
    penerima_ids = request.form.getlist('penerima_ids')
    template_id = request.form.get('template_id') or None
    tanggal = request.form.get('tanggal', date.today().isoformat())
    uid = session['user_id']
    # Generate nomor
    tahun = date.today().year
    cur.execute("SELECT COUNT(*)+1 as n FROM surat_perintah WHERE EXTRACT(YEAR FROM tanggal)=%s", (tahun,))
    n = cur.fetchone()['n']
    nomor = f"SP/{n:03d}/{tahun}"
    cur.execute("""INSERT INTO surat_perintah (nomor,template_id,judul,isi,dibuat_oleh,tanggal)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        (nomor, template_id, judul, isi, uid, tanggal))
    sid = cur.fetchone()['id']
    for pid in penerima_ids:
        cur.execute("INSERT INTO surat_penerima (surat_id,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (sid, int(pid)))
        kirim_notif(conn, int(pid), '📋 Surat Perintah Baru',
            f'Anda menerima surat perintah: {judul}', 'surat', sid, 'surat_perintah')
    conn.commit(); cur.close(); conn.close()
    flash(f'Surat {nomor} berhasil dibuat dan dikirim ke {len(penerima_ids)} penerima.', 'success')
    return redirect(url_for('admin_surat'))

@app.route('/admin/surat/<int:sid>')
@admin_required
def admin_surat_detail(sid):
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT sp.*,u.nama as pembuat,u.jabatan as pembuat_jabatan
        FROM surat_perintah sp JOIN users u ON sp.dibuat_oleh=u.id WHERE sp.id=%s""", (sid,))
    surat = cur.fetchone()
    cur.execute("""SELECT u.nama,u.jabatan,u.departemen,sp2.dibaca,sp2.dibaca_at
        FROM surat_penerima sp2 JOIN users u ON sp2.user_id=u.id
        WHERE sp2.surat_id=%s ORDER BY u.nama""", (sid,))
    penerima = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/surat_detail.html', surat=surat, penerima=penerima)

@app.route('/admin/surat/template', methods=['POST'])
@admin_required
def admin_surat_template():
    nama = request.form.get('nama','').strip()
    konten = request.form.get('konten','').strip()
    jenis = request.form.get('jenis', 'surat_perintah')
    conn = get_db(); cur = q(conn)
    cur.execute("INSERT INTO surat_template (nama,jenis,konten) VALUES (%s,%s,%s)", (nama, jenis, konten))
    conn.commit(); cur.close(); conn.close()
    flash('Template berhasil disimpan.', 'success')
    return redirect(url_for('admin_surat'))

@app.route('/api/surat-template/<int:tid>')
@admin_required
def api_surat_template(tid):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM surat_template WHERE id=%s", (tid,))
    t = cur.fetchone()
    cur.close(); conn.close()
    return jsonify(dict(t) if t else {})

# ══════════════════════════════════════════════════════════════════════════════
# ── NOTA DINAS ────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def get_approval_levels():
    """Ambil level approval dari database (bisa diubah admin)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT level, label FROM approval_config WHERE aktif=1 ORDER BY urutan, level")
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return rows if rows else [
            {'level': 1, 'label': 'Kepala TUUD'},
            {'level': 2, 'label': 'Waka Rumkit'},
            {'level': 3, 'label': 'Karumkit'},
            {'level': 4, 'label': 'Pejabat Pengadaan'},
        ]
    except Exception:
        return [
            {'level': 1, 'label': 'Kepala TUUD'},
            {'level': 2, 'label': 'Waka Rumkit'},
            {'level': 3, 'label': 'Karumkit'},
            {'level': 4, 'label': 'Pejabat Pengadaan'},
        ]

# Backward-compat alias (dipakai di beberapa route lama)
APPROVAL_LEVELS = [
    {'level': 1, 'label': 'Kepala TUUD'},
    {'level': 2, 'label': 'Waka Rumkit'},
    {'level': 3, 'label': 'Karumkit'},
    {'level': 4, 'label': 'Pejabat Pengadaan'},
]

@app.route('/nota-dinas')
@login_required
def nota_dinas_user():
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT nd.*, u.nama as nama_pembuat,
        (SELECT status FROM nota_approval WHERE nota_id=nd.id ORDER BY level LIMIT 1) as status_pertama
        FROM nota_dinas nd JOIN users u ON nd.dari_user=u.id
        WHERE nd.dari_user=%s ORDER BY nd.created_at DESC""", (uid,))
    nota_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template('nota_user.html', nota_list=nota_list)

@app.route('/nota-dinas/buat', methods=['GET','POST'])
@login_required
def nota_dinas_buat():
    uid = session['user_id']
    if request.method == 'POST':
        judul = request.form.get('judul','').strip()
        perihal = request.form.get('perihal','').strip()
        kepada = request.form.get('kepada','').strip()
        isi = request.form.get('isi','').strip()
        conn = get_db(); cur = q(conn)
        # Nomor nota
        tahun = date.today().year
        cur.execute("SELECT COUNT(*)+1 as n FROM nota_dinas WHERE EXTRACT(YEAR FROM tanggal)=%s", (tahun,))
        n = cur.fetchone()['n']
        nomor = f"ND/{n:03d}/{tahun}"
        # Lampiran
        lampiran = None
        f = request.files.get('lampiran')
        if f and f.filename:
            ext = f.filename.rsplit('.',1)[-1].lower()
            if ext in ALLOWED_DOSIR:
                os.makedirs(app.config['SURAT_FOLDER'], exist_ok=True)
                fn = secure_filename(f"nd_{uid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
                f.save(os.path.join(app.config['SURAT_FOLDER'], fn))
                lampiran = fn
        dasar = request.form.get('dasar','').strip()
        cur.execute("""INSERT INTO nota_dinas (nomor,judul,perihal,kepada,isi,dasar,dari_user,lampiran)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (nomor, judul, perihal, kepada, isi, dasar, uid, lampiran))
        nid = cur.fetchone()['id']
        # Buat approval chain (dari DB — bisa diubah admin)
        for lv in get_approval_levels():
            cur.execute("""INSERT INTO nota_approval (nota_id,level,role_label,status,urutan)
                VALUES (%s,%s,%s,'pending',%s)""", (nid, lv['level'], lv['label'], lv['level']))
        # Notif ke admin (level 1)
        cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
        admin = cur.fetchone()
        if admin:
            kirim_notif(conn, admin['id'], '📄 Nota Dinas Baru',
                f'Nota dinas baru dari {session.get("nama","")}: {judul}', 'nota', nid, 'nota_dinas')
        conn.commit(); cur.close(); conn.close()
        flash(f'Nota Dinas {nomor} berhasil diajukan.', 'success')
        return redirect(url_for('nota_dinas_user'))
    return render_template('nota_buat.html')

@app.route('/nota-dinas/<int:nid>')
@login_required
def nota_dinas_detail(nid):
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT nd.*,u.nama as nama_pembuat,u.jabatan as jabatan_pembuat,
        u.departemen as dept_pembuat FROM nota_dinas nd
        JOIN users u ON nd.dari_user=u.id WHERE nd.id=%s""", (nid,))
    nota = cur.fetchone()
    cur.execute("""SELECT na.*,u.nama as approver_nama FROM nota_approval na
        LEFT JOIN users u ON na.user_id=u.id
        WHERE na.nota_id=%s ORDER BY na.level""", (nid,))
    approvals = cur.fetchall()
    cur.close(); conn.close()
    if not nota:
        flash('Nota tidak ditemukan.', 'error')
        return redirect(url_for('nota_dinas_user'))
    return render_template('nota_detail.html', nota=nota, approvals=approvals, levels=APPROVAL_LEVELS)

@app.route('/nota-dinas/<int:nid>/pdf')
@login_required
def nota_dinas_pdf(nid):
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT nd.*,u.nama as nama_pembuat,u.jabatan as jabatan_pembuat,
        u.departemen as dept_pembuat, u.nik as nik_pembuat
        FROM nota_dinas nd
        JOIN users u ON nd.dari_user=u.id WHERE nd.id=%s""", (nid,))
    nota = cur.fetchone()
    cur.execute("""SELECT na.*,u.nama as approver_nama,u.jabatan as approver_jabatan,
        u.nik as approver_nik
        FROM nota_approval na LEFT JOIN users u ON na.user_id=u.id
        WHERE na.nota_id=%s ORDER BY na.level""", (nid,))
    approvals = cur.fetchall()
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.execute("SELECT * FROM nota_template WHERE aktif=1 ORDER BY id DESC LIMIT 1")
    tmpl = cur.fetchone()
    cur.close(); conn.close()

    instansi   = settings['nama_perusahaan'] if settings else 'RS SLAMET RIYADI'
    font_size  = int(tmpl['font_size'])   if tmpl and tmpl.get('font_size')  else 11
    margin_top = float(tmpl['margin_top'])  if tmpl and tmpl.get('margin_top')  else 2.0
    margin_left= float(tmpl['margin_left']) if tmpl and tmpl.get('margin_left') else 3.0
    tmpl_header = (tmpl['header'] or '').strip() if tmpl else ''
    tmpl_footer = (tmpl['footer'] or '').strip() if tmpl else ''

    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
    from reportlab.platypus import HRFlowable, Image as RLImage, KeepTogether
    from reportlab.lib.colors import black, grey, HexColor

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=margin_top*cm, bottomMargin=2*cm,
                            leftMargin=margin_left*cm, rightMargin=2*cm)
    elems = []
    fs = font_size

    BULAN_ID = {1:'Januari',2:'Februari',3:'Maret',4:'April',5:'Mei',6:'Juni',
                7:'Juli',8:'Agustus',9:'September',10:'Oktober',11:'November',12:'Desember'}
    def fmt_tgl(d):
        if hasattr(d,'day'): return f"{d.day} {BULAN_ID[d.month]} {d.year}"
        try:
            from datetime import datetime as _dt
            dd = _dt.fromisoformat(str(d))
            return f"{dd.day} {BULAN_ID[dd.month]} {dd.year}"
        except Exception: return str(d)

    def ps(name, **kw):
        defaults = dict(fontName='Helvetica', fontSize=fs, leading=int(fs*1.4))
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    # ── KOP SURAT ────────────────────────────────────────────────────────────
    header_lines = tmpl_header.split('\n') if tmpl_header else [instansi.upper()]

    # Cek ada logo tidak
    logo_path = None
    if settings and settings.get('logo'):
        lp = os.path.join('static','uploads','logo', settings['logo'])
        if os.path.exists(lp):
            logo_path = lp

    if logo_path:
        # Kop dengan logo di kiri, teks di tengah/kanan
        logo_img = RLImage(logo_path, width=2*cm, height=2*cm)
        logo_img.hAlign = 'LEFT'
        header_paras = [Paragraph(line or '&nbsp;',
            ps(f'kh{i}', fontSize=fs+2 if i==0 else fs, alignment=TA_CENTER,
               fontName='Helvetica-Bold' if i==0 else 'Helvetica', spaceAfter=1))
            for i, line in enumerate(header_lines)]
        kop_data = [[logo_img, header_paras]]
        kop_tbl = Table(kop_data, colWidths=[2.5*cm, 13.5*cm])
        kop_tbl.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ALIGN',(0,0),(0,0),'LEFT'),
            ('ALIGN',(1,0),(1,0),'CENTER'),
        ]))
        elems.append(kop_tbl)
    else:
        for i, line in enumerate(header_lines):
            elems.append(Paragraph(line or '&nbsp;',
                ps(f'kh{i}', fontSize=fs+2 if i==0 else fs,
                   fontName='Helvetica-Bold' if i==0 else 'Helvetica',
                   alignment=TA_CENTER, spaceAfter=1)))

    elems.append(Spacer(1, 0.2*cm))
    elems.append(HRFlowable(width="100%", thickness=2, color=black, spaceAfter=1))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=black, spaceAfter=8))

    # ── JUDUL ─────────────────────────────────────────────────────────────────
    elems.append(Spacer(1, 0.3*cm))
    elems.append(Paragraph("<b>NOTA DINAS</b>",
        ps('judul', fontSize=fs+2, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=2)))
    elems.append(Paragraph(f"<b>NOMOR : {nota.get('nomor') or '-'}</b>",
        ps('nomor', fontSize=fs+1, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=10)))

    # ── INFO SURAT ────────────────────────────────────────────────────────────
    tgl = fmt_tgl(nota.get('tanggal') or nota.get('created_at'))
    pembuat_info = nota['nama_pembuat']
    if nota.get('jabatan_pembuat'): pembuat_info += f" / {nota['jabatan_pembuat']}"
    if nota.get('dept_pembuat'):    pembuat_info += f" / {nota['dept_pembuat']}"

    info_rows = [
        [Paragraph('YTH',  ps('il', fontName='Helvetica')),
         Paragraph(f": {nota.get('kepada') or '-'}", ps('iv'))],
        [Paragraph('Dari', ps('il', fontName='Helvetica')),
         Paragraph(f": {pembuat_info}", ps('iv'))],
        [Paragraph('Perihal', ps('il', fontName='Helvetica')),
         Paragraph(f": {nota.get('perihal') or nota.get('judul') or '-'}", ps('iv'))],
        [Paragraph('Tanggal', ps('il', fontName='Helvetica')),
         Paragraph(f": {tgl}", ps('iv'))],
    ]
    info_tbl = Table(info_rows, colWidths=[3.5*cm, 12.5*cm])
    info_tbl.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),fs),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('TOPPADDING',(0,0),(-1,-1),1),
    ]))
    elems.append(info_tbl)
    elems.append(HRFlowable(width="100%", thickness=0.5, color=grey, spaceBefore=8, spaceAfter=10))

    # ── DASAR ─────────────────────────────────────────────────────────────────
    dasar_text = nota.get('dasar','') or ''
    if dasar_text.strip():
        elems.append(Paragraph("<b>1.&nbsp; Dasar :</b>",
            ps('dasar_hdr', fontName='Helvetica-Bold', spaceAfter=4)))
        dasar_lines = [l.strip() for l in dasar_text.split('\n') if l.strip()]
        huruf = ['a','b','c','d','e','f','g','h','i','j']
        for idx, line in enumerate(dasar_lines):
            label = huruf[idx] if idx < len(huruf) else str(idx+1)
            elems.append(Paragraph(
                f"&nbsp;&nbsp;&nbsp;&nbsp;{label}.&nbsp; {line}",
                ps(f'dasar_{idx}', alignment=TA_JUSTIFY, spaceAfter=3, leftIndent=0.5*cm)))
        angka_isi = "2"
    else:
        angka_isi = "1"

    # ── ISI SURAT ─────────────────────────────────────────────────────────────
    isi_text = (nota.get('isi') or '').strip()
    if isi_text:
        elems.append(Spacer(1, 0.15*cm))
        isi_lines = isi_text.split('\n')
        for idx, line in enumerate(isi_lines):
            stripped = line.strip()
            if not stripped:
                elems.append(Spacer(1, 0.2*cm))
                continue
            elems.append(Paragraph(stripped,
                ps(f'isi_{idx}', alignment=TA_JUSTIFY, spaceAfter=4)))

    elems.append(Spacer(1, 0.8*cm))

    # ── TTD ───────────────────────────────────────────────────────────────────
    # Format: TTD pembuat di kiri, approver di kanan (mirip screenshot)
    TTD_DIR = app.config.get('TTD_FOLDER', os.path.join('static','uploads','ttd'))
    kota = 'Surakarta'  # bisa dari settings nanti

    def make_ttd_cell(label, nama, jabatan, nik, tgl_str, ttd_file=None, status=None):
        items = []
        items.append(Paragraph(f"{kota},&nbsp; {tgl_str}",
            ps('tgl_ttd', fontSize=fs-1, alignment=TA_LEFT, spaceAfter=2)))
        items.append(Paragraph(label,
            ps('lbl_ttd', fontSize=fs-1, alignment=TA_LEFT, spaceAfter=2)))
        # Gambar TTD
        if ttd_file:
            tp = os.path.join(TTD_DIR, ttd_file)
            if os.path.exists(tp):
                try:
                    img = RLImage(tp, width=3*cm, height=1.2*cm)
                    img.hAlign = 'LEFT'
                    items.append(img)
                except Exception:
                    items.append(Spacer(1, 1.5*cm))
            else:
                items.append(Spacer(1, 1.5*cm))
        else:
            items.append(Spacer(1, 1.5*cm))
        nama_str = nama or '________________________'
        if jabatan: nama_str += f"<br/>{jabatan}"
        if nik: nama_str += f"<br/>NIP/NRP {nik}"
        items.append(Paragraph(nama_str, ps('nama_ttd', fontSize=fs-1, spaceAfter=2)))
        if status and status != 'pending':
            warna = '#16a34a' if status=='approved' else '#dc2626'
            items.append(Paragraph(
                f"<font color='{warna}'>{'✓ Disetujui' if status=='approved' else '✗ Ditolak'}</font>",
                ps('st_ttd', fontSize=fs-2)))
        return items

    tgl_str = fmt_tgl(nota.get('tanggal') or nota.get('created_at'))

    if approvals:
        # Pembuat di kiri, approver berurutan di kanan
        ttd_cells = []
        # Cell pembuat
        ttd_cells.append(make_ttd_cell(
            nota.get('jabatan_pembuat') or 'Pembuat,',
            nota['nama_pembuat'],
            nota.get('jabatan_pembuat',''),
            nota.get('nik_pembuat',''),
            tgl_str
        ))
        # Cell tiap approver
        for ap in approvals:
            ttd_cells.append(make_ttd_cell(
                ap.get('role_label','') + ',',
                ap.get('approver_nama',''),
                ap.get('approver_jabatan',''),
                ap.get('approver_nik',''),
                tgl_str,
                ttd_file=ap.get('ttd_file'),
                status=ap.get('status')
            ))
        ncols = len(ttd_cells)
        avail_w = (21 - margin_left - 2) * cm
        col_w = avail_w / ncols
        ttd_tbl = Table([ttd_cells], colWidths=[col_w]*ncols)
        ttd_tbl.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('ALIGN',(0,0),(-1,-1),'LEFT'),
            ('TOPPADDING',(0,0),(-1,-1),6),
            ('BOTTOMPADDING',(0,0),(-1,-1),6),
        ]))
        elems.append(ttd_tbl)
    else:
        # Hanya pembuat
        items = make_ttd_cell(
            nota.get('jabatan_pembuat') or 'Hormat kami,',
            nota['nama_pembuat'],
            nota.get('jabatan_pembuat',''),
            nota.get('nik_pembuat',''),
            tgl_str
        )
        elems.append(Spacer(1,0.3*cm))
        for it in items: elems.append(it)

    # ── LAMPIRAN (halaman baru jika ada) ──────────────────────────────────────
    lampiran = nota.get('lampiran')
    if lampiran:
        SURAT_DIR = app.config.get('SURAT_FOLDER', os.path.join('static','uploads','surat'))
        lamp_path = os.path.join(SURAT_DIR, lampiran)
        if os.path.exists(lamp_path):
            from reportlab.platypus import PageBreak
            elems.append(PageBreak())

            # Header lampiran
            if logo_path:
                logo_img2 = RLImage(logo_path, width=2*cm, height=2*cm)
                header_paras2 = [Paragraph(line or '&nbsp;',
                    ps(f'kh2_{i}', fontSize=fs+2 if i==0 else fs,
                       fontName='Helvetica-Bold' if i==0 else 'Helvetica',
                       alignment=TA_CENTER, spaceAfter=1))
                    for i, line in enumerate(header_lines)]
                kop2 = Table([[logo_img2, header_paras2]], colWidths=[2.5*cm, 13.5*cm])
                kop2.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('ALIGN',(1,0),(1,0),'CENTER')]))
                elems.append(kop2)
            else:
                for i, line in enumerate(header_lines):
                    elems.append(Paragraph(line or '&nbsp;',
                        ps(f'kh2_{i}', fontSize=fs+2 if i==0 else fs,
                           fontName='Helvetica-Bold' if i==0 else 'Helvetica',
                           alignment=TA_CENTER, spaceAfter=1)))

            elems.append(HRFlowable(width="100%", thickness=2, color=black, spaceAfter=1))
            elems.append(HRFlowable(width="100%", thickness=0.5, color=black, spaceAfter=8))

            # Info lampiran di kanan atas
            lamp_info = Table([[
                '',
                Paragraph(f"Lampiran Nota Dinas<br/>Nomor : {nota.get('nomor') or '-'}<br/>Tanggal : {tgl_str}",
                    ps('lamp_info', fontSize=fs-1, alignment=TA_RIGHT))
            ]], colWidths=[10*cm, 6*cm])
            elems.append(lamp_info)
            elems.append(Spacer(1, 0.5*cm))

            ext_lamp = lampiran.rsplit('.',1)[-1].lower() if '.' in lampiran else ''
            if ext_lamp in {'png','jpg','jpeg','gif'}:
                try:
                    img_lamp = RLImage(lamp_path, width=14*cm, height=12*cm, kind='proportional')
                    img_lamp.hAlign = 'LEFT'
                    elems.append(img_lamp)
                except Exception:
                    elems.append(Paragraph(f"[Gambar tidak dapat dimuat]",
                        ps('le', textColor=colors.red)))
            elif ext_lamp == 'pdf':
                elems.append(Paragraph(f"Lampiran PDF: {lampiran} (lihat file terpisah)",
                    ps('lp', textColor=colors.blue)))

    # ── FOOTER KUSTOM ─────────────────────────────────────────────────────────
    if tmpl_footer:
        elems.append(Spacer(1, 0.5*cm))
        elems.append(HRFlowable(width="100%", thickness=0.5, color=grey))
        for baris in tmpl_footer.split('\n'):
            elems.append(Paragraph(baris or '&nbsp;',
                ps('tf', fontSize=fs-2, alignment=TA_CENTER, spaceAfter=2)))

    doc.build(elems)
    buf.seek(0)
    nomor_clean = (nota.get('nomor') or str(nid)).replace('/','_')
    return send_file(buf, mimetype='application/pdf',
                     download_name=f"nota_{nomor_clean}.pdf", as_attachment=False)



# ── ADMIN NOTA DINAS ──────────────────────────────────────────────────────────

# ── Kelola Level Approval ─────────────────────────────────────────────────────
@app.route('/admin/approval-config', methods=['GET','POST'])
@admin_required
def admin_approval_config():
    conn = get_db(); cur = q(conn)
    if request.method == 'POST':
        aksi = request.form.get('aksi','')
        if aksi == 'tambah':
            label = request.form.get('label','').strip()
            cur.execute("SELECT COALESCE(MAX(level),0)+1 as next_lv FROM approval_config")
            next_lv = cur.fetchone()['next_lv']
            cur.execute("INSERT INTO approval_config (level,label,urutan) VALUES (%s,%s,%s)",
                        (next_lv, label, next_lv))
        elif aksi == 'edit':
            aid = int(request.form.get('id'))
            label = request.form.get('label','').strip()
            cur.execute("UPDATE approval_config SET label=%s WHERE id=%s", (label, aid))
        elif aksi == 'hapus':
            aid = int(request.form.get('id'))
            cur.execute("DELETE FROM approval_config WHERE id=%s", (aid,))
            # Re-urut level
            cur.execute("SELECT id FROM approval_config ORDER BY urutan, level")
            rows = cur.fetchall()
            for i, r in enumerate(rows, 1):
                cur.execute("UPDATE approval_config SET level=%s, urutan=%s WHERE id=%s",
                            (i, i, r['id']))
        elif aksi == 'toggle':
            aid = int(request.form.get('id'))
            cur.execute("UPDATE approval_config SET aktif = CASE WHEN aktif=1 THEN 0 ELSE 1 END WHERE id=%s", (aid,))
        conn.commit()
        flash('Konfigurasi approval diperbarui.', 'success')
    cur.execute("SELECT * FROM approval_config ORDER BY urutan, level")
    config_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/approval_config.html', config_list=config_list)

# ── Kelola Template Format Nota Dinas ────────────────────────────────────────
@app.route('/admin/nota-template', methods=['GET','POST'])
@admin_required
def admin_nota_template():
    conn = get_db(); cur = q(conn)
    if request.method == 'POST':
        aksi = request.form.get('aksi','')
        if aksi == 'tambah':
            nama       = request.form.get('nama','').strip()
            header     = request.form.get('header','').strip()
            footer     = request.form.get('footer','').strip()
            font_size  = int(request.form.get('font_size', 11) or 11)
            margin_top = float(request.form.get('margin_top', 2.0) or 2.0)
            margin_left= float(request.form.get('margin_left', 3.0) or 3.0)
            # Nonaktifkan yang lain
            cur.execute("UPDATE nota_template SET aktif=0")
            cur.execute("""INSERT INTO nota_template (nama,header,footer,font_size,margin_top,margin_left,aktif)
                VALUES (%s,%s,%s,%s,%s,%s,1)""",
                (nama, header, footer, font_size, margin_top, margin_left))
            flash(f'Template "{nama}" ditambahkan dan diaktifkan.', 'success')
        elif aksi == 'aktifkan':
            tid = int(request.form.get('id'))
            cur.execute("UPDATE nota_template SET aktif=0")
            cur.execute("UPDATE nota_template SET aktif=1 WHERE id=%s", (tid,))
            flash('Template diaktifkan.', 'success')
        elif aksi == 'hapus':
            tid = int(request.form.get('id'))
            cur.execute("DELETE FROM nota_template WHERE id=%s", (tid,))
            # Pastikan masih ada yang aktif
            cur.execute("SELECT COUNT(*) as n FROM nota_template WHERE aktif=1")
            if cur.fetchone()['n'] == 0:
                cur.execute("UPDATE nota_template SET aktif=1 WHERE id=(SELECT id FROM nota_template ORDER BY id LIMIT 1)")
            flash('Template dihapus.', 'success')
        conn.commit()
    cur.execute("SELECT * FROM nota_template ORDER BY id")
    tmpl_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/nota_template.html', tmpl_list=tmpl_list)

@app.route('/admin/nota-dinas')
@admin_required
def admin_nota_dinas():
    conn = get_db(); cur = q(conn)
    status_f = request.args.get('status','')
    q_sql = """SELECT nd.*,u.nama as nama_pembuat,
        (SELECT COUNT(*) FROM nota_approval WHERE nota_id=nd.id AND status='approved') as approved_count,
        (SELECT COUNT(*) FROM nota_approval WHERE nota_id=nd.id) as total_level
        FROM nota_dinas nd JOIN users u ON nd.dari_user=u.id"""
    params = []
    if status_f:
        q_sql += " WHERE nd.status=%s"; params.append(status_f)
    q_sql += " ORDER BY nd.created_at DESC"
    cur.execute(q_sql, params)
    nota_list = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/nota_dinas.html', nota_list=nota_list, status_f=status_f)

@app.route('/admin/nota-dinas/<int:nid>')
@admin_required
def admin_nota_detail(nid):
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT nd.*,u.nama as nama_pembuat,u.jabatan as jabatan_pembuat,
        u.departemen as dept_pembuat FROM nota_dinas nd
        JOIN users u ON nd.dari_user=u.id WHERE nd.id=%s""", (nid,))
    nota = cur.fetchone()
    cur.execute("""SELECT na.*,u.nama as approver_nama FROM nota_approval na
        LEFT JOIN users u ON na.user_id=u.id
        WHERE na.nota_id=%s ORDER BY na.level""", (nid,))
    approvals = cur.fetchall()
    cur.execute("SELECT id,nama,jabatan FROM users WHERE role='admin' OR role='approver' ORDER BY nama")
    approvers = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/nota_detail.html', nota=nota, approvals=approvals,
        approvers=approvers, levels=APPROVAL_LEVELS)

@app.route('/admin/nota-dinas/<int:nid>/approve/<int:level>', methods=['POST'])
@admin_required
def admin_nota_approve(nid, level):
    action = request.form.get('action','approve')
    catatan = request.form.get('catatan','').strip()
    uid = session['user_id']
    conn = get_db(); cur = q(conn)
    # Upload TTD jika ada
    ttd_file = None
    f = request.files.get('ttd_file')
    if f and f.filename:
        ext = f.filename.rsplit('.',1)[-1].lower()
        if ext in {'png','jpg','jpeg'}:
            os.makedirs(app.config['TTD_FOLDER'], exist_ok=True)
            fn = secure_filename(f"ttd_{uid}_{nid}_{level}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
            f.save(os.path.join(app.config['TTD_FOLDER'], fn))
            ttd_file = fn
    status = 'approved' if action == 'approve' else 'rejected'
    if ttd_file:
        cur.execute("""UPDATE nota_approval SET status=%s,user_id=%s,catatan=%s,ttd_file=%s,
            approved_at=CURRENT_TIMESTAMP WHERE nota_id=%s AND level=%s""",
            (status, uid, catatan, ttd_file, nid, level))
    else:
        cur.execute("""UPDATE nota_approval SET status=%s,user_id=%s,catatan=%s,
            approved_at=CURRENT_TIMESTAMP WHERE nota_id=%s AND level=%s""",
            (status, uid, catatan, nid, level))
    # Cek apakah semua approved
    cur.execute("SELECT * FROM nota_approval WHERE nota_id=%s ORDER BY level", (nid,))
    all_ap = cur.fetchall()
    all_done = all(a['status']=='approved' for a in all_ap)
    any_rejected = any(a['status']=='rejected' for a in all_ap)
    new_status = 'selesai' if all_done else ('ditolak' if any_rejected else 'proses')
    cur.execute("UPDATE nota_dinas SET status=%s WHERE id=%s", (new_status, nid))
    # Notif ke pembuat
    cur.execute("SELECT dari_user,judul FROM nota_dinas WHERE id=%s", (nid,))
    nd = cur.fetchone()
    if nd:
        label = APPROVAL_LEVELS[level-1]['label'] if level <= len(APPROVAL_LEVELS) else f'Level {level}'
        msg = f'Nota Dinas Anda "{nd["judul"]}" telah {"disetujui" if status=="approved" else "ditolak"} oleh {label}'
        kirim_notif(conn, nd['dari_user'], '📄 Update Nota Dinas', msg, 'nota', nid, 'nota_dinas')
    conn.commit(); cur.close(); conn.close()
    flash(f'Nota dinas berhasil {"disetujui" if status=="approved" else "ditolak"}.', 'success')
    return redirect(url_for('admin_nota_detail', nid=nid))




# ── MASTER ROLE ───────────────────────────────────────────────────────────────
@app.route('/admin/master-role', methods=['GET','POST'])
@admin_required
def admin_master_role():
    conn = get_db(); cur = q(conn)
    if request.method == 'POST':
        aksi = request.form.get('aksi')
        if aksi == 'tambah':
            kode  = request.form.get('kode','').strip().lower().replace(' ','_')
            nama  = request.form.get('nama','').strip()
            desk  = request.form.get('deskripsi','').strip()
            urut  = int(request.form.get('urutan', 99))
            try:
                cur.execute("INSERT INTO master_role (kode,nama,deskripsi,urutan) VALUES (%s,%s,%s,%s)",
                    (kode, nama, desk, urut))
                conn.commit()
                flash(f'Role "{nama}" berhasil ditambahkan.', 'success')
            except Exception:
                conn.rollback()
                flash('Kode role sudah ada.', 'error')
        elif aksi == 'edit':
            rid  = request.form.get('id')
            nama = request.form.get('nama','').strip()
            desk = request.form.get('deskripsi','').strip()
            urut = int(request.form.get('urutan', 99))
            aktif= int(request.form.get('aktif', 1))
            cur.execute("UPDATE master_role SET nama=%s,deskripsi=%s,urutan=%s,aktif=%s WHERE id=%s",
                (nama, desk, urut, aktif, rid))
            conn.commit()
            flash('Role berhasil diperbarui.', 'success')
        elif aksi == 'hapus':
            rid = request.form.get('id')
            cur.execute("SELECT COUNT(*) as c FROM users WHERE role=(SELECT kode FROM master_role WHERE id=%s)", (rid,))
            cnt = cur.fetchone()['c']
            if cnt > 0:
                flash(f'Role tidak bisa dihapus, masih dipakai {cnt} pegawai.', 'error')
            else:
                cur.execute("DELETE FROM master_role WHERE id=%s", (rid,))
                conn.commit()
                flash('Role berhasil dihapus.', 'success')
        cur.close(); conn.close()
        return redirect(url_for('admin_master_role'))
    cur.execute("SELECT mr.*, COUNT(u.id) as jml_user FROM master_role mr LEFT JOIN users u ON u.role=mr.kode GROUP BY mr.id ORDER BY mr.urutan")
    roles = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/master_role.html', roles=roles)

# ── REORDER ROLE ──────────────────────────────────────────────────────────────
@app.route('/admin/master-role/reorder', methods=['POST'])
@admin_required
def admin_master_role_reorder():
    try:
        data = request.get_json()
        order = data.get('order', [])
        conn = get_db(); cur = q(conn)
        for idx, rid in enumerate(order):
            cur.execute("UPDATE master_role SET urutan=%s WHERE id=%s", (idx, rid))
        conn.commit(); cur.close(); conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

# ── HAK AKSES ROLE ────────────────────────────────────────────────────────────

def get_role_permissions(role_kode):
    """Kembalikan set modul_kode yang diizinkan untuk role tertentu."""
    try:
        conn = get_db(); cur = q(conn)
        cur.execute("SELECT modul_kode FROM role_permission WHERE role_kode=%s AND aktif=1", (role_kode,))
        perms = {r['modul_kode'] for r in cur.fetchall()}
        cur.close(); conn.close()
        return perms
    except Exception:
        return set()

def has_permission(modul_kode):
    """Cek apakah user session punya akses ke modul_kode."""
    role = session.get('role', '')
    if role == 'admin':
        return True
    return modul_kode in get_role_permissions(role)

def permission_required(modul_kode):
    """Decorator: tolak akses jika tidak punya permission."""
    def decorator(f):
        @wraps(f)
        def dec(*a, **kw):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if not has_permission(modul_kode):
                flash('Anda tidak memiliki akses ke fitur ini.', 'error')
                return redirect(url_for('dashboard'))
            return f(*a, **kw)
        return dec
    return decorator

@app.route('/admin/role-permission')
@admin_required
def admin_role_permission():
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM master_role WHERE aktif=1 ORDER BY urutan")
    roles = cur.fetchall()
    # Ambil semua modul unik, dikelompokkan per grup (urut berdasarkan modul_kode)
    cur.execute("""SELECT DISTINCT modul_kode, modul_nama, grup
        FROM role_permission ORDER BY grup, modul_nama""")
    modul_rows = cur.fetchall()
    # Buat dict: {role_kode: {modul_kode: aktif}}
    cur.execute("SELECT role_kode, modul_kode, aktif FROM role_permission")
    perm_map = {}
    for r in cur.fetchall():
        perm_map.setdefault(r['role_kode'], {})[r['modul_kode']] = r['aktif']
    # Kelompokkan modul per grup
    from collections import OrderedDict
    grups = OrderedDict()
    for m in modul_rows:
        grups.setdefault(m['grup'], []).append(m)
    cur.close(); conn.close()
    return render_template('admin/role_permission.html',
        roles=roles, grups=grups, perm_map=perm_map)

@app.route('/admin/role-permission/save', methods=['POST'])
@admin_required
def admin_role_permission_save():
    """Simpan seluruh matrix permission dari form POST."""
    conn = get_db(); cur = q(conn)
    # Ambil semua kombinasi role × modul yang ada
    cur.execute("SELECT role_kode, modul_kode FROM role_permission")
    all_pairs = {(r['role_kode'], r['modul_kode']) for r in cur.fetchall()}
    # Semua checkbox yang dicentang dikirim sebagai perm_<role>_<modul>
    checked = set()
    for key in request.form:
        if key.startswith('perm_'):
            parts = key[5:].split('_', 1)  # perm_{role}_{modul}
            if len(parts) == 2:
                checked.add((parts[0], parts[1]))
    # Update semua
    for role_kode, modul_kode in all_pairs:
        aktif = 1 if (role_kode, modul_kode) in checked else 0
        cur.execute("UPDATE role_permission SET aktif=%s WHERE role_kode=%s AND modul_kode=%s",
            (aktif, role_kode, modul_kode))
    conn.commit(); cur.close(); conn.close()
    flash('Hak akses berhasil disimpan.', 'success')
    return redirect(url_for('admin_role_permission'))

@app.route('/admin/role-permission/api', methods=['POST'])
@admin_required
def admin_role_permission_api():
    """Toggle satu permission via AJAX (untuk toggle langsung di matrix)."""
    try:
        data = request.get_json()
        role_kode  = data['role_kode']
        modul_kode = data['modul_kode']
        aktif      = int(data['aktif'])
        conn = get_db(); cur = q(conn)
        cur.execute("""INSERT INTO role_permission (role_kode,modul_kode,modul_nama,grup,aktif)
            VALUES (%s,%s,(SELECT modul_nama FROM role_permission WHERE modul_kode=%s LIMIT 1),
                   (SELECT grup FROM role_permission WHERE modul_kode=%s LIMIT 1),%s)
            ON CONFLICT (role_kode,modul_kode) DO UPDATE SET aktif=%s""",
            (role_kode, modul_kode, modul_kode, modul_kode, aktif, aktif))
        conn.commit(); cur.close(); conn.close()
        return jsonify({'ok': True, 'aktif': aktif})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/admin/role-permission/preset/<role_kode>', methods=['POST'])
@admin_required
def admin_role_permission_preset(role_kode):
    """Terapkan preset (aktifkan semua / nonaktifkan semua) untuk satu role."""
    mode = request.json.get('mode', 'none')  # 'all' atau 'none'
    aktif = 1 if mode == 'all' else 0
    conn = get_db(); cur = q(conn)
    cur.execute("UPDATE role_permission SET aktif=%s WHERE role_kode=%s", (aktif, role_kode))
    conn.commit(); cur.close(); conn.close()
    return jsonify({'ok': True})

# ══════════════════════════════════════════════════════════════════════════════
# ██  ROUTE — AUDIT LOG  ███████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/audit-log')
@admin_required
def audit_log_index():
    conn = get_db(); cur = q(conn)
    page      = request.args.get('page', 1, type=int)
    per_page  = min(request.args.get('per_page', 50, type=int), 200)
    offset    = (page - 1) * per_page
    aksi      = request.args.get('aksi', '')
    modul     = request.args.get('modul', '')
    user_id_f = request.args.get('user_id', '')
    status_f  = request.args.get('status', '')
    tgl_dari  = request.args.get('tgl_dari', '')
    tgl_sampai= request.args.get('tgl_sampai', '')
    cari      = request.args.get('cari', '')

    conditions, params = [], []
    if aksi:       conditions.append("aksi=%s");            params.append(aksi)
    if modul:      conditions.append("modul=%s");           params.append(modul)
    if user_id_f and user_id_f.isdigit():
                   conditions.append("user_id=%s");         params.append(int(user_id_f))
    if status_f:   conditions.append("status=%s");          params.append(status_f)
    if tgl_dari:   conditions.append("waktu::date>=%s");    params.append(tgl_dari)
    if tgl_sampai: conditions.append("waktu::date<=%s");    params.append(tgl_sampai)
    if cari:
        conditions.append("(deskripsi ILIKE %s OR user_nama ILIKE %s OR pesan_error ILIKE %s)")
        like = f'%{cari}%'; params += [like,like,like]

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    cur.execute(f"SELECT COUNT(*) as c FROM audit_log {where}", params)
    total = cur.fetchone()['c']
    total_pages = max(1, (total + per_page - 1) // per_page)

    cur.execute(f"""SELECT al.* FROM audit_log al
        {where} ORDER BY al.waktu DESC LIMIT %s OFFSET %s""",
        params + [per_page, offset])
    logs = cur.fetchall()

    cur.execute("""SELECT
        COUNT(*) FILTER (WHERE status='success') as sukses,
        COUNT(*) FILTER (WHERE status='error')   as error,
        COUNT(DISTINCT user_id)                  as user_aktif,
        COUNT(*) FILTER (WHERE aksi='LOGIN')     as total_login,
        COUNT(*) FILTER (WHERE aksi='LOGIN_GAGAL') as login_gagal,
        COUNT(*) FILTER (WHERE aksi IN ('CREATE','UPDATE','DELETE')) as mutasi
        FROM audit_log WHERE waktu >= NOW() - INTERVAL '24 hours'""")
    stats = cur.fetchone()

    cur.execute("""SELECT date_trunc('hour',waktu) as jam, COUNT(*) as jumlah
        FROM audit_log WHERE waktu >= NOW() - INTERVAL '12 hours'
        GROUP BY jam ORDER BY jam""")
    aktivitas_per_jam = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT user_nama, user_role, COUNT(*) as aksi_count
        FROM audit_log WHERE waktu::date=CURRENT_DATE AND user_id IS NOT NULL
        GROUP BY user_nama, user_role ORDER BY aksi_count DESC LIMIT 10""")
    top_users = cur.fetchall()

    cur.execute("""SELECT DISTINCT user_id, user_nama, user_role
        FROM audit_log WHERE user_id IS NOT NULL ORDER BY user_nama LIMIT 100""")
    daftar_user = cur.fetchall()

    cur.close(); conn.close()
    return render_template('admin/audit_log.html',
        logs=logs, stats=stats, aktivitas_per_jam=aktivitas_per_jam,
        top_users=top_users, daftar_user=daftar_user,
        total=total, total_pages=total_pages, page=page, per_page=per_page,
        aksi=aksi, modul=modul, user_id=user_id_f,
        status=status_f, tgl_dari=tgl_dari, tgl_sampai=tgl_sampai, cari=cari,
        AKSI_LABELS=AKSI_LABELS, MODUL_LABELS=MODUL_LABELS)


@app.route('/admin/audit-log/detail/<int:log_id>')
@admin_required
def audit_log_detail(log_id):
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT * FROM audit_log WHERE id=%s", (log_id,))
    log = cur.fetchone()
    cur.close(); conn.close()
    if not log:
        flash('Log tidak ditemukan.', 'error')
        return redirect(url_for('audit_log_index'))
    return render_template('admin/audit_log_detail.html',
        log=dict(log), AKSI_LABELS=AKSI_LABELS, MODUL_LABELS=MODUL_LABELS)


@app.route('/admin/audit-log/api-stats')
@admin_required
def audit_log_api_stats():
    jam = request.args.get('jam', 24, type=int)
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT date_trunc('hour',waktu) as jam,
        COUNT(*) as total,
        COUNT(*) FILTER (WHERE status='error') as error
        FROM audit_log WHERE waktu >= NOW() - INTERVAL '%s hours'
        GROUP BY jam ORDER BY jam""", (jam,))
    per_jam = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT aksi, COUNT(*) as jumlah FROM audit_log
        WHERE waktu >= NOW() - INTERVAL '24 hours'
        GROUP BY aksi ORDER BY jumlah DESC LIMIT 10""")
    per_aksi = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(per_jam=per_jam, per_aksi=per_aksi)


@app.route('/admin/audit-log/export')
@admin_required
def audit_log_export():
    import csv
    tgl_dari   = request.args.get('tgl_dari',   '').strip() or (date.today()-timedelta(days=30)).isoformat()
    tgl_sampai = request.args.get('tgl_sampai', '').strip() or date.today().isoformat()
    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT waktu,user_nama,user_role,aksi,modul,deskripsi,
        ref_id,ref_table,ip_address,status,pesan_error
        FROM audit_log WHERE waktu::date BETWEEN %s AND %s ORDER BY waktu DESC""",
        (tgl_dari, tgl_sampai))
    rows = cur.fetchall(); cur.close(); conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Waktu','User','Role','Aksi','Modul','Deskripsi',
                     'Ref ID','Ref Table','IP Address','Status','Error'])
    for r in rows:
        writer.writerow([r['waktu'],r['user_nama'],r['user_role'],
            r['aksi'],r['modul'],r['deskripsi'],r['ref_id'],r['ref_table'],
            r['ip_address'],r['status'],r['pesan_error']])
    from flask import Response
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition':f'attachment; filename=audit_log_{tgl_dari}_{tgl_sampai}.csv'})


@app.route('/admin/audit-log/purge', methods=['POST'])
@admin_required
def audit_log_purge():
    hari = max(request.form.get('hari', 90, type=int), 7)
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM audit_log WHERE waktu < NOW() - INTERVAL '%s days'", (hari,))
    deleted = cur.rowcount; conn.commit(); cur.close()
    log_audit(conn, 'DELETE', 'sistem',
        deskripsi=f'Purge audit log > {hari} hari — {deleted} baris dihapus')
    conn.close()
    flash(f'Berhasil menghapus {deleted} baris log lama (>{hari} hari).', 'success')
    return redirect(url_for('audit_log_index'))


# ══════════════════════════════════════════════════════════════════════════════
# ██  ROUTE — LUPA PASSWORD  ███████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/lupa-password', methods=['GET','POST'])
def lupa_password():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'GET':
        return render_template('lupa_password.html', step='input')

    identitas = request.form.get('identitas', '').strip()
    metode    = request.form.get('metode', 'email')
    if not identitas:
        flash('Masukkan email atau nomor WhatsApp Anda.', 'error')
        return render_template('lupa_password.html', step='input')

    conn = get_db(); cur = q(conn)
    cur.execute("""SELECT id,nama,email,no_hp,status FROM users
        WHERE email=%s OR no_hp=%s LIMIT 1""", (identitas, identitas))
    user = cur.fetchone()

    if not user:
        cur.close(); conn.close()
        log_audit(conn, 'OTP_KIRIM', 'auth',
            deskripsi=f'Lupa password — akun tidak ditemukan: {identitas}',
            status='error', user_id=None, user_nama=identitas, user_role='-')
        flash('Jika akun dengan data tersebut ada, OTP akan dikirimkan segera.', 'info')
        return render_template('lupa_password.html', step='input')

    if user['status'] in ('pending','rejected'):
        cur.close(); conn.close()
        flash('Akun belum aktif. Hubungi administrator.', 'warning')
        return render_template('lupa_password.html', step='input')

    user = dict(user)
    cfg  = _get_notif_config(conn)
    if metode == 'whatsapp':
        tujuan = user.get('no_hp') or ''
        if not tujuan:
            cur.close(); conn.close()
            flash('Nomor WhatsApp tidak terdaftar pada akun ini. Coba via Email.', 'warning')
            return render_template('lupa_password.html', step='input')
    else:
        metode = 'email'
        tujuan = user.get('email') or ''

    otp = _generate_otp(cfg['otp_length'])
    _simpan_otp(conn, user['id'], otp, metode, tujuan, cfg['otp_expire'])
    cur.close()

    ok, err_msg = (_kirim_email_otp if metode=='email' else _kirim_wa_otp)(cfg, tujuan, user['nama'], otp)
    if not ok:
        conn.close()
        log_audit(conn, 'OTP_KIRIM', 'auth',
            deskripsi=f'Gagal kirim OTP {metode}: {err_msg}',
            status='error', ref_id=user['id'], ref_table='users')
        flash(f'Gagal mengirim OTP: {err_msg}', 'error')
        return render_template('lupa_password.html', step='input')

    log_audit(conn, 'OTP_KIRIM', 'auth',
        deskripsi=f'Kirim OTP {metode} ke {_mask_tujuan(tujuan, metode)}',
        ref_id=user['id'], ref_table='users',
        user_id=user['id'], user_nama=user['nama'], user_role='-')
    conn.close()

    session['reset_user_id']  = user['id']
    session['reset_metode']   = metode
    session['reset_tujuan']   = _mask_tujuan(tujuan, metode)
    session['reset_ts']       = datetime.now().isoformat()
    flash(f'OTP telah dikirim ke {_mask_tujuan(tujuan, metode)}.', 'success')
    return render_template('lupa_password.html', step='otp',
        metode=metode, tujuan=_mask_tujuan(tujuan, metode), expire=cfg['otp_expire'])


@app.route('/lupa-password/verifikasi', methods=['POST'])
def verifikasi_otp():
    user_id = session.get('reset_user_id')
    if not user_id:
        flash('Sesi reset telah berakhir. Mulai ulang.', 'error')
        return redirect(url_for('lupa_password'))
    otp_input = request.form.get('otp', '').strip()
    if len(otp_input) < 4:
        flash('Kode OTP tidak valid.', 'error')
        return render_template('lupa_password.html', step='otp',
            metode=session.get('reset_metode'), tujuan=session.get('reset_tujuan'))
    conn = get_db()
    row  = _verifikasi_otp(conn, user_id, otp_input)
    if not row:
        log_audit(conn, 'OTP_VERIF', 'auth',
            deskripsi=f'OTP salah/kadaluarsa untuk user_id {user_id}',
            status='error', ref_id=user_id, ref_table='users')
        conn.close()
        flash('Kode OTP salah atau sudah kadaluarsa. Coba kirim ulang.', 'error')
        return render_template('lupa_password.html', step='otp',
            metode=session.get('reset_metode'), tujuan=session.get('reset_tujuan'))
    log_audit(conn, 'OTP_VERIF', 'auth',
        deskripsi=f'OTP berhasil diverifikasi untuk user_id {user_id}',
        ref_id=user_id, ref_table='users')
    conn.close()
    session['reset_otp_id']   = row['id']
    session['reset_verified'] = True
    return render_template('lupa_password.html', step='reset')


@app.route('/lupa-password/reset', methods=['POST'])
def reset_password():
    user_id  = session.get('reset_user_id')
    otp_id   = session.get('reset_otp_id')
    verified = session.get('reset_verified')
    if not (user_id and otp_id and verified):
        flash('Sesi reset tidak valid. Mulai ulang.', 'error')
        return redirect(url_for('lupa_password'))
    pw_baru    = request.form.get('password_baru', '')
    pw_konfirm = request.form.get('password_konfirm', '')
    if len(pw_baru) < 6:
        flash('Password minimal 6 karakter.', 'error')
        return render_template('lupa_password.html', step='reset')
    if pw_baru != pw_konfirm:
        flash('Konfirmasi password tidak cocok.', 'error')
        return render_template('lupa_password.html', step='reset')
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET password=%s WHERE id=%s",
        (generate_password_hash(pw_baru), user_id))
    conn.commit()
    _tandai_otp_digunakan(conn, otp_id)
    log_audit(conn, 'RESET_PW', 'auth',
        deskripsi=f'Password berhasil direset untuk user_id {user_id}',
        ref_id=user_id, ref_table='users')
    cur.close(); conn.close()
    for k in ['reset_user_id','reset_otp_id','reset_verified',
              'reset_metode','reset_tujuan','reset_ts']:
        session.pop(k, None)
    flash('Password berhasil direset! Silakan login dengan password baru Anda.', 'success')
    return redirect(url_for('login'))


@app.route('/lupa-password/kirim-ulang', methods=['POST'])
def kirim_ulang_otp():
    user_id = session.get('reset_user_id')
    metode  = session.get('reset_metode', 'email')
    if not user_id:
        return jsonify(success=False, message='Sesi tidak valid.')
    conn = get_db(); cur = q(conn)
    cur.execute("SELECT nama,email,no_hp FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    if not user: cur.close(); conn.close(); return jsonify(success=False, message='User tidak ditemukan.')
    user = dict(user)
    cfg  = _get_notif_config(conn)
    tujuan = user.get('no_hp') if metode=='whatsapp' else user.get('email')
    otp = _generate_otp(cfg['otp_length'])
    _simpan_otp(conn, user_id, otp, metode, tujuan, cfg['otp_expire'])
    ok, err = (_kirim_email_otp if metode=='email' else _kirim_wa_otp)(cfg, tujuan, user['nama'], otp)
    log_audit(conn, 'OTP_KIRIM', 'auth',
        deskripsi=f'Kirim ulang OTP {metode} — {"sukses" if ok else "gagal: "+err}',
        ref_id=user_id, ref_table='users', status='success' if ok else 'error')
    cur.close(); conn.close()
    if ok: return jsonify(success=True, message=f'OTP baru dikirim ke {_mask_tujuan(tujuan,metode)}.')
    return jsonify(success=False, message=f'Gagal kirim ulang: {err}')


@app.route('/admin/settings/notif', methods=['POST'])
@admin_required
def admin_settings_notif():
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""UPDATE settings SET
            smtp_host=%s, smtp_port=%s, smtp_user=%s, smtp_pass=%s,
            smtp_from_name=%s, smtp_tls=%s, fonnte_token=%s WHERE id=1""",
            (request.form.get('smtp_host','').strip(),
             int(request.form.get('smtp_port',587) or 587),
             request.form.get('smtp_user','').strip(),
             request.form.get('smtp_pass','').strip(),
             request.form.get('smtp_from_name','Presensi Digital').strip(),
             request.form.get('smtp_tls','true')=='true',
             request.form.get('fonnte_token','').strip()))
        conn.commit()
        log_audit(conn, 'SETTING', 'settings', deskripsi='Update konfigurasi SMTP & WhatsApp')
        flash('Konfigurasi notifikasi berhasil disimpan!', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Gagal menyimpan: {e}', 'error')
    finally:
        cur.close(); conn.close()
    return redirect(url_for('admin_settings'))


@app.route('/admin/test-notif', methods=['POST'])
@admin_required
def admin_test_notif():
    metode = request.form.get('metode', 'email')
    tujuan = request.form.get('tujuan', '').strip()
    if not tujuan: return jsonify(success=False, message='Tujuan tidak boleh kosong')
    conn = get_db(); cfg = _get_notif_config(conn); conn.close()
    otp = _generate_otp(cfg['otp_length'])
    nama = session.get('nama', 'Admin')
    ok, err = (_kirim_email_otp if metode=='email' else _kirim_wa_otp)(cfg, tujuan, nama, otp)
    if ok: return jsonify(success=True, message=f'Test OTP ({otp}) berhasil dikirim ke {tujuan}')
    return jsonify(success=False, message=err)


def run_migrations():
    """Jalankan migrasi kolom baru secara terpisah — aman dipanggil tiap restart."""
    migrations = [
        "ALTER TABLE dosir_file ADD COLUMN IF NOT EXISTS tanggal_expired DATE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS nip TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS jabatan_kode TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS ttd_image TEXT",
        "ALTER TABLE nota_dinas ADD COLUMN IF NOT EXISTS dasar TEXT",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS logo TEXT",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS smtp_host TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS smtp_port INTEGER DEFAULT 587",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS smtp_user TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS smtp_pass TEXT DEFAULT ''",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS smtp_from_name TEXT DEFAULT 'Presensi Digital'",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS smtp_tls BOOLEAN DEFAULT TRUE",
        "ALTER TABLE settings ADD COLUMN IF NOT EXISTS fonnte_token TEXT DEFAULT ''",
    ]
    try:
        conn = get_db()
        cur = conn.cursor()
        for sql in migrations:
            try:
                cur.execute(sql)
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"[migration] skip: {e}")
        cur.close()
        conn.close()
        print("[migration] selesai.")
    except Exception as e:
        print(f"[migration] error koneksi: {e}")


# Jalankan init_db saat modul dimuat (termasuk saat dijalankan via Gunicorn)
with app.app_context():
    try:
        run_migrations()
    except Exception as _e:
        print(f"[migration] warning: {_e}")
    try:
        init_db()
    except Exception as _e:
        print(f"[init_db] warning: {_e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5030)