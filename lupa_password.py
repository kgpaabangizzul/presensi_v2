# lupa_password.py
# ═══════════════════════════════════════════════════════════════════════
# MODUL LUPA PASSWORD — Presensi Digital
# Mendukung pengiriman OTP via Email (SMTP) dan WhatsApp (Fonnte API)
# ═══════════════════════════════════════════════════════════════════════
#
# CARA INTEGRASI KE app.py:
#
#   1. Letakkan file ini di folder yang sama dengan app.py
#   2. Di bagian import atas app.py:
#
#        from lupa_password import lupa_pw_bp, init_reset_table
#
#   3. Setelah app = Flask(__name__):
#
#        app.register_blueprint(lupa_pw_bp)
#
#   4. Di dalam init_db(), sebelum conn.commit() terakhir:
#
#        init_reset_table(cur)
#
#   5. Konfigurasi environment variable (atau ubah DEFAULT di bawah):
#
#      -- Email (SMTP) --
#      SMTP_HOST       = smtp.gmail.com
#      SMTP_PORT       = 587
#      SMTP_USER       = emailanda@gmail.com
#      SMTP_PASS       = app-password-gmail          ← bukan password biasa!
#      SMTP_FROM_NAME  = Presensi Digital
#
#      -- WhatsApp via Fonnte (https://fonnte.com) --
#      FONNTE_TOKEN    = MsJicxzWZEZXP37JpuSZ
#
#      -- Pengaturan OTP --
#      OTP_EXPIRE_MENIT = 10   (default)
#      OTP_LENGTH       = 6    (default)
#
#   6. Di admin/settings.html tambahkan tab konfigurasi SMTP & WA
#      (lihat bagian bawah file ini untuk snippet HTML)
#
# ═══════════════════════════════════════════════════════════════════════

from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, session, jsonify, g)
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from functools import wraps
import os, random, string, smtplib, ssl, json, re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import psycopg2
import psycopg2.extras

# ── Koneksi DB (sama dengan app.py) ─────────────────────────────────────────
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


# ── Konfigurasi (baca dari env, fallback ke DB settings) ────────────────────
def _get_config(conn=None):
    """Baca konfigurasi SMTP & WA dari tabel settings atau environment."""
    cfg = {
        # SMTP Email
        'smtp_host'      : os.environ.get('SMTP_HOST', ''),
        'smtp_port'      : int(os.environ.get('SMTP_PORT', 587)),
        'smtp_user'      : os.environ.get('SMTP_USER', ''),
        'smtp_pass'      : os.environ.get('SMTP_PASS', ''),
        'smtp_from_name' : os.environ.get('SMTP_FROM_NAME', 'Presensi Digital'),
        'smtp_tls'       : os.environ.get('SMTP_TLS', 'true').lower() == 'true',
        # WhatsApp via Fonnte
        'fonnte_token'   : os.environ.get('FONNTE_TOKEN', ''),
        'fonnte_url'     : 'https://api.fonnte.com/send',
        # OTP
        'otp_expire'     : int(os.environ.get('OTP_EXPIRE_MENIT', 10)),
        'otp_length'     : int(os.environ.get('OTP_LENGTH', 6)),
        # Nama perusahaan
        'nama_perusahaan': 'Presensi Digital',
    }
    # Override dari tabel settings jika ada
    try:
        _conn = conn or _get_db()
        cur = _conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM settings WHERE id=1")
        row = cur.fetchone()
        if row:
            cfg['nama_perusahaan'] = row.get('nama_perusahaan', cfg['nama_perusahaan'])
            # Kolom tambahan (jika sudah di-ALTER)
            for k in ['smtp_host','smtp_port','smtp_user','smtp_pass',
                      'smtp_from_name','fonnte_token']:
                if row.get(k):
                    cfg[k] = row[k]
        cur.close()
        if not conn:
            _conn.close()
    except Exception:
        pass
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# 1. INISIALISASI TABEL
# ─────────────────────────────────────────────────────────────────────────────

def init_reset_table(cur):
    """
    Buat tabel password_reset_otp jika belum ada.
    Tambahkan kolom SMTP/WA ke tabel settings.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_otp (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            otp_code    TEXT NOT NULL,
            metode      TEXT NOT NULL DEFAULT 'email',   -- 'email' atau 'whatsapp'
            tujuan      TEXT NOT NULL,                   -- email atau no_hp tujuan
            kadaluarsa  TIMESTAMP NOT NULL,
            digunakan   BOOLEAN DEFAULT FALSE,
            ip_address  TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_otp_user
        ON password_reset_otp(user_id, digunakan)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_otp_kode
        ON password_reset_otp(otp_code, digunakan)
    """)

    # Tambah kolom konfigurasi ke settings jika belum ada
    kolom_baru = [
        ('smtp_host',      'TEXT DEFAULT \'\''),
        ('smtp_port',      'INTEGER DEFAULT 587'),
        ('smtp_user',      'TEXT DEFAULT \'\''),
        ('smtp_pass',      'TEXT DEFAULT \'\''),
        ('smtp_from_name', 'TEXT DEFAULT \'Presensi Digital\''),
        ('smtp_tls',       'BOOLEAN DEFAULT TRUE'),
        ('fonnte_token',   'TEXT DEFAULT \'\''),
    ]
    for kolom, tipe in kolom_baru:
        try:
            cur.execute(f"ALTER TABLE settings ADD COLUMN IF NOT EXISTS {kolom} {tipe}")
        except Exception:
            pass

    print("✅ Tabel password_reset_otp & kolom settings siap.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. FUNGSI GENERATE & KIRIM OTP
# ─────────────────────────────────────────────────────────────────────────────

def _generate_otp(length=6):
    """Generate kode OTP numerik."""
    return ''.join(random.choices(string.digits, k=length))


def _simpan_otp(conn, user_id, otp_code, metode, tujuan, expire_menit=10):
    """Simpan OTP ke DB. Invalidasi OTP lama user yang sama."""
    cur = conn.cursor()
    # Invalidasi OTP lama
    cur.execute("""
        UPDATE password_reset_otp
        SET digunakan = TRUE
        WHERE user_id = %s AND digunakan = FALSE
    """, (user_id,))
    # Simpan OTP baru
    kadaluarsa = datetime.now() + timedelta(minutes=expire_menit)
    try:
        ip = request.remote_addr
    except RuntimeError:
        ip = 'system'
    cur.execute("""
        INSERT INTO password_reset_otp
          (user_id, otp_code, metode, tujuan, kadaluarsa, ip_address)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (user_id, otp_code, metode, tujuan, kadaluarsa, ip))
    conn.commit()
    cur.close()


def _verifikasi_otp(conn, user_id, otp_input):
    """
    Periksa apakah OTP valid.
    Kembalikan dict row jika valid, None jika tidak.
    """
    cur = _q(conn)
    cur.execute("""
        SELECT * FROM password_reset_otp
        WHERE user_id = %s
          AND otp_code = %s
          AND digunakan = FALSE
          AND kadaluarsa > NOW()
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id, otp_input.strip()))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def _tandai_otp_digunakan(conn, otp_id):
    """Tandai OTP sudah terpakai setelah reset berhasil."""
    cur = conn.cursor()
    cur.execute("UPDATE password_reset_otp SET digunakan=TRUE WHERE id=%s", (otp_id,))
    conn.commit()
    cur.close()


# ── Kirim via Email ──────────────────────────────────────────────────────────

def _kirim_email(cfg, tujuan_email, nama_user, otp_code):
    """
    Kirim OTP via SMTP.
    Kembalikan (True, '') jika berhasil, (False, pesan_error) jika gagal.
    """
    if not cfg['smtp_host'] or not cfg['smtp_user']:
        return False, "Konfigurasi SMTP belum diisi. Hubungi administrator."

    subject = f"[{cfg['nama_perusahaan']}] Kode OTP Reset Password"
    expire  = cfg['otp_expire']

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f8fafc;margin:0;padding:20px">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;
              box-shadow:0 2px 12px rgba(0,0,0,.08);overflow:hidden">

    <div style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 32px">
      <h2 style="color:#fff;margin:0;font-size:20px">🔐 Reset Password</h2>
      <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:13px">
        {cfg['nama_perusahaan']}
      </p>
    </div>

    <div style="padding:32px">
      <p style="color:#1e293b;margin:0 0 16px">Halo <strong>{nama_user}</strong>,</p>
      <p style="color:#475569;font-size:14px;margin:0 0 24px">
        Kami menerima permintaan reset password untuk akun Anda.
        Gunakan kode OTP berikut untuk melanjutkan:
      </p>

      <div style="background:#f1f5f9;border:2px dashed #cbd5e1;border-radius:10px;
                  padding:20px;text-align:center;margin:0 0 24px">
        <div style="font-size:38px;font-weight:700;letter-spacing:10px;
                    color:#2563eb;font-family:monospace">
          {otp_code}
        </div>
        <div style="color:#94a3b8;font-size:12px;margin-top:8px">
          ⏱ Berlaku selama <strong>{expire} menit</strong>
        </div>
      </div>

      <div style="background:#fef9c3;border-left:4px solid #eab308;
                  padding:12px 16px;border-radius:0 8px 8px 0;margin:0 0 24px">
        <p style="margin:0;font-size:13px;color:#713f12">
          ⚠️ <strong>Jangan bagikan kode ini</strong> kepada siapapun,
          termasuk tim support kami. Jika Anda tidak meminta reset password,
          abaikan email ini.
        </p>
      </div>

      <p style="color:#94a3b8;font-size:12px;margin:0">
        Dikirim otomatis oleh sistem {cfg['nama_perusahaan']}.
        Mohon tidak membalas email ini.
      </p>
    </div>
  </div>
</body>
</html>
"""
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
                srv.ehlo()
                srv.starttls(context=ctx)
                srv.login(cfg['smtp_user'], cfg['smtp_pass'])
                srv.sendmail(cfg['smtp_user'], tujuan_email, msg.as_string())
        else:
            with smtplib.SMTP_SSL(cfg['smtp_host'], port, timeout=15) as srv:
                srv.login(cfg['smtp_user'], cfg['smtp_pass'])
                srv.sendmail(cfg['smtp_user'], tujuan_email, msg.as_string())
        return True, ''
    except smtplib.SMTPAuthenticationError:
        return False, "Autentikasi SMTP gagal. Periksa email & App Password."
    except smtplib.SMTPConnectError:
        return False, f"Gagal terhubung ke SMTP server {cfg['smtp_host']}:{cfg['smtp_port']}."
    except Exception as e:
        return False, f"Gagal kirim email: {str(e)}"


# ── Kirim via WhatsApp (Fonnte) ──────────────────────────────────────────────

def _kirim_whatsapp(cfg, no_hp, nama_user, otp_code):
    """
    Kirim OTP via WhatsApp menggunakan Fonnte API.
    Fonnte: https://fonnte.com — daftar, scan QR, dapatkan token.
    """
    if not cfg['fonnte_token']:
        return False, "Token Fonnte WhatsApp belum dikonfigurasi. Hubungi administrator."

    # Normalisasi nomor: hilangkan +, 0 di depan → 62xxx
    nomor = re.sub(r'\D', '', no_hp)
    if nomor.startswith('0'):
        nomor = '62' + nomor[1:]
    elif not nomor.startswith('62'):
        nomor = '62' + nomor

    expire = cfg['otp_expire']
    pesan = (
        f"🔐 *Reset Password — {cfg['nama_perusahaan']}*\n\n"
        f"Halo *{nama_user}*,\n\n"
        f"Kode OTP reset password SIAP RSSR Anda:\n\n"
        f"*{otp_code}*\n\n"
        f"⏱ Berlaku {expire} menit.\n\n"
        f"⚠️ Jangan bagikan kode ini kepada siapapun.\n"
        f"Jika tidak merasa meminta reset, abaikan pesan ini."
    )

    try:
        import urllib.request
        payload = json.dumps({
            'target' : nomor,
            'message': pesan,
            'countryCode': '62',
        }).encode('utf-8')

        req = urllib.request.Request(
            cfg['fonnte_url'],
            data=payload,
            headers={
                'Authorization': cfg['fonnte_token'],
                'Content-Type' : 'application/json',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get('status') == True or result.get('status') == 'true':
                return True, ''
            else:
                reason = result.get('reason') or result.get('message') or str(result)
                return False, f"Fonnte error: {reason}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Gagal kirim WhatsApp: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. BLUEPRINT ROUTES
# ─────────────────────────────────────────────────────────────────────────────

lupa_pw_bp = Blueprint('lupa_pw', __name__)


@lupa_pw_bp.route('/lupa-password', methods=['GET', 'POST'])
def lupa_password():
    """
    Langkah 1: User masukkan email atau nomor HP.
    Sistem cari akun → tampilkan pilihan metode pengiriman → kirim OTP.
    """
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return render_template('lupa_password.html', step='input')

    # ── POST: cari akun ─────────────────────────────────────────────
    identitas = request.form.get('identitas', '').strip()
    metode    = request.form.get('metode', 'email')   # 'email' atau 'whatsapp'

    if not identitas:
        flash('Masukkan email atau nomor WhatsApp Anda.', 'error')
        return render_template('lupa_password.html', step='input')

    conn = _get_db(); cur = _q(conn)

    # Cari user berdasarkan email atau nomor HP
    cur.execute("""
        SELECT id, nama, email, no_hp, status
        FROM users
        WHERE email = %s OR no_hp = %s
        LIMIT 1
    """, (identitas, identitas))
    user = cur.fetchone()

    if not user:
        cur.close(); conn.close()
        # Jangan bocorkan info akun tidak ada — tampilkan pesan netral
        flash('Jika akun dengan data tersebut ada, OTP akan dikirimkan segera.', 'info')
        return render_template('lupa_password.html', step='input')

    if user['status'] in ('pending', 'rejected'):
        cur.close(); conn.close()
        flash('Akun belum aktif. Hubungi administrator.', 'warning')
        return render_template('lupa_password.html', step='input')

    user = dict(user)
    cfg  = _get_config(conn)

    # Tentukan tujuan pengiriman
    if metode == 'whatsapp':
        tujuan = user.get('no_hp') or ''
        if not tujuan:
            cur.close(); conn.close()
            flash('Nomor WhatsApp tidak terdaftar pada akun ini. Coba via Email.', 'warning')
            return render_template('lupa_password.html', step='input')
    else:
        metode = 'email'
        tujuan = user.get('email') or ''

    # Generate & simpan OTP
    otp = _generate_otp(cfg['otp_length'])
    _simpan_otp(conn, user['id'], otp, metode, tujuan, cfg['otp_expire'])

    # Kirim OTP
    if metode == 'email':
        ok, err_msg = _kirim_email(cfg, tujuan, user['nama'], otp)
    else:
        ok, err_msg = _kirim_whatsapp(cfg, tujuan, user['nama'], otp)

    cur.close()

    if not ok:
        conn.close()
        flash(f'Gagal mengirim OTP: {err_msg}', 'error')
        return render_template('lupa_password.html', step='input')

    conn.close()

    # Simpan user_id di session sementara (bukan login penuh)
    session['reset_user_id']  = user['id']
    session['reset_metode']   = metode
    session['reset_tujuan']   = _mask(tujuan, metode)
    session['reset_ts']       = datetime.now().isoformat()

    flash(f'OTP telah dikirim ke {_mask(tujuan, metode)}.', 'success')
    return render_template('lupa_password.html',
                           step='otp',
                           metode=metode,
                           tujuan=_mask(tujuan, metode),
                           expire=cfg['otp_expire'])


@lupa_pw_bp.route('/lupa-password/verifikasi', methods=['POST'])
def verifikasi_otp():
    """Langkah 2: Verifikasi kode OTP yang dimasukkan user."""
    user_id = session.get('reset_user_id')
    if not user_id:
        flash('Sesi reset telah berakhir. Mulai ulang.', 'error')
        return redirect(url_for('lupa_pw.lupa_password'))

    otp_input = request.form.get('otp', '').strip()
    if len(otp_input) < 4:
        flash('Kode OTP tidak valid.', 'error')
        return render_template('lupa_password.html',
                               step='otp',
                               metode=session.get('reset_metode'),
                               tujuan=session.get('reset_tujuan'))

    conn = _get_db()
    row  = _verifikasi_otp(conn, user_id, otp_input)
    conn.close()

    if not row:
        flash('Kode OTP salah atau sudah kadaluarsa. Coba kirim ulang.', 'error')
        return render_template('lupa_password.html',
                               step='otp',
                               metode=session.get('reset_metode'),
                               tujuan=session.get('reset_tujuan'))

    # OTP valid — simpan otp_id di session, lanjut ke form password baru
    session['reset_otp_id']   = row['id']
    session['reset_verified'] = True
    return render_template('lupa_password.html', step='reset')


@lupa_pw_bp.route('/lupa-password/reset', methods=['POST'])
def reset_password():
    """Langkah 3: Set password baru."""
    user_id  = session.get('reset_user_id')
    otp_id   = session.get('reset_otp_id')
    verified = session.get('reset_verified')

    if not (user_id and otp_id and verified):
        flash('Sesi reset tidak valid. Mulai ulang.', 'error')
        return redirect(url_for('lupa_pw.lupa_password'))

    pw_baru    = request.form.get('password_baru', '')
    pw_konfirm = request.form.get('password_konfirm', '')

    if len(pw_baru) < 6:
        flash('Password minimal 6 karakter.', 'error')
        return render_template('lupa_password.html', step='reset')

    if pw_baru != pw_konfirm:
        flash('Konfirmasi password tidak cocok.', 'error')
        return render_template('lupa_password.html', step='reset')

    conn = _get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET password=%s WHERE id=%s",
                (generate_password_hash(pw_baru), user_id))
    conn.commit()
    _tandai_otp_digunakan(conn, otp_id)
    cur.close(); conn.close()

    # Bersihkan session reset
    for k in ['reset_user_id','reset_otp_id','reset_verified',
              'reset_metode','reset_tujuan','reset_ts']:
        session.pop(k, None)

    flash('Password berhasil direset! Silakan login dengan password baru Anda.', 'success')
    return redirect(url_for('login'))


@lupa_pw_bp.route('/lupa-password/kirim-ulang', methods=['POST'])
def kirim_ulang_otp():
    """Kirim ulang OTP ke user yang sama."""
    user_id = session.get('reset_user_id')
    metode  = session.get('reset_metode', 'email')
    if not user_id:
        return jsonify(success=False, message='Sesi tidak valid.')

    conn = _get_db(); cur = _q(conn)
    cur.execute("SELECT nama, email, no_hp FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close(); conn.close()
        return jsonify(success=False, message='User tidak ditemukan.')

    user = dict(user)
    cfg  = _get_config(conn)
    tujuan = user.get('no_hp') if metode == 'whatsapp' else user.get('email')

    otp = _generate_otp(cfg['otp_length'])
    _simpan_otp(conn, user_id, otp, metode, tujuan, cfg['otp_expire'])

    if metode == 'email':
        ok, err = _kirim_email(cfg, tujuan, user['nama'], otp)
    else:
        ok, err = _kirim_whatsapp(cfg, tujuan, user['nama'], otp)

    cur.close(); conn.close()

    if ok:
        return jsonify(success=True,
                       message=f'OTP baru telah dikirim ke {_mask(tujuan, metode)}.')
    else:
        return jsonify(success=False, message=f'Gagal kirim ulang: {err}')


# ── Route admin: test koneksi SMTP & WA ─────────────────────────────────────

@lupa_pw_bp.route('/admin/test-notif', methods=['POST'])
def admin_test_notif():
    """Admin bisa test kirim OTP ke dirinya sendiri dari halaman settings."""
    if session.get('role') != 'admin':
        return jsonify(success=False, message='Akses ditolak'), 403

    metode = request.form.get('metode', 'email')
    tujuan = request.form.get('tujuan', '').strip()
    if not tujuan:
        return jsonify(success=False, message='Tujuan tidak boleh kosong')

    conn = _get_db()
    cfg  = _get_config(conn)
    conn.close()

    otp = _generate_otp(cfg['otp_length'])
    nama = session.get('nama', 'Admin')

    if metode == 'email':
        ok, err = _kirim_email(cfg, tujuan, nama, otp)
    else:
        ok, err = _kirim_whatsapp(cfg, tujuan, nama, otp)

    if ok:
        return jsonify(success=True,
                       message=f'Test OTP ({otp}) berhasil dikirim ke {tujuan}')
    else:
        return jsonify(success=False, message=err)


# ── Route admin: simpan konfigurasi SMTP & WA ────────────────────────────────

@lupa_pw_bp.route('/admin/settings/notif', methods=['POST'])
def admin_settings_notif():
    """Simpan konfigurasi SMTP & WhatsApp dari form admin settings."""
    if session.get('role') != 'admin':
        flash('Akses ditolak.', 'error')
        return redirect(url_for('login'))

    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE settings SET
                smtp_host      = %s,
                smtp_port      = %s,
                smtp_user      = %s,
                smtp_pass      = %s,
                smtp_from_name = %s,
                smtp_tls       = %s,
                fonnte_token   = %s
            WHERE id = 1
        """, (
            request.form.get('smtp_host','').strip(),
            int(request.form.get('smtp_port', 587) or 587),
            request.form.get('smtp_user','').strip(),
            request.form.get('smtp_pass','').strip(),
            request.form.get('smtp_from_name','Presensi Digital').strip(),
            request.form.get('smtp_tls','true') == 'true',
            request.form.get('fonnte_token','').strip(),
        ))
        conn.commit()
        flash('Konfigurasi notifikasi berhasil disimpan!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Gagal menyimpan: {e}', 'error')
    finally:
        cur.close(); conn.close()

    return redirect(url_for('admin_settings'))


# ─────────────────────────────────────────────────────────────────────────────
# 4. HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _mask(value, metode):
    """Sembunyikan sebagian email atau nomor HP untuk privasi."""
    if not value:
        return '***'
    if metode == 'email':
        parts = value.split('@')
        if len(parts) == 2:
            name, domain = parts
            masked_name = name[:2] + '*' * max(1, len(name)-2)
            return f"{masked_name}@{domain}"
        return value[:3] + '***'
    else:
        # WhatsApp / nomor HP
        digits = re.sub(r'\D', '', value)
        if len(digits) >= 8:
            return digits[:4] + '****' + digits[-3:]
        return '****'
