@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def gestion_usuarios():
    conn, db_type = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        nuevo_user = request.form.get('username')
        nuevo_pass = request.form.get('password')
        nuevo_email = request.form.get('email')
        nuevo_rol = request.form.get('rol', 'estandar')

        try:
            q_ins = "INSERT INTO usuarios (username, password, email, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)"
            cursor.execute(q_ins, (nuevo_user, nuevo_pass, nuevo_email, nuevo_rol))
            conn.commit()
            registrar_log(session['username'], "Creación de Usuario", f"Nuevo usuario: '{nuevo_user}' (Rol: {nuevo_rol}, Email: {nuevo_email})")
            return redirect(url_for('gestion_usuarios'))
        except Exception as e:
            conn.rollback()  # 🔄 OBLIGATORIO PARA POSTGRESQL TRAS UN ERROR
            print(f"Error al crear usuario: {e}")

    busqueda = request.args.get('q', '').strip().lower()
    try:
        if busqueda:
            q_search = "SELECT id, username, email, rol FROM usuarios WHERE LOWER(username) LIKE %s OR LOWER(email) LIKE %s" if db_type == 'postgres' else "SELECT id, username, email, rol FROM usuarios WHERE LOWER(username) LIKE ? OR LOWER(email) LIKE ?"
            cursor.execute(q_search, (f"%{busqueda}%", f"%{busqueda}%"))
        else:
            cursor.execute("SELECT id, username, email, rol FROM usuarios ORDER BY id ASC")

        lista_usuarios = cursor.fetchall()
    except Exception as e:
        conn.rollback()
        lista_usuarios = []

    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, busqueda=busqueda)


@app.route('/editar_usuario/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def editar_usuario(user_id):
    nuevo_user = request.form.get('username')
    nuevo_email = request.form.get('email')
    nueva_pass = request.form.get('password')
    nuevo_rol = request.form.get('rol')

    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        q_sel = "SELECT username, email, rol FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT username, email, rol FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (user_id,))
        anterior = cursor.fetchone()

        if anterior:
            user_ant, email_ant, rol_ant = anterior[0], anterior[1], anterior[2]
            
            if nueva_pass and nueva_pass.strip():
                q_upd = "UPDATE usuarios SET username = %s, email = %s, password = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET username = ?, email = ?, password = ?, rol = ? WHERE id = ?"
                cursor.execute(q_upd, (nuevo_user, nuevo_email, nueva_pass, nuevo_rol, user_id))
            else:
                q_upd = "UPDATE usuarios SET username = %s, email = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET username = ?, email = ?, rol = ? WHERE id = ?"
                cursor.execute(q_upd, (nuevo_user, nuevo_email, nuevo_rol, user_id))

            conn.commit()

            cambios = []
            if user_ant != nuevo_user:
                cambios.append(f"Usuario: '{user_ant}' ➔ '{nuevo_user}'")
            if email_ant != nuevo_email:
                cambios.append(f"Email: '{email_ant}' ➔ '{nuevo_email}'")
            if rol_ant != nuevo_rol:
                cambios.append(f"Rol: '{rol_ant}' ➔ '{nuevo_rol}'")
            if nueva_pass and nueva_pass.strip():
                cambios.append("Contraseña actualizada")

            detalle_log = " | ".join(cambios) if cambios else "Sin cambios de datos"
            registrar_log(session['username'], "Modificación de Usuario", f"Usuario ID {user_id}: {detalle_log}")

    except Exception as e:
        conn.rollback()  # 🔄 OBLIGATORIO PARA EVITAR EL 500
        print(f"Error al editar usuario: {e}")

    conn.close()
    return redirect(url_for('gestion_usuarios'))
