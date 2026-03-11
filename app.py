from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
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
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'photos')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_LAMPIRAN   = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}   # <-- FIX: tambah pdf

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
                  "shift_id=%s","no_hp=%s","alamat=%s","tanggal_lahir=%s","jenis_kelamin=%s","status=%s"]
        params = [request.form['nik'], request.form['nama'], request.form['email'],
                  request.form.get('jabatan',''), dept_nama, dept_id,
                  request.form.get('shift_id') or None, request.form.get('no_hp',''),
                  request.form.get('alamat',''), request.form.get('tanggal_lahir',''),
                  request.form.get('jenis_kelamin',''), request.form.get('status','active')]
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
        cur.execute("""UPDATE settings SET nama_perusahaan=%s,jam_masuk=%s,jam_keluar=%s,
            office_lat=%s,office_lng=%s,max_distance=%s WHERE id=1""",
            (request.form['nama_perusahaan'], request.form['jam_masuk'], request.form['jam_keluar'],
             float(request.form['office_lat']), float(request.form['office_lng']),
             int(request.form['max_distance'])))
        conn.commit(); flash('Settings disimpan!', 'success')
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close(); conn.close()
    return render_template('admin/settings.html', settings=settings)

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

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5030)