"""Run with a Python containing Playwright. Uses temporary synthetic data, never the book.
Requires a completed app build and Chromium. Owns and stops both subprocesses.
"""
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/bin/python'

def wait(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200: return
        except Exception: time.sleep(.2)
    raise RuntimeError(f'Service not ready: {url}')

with tempfile.TemporaryDirectory(prefix='neufert-browser-') as temporary:
    env={**os.environ,'NEUFERT_DATA_DIR':temporary,'NEUFERT_APP_ORIGIN':'http://localhost:3000'}
    seed='''
from pathlib import Path
import fitz
from pipeline.ingest import ingest
from pipeline.storage import data_dir
path=data_dir()/'synthetic-not-neufert.pdf'
doc=fitz.open()
for number in range(2):
    page=doc.new_page(width=500,height=700)
    page.insert_text((40,60),'Krankenhaus Flure' if number==0 else 'Wohnhaus Treppen',fontsize=20)
    page.insert_text((40,110),'Der Flur im Krankenhaus ist 2,40 m breit. Betten und Bewegung.' if number==0 else 'Die Treppe im Wohnhaus ist 90 cm breit. Wohnen und Arbeiten.',fontsize=10)
    page.draw_rect(fitz.Rect(40,160,240,280))
    page.insert_text((250,680),str(number+101),fontsize=10)
doc.set_metadata({'title':'SYNTHETIC TEST FIXTURE — NOT THE NEUFERT BOOK'})
doc.set_toc([[1,'Krankenhaus',1],[1,'Wohnhaus',2]])
doc.save(path);doc.close();ingest(path)
'''
    subprocess.run([str(PYTHON),'-c',seed],cwd=ROOT,env=env,check=True)
    with open(Path(temporary)/'api.log','w') as api_log,open(Path(temporary)/'web.log','w') as web_log:
        api=subprocess.Popen([str(PYTHON),'-m','uvicorn','pipeline.api:app','--host','127.0.0.1','--port','8000'],cwd=ROOT,env=env,stdout=api_log,stderr=subprocess.STDOUT)
        web=subprocess.Popen(['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1'],cwd=ROOT/'app',env=env,stdout=web_log,stderr=subprocess.STDOUT)
        try:
            wait('http://127.0.0.1:8000/api/status');wait('http://127.0.0.1:3000')
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1280,'height':900})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto('http://localhost:3000')
                expect(page.get_by_role('heading',name='Neufert Digital',exact=True)).to_be_visible()
                page.get_by_label('Palabras clave o pregunta').fill('pasillo')
                page.get_by_role('button',name='Buscar ⭢',exact=True).click()
                page.get_by_role('link',name='Krankenhaus Flure',exact=True).click()
                expect(page.get_by_role('cell',name='2.4',exact=True)).to_be_visible()
                page.get_by_role('button',name='Guardar favorito').click()
                expect(page.get_by_role('button',name='Quitar favorito')).to_be_visible()
                page.get_by_role('link',name='colecciones',exact=True).click()
                page.get_by_label('Nueva colección').fill('Proyecto sintético')
                page.get_by_role('button',name='Crear',exact=True).click()
                expect(page.get_by_role('button',name='Proyecto sintético (0) ⭢')).to_be_visible()
                page.get_by_role('link',name='biblioteca',exact=True).click()
                page.get_by_role('link',name='Krankenhaus Flure',exact=True).click()
                page.get_by_label('Añadir a colección').select_option(label='Proyecto sintético')
                page.get_by_role('button',name='Ver página original ⭢').click()
                expect(page.locator('svg rect')).to_have_count(1)
                page.get_by_role('button',name='Siguiente',exact=True).click()
                expect(page.get_by_role('heading',name='Página PDF 2',exact=True)).to_be_visible()
                expect(page.locator('svg rect')).to_have_count(0)
                page.get_by_role('button',name='Anterior',exact=True).click()
                expect(page.get_by_role('heading',name='Página PDF 1',exact=True)).to_be_visible()
                page.get_by_label('Idioma').select_option('en')
                expect(page.locator('html')).to_have_attribute('lang','en')
                page.get_by_role('link',name='collections',exact=True).click()
                page.get_by_role('button',name='Proyecto sintético (1) ⭢').click()
                with page.expect_download() as download:
                    page.get_by_role('link',name='Export Markdown ⭢').click()
                assert 'PDF p. 1' in Path(download.value.path()).read_text()
                with page.expect_download() as download:
                    page.get_by_role('link',name='Export PDF ⭢').click()
                assert Path(download.value.path()).read_bytes().startswith(b'%PDF')
                page.get_by_label('Language').select_option('de')
                expect(page.locator('html')).to_have_attribute('lang','de')
                page.set_viewport_size({'width':390,'height':844})
                page.get_by_role('link',name='bibliothek',exact=True).click()
                page.get_by_label('Stichwörter oder Frage').fill('Treppen')
                page.get_by_role('button',name='Suchen ⭢',exact=True).click()
                page.get_by_role('link',name='Wohnhaus Treppen',exact=True).click()
                expect(page.get_by_role('cell',name='90',exact=True)).to_be_visible()
                # Keyboard focus remains available in the native HTML version.
                page.keyboard.press('Tab')
                assert page.evaluate('document.activeElement !== document.body')
                assert errors==[],errors
                browser.close()
                print('Browser smoke passed: search, detail, favorites, collections, viewer bbox/navigation, exports, ES/EN/DE, mobile interaction.')
        except Exception:
            print((Path(temporary)/'api.log').read_text())
            print((Path(temporary)/'web.log').read_text())
            raise
        finally:
            for process in (web,api):
                process.terminate()
            for process in (web,api):
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill();process.wait()
