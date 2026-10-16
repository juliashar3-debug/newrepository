# Инструменты помощника СМС

Шесть скиллов находятся в `.agents/skills/` и доступны агенту при открытии этого репозитория в среде с поддержкой repository skills. После обновления откройте новую сессию Codex с выбранным репозиторием. Это инструкции агенту, а не кнопки сайта и не фоновый планировщик.

| Скилл | Пример запроса |
| --- | --- |
| `sms-intake` | Добавь мероприятие и проверь, каких данных не хватает |
| `sms-photos` | Подбери общий снимок и подготовь коллаж |
| `sms-report` | Собери IV квартал в PPTX и PDF |
| `sms-review` | Проверь отчёт перед отправкой |
| `sms-planning` | Предложи цели и задачи на следующий квартал |
| `sms-maintenance` | Обнови сайт, сохрани данные и проверь экспорт |

## Установка

Windows: распакуйте свежий архив репозитория и запустите **INSTALL-TOOLS-WINDOWS.bat**. Нужен Python 3.10+ и интернет. Скрипт создаёт/обновляет `webapp/.venv`, устанавливает библиотеки и Chromium для Playwright, затем проверяет пакеты и шесть скиллов. Для обычной работы запускайте **START-WINDOWS.bat**. Установка не переносит и не перезаписывает мероприятия из `.data`.

macOS/Linux:

```sh
python3 tools/install_tools.py
webapp/.venv/bin/python tools/check_tools.py
```

Если системный Chromium уже установлен, используйте `python3 tools/install_tools.py --skip-browser`; при запуске Playwright укажите `executable_path` системного браузера. В Linux браузеру могут потребоваться системные зависимости — `python -m playwright install-deps chromium` выполняют с нужными системными правами.

Установщик использует `webapp/requirements-all.lock`, если этот файл присутствует. Исходный список — `webapp/requirements-all.txt`; он включает инструменты разработки и `requirements-toolkit.txt`, который включает базовый `requirements.txt`.

## Состав

- Отчёты: python-pptx, Pillow, pypdf, fonttools; хранение — встроенный sqlite3.
- Предпросмотр PDF: pypdfium2 и `tools/preview_pdf.py`.
- Структурированные данные: Pydantic; Excel — openpyxl; Word — python-docx.
- Фото HEIC/HEIF: pillow-heif. Агент может конвертировать копии; форма сайта пока принимает JPG/PNG/WebP.
- OCR: pytesseract и отдельно установленная программа Tesseract.
- ИИ: OpenAI SDK. Пакет установлен для дальнейшей разработки; запросы, ключ и оплату пользователь настраивает отдельно. Скиллы не требуют этого ключа для работы в Codex.
- Проверка браузера: Playwright; упаковка программы: PyInstaller; зависимости: uv; проверка Python: Ruff. PyInstaller не означает, что готовый Windows EXE уже собран: его собирают и проверяют на Windows.

Предпросмотр:

```sh
webapp/.venv/bin/python tools/preview_pdf.py REPORT.pdf --output /tmp/sms-preview
```

## Отдельные программы

**PDF:** установленный PowerPoint на Windows или LibreOffice. При нестандартном пути LibreOffice задайте `SMS_SOFFICE`. Для оформления отчёта нужен Verdana; проверяйте замену шрифта при экспорте на другой системе.

**OCR:** в Windows можно установить Tesseract командой `winget install --id UB-Mannheim.TesseractOCR --exact`, если этот пакет доступен в вашем каталоге winget. Проверьте наличие языков `rus` и `eng` командой `tesseract --list-langs`. Для Ubuntu/Debian — пакеты `tesseract-ocr` и `tesseract-ocr-rus`. Если программа вне PATH, для Python укажите `pytesseract.pytesseract.tesseract_cmd` или задайте `TESSERACT_CMD` для диагностики. Проверка пакета pytesseract не подтверждает наличие языковых моделей.

Установщик скачивает модели `rus` и `eng` из официального проекта `tesseract-ocr/tessdata_fast` в `webapp/.tools/tessdata`. При OCR передайте путь в `config='--tessdata-dir "ПОЛНЫЙ_ПУТЬ_К_ПАПКЕ"'` и `lang='rus+eng'`. Модели не устанавливают сам исполняемый файл Tesseract.

**Подключения:** Google Drive, SharePoint и календари подключаются к выбранному аккаунту отдельно. Python-библиотеки не дают доступ к облачным данным и не включают синхронизацию локальной базы.

## Проверки и обновление

```sh
webapp/.venv/bin/python -m pip check
webapp/.venv/bin/python tools/check_tools.py
webapp/.venv/bin/python -m unittest discover -s webapp -p 'test_*.py' -v
```

Для обновления файла версий из корня: `webapp/.venv/bin/uv pip compile --universal --python-version 3.10 webapp/requirements-all.txt -o webapp/requirements-all.lock`. После обновления повторите проверки. Системные PowerPoint/Tesseract/Chromium и шрифты в Python lock-файл не входят.

Версии `.data`, окружения `.venv`, ключи, временные изображения и исполняемые сборки не хранятся в Git. Перед обновлением папки сайта остановите сервер и перенесите сохранённую `.data` в новую папку до запуска.
