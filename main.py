import flet as ft
import time
import os
import datetime
import base64
import sqlite3

try:
    from gtts import gTTS
    HAS_VOICE = True
except ImportError:
    HAS_VOICE = False

# ==========================================
# 0. БАЗОВІ НАЛАШТУВАННЯ (100% СУМІСНІСТЬ З ANDROID)
# ==========================================
# Використовуємо універсальний шлях "~", який на Android веде в безпечну папку додатку
SAFE_DIR = os.path.expanduser("~")

KEY_FILE = os.path.join(SAFE_DIR, "api_key_turkey.txt")
REPORTS_DIR = os.path.join(SAFE_DIR, "Рапорти_Індичка")
DB_FILE = os.path.join(SAFE_DIR, "turkey_erp.db")

try:
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR, exist_ok=True)
except: pass

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS batches (name TEXT PRIMARY KEY, status TEXT, initial_count INTEGER DEFAULT 0)''')
        try: c.execute("ALTER TABLE batches ADD COLUMN initial_count INTEGER DEFAULT 0")
        except: pass
        try: c.execute("ALTER TABLE batches ADD COLUMN start_date TEXT")
        except: pass
        try: c.execute("ALTER TABLE batches ADD COLUMN initial_age INTEGER DEFAULT 1")
        except: pass
            
        c.execute('''CREATE TABLE IF NOT EXISTS daily_reports 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_name TEXT, date TEXT, water REAL, feed REAL, dead INTEGER, cull INTEGER, notes TEXT DEFAULT '')''')
        try: c.execute("ALTER TABLE daily_reports ADD COLUMN notes TEXT DEFAULT ''")
        except: pass

        c.execute('''CREATE TABLE IF NOT EXISTS vet_cases 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_name TEXT, date TEXT, photo_path TEXT, user_msg TEXT, ai_response TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Помилка БД: {e}")

init_db()

SYSTEM_PROMPT = """
Роль: Ти — висококваліфікований ветеринарний лікар птиці, зоотехнік та ветеринарно-санітарний експерт корпоративної ERP-системи "Проскурівська індичка".
Жорсткий фокус: Ти консультуєш ВИКЛЮЧНО щодо індиків (усі кроси: BIG6 та ін.).
Правило безпеки: Не генеруй точні дозування без точної ваги, віку та залишку поголів'я. Оперуй назвами діючих речовин.
Правило "Стоп-аналіз": Якщо ввідних даних недостатньо, зупиняй генерацію і вимагай уточнити параметри.
Світові практики: Завжди пропонуй варіанти вирішення проблем, спираючись на порівняння міжнародного досвіду (ЄС, США, Канада). Порівнюй показники зі стандартами кросу відповідно до віку.
"""

def get_saved_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as f: return f.read().strip()
    return ""

def save_key(key):
    with open(KEY_FILE, "w", encoding="utf-8") as f: f.write(key)

def get_img_base64(path):
    if not path or not os.path.exists(path): return ""
    try:
        with open(path, "rb") as f: return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")
    except: return ""

def get_active_batches():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT name FROM batches WHERE status='ACTIVE'")
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except: return []

def get_batch_stats(batch_name):
    if not batch_name: return {"rem": 0, "age": 0}
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT initial_count, start_date, initial_age FROM batches WHERE name=?", (batch_name,))
        res = c.fetchone()
        initial = res[0] if res and res[0] else 0
        start_date_str = res[1] if res and len(res)>1 and res[1] else None
        initial_age = res[2] if res and len(res)>2 and res[2] else 1
        
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
                today = datetime.datetime.now().date()
                days_passed = (today - start_date).days
                current_age = initial_age + (days_passed if days_passed > 0 else 0)
            except: pass

        return {"rem": rem_birds, "age": current_age}
    except: return {"rem": 0, "age": 0}

def main(page: ft.Page):
    page.title = "Проскурівська Індичка: ERP & AI"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0

    ai_audio_player = ft.Audio(autoplay=True)
    page.overlay.append(ai_audio_player)

    tf_api_key = ft.TextField(label="Gemini API Key", value=get_saved_key(), password=True, can_reveal_password=True, width=300)

    def close_settings(e=None): dlg_settings.open = False; page.update()
    def save_api_key(e): save_key(tf_api_key.value.strip()); close_settings(); page.snack_bar = ft.SnackBar(ft.Text("✅ Ключ збережено!"), bgcolor="green"); page.snack_bar.open = True; page.update()
    def open_settings(e): tf_api_key.value = get_saved_key(); dlg_settings.open = True; page.update()

    dlg_settings = ft.AlertDialog(
        title=ft.Text("🔑 Налаштування ШІ", weight=ft.FontWeight.BOLD),
        content=ft.Column([ft.Text("Введіть ваш ключ від Google Gemini:"), tf_api_key], tight=True),
        actions=[ft.TextButton("Скасувати", on_click=close_settings), ft.ElevatedButton("Зберегти", on_click=save_api_key, bgcolor=ft.colors.ORANGE_700, color="white")]
    )
    page.overlay.append(dlg_settings)

    # Зверніть увагу: ми прибрали "assets/" з назви файлу, бо Flet сам шукатиме в цій папці
    splash_view = ft.Container(
        content=ft.Column([
            ft.Image(src="logo.png", width=200, height=200, fit=ft.ImageFit.CONTAIN),
            ft.Text("ПРОСКУРІВСЬКА ІНДИЧКА", size=22, weight=ft.FontWeight.BOLD, color=ft.colors.BROWN_800),
            ft.Container(height=20), ft.ProgressRing(color=ft.colors.ORANGE_700),
            ft.Text("Завантаження баз даних...", color=ft.colors.GREY_600, italic=True)
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.alignment.center, expand=True, bgcolor=ft.colors.WHITE
    )

    dd_batch = ft.Dropdown(label="Оберіть партію", expand=True)
    dd_archive_batch = ft.Dropdown(label="Оберіть партію для Фінального Звіту", expand=True)
    
    new_batch_input = ft.TextField(label="Назва", expand=True, height=50)
    new_batch_count = ft.TextField(label="Голів", width=80, height=50, keyboard_type=ft.KeyboardType.NUMBER)
    new_batch_age = ft.TextField(label="Вік (днів)", width=80, height=50, keyboard_type=ft.KeyboardType.NUMBER, value="1")
    
    batches_listview = ft.ListView(height=150, spacing=5)

    def refresh_batches_ui():
        batches = get_active_batches()
        dd_batch.options = [ft.dropdown.Option(b) for b in batches]
        dd_archive_batch.options = [ft.dropdown.Option(b) for b in batches]
        if batches:
            if dd_batch.value not in batches: dd_batch.value = batches[0]
            if dd_archive_batch.value not in batches: dd_archive_batch.value = batches[0]
        else:
            dd_batch.value = None; dd_archive_batch.value = None
            
        context_options = [ft.dropdown.Option("Загальний випадок")] + [ft.dropdown.Option(f"Діагностика: {b}") for b in batches]
        dd_context.options = context_options
        dd_context.value = "Загальний випадок"

        batches_listview.controls.clear()
        for b in batches:
            batches_listview.controls.append(ft.Container(content=ft.Row([ft.Text(b, expand=True, weight=ft.FontWeight.BOLD), ft.IconButton(ft.icons.DELETE, icon_color="red", data=b, on_click=delete_batch)]), bgcolor=ft.colors.GREY_100, padding=5, border_radius=5))
        
        update_remaining_birds_ui(None)
        page.update()

    def add_batch(e):
        name = new_batch_input.value.strip()
        count_val = new_batch_count.value.strip()
        age_val = new_batch_age.value.strip()
        count = int(count_val) if count_val.isdigit() else 0
        age = int(age_val) if age_val.isdigit() else 1
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        if name:
            try:
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO batches (name, status, initial_count, start_date, initial_age) VALUES (?, 'ACTIVE', ?, ?, ?)", (name, count, today, age))
                conn.commit(); conn.close()
            except: pass
            new_batch_input.value = ""; new_batch_count.value = ""; new_batch_age.value = "1"
            refresh_batches_ui()

    def delete_batch(e):
        name = e.control.data
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("UPDATE batches SET status='CLOSED' WHERE name=?", (name,))
            conn.commit(); conn.close()
        except: pass
        refresh_batches_ui()

    dlg_manage_batches = ft.AlertDialog(
        title=ft.Text("Керування партіями"),
        content=ft.Column([
            ft.Row([new_batch_input, new_batch_count, new_batch_age]), 
            ft.ElevatedButton("Додати", icon=ft.icons.ADD_CIRCLE, icon_color="green", on_click=add_batch, expand=True),
            ft.Divider(), batches_listview
        ], tight=True, height=350),
        actions=[ft.TextButton("Закрити", on_click=lambda e: (setattr(dlg_manage_batches, 'open', False), page.update()))]
    )
    page.overlay.append(dlg_manage_batches)

    # ==========================================
    # ВКЛАДКА 1: РАПОРТ 
    # ==========================================
    txt_remaining = ft.Text("Фактичний залишок: Оновлюється...", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_700)
    
    def update_remaining_birds_ui(e):
        stats = get_batch_stats(dd_batch.value)
        txt_remaining.value = f"Залишок: {stats['rem']} голів | Вік: {stats['age']} днів"
        page.update()
        
    dd_batch.on_change = update_remaining_birds_ui

    tf_water = ft.TextField(label="Вода (л)", value="0", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    tf_feed = ft.TextField(label="Корм (кг)", value="0", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    tf_dead = ft.TextField(label="Падіж", value="0", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    tf_cull = ft.TextField(label="Брак", value="0", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    tf_temp = ft.TextField(label="T (°C)", value="28", expand=True)
    tf_humidity = ft.TextField(label="Волога (%)", value="60", expand=True)
    tf_ammonia = ft.TextField(label="Аміак (ppm)", value="10", expand=True)
    dd_litter = ft.Dropdown(label="Підстилка", options=[ft.dropdown.Option("Суха/пухка"), ft.dropdown.Option("Волога"), ft.dropdown.Option("Кірка")], value="Суха/пухка", expand=True)
    dd_droppings = ft.Dropdown(label="Послід", options=[ft.dropdown.Option("Норма"), ft.dropdown.Option("Рідкий"), ft.dropdown.Option("Жовтий/Оранж"), ft.dropdown.Option("З кров'ю")], value="Норма", expand=True)
    tf_operator_notes = ft.TextField(label="Коментар оператора", multiline=True, expand=True)
    
    def save_daily_report(e):
        if not dd_batch.value:
            page.snack_bar = ft.SnackBar(ft.Text("❌ Оберіть партію!"), bgcolor="red"); page.snack_bar.open = True; page.update(); return
        try:
            w, f, d, c = float(tf_water.value), float(tf_feed.value), int(tf_dead.value), int(tf_cull.value)
            conn = sqlite3.connect(DB_FILE)
            conn.execute("INSERT INTO daily_reports (batch_name, date, water, feed, dead, cull, notes) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                         (dd_batch.value, datetime.datetime.now().strftime('%Y-%m-%d'), w, f, d, c, tf_operator_notes.value))
            conn.commit(); conn.close()
            page.snack_bar = ft.SnackBar(ft.Text(f"✅ Дані збережено в БД!"), bgcolor="green")
            update_remaining_birds_ui(None)
            tf_dead.value = "0"; tf_cull.value = "0"; tf_operator_notes.value = ""
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"❌ Помилка: {ex}"), bgcolor="red")
        page.snack_bar.open = True; page.update()

    def generate_and_print_report(e):
        api_key = get_saved_key()
        if not api_key:
            page.snack_bar = ft.SnackBar(ft.Text("❌ Введіть API ключ в налаштуваннях!"), bgcolor=ft.colors.RED); page.snack_bar.open = True; page.update(); return
        page.snack_bar = ft.SnackBar(ft.Text("⏳ ШІ формує рапорт..."), bgcolor=ft.colors.BLUE); page.snack_bar.open = True; page.update()
        stats = get_batch_stats(dd_batch.value)
        try:
            # ЗАВАНТАЖУЄМО ШІ ТІЛЬКИ ТУТ
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            ai_prompt = f"Партія: {dd_batch.value}. Залишок: {stats['rem']}. Вік: {stats['age']} днів.\nВода: {tf_water.value}л, Корм: {tf_feed.value}кг.\nT={tf_temp.value}°C, Вологість={tf_humidity.value}%, Аміак={tf_ammonia.value} ppm.\nСтан: Підстилка {dd_litter.value}, Послід {dd_droppings.value}, Падіж {tf_dead.value}.\nНотатки: {tf_operator_notes.value}\nАналізуй."
            ai_analysis = model.generate_content([SYSTEM_PROMPT, ai_prompt]).text
        except Exception as ex: ai_analysis = f"❌ Помилка підключення до ШІ: {ex}"

        date_str = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
        filepath = os.path.join(REPORTS_DIR, f"Рапорт_{dd_batch.value}_{datetime.datetime.now().strftime('%d%m_%H%M')}.html")
        html_content = f"<html><head><meta charset='utf-8'></head><body><h2>Рапорт - {dd_batch.value}</h2><p>Дата: {date_str} | Вік: {stats['age']} | Залишок: {stats['rem']}</p><p>Вода: {tf_water.value} л | Корм: {tf_feed.value} кг | Падіж: {tf_dead.value}</p><h3>Аналіз ШІ:</h3>{ai_analysis}<script>window.print();</script></body></html>"
        try:
            with open(filepath, "w", encoding="utf-8") as f: f.write(html_content)
            page.snack_bar = ft.SnackBar(ft.Text(f"✅ Збережено в {filepath}"), bgcolor=ft.colors.GREEN)
        except: page.snack_bar = ft.SnackBar(ft.Text(f"❌ Помилка запису файлу"), bgcolor="red")
        page.snack_bar.open = True; page.update()

    report_content = ft.ListView(
        controls=[
            ft.Row([dd_batch, ft.IconButton(ft.icons.SETTINGS, icon_color=ft.colors.BLUE_700, on_click=lambda e: (setattr(dlg_manage_batches, 'open', True), page.update()))]),
            ft.Container(content=ft.Column([txt_remaining]), padding=10, bgcolor=ft.colors.BLUE_50, border_radius=10),
            ft.Text("Відхід:", weight=ft.FontWeight.W_600),
            ft.Row([tf_water, tf_feed]), ft.Row([tf_dead, tf_cull]),
            ft.Text("Мікроклімат:", weight=ft.FontWeight.W_600),
            ft.Row([tf_temp, tf_humidity, tf_ammonia]),
            ft.Text("Контроль:", weight=ft.FontWeight.W_600),
            ft.Row([dd_litter, dd_droppings]),
            ft.Row([tf_operator_notes, ft.IconButton(ft.icons.MIC, icon_color="blue", on_click=lambda e: tf_operator_notes.focus())]),
            ft.Column([
                ft.ElevatedButton("💾 ЗБЕРЕГТИ", on_click=save_daily_report, bgcolor=ft.colors.ORANGE_700, color=ft.colors.WHITE, height=50, expand=True),
                ft.ElevatedButton("🖨️ ДРУК ТА АНАЛІЗ", on_click=generate_and_print_report, bgcolor=ft.colors.BLUE_700, color=ft.colors.WHITE, height=50, expand=True)
            ])
        ], padding=20, spacing=10, expand=True
    )

    # ==========================================
    # ВКЛАДКА 2: ШІ-ЧАТ
    # ==========================================
    dd_context = ft.Dropdown(label="Контекст аналізу", expand=True)
    switch_voice = ft.Switch(label="🗣️ Голос", value=False)
    chat_list = ft.ListView(expand=True, spacing=10, auto_scroll=True)
    chat_input = ft.TextField(hint_text="Опишіть симптоми...", expand=True, border_radius=20)
    chat_image_path = [None]; current_chat_history = []
    img_preview = ft.Image(src="", width=80, height=80, fit=ft.ImageFit.COVER, border_radius=10)
    
    preview_row = ft.Row([img_preview, ft.IconButton(ft.icons.CANCEL, icon_color="red", on_click=lambda e: (chat_image_path.__setitem__(0, None), setattr(preview_row, 'visible', False), page.update()))], visible=False)
    fp_chat = ft.FilePicker(on_result=lambda e: (chat_image_path.__setitem__(0, e.files[0].path), setattr(img_preview, 'src', e.files[0].path), setattr(preview_row, 'visible', True), page.update()) if e.files else None)
    page.overlay.append(fp_chat)

    def clear_chat(e):
        chat_list.controls.clear(); current_chat_history.clear()
        page.snack_bar = ft.SnackBar(ft.Text("🧹 Очищено!"), bgcolor=ft.colors.BLUE); page.snack_bar.open = True; page.update()

    def send_chat(e):
        user_msg = chat_input.value; img_path = chat_image_path[0]; context = dd_context.value
        if not user_msg and not img_path: return

        current_chat_history.append({"role": "Лікар", "text": user_msg, "image": img_path})
        user_elements = []
        if img_path: user_elements.append(ft.Image(src=img_path, width=150, border_radius=10))
        if user_msg: user_elements.append(ft.Text(f"👨‍⚕️: {user_msg}", color="white"))
        chat_list.controls.append(ft.Container(content=ft.Column(user_elements, spacing=5, alignment=ft.MainAxisAlignment.END, horizontal_alignment=ft.CrossAxisAlignment.END), bgcolor=ft.colors.BLUE_600, padding=10, border_radius=10, alignment=ft.alignment.center_right))
        chat_input.value = ""; chat_image_path[0] = None; preview_row.visible = False; page.update()
        
        api_key = get_saved_key()
        if not api_key:
            chat_list.controls.append(ft.Text("❌ API Ключ не знайдено в налаштуваннях!", color="red")); page.update(); return

        thinking = ft.Text("🤖 ШІ думає...", color=ft.colors.GREY_500, italic=True)
        chat_list.controls.append(thinking); page.update()

        try:
            # ЗАВАНТАЖУЄМО ШІ ТІЛЬКИ ТУТ
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            stats = get_batch_stats(context.replace("Діагностика: ", "")) if "Діагностика: " in context else {"rem": "Невідомо", "age": "Невідомо"}
            prompt = [SYSTEM_PROMPT, f"Контекст: {context}. Залишок: {stats['rem']}. Вік: {stats['age']}.\nПитання: {user_msg}"]
            if img_path:
                with open(img_path, "rb") as f: prompt.append({"mime_type": "image/jpeg", "data": f.read()})
            reply = model.generate_content(prompt).text
            
            if "Діагностика: " in context:
                b_name = context.replace("Діагностика: ", "")
                conn = sqlite3.connect(DB_FILE)
                conn.execute("INSERT INTO vet_cases (batch_name, date, photo_path, user_msg, ai_response) VALUES (?, ?, ?, ?, ?)", (b_name, datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), img_path or "", user_msg, reply))
                conn.commit(); conn.close()
                reply += "\n\n*(💾 Підшито до справи)*"

            current_chat_history.append({"role": "ШІ", "text": reply, "image": None})
            
            if switch_voice.value and HAS_VOICE:
                clean_text = reply.replace("*", "").replace("#", "") 
                tts = gTTS(text=clean_text, lang='uk')
                audio_file = os.path.join(SAFE_DIR, f"reply_{int(time.time())}.mp3")
                try:
                    tts.save(audio_file)
                    audio_player = ft.Audio(src=audio_file, autoplay=True)
                    page.overlay.append(audio_player); page.update()
                except: pass
        except Exception as ex: reply = f"❌ Помилка: {str(ex)}"

        chat_list.controls.remove(thinking)
        chat_list.controls.append(ft.Container(content=ft.Markdown(reply), bgcolor=ft.colors.GREY_200, padding=10, border_radius=10, alignment=ft.alignment.center_left)); page.update()

    chat_content = ft.Container(
        content=ft.Column([
            ft.Row([ft.Icon(ft.icons.SMART_TOY, color=ft.colors.ORANGE_700), ft.Text("AI Експерт", size=18, weight=ft.FontWeight.BOLD), switch_voice]),
            dd_context,
            ft.Row([ft.ElevatedButton("🧹", icon_color="red", on_click=clear_chat), ft.ElevatedButton("💾 Зберегти", icon_color="green", on_click=lambda e: None, expand=True)]),
            ft.Container(content=chat_list, expand=True, border=ft.border.all(1, ft.colors.GREY_300), border_radius=10, padding=10),
            preview_row,
            ft.Row([
                ft.IconButton(ft.icons.ADD_A_PHOTO, icon_color=ft.colors.BLUE, on_click=lambda _: fp_chat.pick_files()), 
                chat_input, 
                ft.IconButton(ft.icons.MIC, icon_color="purple", on_click=lambda e: chat_input.focus()),
                ft.IconButton(ft.icons.SEND, icon_color=ft.colors.GREEN, on_click=send_chat)
            ])
        ]), padding=20, expand=True
    )

    # ==========================================
    # ВКЛАДКА 3: АРХІВ
    # ==========================================
    def generate_final_report(e):
        page.snack_bar = ft.SnackBar(ft.Text("⏳ Функція генерації..."), bgcolor=ft.colors.BLUE); page.snack_bar.open = True; page.update()

    archive_content = ft.Container(
        content=ft.Column([
            ft.Icon(ft.icons.INVENTORY, size=50, color="grey"), ft.Text("Генератор Звіту", size=22, weight=ft.FontWeight.BOLD),
            ft.Container(height=20), dd_archive_batch,
            ft.ElevatedButton("🏆 ЗГЕНЕРУВАТИ", icon=ft.icons.STAR, on_click=generate_final_report, bgcolor="blue", color="white", height=60, width=350)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER), padding=30
    )

    # --- ШАПКА ТА ГОЛОВНЕ МЕНЮ ---
    refresh_batches_ui()
    
    top_app_bar = ft.Container(
        content=ft.Row([
            # Зверніть увагу: ми прибрали "assets/" з назви файлу
            ft.Row([ft.Image(src="logo.png", width=35, height=35), ft.Text("Проскурівська Індичка", size=16, weight=ft.FontWeight.BOLD, color=ft.colors.BROWN_800)]),
            ft.IconButton(icon=ft.icons.VPN_KEY, icon_color=ft.colors.ORANGE_700, on_click=open_settings)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=ft.padding.only(left=15, right=10, top=10, bottom=5), bgcolor=ft.colors.GREY_100
    )

    main_view = ft.Column([
        top_app_bar,
        ft.Tabs(selected_index=0, animation_duration=300, tabs=[
            ft.Tab(text="📊 РАПОРТ", icon=ft.icons.DASHBOARD, content=report_content),
            ft.Tab(text="🤖 ЧАТ", icon=ft.icons.CHAT, content=chat_content),
            ft.Tab(text="📁 АРХІВ", icon=ft.icons.ARCHIVE, content=archive_content),
        ], expand=True)
    ], expand=True, visible=False, spacing=0)

    page.add(splash_view, main_view)
    page.update(); time.sleep(1.5); splash_view.visible = False; main_view.visible = True; page.update()

# ДОДАНО assets_dir="assets" ДЛЯ ПРАВИЛЬНОЇ РОБОТИ ЛОГОТИПУ НА ANDROID
ft.app(target=main, assets_dir="assets")
