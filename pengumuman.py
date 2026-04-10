"""
pengumuman.py — Blueprint fitur Pengumuman Popup
Daftarkan di app.py:
    from pengumuman import pengumuman_bp, init_pengumuman_table
    app.register_blueprint(pengumuman_bp)
Panggil init_pengumuman_table(cur) di dalam fungsi init_db() Anda.
"""

from flask import Blueprint, request, jsonify, session, redirect, url_for, flash
from functools import wraps
import psycopg2, psycopg2.extras, os, json
from datetime import datetime

pengumuman_bp = Blueprint('pengumuman', __name__)

# ── DB helper (ikut config app.py) ──────────────────────────────────────────
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

# ── Dekorator admin (sama dengan app.py) ────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id') or session.get('role') != 'admin':
            flash('Akses ditolak.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── DDL: buat tabel jika belum ada ──────────────────────────────────────────
def init_pengumuman_table(cur):
    """Panggil di dalam init_db() di app.py."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pengumuman (
            id          SERIAL PRIMARY KEY,
            judul       TEXT    NOT NULL DEFAULT 'Pengumuman',
            isi         TEXT    NOT NULL DEFAULT '',
            aktif       BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by  INTEGER
        )
    """)
    # Seed baris pertama agar settings.html selalu punya data
    cur.execute("SELECT COUNT(*) FROM pengumuman")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO pengumuman (judul, isi, aktif)
            VALUES ('Selamat Datang!', 'Halo! Ada pengumuman penting untuk Anda.', FALSE)
        """)

# ── Helper ambil pengumuman aktif ────────────────────────────────────────────
def get_pengumuman_aktif(conn):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM pengumuman WHERE aktif = TRUE ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None

# ════════════════════════════════════════════════════════════════════════
#  API — dipanggil dari JavaScript di halaman user setelah login
# ════════════════════════════════════════════════════════════════════════

@pengumuman_bp.route('/api/pengumuman-aktif', methods=['GET'])
def api_pengumuman_aktif():
    """
    Dipanggil JS di halaman dashboard user.
    Mengembalikan pengumuman aktif jika user belum melihatnya hari ini.
    Client menyimpan tanggal terakhir lihat di localStorage.
    """
    if not session.get('user_id'):
        return jsonify(aktif=False)
    try:
        conn = get_db()
        row  = get_pengumuman_aktif(conn)
        conn.close()
        if not row:
            return jsonify(aktif=False)
        return jsonify(
            aktif  = True,
            judul  = row['judul'],
            isi    = row['isi'],
            id     = row['id'],
            updated_at = row['updated_at'].isoformat() if row.get('updated_at') else ''
        )
    except Exception as e:
        return jsonify(aktif=False, error=str(e))


# ════════════════════════════════════════════════════════════════════════
#  ADMIN — simpan / toggle pengumuman
# ════════════════════════════════════════════════════════════════════════

@pengumuman_bp.route('/admin/pengumuman/simpan', methods=['POST'])
@admin_required
def admin_simpan_pengumuman():
    judul = request.form.get('pengumuman_judul', '').strip()
    isi   = request.form.get('pengumuman_isi',   '').strip()
    aktif = request.form.get('pengumuman_aktif', '0') == '1'

    if not judul or not isi:
        flash('Judul dan isi pengumuman tidak boleh kosong.', 'error')
        return redirect(url_for('admin_settings') + '#pengumuman')

    try:
        conn = get_db(); cur = conn.cursor()
        # Cek sudah ada baris?
        cur.execute("SELECT id FROM pengumuman ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE pengumuman
                   SET judul=%s, isi=%s, aktif=%s,
                       updated_at=NOW(), updated_by=%s
                 WHERE id=%s
            """, (judul, isi, aktif, session.get('user_id'), row[0]))
        else:
            cur.execute("""
                INSERT INTO pengumuman (judul, isi, aktif, updated_by)
                VALUES (%s,%s,%s,%s)
            """, (judul, isi, aktif, session.get('user_id')))
        conn.commit()
        cur.close(); conn.close()
        flash('Pengumuman berhasil disimpan!', 'success')
    except Exception as e:
        flash(f'Gagal menyimpan pengumuman: {e}', 'error')

    return redirect(url_for('admin_settings') + '#pengumuman')


@pengumuman_bp.route('/admin/pengumuman/toggle', methods=['POST'])
@admin_required
def admin_toggle_pengumuman():
    """Toggle aktif/nonaktif via AJAX (opsional)."""
    try:
        conn = get_db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, aktif FROM pengumuman ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify(ok=False, message='Belum ada pengumuman.')
        new_state = not row['aktif']
        cur.execute("UPDATE pengumuman SET aktif=%s, updated_at=NOW(), updated_by=%s WHERE id=%s",
                    (new_state, session.get('user_id'), row['id']))
        conn.commit(); cur.close(); conn.close()
        return jsonify(ok=True, aktif=new_state)
    except Exception as e:
        return jsonify(ok=False, message=str(e))