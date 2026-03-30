from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os, math, json, io
from functools import wraps
import psycopg2
import psycopg2.extras
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm

app = Flask(__name__)
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
            nama TEXT NOT NULL,
            jam_masuk TEXT NOT NULL,
            jam_keluar TEXT NOT NULL,
            toleransi_menit INTEGER DEFAULT 15,
            deskripsi TEXT,
            warna TEXT DEFAULT '#10b981',
            aktif INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
    # Approval roles default
    cur.execute("""
        INSERT INTO surat_template (nama, jenis, konten) VALUES
        ('Surat Perintah Tugas', 'surat_perintah',
         'Diperintahkan kepada:

Nama    : {{nama}}
Jabatan : {{jabatan}}
Unit    : {{departemen}}

Untuk melaksanakan tugas:
{{isi}}

Dilaksanakan mulai tanggal {{tanggal}} s.d. selesai.')
        ON CONFLICT DO NOTHING
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
        cur.execute("INSERT INTO shift (nama,jam_masuk,jam_keluar,toleransi_menit,deskripsi,warna) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", s)


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
        cur.close(); conn.close()
        if user and check_password_hash(user['password'], request.form.get('password','')):
            if user['status'] == 'pending':
                flash('Akun belum divalidasi admin.', 'warning')
            elif user['status'] == 'rejected':
                flash('Akun ditolak. Hubungi admin.', 'error')
            else:
                session.update({'user_id':user['id'],'nama':user['nama'],'role':user['role'],'foto':user['foto']})
                return redirect(url_for('dashboard'))
        else:
            flash('Email atau password salah.', 'error')
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
            cur.execute("""INSERT INTO users (nik,nama,email,password,jabatan,departemen,departemen_id,no_hp,alamat,tanggal_lahir,jenis_kelamin,foto)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (request.form['nik'].strip(), request.form['nama'].strip(), request.form['email'].strip(),
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
    session.clear(); return redirect(url_for('login'))

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
        if foto_path:
            cur.execute("UPDATE users SET no_hp=%s,alamat=%s,foto=%s WHERE id=%s",
                (request.form.get('no_hp',''), request.form.get('alamat',''), foto_path, uid))
            session['foto'] = foto_path
        else:
            cur.execute("UPDATE users SET no_hp=%s,alamat=%s WHERE id=%s",
                (request.form.get('no_hp',''), request.form.get('alamat',''), uid))
        conn.commit()
        flash('Profil berhasil diperbarui!', 'success')

    cur.execute("""SELECT u.*,d.nama as dept_nama,d.warna as dept_warna,
        s.nama as shift_nama,s.jam_masuk as shift_masuk,s.jam_keluar as shift_keluar
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()
    cur.close(); conn.close()
    if not user:
        session.clear()
        flash('Sesi tidak valid, silakan login kembali.', 'warning')
        return redirect(url_for('login'))
    return render_template('profil.html', user=user)

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
        dept_shifts.setdefault(ds['departemen_id'], []).append(ds['shift_id'])
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
    cur.execute("DELETE FROM departemen_shift WHERE departemen_id=%s", (did,))
    for sid in request.form.getlist('shift_ids'):
        cur.execute("INSERT INTO departemen_shift (departemen_id,shift_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (did, sid))
    conn.commit(); cur.close(); conn.close()
    flash('Shift departemen diperbarui!', 'success')
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
    try:
        cur.execute("INSERT INTO shift (nama,jam_masuk,jam_keluar,toleransi_menit,deskripsi,warna) VALUES (%s,%s,%s,%s,%s,%s)",
            (request.form['nama'], request.form['jam_masuk'], request.form['jam_keluar'],
             int(request.form.get('toleransi_menit', 15)), request.form.get('deskripsi',''),
             request.form.get('warna','#10b981')))
        conn.commit(); flash(f'Shift "{request.form["nama"]}" ditambahkan!', 'success')
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
        dept_id = request.form.get('departemen_id') or None; dept_nama = ''
        if dept_id:
            cur.execute("SELECT nama FROM departemen WHERE id=%s", (dept_id,))
            d = cur.fetchone()
            if d: dept_nama = d['nama']
        foto_path = None
        if 'foto' in request.files:
            f = request.files['foto']
            if f and f.filename and allowed_file(f.filename):
                fn = secure_filename(f"user_{uid}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{f.filename.rsplit('.',1)[-1].lower()}")
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn)); foto_path = fn
        fields = ["nik=%s","nama=%s","email=%s","jabatan=%s","departemen=%s","departemen_id=%s",
                  "shift_id=%s","no_hp=%s","alamat=%s","tanggal_lahir=%s","jenis_kelamin=%s","status=%s","role=%s"]
        params = [request.form['nik'], request.form['nama'], request.form['email'],
                  request.form.get('jabatan',''), dept_nama, dept_id,
                  request.form.get('shift_id') or None, request.form.get('no_hp',''),
                  request.form.get('alamat',''), request.form.get('tanggal_lahir',''),
                  request.form.get('jenis_kelamin',''), request.form.get('status','active'),
                  request.form.get('role','user')]
        if foto_path: fields.append("foto=%s"); params.append(foto_path)
        if request.form.get('password'): fields.append("password=%s"); params.append(generate_password_hash(request.form['password']))
        params.append(uid)
        cur.execute(f"UPDATE users SET {','.join(fields)} WHERE id=%s", params)
        conn.commit(); cur.close(); conn.close()
        flash('Data pegawai diperbarui!', 'success')
        return redirect(url_for('admin_pegawai'))
    cur.execute("""SELECT u.*,d.nama as dept_nama,s.nama as shift_nama
        FROM users u LEFT JOIN departemen d ON u.departemen_id=d.id
        LEFT JOIN shift s ON u.shift_id=s.id WHERE u.id=%s""", (uid,))
    user = cur.fetchone()
    cur.execute("SELECT * FROM departemen WHERE aktif=1 ORDER BY nama")
    depts = cur.fetchall()
    cur.execute("SELECT * FROM shift WHERE aktif=1 ORDER BY jam_masuk")
    shifts = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/edit_pegawai.html', user=user, depts=depts, shifts=shifts)

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
    cur.execute("UPDATE users SET status=%s WHERE id=%s",
        ('active' if action=='approve' else 'rejected', uid))
    conn.commit(); cur.close(); conn.close()
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
        conn.commit(); flash('Settings disimpan!', 'success')
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    return render_template('admin/settings.html', settings=settings)

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
    conn.commit(); cur.close(); conn.close()
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
    return render_template('dosir.html', jenis_list=jenis_list, uploads=uploads, user=user)


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

    cur.execute("""INSERT INTO dosir_file (user_id, jenis_id, filename, original_name, keterangan, status)
        VALUES (%s,%s,%s,%s,%s,'pending')
        ON CONFLICT (user_id, jenis_id) DO UPDATE
        SET filename=EXCLUDED.filename, original_name=EXCLUDED.original_name,
            keterangan=EXCLUDED.keterangan, status='pending',
            catatan_admin=NULL, uploaded_at=CURRENT_TIMESTAMP, verified_at=NULL""",
        (uid, jid, fn, original, keterangan))
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
    cur.execute("""SELECT jenis_id,
        COUNT(*) as total,
        SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) as verified,
        SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
        SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) as rejected
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
    query = """SELECT df.*, u.nama as user_nama, u.nik, d.nama as dept_nama,
        dj.nama as jenis_nama, dj.wajib
        FROM dosir_file df
        JOIN users u ON df.user_id=u.id
        LEFT JOIN departemen d ON u.departemen_id=d.id
        JOIN dosir_jenis dj ON df.jenis_id=dj.id
        WHERE 1=1"""
    params = []
    if dept_id:
        query += " AND u.departemen_id=%s"; params.append(dept_id)
    if status_filter:
        query += " AND df.status=%s"; params.append(status_filter)
    query += " ORDER BY df.uploaded_at DESC"
    cur.execute(query, params)
    files = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin/dosir_files.html', files=files, depts=depts,
        dept_id=dept_id, status_filter=status_filter)


@app.route('/admin/dosir/verify/<int:fid>/<action>', methods=['POST'])
@admin_required
def admin_dosir_verify(fid, action):
    catatan = request.form.get('catatan','').strip()
    conn = get_db(); cur = q(conn)
    if action == 'verify':
        cur.execute("""UPDATE dosir_file SET status='verified', catatan_admin=%s,
            verified_at=CURRENT_TIMESTAMP WHERE id=%s""", (catatan, fid))
        flash('Dokumen berhasil diverifikasi.', 'success')
    elif action == 'reject':
        cur.execute("""UPDATE dosir_file SET status='rejected', catatan_admin=%s,
            verified_at=CURRENT_TIMESTAMP WHERE id=%s""", (catatan, fid))
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
        cur.execute("""INSERT INTO nota_dinas (nomor,judul,perihal,kepada,isi,dari_user,lampiran)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (nomor, judul, perihal, kepada, isi, uid, lampiran))
        nid = cur.fetchone()['id']
        # Buat approval chain
        for lv in APPROVAL_LEVELS:
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
        u.departemen as dept_pembuat FROM nota_dinas nd
        JOIN users u ON nd.dari_user=u.id WHERE nd.id=%s""", (nid,))
    nota = cur.fetchone()
    cur.execute("""SELECT na.*,u.nama as approver_nama,u.jabatan as approver_jabatan
        FROM nota_approval na LEFT JOIN users u ON na.user_id=u.id
        WHERE na.nota_id=%s ORDER BY na.level""", (nid,))
    approvals = cur.fetchall()
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    instansi = settings['nama_perusahaan'] if settings else 'RS Slamet Riyadi'
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.platypus import HRFlowable, Image as RLImage
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=3*cm, rightMargin=2*cm)
    elems = []
    # Header
    elems.append(Paragraph(f"<b>{instansi.upper()}</b>", ParagraphStyle('h',fontSize=14,alignment=TA_CENTER,spaceAfter=4)))
    elems.append(HRFlowable(width="100%", thickness=2, color=colors.black))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=colors.black, spaceAfter=8))
    elems.append(Paragraph("<b>NOTA DINAS</b>", ParagraphStyle('t',fontSize=13,alignment=TA_CENTER,spaceAfter=10)))
    # Info
    tgl = nota['tanggal'].strftime('%d %B %Y') if hasattr(nota['tanggal'],'strftime') else str(nota['tanggal'])
    info = [
        ['Nomor', f": {nota['nomor'] or '-'}"],
        ['Kepada', f": {nota['kepada'] or '-'}"],
        ['Dari', f": {nota['nama_pembuat']} / {nota['jabatan_pembuat'] or '-'}"],
        ['Perihal', f": {nota['perihal'] or nota['judul']}"],
        ['Tanggal', f": {tgl}"],
    ]
    info_table = Table(info, colWidths=[3.5*cm, 12.5*cm])
    info_table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'Helvetica'),
                                    ('FONTSIZE',(0,0),(-1,-1),11),
                                    ('VALIGN',(0,0),(-1,-1),'TOP'),
                                    ('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    elems.append(info_table)
    elems.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceBefore=8, spaceAfter=10))
    # Isi
    for line in (nota['isi'] or '').split('\n'):
        elems.append(Paragraph(line or '&nbsp;', ParagraphStyle('body',fontSize=11,leading=16,
            alignment=TA_JUSTIFY, spaceAfter=4)))
    elems.append(Spacer(1, 1*cm))
    # Kolom TTD berjenjang
    elems.append(Paragraph("<b>Mengetahui / Menyetujui:</b>", ParagraphStyle('k',fontSize=11,spaceAfter=8)))
    ttd_cols = []
    for ap in approvals:
        status_txt = '✓ Disetujui' if ap['status']=='approved' else ('✗ Ditolak' if ap['status']=='rejected' else 'Menunggu...')
        ttd_cols.append(Paragraph(f"<b>{ap['role_label']}</b><br/><br/><br/><br/>{ap['approver_nama'] or '____________'}<br/><font size=9>{status_txt}</font>",
            ParagraphStyle('ttd',fontSize=10,alignment=TA_CENTER)))
    if ttd_cols:
        w = 16/len(ttd_cols)
        ttd_table = Table([ttd_cols], colWidths=[w*cm]*len(ttd_cols))
        ttd_table.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),
                                        ('VALIGN',(0,0),(-1,-1),'TOP'),
                                        ('BOX',(0,0),(-1,-1),0.5,colors.grey),
                                        ('INNERGRID',(0,0),(-1,-1),0.5,colors.grey),
                                        ('TOPPADDING',(0,0),(-1,-1),8),
                                        ('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        elems.append(ttd_table)
    doc.build(elems)
    buf.seek(0)
    nomor_clean = (nota['nomor'] or str(nid)).replace('/','_')
    return send_file(buf, mimetype='application/pdf',
                     download_name=f"nota_{nomor_clean}.pdf", as_attachment=False)

# ── ADMIN NOTA DINAS ──────────────────────────────────────────────────────────

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




if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5030)