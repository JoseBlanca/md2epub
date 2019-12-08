
from pathlib import Path
from tempfile import NamedTemporaryFile
from subprocess import run, PIPE
import re
from pprint import pprint
from collections import OrderedDict
import os
import uuid

from bs4 import BeautifulSoup

#pandoc --csl chicago-note-bibliography-with-ibid.csl --bibliography my_library.csl.json --filter pandoc-citeproc citas.md

PANDOC_BIN = 'pandoc'

CSL_PATHS = {'chicago-note-bibliography-with-ibid': Path('chicago-note-bibliography-with-ibid.csl')}
this_module_dir = Path(os.path.dirname(os.path.abspath(__file__)))
CSL_PATHS = {csl: this_module_dir / fname for  csl, fname in CSL_PATHS.items()}

ID_RE = re.compile(r'&lt;[0-9a-g]*[-–][0-9a-g]*[-–][0-9a-g]*[-–][0-9a-g]*[-–][0-9a-g]*&gt;')
CITATION_KEY_RE = re.compile(r'@([^ \]]+)')


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


def _get_ids_from_html_text(html_text):
    matches = ID_RE.findall(html_text)

    ids = []
    for match in matches:
        match = str(match)
        if match.startswith('&lt;'):
            ids.append(match[4:-4])
    return ids


def _remove_ids_from_html_text(html_text):
    html_text = ID_RE.sub('', html_text).replace(', ;', ';')
    return html_text


def _get_citation_keys_from_md_text(md_text):
    citation_keys = [match for match in re.findall(CITATION_KEY_RE, md_text)]
    return citation_keys


def _remove_p_tags_from_text(html_text):
    html_text = html_text.strip()
    if html_text.startswith('<p>') and html_text.endswith('</p>'):
        html_text = html_text[3:-4]
    return html_text


def _parse_pandoc_citations(pandoc_html):

    soup = BeautifulSoup(pandoc_html, 'html.parser')

    in_text_items_by_footnote = {}
    for idx, span in enumerate(soup.find_all('span', "citation")):
        citation_keys = span['data-cites'].split()
        link = span.a
        in_text_html_text = ' '.join([str(content) for content in span.a.contents])
        footnote_id = link['href'].strip('#')
        anchor_id = link['id']
        in_text_items_by_footnote[footnote_id] = {'in_text_html_text': in_text_html_text,
                                                  'pandoc_in_text_anchor_id': anchor_id,
                                                  'pandoc_footnote_anchor_id': footnote_id,
                                                  'citation_keys': citation_keys,
                                                  'pandoc_citation_span_idx': idx}

    footnotes_section = soup.find('section', "footnotes")
    ol = footnotes_section.find('ol')
    for li in ol.find_all('li'):
        id_ = li['id']
        html_text = re.sub('<a.*>.*</a>', '', str(li.p))
        ids = _get_ids_from_html_text(html_text)

        html_text = _remove_ids_from_html_text(html_text)
        html_text = _remove_p_tags_from_text(html_text)
        html_text = html_text.replace(',”', '”')
        html_text = html_text.replace(' .', '.')
        html_text = html_text.replace(',.', '.')

        if 'citeproc-not-found' in html_text:
            html_text = None
        in_text_items_by_footnote[id_]['footnote_html_text'] = html_text
        in_text_items_by_footnote[id_]['ids'] = ids

    references = OrderedDict()
    references_div = soup.find('div', "references")
    if references_div:
        for div in references_div.find_all('div'):
            citation_key = div['id'][4:]
            html_text = str(div.p)
            html_text = _remove_p_tags_from_text(html_text)
            references[citation_key] = html_text

    citations = sorted(in_text_items_by_footnote.values(), key=lambda x: x['pandoc_citation_span_idx'])

    return {'citations': citations, 'references': references}


def _get_uuid():
    # we avoid uuids that start with a letter to avoid a problem with pandoc-citeproc
    while True:
        one_uuid = str(uuid.uuid4())
        if one_uuid[0].isdigit():
            return one_uuid

def _prepare_items(md_items):
    items = []
    for idx, item in enumerate(md_items):
        if ';' in item:
            citations = [{'strip_md_text': citation_text} for citation_text in item.lstrip('[').rstrip(']').split(';')]
        else:
            citations = [{'orig_md_text' :item}]

        for citation in citations:
            citation['id'] = _get_uuid()
            
        items.append({'idx': idx,
                      'orig_md_text': item,
                      'citations': citations,
                     })
    return items


def _prepare_md_text_for_pandoc(items):

    for item in items:
        if len(item['citations']) == 1:
            citation = item['citations'][0]
            orig_text = citation['orig_md_text']
            first_half, second_half = orig_text.split(']')
            text_for_pandoc = f'{first_half} <{citation["id"]}>{second_half}]'
        else:
            texts = [f'{citation["strip_md_text"]} <{citation["id"]}>'  for citation in item['citations']]
            text_for_pandoc = '[' + ';'.join(texts) + ']'
        item['text_for_pandoc'] = text_for_pandoc

    return '\n\n'.join([f'item {item["text_for_pandoc"]}' for item in items])


def process_citations(md_items, libray_csl_json_path,
                      csl='chicago-note-bibliography-with-ibid'):
    csl_path = CSL_PATHS[csl]

    items = _prepare_items(md_items)

    md_text = _prepare_md_text_for_pandoc(items)
  
    process = _run_pandoc(md_text, csl_path, libray_csl_json_path)

    results = _parse_pandoc_citations(process.stdout.decode())

    parsed_results_by_id = {}
    for res in results['citations']:
        for id_ in res['ids']:
            id_ = id_.replace('–', '-')
            parsed_results_by_id[id_] = res

    for item in items:

        one_parsed_result = None
        for citation in item['citations']:
            try:
                one_parsed_result = parsed_results_by_id[citation['id']]
            except KeyError:
                pass

        if one_parsed_result:
            item['citation_keys'] = one_parsed_result['citation_keys']
            item['footnote_html_text'] = one_parsed_result['footnote_html_text']
            item['in_text_html_text'] = one_parsed_result['in_text_html_text']

    for item in items:
        item['num_citations'] = len(item['citations'])
        del item['citations']
        del item['text_for_pandoc']   

        if not 'citation_keys' in item or not item['citation_keys']:
               item['citation_keys'] = _get_citation_keys_from_md_text(item['orig_md_text'])

        if 'in_text_html_text' in item and item['in_text_html_text']:
            item['citations_found'] = True
        else:
            item['citations_found'] = False

    return {'citation_items': items, 'references': results['references']}


if __name__ == '__main__':
    libray_csl_json_path = Path('my_library.csl.json')
    csl_path = Path('chicago-note-bibliography-with-ibid.csl')

    result = process_citations(['[see @noGapsClassic, pp. 33-35]',
                                '[@noGapsClassic, pp. 100]',
                                'Adamson says blah [-@smith04]',
                                '[@noGapsClassic; also @noGapsClassic, chap. 1]',
                                '[@noref1]',
                                '[@noref2]'],
                                csl='chicago-note-bibliography-with-ibid',
                                libray_csl_json_path=libray_csl_json_path)
    #pprint(result)
