import flet as ft
import traceback

def main(page: ft.Page):
    page.title = "Проскурівська Індичка: ERP"
    page.theme_mode = "light"
    page.padding = 0

    try:
        import os
        import time
        import datetime
        import sqlite3
        import json
        import urllib.request
        import base64

        # Беремо ваш крутий безпечний метод шляхів
        SAFE_DIR = os.environ.get("FLET_APP_STORAGE", os.path.dirname(os.path.abspath(__file__)))
        KEY_FILE = os.path.join(SAFE_DIR, "api_key_turkey.txt")
        REPORTS_DIR = os.path.join(SAFE_DIR, "Рапорти_Індичка")
        DB_FILE = os.path.join(SAFE_DIR, "turkey_erp.db")

        os.makedirs(REPORTS_DIR, exist_ok=True)

        def init_db():
            conn = sqlite3.connect(DB_FILE)
            conn.execute('''CREATE TABLE IF NOT EXISTS batches (name TEXT PRIMARY KEY, status TEXT, initial_count INTEGER DEFAULT 0, start_date TEXT, initial_age INTEGER DEFAULT 1)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS daily_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_name TEXT, date TEXT, water REAL, feed REAL, dead INTEGER, cull INTEGER, notes TEXT DEFAULT '')''')
            conn.execute('''CREATE TABLE IF NOT EXISTS vet_cases (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_name TEXT, date TEXT, photo_path TEXT, user_msg TEXT, ai_response TEXT)''')
            conn.commit(); conn.close()

        init_db()

        SYSTEM_PROMPT = """Роль: Ти — висококваліфікований ветеринарний лікар птиці та зоотехнік "Проскурівська індичка". Консультуй ВИКЛЮЧНО щодо індиків (усі кроси: BIG6). Світові практики: Завжди порівнюй показники зі стандартами кросу відповідно до віку."""

        def get_saved_key():
            try:
                with open(KEY_FILE, "r") as f: return f.read().strip()
            except: return ""

        def save_key(key):
            with open(KEY_FILE, "w") as f: f.write(key)

        def get_img_base64(path):
            try:
                with open(path, "rb") as f: return base64.b64encode(f.read()).decode("utf-8")
            except: return None

        def call_gemini(prompt_text, img_path=None):
            api_key = get_saved_key()
            if not api_key: return "❌ Введіть API ключ у налаштуваннях!"
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            parts = [{"text": prompt_text}]
            
            if img_path:
                b64 = get_img_base64(img_path)
                if b64: parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
                
            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": parts}]
            }
            
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    return res_data['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                return f"❌ Помилка з'єднання з ШІ: {e}"

        def get_active_batches():
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT name FROM batches WHERE status='ACTIVE'")
            rows = c.fetchall()
            conn.close()
            return [r[0] for r in rows]

        def get_batch_stats(batch_name):
            if not batch_name: return {"rem": 0, "age": 0}
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT initial_count, start_date, initial_age FROM batches WHERE name=?", (batch_name,))
            res = c.fetchone()
            initial = res[0] if res else 0
            start_date_str = res[1] if res and res[1] else None
            initial_age = res[2] if res and res[2] else 1
            
            c.execute("SELECT SUM(dead), SUM(cull) FROM daily_reports WHERE batch_name=?", (batch_name,))
            sums = c.fetchone()
            dead = sums[0] if sums and sums[0] else 0
            cull = sums[1] if sums and sums[1] else 0
            conn.close()
            
            rem_birds = initial - dead - cull
            current_age = initial_age
            if start_date_str:
                try:
                    start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    current_age = initial_age + (datetime.datetime.now().date() - start_date).days
                except: pass
            return {"rem": rem_birds, "age": current_age}

        tf_api_key = ft.TextField(label="Gemini API Key", value=get_saved_key(), password=True, width=300)
        dlg_settings = ft.AlertDialog(title=ft.Text("🔑 Налаштування"), content=tf_api_key, actions=[ft.ElevatedButton("Зберегти", on_click=lambda e: (save_key(tf_api_key.value), setattr(dlg_settings, 'open', False), page.update()))])
        page.overlay.append(dlg_settings)

        splash_view = ft.Container(content=ft.Column([ft.Image(src="logo.png", width=150, height=150), ft.Text("ПРОСКУРІВСЬКА ІНДИЧКА", size=20, weight="bold"), ft.ProgressRing()], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER), expand=True)

        dd_batch = ft.Dropdown(label="Оберіть партію", expand=True)
        dd_archive_batch = ft.Dropdown(label="Оберіть партію", expand=True) 
        new_batch_input = ft.TextField(label="Назва", expand=True)
        new_batch_count = ft.TextField(label="Голів", width=80)
        new_batch_age = ft.TextField(label="Вік", width=80, value="1")
        batches_listview = ft.ListView(height=150, spacing=5)

        def refresh_batches_ui(e=None):
            batches = get_active_batches()
            opts = [ft.dropdown.Option(b) for b in batches]
            dd_batch.options = opts
            dd_archive_batch.options = opts
            if batches:
                if dd_batch.value not in batches: dd_batch.value = batches[0]
                if dd_archive_batch.value not in batches: dd_archive_batch.value = batches[0]
            
            batches_listview.controls.clear()
            for b in batches:
                batches_listview.controls.append(ft.Row([ft.Text(b, expand=True), ft.ElevatedButton("❌", on_click=lambda e, name=b: (sqlite3.connect(DB_FILE).execute("UPDATE batches SET status='CLOSED' WHERE name=?", (name,)).connection.commit(), refresh_batches_ui()))]))
            update_remaining_birds_ui(None)
            page.update()

        def add_batch(e):
            if new_batch_input.value:
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO batches (name, status, initial_count, start_date, initial_age) VALUES (?, 'ACTIVE', ?, ?, ?)", (new_batch_input.value, int(new_batch_count.value or 0), datetime.datetime.now().strftime('%Y-%m-%d'), int(new_batch_age.value or 1)))
                conn.commit(); conn.close()
                new_batch_input.value = ""; refresh_batches_ui()

        dlg_manage_batches = ft.AlertDialog(title=ft.Text("Керування партіями"), content=ft.Column([ft.Row([new_batch_input, new_batch_count, new_batch_age]), ft.ElevatedButton("➕ Додати", on_click=add_batch), batches_listview], height=300), actions=[ft.TextButton("Закрити", on_click=lambda e: (setattr(dlg_manage_batches, 'open', False), page.update()))])
        page.overlay.append(dlg_manage_batches)

        # РАПОРТ
        txt_remaining = ft.Text("Оновлюється...", size=16, weight="bold")
        def update_remaining_birds_ui(e):
            s = get_batch_stats(dd_batch.value)
            txt_remaining.value = f"Залишок: {s['rem']} | Вік: {s['age']} днів"
            page.update()
        dd_batch.on_change = update_remaining_birds_ui

        tf_w = ft.TextField(label="Вода(л)", value="0", expand=True); tf_f = ft.TextField(label="Корм(кг)", value="0", expand=True)
        tf_d = ft.TextField(label="Падіж", value="0", expand=True); tf_c = ft.TextField(label="Брак", value="0", expand=True)
        tf_t = ft.TextField(label="T(°C)", value="28", expand=True); tf_h = ft.TextField(label="Волога(%)", value="60", expand=True); tf_a = ft.TextField(label="Аміак", value="10", expand=True)
        dd_litter = ft.Dropdown(label="Підстилка", options=[ft.dropdown.Option("Суха/пухка"), ft.dropdown.Option("Волога"), ft.dropdown.Option("Кірка")], value="Суха/пухка", expand=True)
        dd_droppings = ft.Dropdown(label="Послід", options=[ft.dropdown.Option("Норма"), ft.dropdown.Option("Рідкий"), ft.dropdown.Option("Жовтий"), ft.dropdown.Option("З кров'ю")], value="Норма", expand=True)
        tf_notes = ft.TextField(label="Коментар", expand=True)

        def save_report(e):
            if dd_batch.value:
                notes_full = f"{tf_notes.value} | Підстилка: {dd_litter.value} | Послід: {dd_droppings.value}"
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO daily_reports (batch_name, date, water, feed, dead, cull, notes) VALUES (?, ?, ?, ?, ?, ?, ?)", (dd_batch.value, datetime.datetime.now().strftime('%Y-%m-%d'), float(tf_w.value), float(tf_f.value), int(tf_d.value), int(tf_c.value), notes_full))
                conn.commit(); conn.close()
                page.snack_bar = ft.SnackBar(ft.Text("✅ Збережено", color="white"), bgcolor="green"); page.snack_bar.open = True; update_remaining_birds_ui(None)
                tf_d.value="0"; tf_c.value="0"; page.update()

        def analyze_report(e):
            page.snack_bar = ft.SnackBar(ft.Text("⏳ ШІ формує рапорт...", color="white"), bgcolor="blue"); page.snack_bar.open = True; page.update()
            s = get_batch_stats(dd_batch.value)
            prompt = f"Партія: {dd_batch.value}. Залишок: {s['rem']}. Вік: {s['age']}.\nВода: {tf_w.value}л, Корм: {tf_f.value}кг.\nT={tf_t.value}°C, Вологість={tf_h.value}%, Аміак={tf_a.value}.\nПадіж: {tf_d.value}. Підстилка: {dd_litter.value}. Послід: {dd_droppings.value}. Нотатки: {tf_notes.value}\nПроаналізуй."
            ans = call_gemini(prompt)
            filepath = os.path.join(REPORTS_DIR, f"Рапорт_{dd_batch.value}_{int(time.time())}.html")
            with open(filepath, "w", encoding="utf-8") as f: f.write(f"<html><head><meta charset='utf-8'></head><body><h2>Рапорт {dd_batch.value}</h2><p>Вік: {s['age']}</p>{ans}</body></html>")
            page.snack_bar = ft.SnackBar(ft.Text(f"✅ Збережено в {filepath}", color="white"), bgcolor="green"); page.snack_bar.open = True; page.update()

        report_screen = ft.Container(
            content=ft.ListView([
                ft.Row([ft.Text("Поточна партія:", weight="bold"), ft.ElevatedButton("⚙️ Керування", on_click=lambda e: (setattr(dlg_manage_batches, 'open', True), page.update()))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                dd_batch, txt_remaining, 
                ft.Row([tf_w, tf_f]), ft.Row([tf_d, tf_c]), ft.Row([tf_t, tf_h, tf_a]), 
                ft.Row([dd_litter, dd_droppings]), tf_notes,
                ft.Row([ft.ElevatedButton("💾 ЗБЕРЕГТИ", on_click=save_report, expand=True), ft.ElevatedButton("🤖 АНАЛІЗ", on_click=analyze_report, expand=True)])
            ], padding=10, expand=True), expand=True, visible=True
        )

        # ЧАТ З ФОТОАПАРАТОМ (Тепер точно запрацює!)
        chat_list = ft.ListView(expand=True, spacing=10, auto_scroll=True)
        chat_input = ft.TextField(hint_text="Питання...", expand=True)
        img_path = [None]

        fp_chat = ft.FilePicker()
        def on_file_picked(e):
            if e.files and len(e.files) > 0:
                img_path[0] = e.files[0].path
                page.snack_bar = ft.SnackBar(ft.Text("✅ Фото прикріплено! Напишіть питання.", color="white"), bgcolor="green")
                page.snack_bar.open = True; page.update()
        fp_chat.on_result = on_file_picked
        page.overlay.append(fp_chat)
        
        def send_chat(e):
            msg = chat_input.value
            if not msg and not img_path[0]: return
            display_msg = f"👨‍⚕️: 📷 [Фото] {msg}" if img_path[0] else f"👨‍⚕️: {msg}"
            chat_list.controls.append(ft.Row([ft.Container(content=ft.Text(display_msg, color="white"), bgcolor="blue", padding=10, border_radius=10)], alignment=ft.MainAxisAlignment.END))
            chat_input.value = ""; page.update()
            
            s = get_batch_stats(dd_batch.value) if dd_batch.value else None
            prompt = f"Контекст: {dd_batch.value}. Залишок: {s['rem'] if s else '?'}. Вік: {s['age'] if s else '?'}.\nПитання: {msg}"
            
            ans = call_gemini(prompt, img_path[0])
            img_path[0] = None 
            chat_list.controls.append(ft.Row([ft.Container(content=ft.Markdown(ans), bgcolor="#EEEEEE", padding=10, border_radius=10)], alignment=ft.MainAxisAlignment.START))
            page.update()

        chat_screen = ft.Container(
            content=ft.Column([
                ft.Text("🤖 AI Експерт", size=18, weight="bold"),
                ft.Container(content=chat_list, expand=True),
                ft.Row([ft.ElevatedButton("📷", on_click=lambda _: fp_chat.pick_files()), chat_input, ft.ElevatedButton("📤", on_click=send_chat)])
            ], expand=True), padding=10, expand=True, visible=False
        )

        # АРХІВ
        def generate_final_report(e):
            b_name = dd_archive_batch.value
            if not b_name: return
            page.snack_bar = ft.SnackBar(ft.Text("⏳ ШІ формує бізнес-звіт...", color="white"), bgcolor="blue"); page.snack_bar.open = True; page.update()

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT initial_count FROM batches WHERE name=?", (b_name,))
            res = c.fetchone()
            initial = res[0] if res else 0

            c.execute("SELECT SUM(water), SUM(feed), SUM(dead), SUM(cull) FROM daily_reports WHERE batch_name=?", (b_name,))
            sums = c.fetchone()
            t_w = sums[0] or 0; t_f = sums[1] or 0; t_d = sums[2] or 0; t_c = sums[3] or 0
            rem_birds = initial - t_d - t_c
            conn.close()

            prompt = f"Фінальний звіт: {b_name}. Початково: {initial}. Випито води: {t_w}л, З'їдено корму: {t_f}кг. Відхід: {t_d + t_c}. Збереженість: {rem_birds}. Напиши аналітичний висновок та рекомендації для керівника птахофабрики."
            ai_ceo_report = call_gemini(prompt)

            filepath = os.path.join(REPORTS_DIR, f"ФІНАЛ_{b_name}_{int(time.time())}.html")
            html = f"<html><head><meta charset='utf-8'></head><body><h1>БІЗНЕС-ЗВІТ: {b_name}</h1><h3>Збережено: {rem_birds} голів</h3><div>{ai_ceo_report}</div></body></html>"
            with open(filepath, "w", encoding="utf-8") as f: f.write(html)
            page.snack_bar = ft.SnackBar(ft.Text(f"✅ ЗГЕНЕРОВАНО В АРХІВ!", color="white"), bgcolor="green"); page.snack_bar.open = True; page.update()

        archive_screen = ft.Container(
            content=ft.Column([
                ft.Text("📁 ГЕНЕРАТОР ФІНАЛЬНОГО ЗВІТУ", size=18, weight="bold"),
                ft.Container(height=20), dd_archive_batch, ft.Container(height=20),
                ft.ElevatedButton("🏆 ЗГЕНЕРУВАТИ ЗВІТ", on_click=generate_final_report, expand=True, height=60)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER), padding=30, expand=True, visible=False
        )

        def switch_tab(tab_index):
            report_screen.visible = (tab_index == 0)
            chat_screen.visible = (tab_index == 1)
            archive_screen.visible = (tab_index == 2)
            page.update()

        btn_tab_report = ft.ElevatedButton("📊", expand=True, on_click=lambda e: switch_tab(0))
        btn_tab_chat = ft.ElevatedButton("💬", expand=True, on_click=lambda e: switch_tab(1))
        btn_tab_archive = ft.ElevatedButton("📁", expand=True, on_click=lambda e: switch_tab(2))

        custom_tabs_bar = ft.Container(content=ft.Row([btn_tab_report, btn_tab_chat, btn_tab_archive]), bgcolor="#EEEEEE", padding=5)

        top_app_bar = ft.Container(content=ft.Row([ft.Row([ft.Image(src="logo.png", width=30, height=30), ft.Text(" ERP Індичка", weight="bold")]), ft.ElevatedButton("🔑 API", on_click=lambda e: (setattr(dlg_settings, 'open', True), page.update()))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=10)
        
        main_view = ft.Column([
            top_app_bar, custom_tabs_bar, report_screen, chat_screen, archive_screen
        ], expand=True, visible=False)

        page.add(splash_view, main_view)
        refresh_batches_ui()
        page.update(); time.sleep(1.5); splash_view.visible = False; main_view.visible = True; page.update()

    except Exception as e:
        error_text = f"🚨 КРИТИЧНА ПОМИЛКА СТАРТУ:\n{traceback.format_exc()}"
        page.add(ft.SafeArea(ft.Text(error_text, color="red", selectable=True)))
        page.update()

ft.app(target=main, assets_dir="assets")
