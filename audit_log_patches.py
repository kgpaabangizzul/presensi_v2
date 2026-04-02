# audit_log_patches.py
# ═══════════════════════════════════════════════════════════════════
# PATCH APP.PY — Potongan kode yang ditambahkan ke setiap route
# ═══════════════════════════════════════════════════════════════════
#
# File ini adalah panduan lengkap. Salin setiap blok ke lokasi
# yang ditunjuk di app.py Anda.
# ═══════════════════════════════════════════════════════════════════

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [A] TAMBAHKAN DI ATAS app.py — setelah import yang ada
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IMPORTS_TAMBAHAN = """
from audit_log import init_audit_table, log_audit, log_error, audit_bp
"""

REGISTER_BLUEPRINT = """
# Setelah: app = Flask(__name__)
app.register_blueprint(audit_bp)
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [B] DI init_db() — sebelum conn.commit() paling akhir
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INIT_DB_TAMBAHAN = """
    # ── AUDIT LOG TABLE ────────────────────────────────────────────
    init_audit_table(cur)
    # ──────────────────────────────────────────────────────────────
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [C] PATCH ROUTE — Login berhasil & gagal (~baris 680)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOGIN_PATCH = """
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
                session.update({'user_id':user['id'],'nama':user['nama'],
                                'role':user['role'],'foto':user['foto']})
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
                      status='error',
                      user_id=None, user_nama=email_input, user_role='-')
            flash('Email atau password salah.', 'error')

        conn.close()
    return render_template('login.html')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [D] PATCH ROUTE — Logout (~baris 737)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOGOUT_PATCH = """
@app.route('/logout')
def logout():
    if 'user_id' in session:
        conn = get_db()
        log_audit(conn, 'LOGOUT', 'auth',
                  deskripsi=f'Logout: {session.get("nama")}')
        conn.close()
    session.clear()
    return redirect(url_for('login'))
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [E] PATCH ROUTE — Absen masuk/keluar (~baris 803)
#     Tambahkan log_audit setelah conn.commit() di setiap cabang
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ABSEN_PATCH_MASUK = """
            # Setelah: conn.commit() pada tipe=='masuk'
            log_audit(conn, 'ABSEN_MASUK', 'absensi',
                      deskripsi=f'Absen masuk — {session.get("nama")} '
                                f'| Jarak: {jarak:.0f}m | Status: {status}',
                      data_baru={'tanggal': today, 'jam': now, 'jarak': jarak,
                                 'shift_id': shift_id, 'status': status},
                      ref_id=uid, ref_table='users')
"""

ABSEN_PATCH_KELUAR = """
            # Setelah: conn.commit() pada tipe=='keluar'
            log_audit(conn, 'ABSEN_KELUAR', 'absensi',
                      deskripsi=f'Absen keluar — {session.get("nama")} '
                                f'| Jarak: {jarak:.0f}m',
                      data_baru={'tanggal': today, 'jam': now, 'jarak': jarak},
                      ref_id=uid, ref_table='users')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [F] PATCH ROUTE — Izin submit (~baris 942)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IZIN_SUBMIT_PATCH = """
            # Setelah: conn.commit() di route /izin POST
            log_audit(conn, 'IZIN', 'izin',
                      deskripsi=f'Pengajuan izin: {request.form.get("jenis")} '
                                f'({request.form.get("tanggal_mulai")} s/d '
                                f'{request.form.get("tanggal_selesai")})',
                      data_baru={'jenis': request.form.get('jenis'),
                                 'mulai': request.form.get('tanggal_mulai'),
                                 'selesai': request.form.get('tanggal_selesai')},
                      ref_id=uid, ref_table='users')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [G] PATCH ROUTE — Admin validasi user (~baris 1353)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VALIDASI_PATCH = """
@app.route('/admin/validasi/<int:uid>/<action>')
@admin_required
def validasi_user(uid, action):
    conn = get_db(); cur = q(conn)
    # Ambil data user sebelum diubah
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    target_user = cur.fetchone()
    status_lama = target_user['status'] if target_user else '-'
    status_baru = 'active' if action=='approve' else 'rejected'

    cur.execute("UPDATE users SET status=%s WHERE id=%s", (status_baru, uid))
    conn.commit()

    log_audit(conn, 'VALIDASI', 'pegawai',
              deskripsi=f'Validasi akun {target_user["nama"] if target_user else uid}: '
                        f'{status_lama} → {status_baru}',
              data_lama={'status': status_lama},
              data_baru={'status': status_baru},
              ref_id=uid, ref_table='users')

    cur.close(); conn.close()
    flash('Akun disetujui!' if action=='approve' else 'Akun ditolak!',
          'success' if action=='approve' else 'info')
    return redirect(url_for('admin_pegawai'))
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [H] PATCH ROUTE — Admin proses izin (~baris 1394)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROSES_IZIN_PATCH = """
    # Setelah conn.commit() di route /admin/izin/<iid>/<action>
    log_audit(conn,
              'APPROVE' if action=='approve' else 'REJECT',
              'izin',
              deskripsi=f'{"Setujui" if action=="approve" else "Tolak"} izin ID {iid} '
                        f'— {iz["jenis"]} milik user_id {iz["user_id"]}',
              data_lama={'status': 'pending'},
              data_baru={'status': 'approved' if action=="approve" else 'rejected'},
              ref_id=iid, ref_table='izin')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [I] PATCH ROUTE — Admin tambah/edit/hapus pegawai
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TAMBAH_PEGAWAI_PATCH = """
    # Setelah conn.commit() di route /admin/pegawai/tambah
    log_audit(conn, 'CREATE', 'pegawai',
              deskripsi=f'Tambah pegawai baru: {request.form.get("nama")} '
                        f'(NIK: {request.form.get("nik")})',
              data_baru={'nama': request.form.get('nama'), 'nik': request.form.get('nik'),
                         'email': request.form.get('email'), 'jabatan': request.form.get('jabatan')},
              ref_table='users')
"""

EDIT_PEGAWAI_PATCH = """
    # Setelah conn.commit() di route /admin/pegawai/edit/<uid>
    log_audit(conn, 'UPDATE', 'pegawai',
              deskripsi=f'Edit data pegawai ID {uid}: {user_lama.get("nama")}',
              data_lama={'nama': user_lama.get('nama'), 'jabatan': user_lama.get('jabatan'),
                         'departemen_id': user_lama.get('departemen_id'),
                         'shift_id': user_lama.get('shift_id'), 'role': user_lama.get('role')},
              data_baru={'nama': request.form.get('nama'), 'jabatan': request.form.get('jabatan'),
                         'departemen_id': request.form.get('departemen_id'),
                         'shift_id': request.form.get('shift_id'), 'role': request.form.get('role')},
              ref_id=uid, ref_table='users')
"""

HAPUS_PEGAWAI_PATCH = """
    # Sebelum DELETE user, ambil dulu datanya, lalu setelah commit:
    log_audit(conn, 'DELETE', 'pegawai',
              deskripsi=f'Hapus pegawai: {user_lama["nama"]} (NIK: {user_lama["nik"]})',
              data_lama={'nama': user_lama['nama'], 'nik': user_lama['nik'],
                         'email': user_lama['email']},
              ref_id=uid, ref_table='users')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [J] PATCH ROUTE — Settings (~baris 1568)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SETTINGS_PATCH = """
    # Setelah conn.commit() di route /admin/settings POST
    log_audit(conn, 'SETTING', 'settings',
              deskripsi='Update pengaturan sistem',
              data_baru={
                  'nama_perusahaan': request.form.get('nama_perusahaan'),
                  'jam_masuk': request.form.get('jam_masuk'),
                  'jam_keluar': request.form.get('jam_keluar'),
                  'max_distance': request.form.get('max_distance'),
                  'office_lat': request.form.get('office_lat'),
                  'office_lng': request.form.get('office_lng'),
              })
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [K] PATCH ROUTE — Tambah/Edit/Hapus Departemen
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEPT_PATCH = """
    # Tambah departemen — setelah commit
    log_audit(conn, 'CREATE', 'departemen',
              deskripsi=f'Tambah departemen: {request.form.get("nama")}',
              data_baru={'nama': request.form.get('nama'), 'kode': request.form.get('kode')},
              ref_table='departemen')

    # Edit departemen — setelah commit
    log_audit(conn, 'UPDATE', 'departemen',
              deskripsi=f'Edit departemen ID {did}',
              data_baru={'nama': request.form.get('nama'), 'kode': request.form.get('kode'),
                         'warna': request.form.get('warna')},
              ref_id=did, ref_table='departemen')

    # Hapus departemen — setelah commit
    log_audit(conn, 'DELETE', 'departemen',
              deskripsi=f'Hapus departemen ID {did}',
              ref_id=did, ref_table='departemen')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [L] PATCH ROUTE — Export laporan
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXPORT_PATCH = """
    # Di awal fungsi admin_export_excel / admin_export_pdf
    conn2 = get_db()
    log_audit(conn2, 'EXPORT', 'laporan',
              deskripsi=f'Export laporan {format_} — bulan {bulan}')
    conn2.close()
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [M] PATCH ROUTE — Ubah password
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASSWORD_PATCH = """
    # Setelah commit di /ubah-password
    log_audit(conn, 'PASSWORD', 'profil',
              deskripsi=f'Ubah password: {session.get("nama")}',
              ref_id=uid, ref_table='users')
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [N] TAMBAHKAN link di nav admin — templates/admin/base.html
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NAV_LINK_HTML = """
<!-- Tambahkan di sidebar/navbar admin -->
<a href="{{ url_for('audit.index') }}" class="nav-link">
    <i class="fas fa-clipboard-list"></i> Audit Log
</a>
"""
