
from pathlib import Path
from tempfile import NamedTemporaryFile
from subprocess import run, PIPE
import re
from pprint import pprint
from collections import OrderedDict
import os

from bs4 import BeautifulSoup

#pandoc --csl chicago-note-bibliography-with-ibid.csl --bibliography my_library.csl.json --filter pandoc-citeproc citas.md

PANDOC_BIN = 'pandoc'

CSL_PATHS = {'chicago-note-bibliography-with-ibid': Path('chicago-note-bibliography-with-ibid.csl')}
this_module_dir = Path(os.path.dirname(os.path.abspath(__file__)))
CSL_PATHS = {csl: this_module_dir / fname for  csl, fname in CSL_PATHS.items()}


def _run_pandoc(mk_text, csl_path, libray_csl_json_path):

    with NamedTemporaryFile('wt') as fhand:
        fhand.write(mk_text)
        fhand.flush()

        cmd = [PANDOC_BIN,
               '--csl', str(csl_path),
               '--bibliography', str(libray_csl_json_path),
               '--filter', 'pandoc-citeproc',
               fhand.name]
        process = run(cmd, stdout=PIPE, stderr=PIPE, check=True)
    return process


def _parse_pandoc_citations(pandoc_html):

    soup = BeautifulSoup(pandoc_html, 'html.parser')

    in_text_citations_by_footnote = {}
    for idx, span in enumerate(soup.find_all('span', "citation")):
        citation_key = span['data-cites']
        link = span.a
        in_text_html_text = ' '.join([str(content) for content in span.a.contents])
        footnote_id = link['href'].strip('#')
        anchor_id = link['id']
        in_text_citations_by_footnote[footnote_id] = {'in_text_html_text': in_text_html_text,
                                                      'in_text_id': anchor_id,
                                                      'footnote_id': footnote_id,
                                                      'citation_key': citation_key,
                                                      'idx': idx}

    footnotes_section = soup.find('section', "footnotes")
    ol = footnotes_section.find('ol')
    for li in ol.find_all('li'):
        id_ = li['id']
        html_text = re.sub('<a.*>.*</a>', '', str(li.p))
        in_text_citations_by_footnote[id_]['footnote_html_text'] = html_text

    references = OrderedDict()
    references_div = soup.find('div', "references")
    if references_div:
        for div in references_div.find_all('div'):
            citation_key = div['id'][4:]
            html_text = str(div.p)
            references[citation_key] = html_text

    citations = sorted(in_text_citations_by_footnote.values(), key=lambda x: x['idx'])
    return {'citations': citations, 'references': references}


def process_citations(mk_citations, libray_csl_json_path,
                      csl='chicago-note-bibliography-with-ibid'):
    csl_path = CSL_PATHS[csl]
    mk_text = '\n'.join(mk_citations)
    process = _run_pandoc(mk_text, csl_path, libray_csl_json_path)

    result = _parse_pandoc_citations(process.stdout.decode())

    stderr = process.stderr.decode()
    references_not_found = []
    if 'pandoc-citeproc: reference' in stderr and 'not found' in stderr:
        for line in stderr.splitlines():
            reference = line[26:][:-10].strip()
            if reference not in references_not_found:
                references_not_found.append(reference)
    result['references_not_found'] = references_not_found
    return result


if __name__ == '__main__':
    libray_csl_json_path = Path('my_library.csl.json')
    csl_path = Path('chicago-note-bibliography-with-ibid.csl')

    result = process_citations(['[see @noGapsClassic, pp. 33-35]',
                                '[@noGapsClassic, pp. 100]',
                                '[@noGapsClassic]',
                                '[@noref1]',
                                '[@noref2]'],
                                csl='chicago-note-bibliography-with-ibid',
                                libray_csl_json_path=libray_csl_json_path)
    pprint(result)
