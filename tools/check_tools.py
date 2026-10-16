"""Report toolkit readiness without reading user data or making API requests."""
from importlib import import_module, metadata
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    'python-pptx': 'pptx', 'Pillow': 'PIL', 'pypdf': 'pypdf', 'fonttools': 'fontTools',
    'pypdfium2': 'pypdfium2', 'pydantic': 'pydantic', 'pillow-heif': 'pillow_heif',
    'openpyxl': 'openpyxl', 'python-docx': 'docx', 'pytesseract': 'pytesseract',
    'openai': 'openai', 'playwright': 'playwright.sync_api', 'pyinstaller': 'PyInstaller',
    'uv': 'uv', 'ruff': 'ruff',
}
SKILLS = ['sms-intake', 'sms-photos', 'sms-report', 'sms-review', 'sms-planning', 'sms-maintenance']


def main():
    failures = []
    for package, module in PACKAGES.items():
        try:
            import_module(module)
            print(f'OK package {package} {metadata.version(package)}')
        except (ImportError, OSError, metadata.PackageNotFoundError) as error:
            failures.append(package)
            print(f'MISSING package {package}: {error}')
    for skill in SKILLS:
        path = ROOT / '.agents/skills' / skill / 'SKILL.md'
        text = path.read_text(encoding='utf-8') if path.is_file() else ''
        valid = text.startswith('---\n') and f'name: {skill}\n' in text and bool(re.search(r'^description: .+', text, re.M)) and len(text.split('---', 2)[-1].strip()) > 200
        print(f'{"OK" if valid else "MISSING"} skill {skill}')
        if not valid:
            failures.append(skill)
    sys.path.insert(0, str(ROOT / 'webapp'))
    import report_builder
    office = report_builder.converter()
    print('PDF converter:', office[0] if office else 'not detected; install PowerPoint or LibreOffice')
    tesseract = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    if not tesseract and sys.platform == 'win32':
        candidate = Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Tesseract-OCR/tesseract.exe'
        tesseract = str(candidate) if candidate.is_file() else None
    if tesseract:
        try:
            arguments = [tesseract, '--list-langs']
            languages = ROOT / 'webapp/.tools/tessdata'
            if (languages / 'rus.traineddata').is_file():
                arguments.extend(['--tessdata-dir', str(languages)])
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=10)
            print('OCR languages:', ', '.join(result.stdout.splitlines()[1:]) or 'not available')
        except (OSError, subprocess.TimeoutExpired) as error:
            print('OCR runtime:', error)
    else:
        print('OCR runtime: install Tesseract and Russian/English language data; see docs/TOOLKIT.md')
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            bundled = Path(playwright.chromium.executable_path)
        browser = str(bundled) if bundled.is_file() else shutil.which('chromium') or shutil.which('google-chrome')
        print('Browser:', browser or 'run python -m playwright install chromium')
    except (ImportError, OSError) as error:
        print('Browser:', error)
    print('OpenAI SDK: library only; API calls require a separately configured key and billing.')
    print('A package check does not verify PowerPoint COM or add new website buttons.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
