"""Install the SMS toolkit into the site's virtual environment without touching data."""
import argparse
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-browser', action='store_true',
                        help='Use an existing Chromium/Chrome instead of downloading Playwright Chromium.')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required.')
    environment = ROOT / 'webapp' / '.venv'
    executable = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not executable.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    lock = ROOT / 'webapp' / 'requirements-all.lock'
    requirements = lock if lock.is_file() else ROOT / 'webapp' / 'requirements-all.txt'
    subprocess.run([str(executable), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
    subprocess.run([str(executable), '-m', 'pip', 'check'], check=True)
    if not args.skip_browser:
        subprocess.run([str(executable), '-m', 'playwright', 'install', 'chromium'], check=True)
    languages = ROOT / 'webapp' / '.tools' / 'tessdata'
    languages.mkdir(parents=True, exist_ok=True)
    for language in ['eng', 'rus']:
        target = languages / f'{language}.traineddata'
        if target.is_file() and target.stat().st_size > 10000:
            continue
        url = f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{language}.traineddata'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if len(data) < 10000:
            raise ValueError('Unexpected Tesseract language download.')
        temporary = target.with_suffix('.download')
        temporary.write_bytes(data)
        temporary.replace(target)
    subprocess.run([str(executable), str(ROOT / 'tools' / 'check_tools.py')], check=True)
    print('Installed into:', environment)
    print('Skills are in .agents/skills. Reopen the repository in Codex to discover them.')


if __name__ == '__main__':
    main()
