@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def editar_galeria(galeria_id):
    nuevo_titulo = request.form.get('titulo')
    nueva_desc = request.form.get('descripcion')
    nuevos_archivos = request.files.getlist('nuevos_archivos')
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        # 1. Actualizar título y descripción
        q_sel = "SELECT titulo, descripcion FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo, descripcion FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        anterior = cursor.fetchone()
        
        if anterior:
            titulo_ant, desc_ant = anterior[0], anterior[1]
            q_upd = "UPDATE galerias SET titulo = %s, descripcion = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, descripcion = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_titulo, nueva_desc, galeria_id))
            
            # 2. Guardar y adjuntar nuevas imágenes si se subieron
            archivos_guardados = []
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            for file in nuevos_archivos:
                if file and archivo_permitido(file.filename):
                    nombre_seguro = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                    file.save(filepath)
                    
                    q_ins_arch = "INSERT INTO archivos (galeria_id, filename) VALUES (%s, %s)" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename) VALUES (?, ?)"
                    cursor.execute(q_ins_arch, (galeria_id, nombre_seguro))
                    archivos_guardados.append(nombre_seguro)

            conn.commit()
            
            # Registrar en la bitácora
            cambios = []
            if titulo_ant != nuevo_titulo:
                cambios.append(f"Título: '{titulo_ant}' ➔ '{nuevo_titulo}'")
            if desc_ant != nueva_desc:
                cambios.append(f"Descripción: '{desc_ant}' ➔ '{nueva_desc}'")
            if archivos_guardados:
                cambios.append(f"Se agregaron {len(archivos_guardados)} archivo(s) nuevo(s)")
                
            detalle_log = " | ".join(cambios) if cambios else "Sin cambios detectados"
            registrar_log(session['username'], "Edición de Galería", f"Galería ID {galeria_id}: {detalle_log}")

    except Exception as e:
        conn.rollback()
        print(f"Error al editar galería: {e}")

    conn.close()
    return redirect(url_for('index'))
