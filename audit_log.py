# audit_log.py
# ═══════════════════════════════════════════════════════════════════
# MODUL AUDIT LOG - Presensi Digital
# ═══════════════════════════════════════════════════════════════════
#
# CARA INTEGRASI KE app.py:
#
#   1. Letakkan file ini di folder yang sama dengan app.py
#   2. Di bagian import atas app.py, tambahkan:
#
#        from audit_log import init_audit_table, log_audit, audit_bp
#
#   3. Setelah app = Flask(__name__), tambahkan:
#
#        app.register_blueprint(audit_bp)
#
#   4. Di dalam fungsi init_db(), sebelum conn.commit() akhir, tambahkan:
#
#        init_audit_table(cur)
#
#   5. Di setiap route yang ingin di-log, panggil:
#
#        log_audit(conn, aksi, modul, deskripsi, data_lama, data_baru, ref_id)
#
#   Contoh:
#        log_audit(conn, 'UPDATE', 'pegawai', f'Edit data {user["nama"]}',
#                  data_lama={'status': 'active'}, data_baru={'status': 'inactive'},
#                  ref_id=uid)
#
# ═══════════════════════════════════════════════════════════════════

from flask import Blueprint, request, session, render_template, jsonify, g
from datetime import datetime, date, timedelta
from functools import wraps
import json
import psycopg2
import psycopg2.extras
import os

# ── Config DB (sama seperti app.py) ─────────────────────────────────────────
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'presensi')
DB_USER = os.environ.get('DB_USER', 'presensi')
DB_PASS = os.environ.get('DB_PASS', 'presensi123')

def _get_db():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )
    conn.autocommit = False
    return conn

def _q(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# ── Daftar semua aksi dan modul yang dimonitor ───────────────────────────────
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
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. INISIALISASI TABEL
# ─────────────────────────────────────────────────────────────────────────────

def init_audit_table(cur):
    """
    Buat tabel audit_log jika belum ada.
    Dipanggil dari dalam init_db() di app.py, parameter cur adalah cursor aktif.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          BIGSERIAL PRIMARY KEY,
            waktu       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
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

    # Index untuk query cepat
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_waktu    ON audit_log(waktu DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_user     ON audit_log(user_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_modul    ON audit_log(modul)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_aksi     ON audit_log(aksi)
    """)
    print("✅ Tabel audit_log siap.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. FUNGSI LOG UTAMA
# ─────────────────────────────────────────────────────────────────────────────

def log_audit(conn, aksi, modul, deskripsi=None,
              data_lama=None, data_baru=None,
              ref_id=None, ref_table=None,
              status='success', pesan_error=None,
              user_id=None, user_nama=None, user_role=None):
    """
    Catat satu baris audit log. Aman dipanggil dari mana saja.

    Parameter:
      conn         -- koneksi psycopg2 aktif (yang sudah commit/rollback urusan bisnis)
      aksi         -- kode aksi (lihat AKSI_LABELS), misal 'LOGIN', 'UPDATE', 'DELETE'
      modul        -- nama modul (lihat MODUL_LABELS), misal 'pegawai', 'absensi'
      deskripsi    -- teks bebas, misal 'Admin edit shift Pagi → Siang'
      data_lama    -- dict data sebelum diubah (opsional)
      data_baru    -- dict data sesudah diubah (opsional)
      ref_id       -- ID baris yang terkait (misal id user, id izin)
      ref_table    -- nama tabel terkait (misal 'users', 'izin')
      status       -- 'success' atau 'error'
      pesan_error  -- pesan error jika status='error'
    """
    try:
        # Ambil info user dari session Flask jika tidak disupply
        if user_id is None:
            user_id   = session.get('user_id')
        if user_nama is None:
            user_nama = session.get('nama', 'System')
        if user_role is None:
            user_role = session.get('role', '-')

        # Ambil IP dan user agent dari request Flask
        try:
            ip  = request.headers.get('X-Forwarded-For', request.remote_addr) or '-'
            ua  = (request.user_agent.string or '-')[:300]
        except RuntimeError:
            # Dipanggil di luar request context
            ip = 'system'
            ua = 'system'

        # Sanitasi data: hapus field sensitif
        def _sanitize(d):
            if not isinstance(d, dict):
                return d
            skip = {'password', 'password_hash', 'token', 'secret'}
            return {k: '***' if k in skip else v for k, v in d.items()}

        dl = json.dumps(_sanitize(data_lama), default=str) if data_lama else None
        db = json.dumps(_sanitize(data_baru),  default=str) if data_baru else None

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_log
              (user_id, user_nama, user_role, aksi, modul, deskripsi,
               data_lama, data_baru, ref_id, ref_table,
               ip_address, user_agent, status, pesan_error)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            user_id, user_nama, user_role,
            aksi, modul, deskripsi,
            dl, db,
            ref_id, ref_table,
            ip, ua,
            status, pesan_error
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        # Audit log TIDAK boleh mengganggu bisnis utama
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[AUDIT ERROR] {e}")


def log_error(conn, aksi, modul, pesan_error, deskripsi=None, ref_id=None):
    """Shortcut untuk mencatat kejadian error."""
    log_audit(conn, aksi, modul, deskripsi=deskripsi,
              ref_id=ref_id, status='error', pesan_error=str(pesan_error))


# ─────────────────────────────────────────────────────────────────────────────
# 3. DECORATOR — auto-log setiap request
# ─────────────────────────────────────────────────────────────────────────────

# Route yang di-skip dari auto-log (terlalu berisik)
_SKIP_AUTO_LOG = {
    '/static', '/favicon', '/api/notifikasi',
    '/api/shift', '/dashboard', '/riwayat',
}

def auto_audit_middleware(app):
    """
    Pasang after_request hook untuk mencatat semua mutasi HTTP (POST/PUT/DELETE).
    Dipanggil sekali saat app startup:  auto_audit_middleware(app)
    """
    @app.after_request
    def _after(response):
        if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return response
        path = request.path
        if any(path.startswith(s) for s in _SKIP_AUTO_LOG):
            return response
        # Hanya log yang berhasil (2xx) atau redirect (3xx) — bukan error server
        if response.status_code >= 500:
            return response
        try:
            conn = _get_db()
            log_audit(
                conn,
                aksi='VIEW',
                modul=_path_to_modul(path),
                deskripsi=f'{request.method} {path} → {response.status_code}',
            )
            conn.close()
        except Exception:
            pass
        return response

def _path_to_modul(path):
    """Tebak modul dari URL path."""
    mapping = [
        ('/admin/pegawai',   'pegawai'),
        ('/admin/absensi',   'absensi'),
        ('/admin/izin',      'izin'),
        ('/admin/laporan',   'laporan'),
        ('/admin/departemen','departemen'),
        ('/admin/shift',     'shift'),
        ('/admin/settings',  'settings'),
        ('/admin/nota',      'nota_dinas'),
        ('/admin/surat',     'surat'),
        ('/admin/dosir',     'dosir'),
        ('/admin/role',      'role'),
        ('/admin/approval',  'approval'),
        ('/nota-dinas',      'nota_dinas'),
        ('/surat',           'surat'),
        ('/izin',            'izin'),
        ('/absen',           'absensi'),
        ('/profil',          'profil'),
        ('/login',           'auth'),
        ('/logout',          'auth'),
        ('/register',        'auth'),
        ('/dosir',           'dosir'),
    ]
    for prefix, modul in mapping:
        if path.startswith(prefix):
            return modul
    return 'sistem'


# ─────────────────────────────────────────────────────────────────────────────
# 4. BLUEPRINT — halaman admin audit log
# ─────────────────────────────────────────────────────────────────────────────

audit_bp = Blueprint('audit', __name__, url_prefix='/admin/audit-log')

def _admin_required_bp(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session or session.get('role') != 'admin':
            from flask import flash, redirect, url_for
            flash('Akses ditolak!', 'error')
            return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return dec


@audit_bp.route('/')
@_admin_required_bp
def index():
    """Halaman utama audit log dengan filter & paginasi."""
    conn = _get_db(); cur = _q(conn)

    page      = request.args.get('page', 1, type=int)
    per_page  = request.args.get('per_page', 50, type=int)
    per_page  = min(per_page, 200)
    offset    = (page - 1) * per_page

    # Filter
    aksi      = request.args.get('aksi', '')
    modul     = request.args.get('modul', '')
    user_id   = request.args.get('user_id', '', type=str)
    status    = request.args.get('status', '')
    tgl_dari  = request.args.get('tgl_dari', '')
    tgl_sampai= request.args.get('tgl_sampai', '')
    cari      = request.args.get('cari', '')

    conditions = []
    params     = []

    if aksi:
        conditions.append("aksi = %s"); params.append(aksi)
    if modul:
        conditions.append("modul = %s"); params.append(modul)
    if user_id and user_id.isdigit():
        conditions.append("user_id = %s"); params.append(int(user_id))
    if status:
        conditions.append("status = %s"); params.append(status)
    if tgl_dari:
        conditions.append("waktu::date >= %s"); params.append(tgl_dari)
    if tgl_sampai:
        conditions.append("waktu::date <= %s"); params.append(tgl_sampai)
    if cari:
        conditions.append("(deskripsi ILIKE %s OR user_nama ILIKE %s OR pesan_error ILIKE %s)")
        like = f'%{cari}%'
        params += [like, like, like]

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

    # Total count
    cur.execute(f"SELECT COUNT(*) FROM audit_log {where}", params)
    total = cur.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Data
    cur.execute(f"""
        SELECT al.*,
               u.foto as user_foto
        FROM audit_log al
        LEFT JOIN users u ON al.user_id = u.id
        {where}
        ORDER BY al.waktu DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset])
    logs = cur.fetchall()

    # Statistik ringkasan (24 jam terakhir)
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE status='success') as sukses,
            COUNT(*) FILTER (WHERE status='error')   as error,
            COUNT(DISTINCT user_id)                  as user_aktif,
            COUNT(*) FILTER (WHERE aksi='LOGIN')     as total_login,
            COUNT(*) FILTER (WHERE aksi='LOGIN_GAGAL') as login_gagal,
            COUNT(*) FILTER (WHERE aksi IN ('CREATE','UPDATE','DELETE')) as mutasi
        FROM audit_log
        WHERE waktu >= NOW() - INTERVAL '24 hours'
    """)
    stats = cur.fetchone()

    # Aktivitas per jam (12 jam terakhir)
    cur.execute("""
        SELECT
            date_trunc('hour', waktu) as jam,
            COUNT(*) as jumlah
        FROM audit_log
        WHERE waktu >= NOW() - INTERVAL '12 hours'
        GROUP BY jam ORDER BY jam
    """)
    aktivitas_per_jam = cur.fetchall()

    # Top users hari ini
    cur.execute("""
        SELECT user_nama, user_role, COUNT(*) as aksi_count
        FROM audit_log
        WHERE waktu::date = CURRENT_DATE AND user_id IS NOT NULL
        GROUP BY user_nama, user_role
        ORDER BY aksi_count DESC LIMIT 10
    """)
    top_users = cur.fetchall()

    # Daftar user untuk filter
    cur.execute("""
        SELECT DISTINCT al.user_id, al.user_nama, al.user_role
        FROM audit_log al
        WHERE al.user_id IS NOT NULL
        ORDER BY al.user_nama LIMIT 100
    """)
    daftar_user = cur.fetchall()

    cur.close(); conn.close()

    return render_template('admin/audit_log.html',
        logs=logs,
        stats=stats,
        aktivitas_per_jam=[dict(r) for r in aktivitas_per_jam],
        top_users=top_users,
        daftar_user=daftar_user,
        total=total,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        aksi=aksi, modul=modul, user_id=user_id,
        status=status, tgl_dari=tgl_dari, tgl_sampai=tgl_sampai,
        cari=cari,
        AKSI_LABELS=AKSI_LABELS,
        MODUL_LABELS=MODUL_LABELS,
    )


@audit_bp.route('/detail/<int:log_id>')
@_admin_required_bp
def detail(log_id):
    """Detail satu baris audit log (JSON diff)."""
    conn = _get_db(); cur = _q(conn)
    cur.execute("SELECT * FROM audit_log WHERE id=%s", (log_id,))
    log = cur.fetchone()
    cur.close(); conn.close()
    if not log:
        from flask import abort
        abort(404)
    return render_template('admin/audit_log_detail.html',
        log=dict(log), AKSI_LABELS=AKSI_LABELS, MODUL_LABELS=MODUL_LABELS)


@audit_bp.route('/api/stats')
@_admin_required_bp
def api_stats():
    """JSON endpoint untuk grafik realtime."""
    conn = _get_db(); cur = _q(conn)
    jam = request.args.get('jam', 24, type=int)

    cur.execute("""
        SELECT
            date_trunc('hour', waktu) as jam,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status='error') as error
        FROM audit_log
        WHERE waktu >= NOW() - INTERVAL '%s hours'
        GROUP BY jam ORDER BY jam
    """, (jam,))
    per_jam = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT aksi, COUNT(*) as jumlah
        FROM audit_log
        WHERE waktu >= NOW() - INTERVAL '24 hours'
        GROUP BY aksi ORDER BY jumlah DESC LIMIT 10
    """)
    per_aksi = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT modul, COUNT(*) as jumlah
        FROM audit_log
        WHERE waktu >= NOW() - INTERVAL '24 hours'
        GROUP BY modul ORDER BY jumlah DESC
    """)
    per_modul = [dict(r) for r in cur.fetchall()]

    cur.close(); conn.close()
    return jsonify(per_jam=per_jam, per_aksi=per_aksi, per_modul=per_modul)


@audit_bp.route('/export')
@_admin_required_bp
def export_csv():
    """Export audit log ke CSV."""
    import csv, io
    conn = _get_db(); cur = _q(conn)

    tgl_dari   = request.args.get('tgl_dari',   (date.today() - timedelta(days=30)).isoformat())
    tgl_sampai = request.args.get('tgl_sampai', date.today().isoformat())

    cur.execute("""
        SELECT waktu, user_nama, user_role, aksi, modul, deskripsi,
               ref_id, ref_table, ip_address, status, pesan_error
        FROM audit_log
        WHERE waktu::date BETWEEN %s AND %s
        ORDER BY waktu DESC
    """, (tgl_dari, tgl_sampai))
    rows = cur.fetchall()
    cur.close(); conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Waktu','User','Role','Aksi','Modul','Deskripsi',
                     'Ref ID','Ref Table','IP Address','Status','Error'])
    for r in rows:
        writer.writerow([
            r['waktu'], r['user_nama'], r['user_role'],
            r['aksi'], r['modul'], r['deskripsi'],
            r['ref_id'], r['ref_table'], r['ip_address'],
            r['status'], r['pesan_error']
        ])

    from flask import Response
    return Response(
        '\ufeff' + output.getvalue(),  # BOM untuk Excel UTF-8
        mimetype='text/csv',
        headers={'Content-Disposition':
                 f'attachment; filename=audit_log_{tgl_dari}_{tgl_sampai}.csv'}
    )


@audit_bp.route('/purge', methods=['POST'])
@_admin_required_bp
def purge():
    """Hapus log lama (default: lebih dari 90 hari)."""
    hari = request.form.get('hari', 90, type=int)
    hari = max(hari, 7)  # minimal 7 hari

    conn = _get_db(); cur = conn.cursor()
    cur.execute("""
        DELETE FROM audit_log
        WHERE waktu < NOW() - INTERVAL '%s days'
    """, (hari,))
    deleted = cur.rowcount
    conn.commit()
    cur.close(); conn.close()

    # Log aksi purge itu sendiri
    conn2 = _get_db()
    log_audit(conn2, 'DELETE', 'sistem',
              deskripsi=f'Purge audit log > {hari} hari — {deleted} baris dihapus')
    conn2.close()

    from flask import flash, redirect, url_for
    flash(f'Berhasil menghapus {deleted} baris log lama (>{hari} hari).', 'success')
    return redirect(url_for('audit.index'))
