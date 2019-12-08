
# A example of how to compile a site

from pathlib import Path
import sys
import shutil

user_dir = Path('/Users/jose')

epub_lib_path =  user_dir / 'Desktop/mk2epub/'

sys.path.append(str(epub_lib_path))

from book_section import BookSection
from site_creation import SiteRenderer, EPUB3, HTML, check_epub

base_dir = user_dir / 'Desktop/epistemiologia/el_arte_de_la_duda/capitulos/libro'
book_dir = base_dir / 'redactado'

book = BookSection(book_dir)
epub_path = base_dir / 'el_arte_de_la_duda.epub'
out_dir = base_dir / 'el_arte_de_la_duda_epub'
if out_dir.exists():
    shutil.rmtree(out_dir)
with SiteRenderer(book, zip_path=epub_path, out_dir=out_dir, site_kind=EPUB3) as renderer:
    renderer.render()
check_epub(epub_path)

book = BookSection(book_dir)
html_path = base_dir / 'el_arte_de_la_duda'
if html_path.exists():
    shutil.rmtree(html_path)
with SiteRenderer(book, out_dir=html_path, site_kind=HTML) as renderer:
    renderer.render()
