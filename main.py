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

        SAFE_DIR = os.path.dirname(os.path.abspath(__file__))
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

        def call_gemini(prompt_text):
            api_key = get_saved_key()
            if not api_key: return "❌ Введіть API ключ у налаштуваннях!"
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": prompt_text}]}]
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

        # --- ІНТЕРФЕЙС ---
        tf_api_key = ft.TextField(label="Gemini API Key", value=get_saved_key(), password=True, width=300)
        dlg_settings = ft.AlertDialog(title=ft.Text("🔑 Налаштування"), content=tf_api_key, actions=[ft.ElevatedButton("Зберегти", on_click=lambda e: (save_key(tf_api_key.value), setattr(dlg_settings, 'open', False), page.update()))])
        page.overlay.append(dlg_settings)

        splash_view = ft.Container(
            content=ft.Column([
                ft.Image(src="logo.png", width=150, height=150), 
                ft.Text("ПРОСКУРІВСЬКА ІНДИЧКА", size=20, weight="bold"),
                ft.ProgressRing()
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            expand=True
        )

        dd_batch = ft.Dropdown(label="Оберіть партію", expand=True)
        dd_archive_batch = ft.Dropdown(label="Партія для Звіту", expand=True)
        new_batch_input = ft.TextField(label="Назва", expand=True)
        new_batch_count = ft.TextField(label="Голів", width=80)
        new_batch_age = ft.TextField(label="Вік", width=80, value="1")
        batches_listview = ft.ListView(height=150, spacing=5)

        def refresh_batches_ui(e=None):
            batches = get_active_batches()
            dd_batch.options = [ft.dropdown.Option(b) for b in batches]
            dd_archive_batch.options = [ft.dropdown.Option(b) for b in batches]
            if batches and dd_batch.value not in batches: dd_batch.value = batches[0]
            
            batches_listview.controls.clear()
            for b in batches:
                batches_listview.controls.append(ft.Row([ft.Text(b, expand=True), ft.IconButton("delete", icon_color="red", on_click=lambda e, name=b: (sqlite3.connect(DB_FILE).execute("UPDATE batches SET status='CLOSED' WHERE name=?", (name,)).connection.commit(), refresh_batches_ui()))]))
            update_remaining_birds_ui(None)
            page.update()

        def add_batch(e):
            if new_batch_input.value:
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO batches (name, status, initial_count, start_date, initial_age) VALUES (?, 'ACTIVE', ?, ?, ?)", (new_batch_input.value, int(new_batch_count.value or 0), datetime.datetime.now().strftime('%Y-%m-%d'), int(new_batch_age.value or 1)))
                conn.commit(); conn.close()
                new_batch_input.value = ""; refresh_batches_ui()

        dlg_manage_batches = ft.AlertDialog(
            title=ft.Text("Керування партіями"),
            content=ft.Column([ft.Row([new_batch_input, new_batch_count, new_batch_age]), ft.ElevatedButton("Додати", icon="add_circle", icon_color="green", on_click=add_batch), batches_listview], height=300),
            actions=[ft.TextButton("Закрити", on_click=lambda e: (setattr(dlg_manage_batches, 'open', False), page.update()))]
        )
        page.overlay.append(dlg_manage_batches)

        # РАПОРТ
        txt_remaining = ft.Text("Оновлюється...", size=16, weight="bold", color="blue")
        def update_remaining_birds_ui(e):
            s = get_batch_stats(dd_batch.value)
            txt_remaining.value = f"Залишок: {s['rem']} | Вік: {s['age']} днів"
            page.update()
        dd_batch.on_change = update_remaining_birds_ui

        tf_w = ft.TextField(label="Вода(л)", value="0", expand=True); tf_f = ft.TextField(label="Корм(кг)", value="0", expand=True)
        tf_d = ft.TextField(label="Падіж", value="0", expand=True); tf_c = ft.TextField(label="Брак", value="0", expand=True)
        tf_t = ft.TextField(label="T(°C)", value="28", expand=True); tf_h = ft.TextField(label="Волога(%)", value="60", expand=True); tf_a = ft.TextField(label="Аміак", value="10", expand=True)
        tf_notes = ft.TextField(label="Коментар", expand=True)

        def save_report(e):
            if dd_batch.value:
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO daily_reports (batch_name, date, water, feed, dead, cull, notes) VALUES (?, ?, ?, ?, ?, ?, ?)", (dd_batch.value, datetime.datetime.now().strftime('%Y-%m-%d'), float(tf_w.value), float(tf_f.value), int(tf_d.value), int(tf_c.value), tf_notes.value))
                conn.commit(); conn.close()
                page.snack_bar = ft.SnackBar(ft.Text("✅ Збережено"), bgcolor="green"); page.snack_bar.open = True; update_remaining_birds_ui(None)
                tf_d.value="0"; tf_c.value="0"; page.update()

        def analyze_report(e):
            page.snack_bar = ft.SnackBar(ft.Text("⏳ ШІ формує рапорт...")); page.snack_bar.open = True; page.update()
            s = get_batch_stats(dd_batch.value)
            prompt = f"Партія: {dd_batch.value}. Залишок: {s['rem']}. Вік: {s['age']}.\nВода: {tf_w.value}л, Корм: {tf_f.value}кг.\nT={tf_t.value}°C, Вологість={tf_h.value}%, Аміак={tf_a.value}.\nПадіж: {tf_d.value}. Нотатки: {tf_notes.value}\nПроаналізуй споживання води/корму для віку {s['age']} днів."
            ans = call_gemini(prompt)
            filepath = os.path.join(REPORTS_DIR, f"Рапорт_{dd_batch.value}_{int(time.time())}.html")
            with open(filepath, "w", encoding="utf-8") as f: f.write(f"<html><head><meta charset='utf-8'></head><body><h2>Рапорт {dd_batch.value}</h2><p>Вік: {s['age']}</p>{ans}</body></html>")
            page.snack_bar = ft.SnackBar(ft.Text(f"✅ Збережено в {filepath}"), bgcolor="green"); page.snack_bar.open = True; page.update()

        report_tab = ft.ListView([
            ft.Row([dd_batch, ft.IconButton("settings", icon_color="blue", on_click=lambda e: (setattr(dlg_manage_batches, 'open', True), page.update()))]),
            txt_remaining, ft.Row([tf_w, tf_f]), ft.Row([tf_d, tf_c]), ft.Row([tf_t, tf_h, tf_a]), tf_notes,
            ft.Row([ft.ElevatedButton("💾", on_click=save_report, expand=True), ft.ElevatedButton("🤖 АНАЛІЗ", on_click=analyze_report, expand=True)])
        ], padding=10, expand=True)

        # ЧАТ (БЕЗ ФОТО)
        chat_list = ft.ListView(expand=True, spacing=10, auto_scroll=True)
        chat_input = ft.TextField(hint_text="Питання...", expand=True)
        
        def send_chat(e):
            msg = chat_input.value
            if not msg: return
            chat_list.controls.append(ft.Row([ft.Container(content=ft.Text(f"👨‍⚕️: {msg}", color="white"), bgcolor="blue", padding=10, border_radius=10)], alignment=ft.MainAxisAlignment.END))
            chat_input.value = ""; page.update()
            
            s = get_batch_stats(dd_batch.value) if dd_batch.value else None
            prompt = f"Контекст: {dd_batch.value}. Залишок: {s['rem'] if s else '?'}. Вік: {s['age'] if s else '?'}.\nПитання: {msg}"
            
            ans = call_gemini(prompt)
            
            chat_list.controls.append(ft.Row([ft.Container(content=ft.Markdown(ans), bgcolor="#EEEEEE", padding=10, border_radius=10)], alignment=ft.MainAxisAlignment.START))
            page.update()

        chat_tab = ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon("smart_toy", color="orange"), ft.Text("🤖 AI Експерт", size=18, weight="bold")]),
                ft.Container(content=chat_list, expand=True),
                ft.Row([chat_input, ft.IconButton("send", icon_color="green", on_click=send_chat)])
            ], expand=True),
            padding=10, 
            expand=True
        )

        # ШАПКА ТА ГОЛОВНИЙ ЕКРАН
        top_app_bar = ft.Container(content=ft.Row([ft.Row([ft.Image(src="logo.png", width=30, height=30), ft.Text(" ERP Індичка", weight="bold")]), ft.IconButton("vpn_key", icon_color="orange", on_click=lambda e: (setattr(dlg_settings, 'open', True), page.update()))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=10)
        
        # ОНОВЛЕНО: Бронебійні вкладки без параметра text
        main_view = ft.Column([
            top_app_bar, 
            ft.Tabs(
                selected_index=0, 
                tabs=[
                    ft.Tab(tab_content=ft.Text("РАПОРТ"), content=report_tab), 
                    ft.Tab(tab_content=ft.Text("ЧАТ"), content=chat_tab)
                ], 
                expand=True
            )
        ], expand=True, visible=False)

        page.add(splash_view, main_view)
        refresh_batches_ui()
        page.update(); time.sleep(1.5); splash_view.visible = False; main_view.visible = True; page.update()

    except Exception as e:
        error_text = f"🚨 КРИТИЧНА ПОМИЛКА СТАРТУ:\n{traceback.format_exc()}"
        page.add(ft.SafeArea(ft.Text(error_text, color="red", selectable=True)))
        page.update()

ft.app(target=main, assets_dir="assets")
