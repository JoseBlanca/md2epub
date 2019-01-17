
import zipfile
from functools import partial
import re
from collections import OrderedDict, Counter, defaultdict
import shutil
import os
from pprint import pprint
import datetime
import subprocess
import sys

import mistune

from book_section import (CHAPTER, PART, SUBCHAPTER, TOC,
                          _parse_header_line,
                          BookSectionWithNoFiles)
from citations import create_citation_note, create_bibliography_citation

EPUBCHECK_JAR = 'epubcheck-4.0.2/epubcheck.jar'

CONTAINER_XML = '''<?xml version='1.0' encoding='utf-8'?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile media-type="application/oebps-package+xml" full-path="EPUB/content.opf"/>
  </rootfiles>
</container>'''

NAV_HEADER_XML = '''<?xml version='1.0' encoding='utf-8'?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head>
<title>{title}</title>
</head>
<body>
'''

NBSP = '&nbsp;'
NBSP = '&#160;'
EPUB_VERSION = 'old'
ENDNOTES_EPUB_TYPE = {'old': 'rearnotes',
                      '3.1': 'endnotes'}
EPUB_META_DIR = 'META-INF'
EPUB_DIR = 'EPUB'
XHTML_FILES_EXTENSION = 'xhtml'
CONTAINER_XML_FPATH = EPUB_META_DIR + '/container.xml'
ENDNOTE_CHAPTER_ID = 'endnotes'
ENDNOTE_CHAPTER_TITLE = {'es': 'Notas',
                         'en': 'Notes'}
BIBLIOGRAPHY_CHAPTER_ID = 'bibliography'
BIBLIOGRAPHY_CHAPTER_TITLE = {'es': 'Bibliografía',
                              'en': 'Bibliography'}
BACK_MATTER_PART_ID = 'back_matter_part'
BACK_MATTER_PART_FPATH = EPUB_DIR + f'/appendices.{XHTML_FILES_EXTENSION}'
APPENDICES_PART_TITLE = {'es': 'Apéndices',
                         'en': 'Appendices'}
TOC_CHAPTER_TITLE = {'es': 'Índice',
                     'en': 'Table of contents'}
TOC_CHAPTER_ID = 'toc'
NAV_FPATH = EPUB_DIR + f'/nav.{XHTML_FILES_EXTENSION}'

CHAPTER_HEADER_HTML = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
<title>{title}</title>
</head>\n'''

CHAPTER_SECTION_LINE = '''<section epub:type="{epub_type}" id="{section_id}" class="{epub_type}">
<span id="nav_span_{section_id}">&#160;</span>
'''

NCX_HEADER_XML = '''<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'''
NCX_FPATH = os.path.join(EPUB_DIR, 'toc.ncx')

OPF_HEADER_XML = '''<?xml version='1.0' encoding='utf-8'?>
<package unique-identifier="id" version="3.0" xmlns="http://www.idpf.org/2007/opf" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
'''
OPF_FPATH = os.path.join(EPUB_DIR, 'content.opf')


def _get_epub_fpath_for_endnote_chapter():
    return EPUB_DIR + f'/endnotes.{XHTML_FILES_EXTENSION}'


def _get_epub_fpath_for_bibliography_chapter():
    return EPUB_DIR + f'/bibliography.{XHTML_FILES_EXTENSION}'


def _get_epub_fpath_for_toc_chapter():
    return EPUB_DIR + f'/toc.{XHTML_FILES_EXTENSION}'


def _create_epub_fpath_for_section(section):
    if section.kind == CHAPTER:
        if section.id == ENDNOTE_CHAPTER_ID:
            fpath_in_epub = _get_epub_fpath_for_endnote_chapter()
        elif section.id == BIBLIOGRAPHY_CHAPTER_ID:
            fpath_in_epub = _get_epub_fpath_for_bibliography_chapter()
        elif section.id == TOC_CHAPTER_ID:
            fpath_in_epub =  _get_epub_fpath_for_toc_chapter()
        else:
            fpath_in_epub = EPUB_DIR + f'/chapter_{section.idx}.{XHTML_FILES_EXTENSION}'
    elif section.kind == PART:
        fpath_in_epub = EPUB_DIR + f'/part_{section.idx}.{XHTML_FILES_EXTENSION}'
    elif section.kind == SUBCHAPTER:
        fpath_in_epub = EPUB_DIR + f'/chapter_{section.parent.idx}.{XHTML_FILES_EXTENSION}'
    else:
        raise ValueError(f'No fpath defined for this kind of section: {section.kind}')
    return fpath_in_epub


_NUM_FOOTNOTES_AND_CITATIONS_SEEN = Counter()
_FOOTNOTE_IDS_SEEN = defaultdict(set)
_CITATION_COUNTS = defaultdict(Counter)
_FOOTNOTE_DEFINITION_ID_COUNTS = defaultdict(Counter)


def _footnote_processor(footnote, endnote_chapter_fpath, book):
    footnote_id = footnote['match'].group('id')
    book_id = id(book)

    if footnote_id in _FOOTNOTE_IDS_SEEN[book_id]:
        raise RuntimeError('Repeated footnote ID: ' + footnote_id)
    _FOOTNOTE_IDS_SEEN[book_id].add(footnote_id)
    _NUM_FOOTNOTES_AND_CITATIONS_SEEN[book_id] += 1

    fpath = os.path.join('..', endnote_chapter_fpath)
    href_to_footnote_definition = f'{fpath}#ftd_{footnote_id}'
    a_id = f'ft_{footnote_id}'

    text = f'<a id="{a_id}" href="{href_to_footnote_definition}" role="doc-noteref" epub:type="noteref">{_NUM_FOOTNOTES_AND_CITATIONS_SEEN[book_id]}</a>'
    return {'processed_text': text,
            'match_location': footnote['match'].span()[0],
            'footnote_id': footnote_id}


def _footnote_definition_processor(footnote_definition,
                                   fpath_for_section_in_epub, book):
    footnote_id = footnote_definition['match'].group('id')
    book_id = id(book)
    _FOOTNOTE_DEFINITION_ID_COUNTS[book_id][footnote_id] += 1
    if _FOOTNOTE_DEFINITION_ID_COUNTS[book_id][footnote_id] > 1:
        raise RuntimeError('More than one footnote definition for footnote ID: ' + footnote_id)

    li_id = f'ftd_{footnote_id}'
    content = footnote_definition['match'].group('content').strip()
    text = f'<li id= "{li_id}" role="doc-endnote"><p>{content}</p></li>'

    return {'footnote_definition_li': text,
            'footnote_id': footnote_id}


def _citation_processor(citation, bibliography_chapter_fpath,
                        fpath_for_section_in_epub,
                        endnote_chapter_fpath,
                        bibliography_entries_seen,
                        book):

    bibliography_db = book.bibliography_db
    if bibliography_db is None:
        msg = 'No bibliography defined in metadata, but citations are used'
        raise ValueError(msg)

    book_id = id(book)
    citation_id = citation['match'].group('id')
    _CITATION_COUNTS[book_id][citation_id] += 1
    footnote_id = f'{citation_id}_{_CITATION_COUNTS[book_id][citation_id]}'
    _NUM_FOOTNOTES_AND_CITATIONS_SEEN[book_id] += 1

    fpath = os.path.join('..', endnote_chapter_fpath)
    href_to_footnote_definition = f'{fpath}#ftd_{footnote_id}'
    a_id = f'ft_{footnote_id}'

    text = f'<a id="{a_id}" href="{href_to_footnote_definition}" role="doc-noteref" epub:type="noteref">{_NUM_FOOTNOTES_AND_CITATIONS_SEEN[book_id]}</a>'

    footnote_definition_content = create_citation_note(bibliography_db,
                                                       citation_id)
    li_id = f'ftd_{footnote_id}'
    back_href_to_footnote = f'{fpath_for_section_in_epub}#ft_{footnote_id}'
    footnote_definition_text = f'<li id= "{li_id}" role="doc-endnote"><p>{footnote_definition_content}</p></li>'

    bibliography_entries_seen.add(citation_id)

    return {'footnote_definition_li': footnote_definition_text,
            'processed_text': text,
            'match_location': citation['match'].span()[0]}


def _internal_link_processor(internal_link, book):
    text = internal_link['match'].group('text')
    link_id = internal_link['match'].group('link_id')
    section = book.get_section_by_id(link_id)
    fname = Path(_create_epub_fpath_for_section(section)).name
    link = fname

    link = _build_link(link, text, id_=section.id, no_id=True)
    return {'processed_text': link}


def _get_citation_location_in_text(footnote_definition, footnote_locations):
    if 'match_location' in footnote_definition:
        return footnote_definition['match_location']
    else:
        return footnote_locations[footnote_definition['footnote_id']]


def _split_md_text_in_items(md_text):

    # This algorithm has one limitation, it does not allow to have trees
    # it can only yield a stream of items, but not items within an item

    footnote_re = re.compile(r' *\[\^(?P<id>[^\]]+)\]')
    footnote_definition_re = re.compile(r'\[\^(?P<id>[^\]]*)\]:(?P<content>[^\n]+)')
    citation_re = re.compile(r' *\[@(?P<id>[^\],]+),? *(?P<locator_term>[\w]*) *(?P<locator_positions>[0-9]*)\]', re.UNICODE)
    internal_link_re = re.compile(r'\[(?P<text>[^\]]+)\]\(#(?P<link_id>[^\)]+)\)')

    item_kinds = OrderedDict([('footnote_definition', {'re': footnote_definition_re}),
                              ('footnote', {'re': footnote_re}),
                              ('citation', {'re': citation_re}),
                              ('internal_link', {'re': internal_link_re}),
                              ])
    re_idx = {item_kind: idx for idx, item_kind in enumerate(item_kinds.keys())}

    start_pos_to_search = 0
    while True:
        matches = []
        for kind, item_def in item_kinds.items():
            match = item_def['re'].search(md_text, start_pos_to_search)
            if match is None:
                continue
            matches.append({'kind': kind, 'match': match})
        if matches:
            matches.sort(key=lambda match: re_idx[match['kind']])
            matches.sort(key=lambda match: match['match'].start())
            next_match = matches[0]['match']
            kind = matches[0]['kind']
        else:
            yield {'kind': 'std_md',
                   'text': md_text[start_pos_to_search:]}
            break

        if start_pos_to_search < next_match.start():
            yield {'kind': 'std_md',
                   'text': md_text[start_pos_to_search:next_match.start()]}
        yield {'kind': kind,
               'text': md_text[next_match.start():next_match.end()],
               'match': next_match}
        start_pos_to_search = next_match.end()

        if start_pos_to_search >= len(md_text):
            break


def _process_citations_and_footnotes(md_text,
                                     section):
    items = _split_md_text_in_items(md_text)

    bibliography_entries_seen = set()
    footnote_definitions = []

    fpath_for_section_in_epub = _create_epub_fpath_for_section(section)
    #split_text_in_items, item kinds: std_markdown, citation, footnote, footnote_definition,
    item_processors = {'footnote': partial(_footnote_processor,
                                           endnote_chapter_fpath=_get_epub_fpath_for_endnote_chapter(),
                                           book=section.book),
                       'footnote_definition': partial(_footnote_definition_processor,
                                                      fpath_for_section_in_epub=fpath_for_section_in_epub,
                                                      book=section.book),
                       'citation': partial(_citation_processor,
                                           fpath_for_section_in_epub=fpath_for_section_in_epub,
                                           endnote_chapter_fpath=_get_epub_fpath_for_endnote_chapter(),
                                           bibliography_chapter_fpath=_get_epub_fpath_for_bibliography_chapter(),
                                           bibliography_entries_seen=bibliography_entries_seen,
                                           book=section.book),
                        'internal_link': partial(_internal_link_processor,
                                                 book=section.book)
                      }
    processed_text = []
    debug_item = 'citation'
    debug_item = None
    footnote_locations = {}
    for item in items:
        processor = item_processors.get(item['kind'], None)
        if debug_item and item['kind'] == debug_item:
            pprint(item)
        if processor:
            processed_item = processor(item)
            if 'processed_text' in processed_item:
                text = processed_item['processed_text']
            else:
                text = None
        else:
            processed_item = None
            text = item['text']
        if debug_item and item['kind'] == debug_item:
            print('text', text)

        if processed_item and 'footnote_definition_li' in processed_item:
            definition = {'footnote_definition_li': processed_item['footnote_definition_li']}
            if 'match_location' in processed_item:
                definition['match_location'] = processed_item['match_location']
            if 'footnote_id' in processed_item:
                definition['footnote_id'] = processed_item['footnote_id']
            footnote_definitions.append(definition)

        if item['kind'] == 'footnote':
            footnote_locations[processed_item['footnote_id']] = processed_item['match_location']

        if text is not None:
            processed_text.append(text)

    get_citation_location_in_text = partial(_get_citation_location_in_text,
                                            footnote_locations=footnote_locations)
    footnote_definitions.sort(key=get_citation_location_in_text)

    return {'rendered_text': ''.join(processed_text),
            'footnote_definitions': footnote_definitions,
            'bibliography_entries_seen': bibliography_entries_seen
            }


def _process_basic_markdown(md_text):
    renderer = mistune.Renderer(use_xhtml=True)
    render_markdown = mistune.Markdown(renderer)
    xhtml_text = render_markdown(md_text)
    xhtml_text = xhtml_text.replace('&lt;', '<').replace('&gt;', '>')
    assert '<h' not in xhtml_text
    return xhtml_text


def _process_md_text(md_text, section):
    md_text = '\n'.join(md_text)

    result = _process_citations_and_footnotes(md_text=md_text,
                                              section=section)
    result['rendered_lines'] = _process_basic_markdown(result['rendered_text'])
    return result


def _split_section_in_fragments(lines):
    fragment_lines = []
    for line in lines:
        if line.startswith('#'):
            if fragment_lines:
                yield {'kind': 'fragment',
                       'lines': fragment_lines}
            fragment_lines = []
            yield {'kind': 'header',
                   'text': line}
        else:
            fragment_lines.append(line)
    if fragment_lines:
        yield {'kind': 'fragment',
               'lines': fragment_lines}


def _create_html_for_md_text_in_section(section):
    md_text = section.md_text

    rendered_lines = []
    footnote_definitions = []
    bibliography_entries_seen = set()

    for fragment in _split_section_in_fragments(md_text):
        if fragment['kind'] == 'header':
            text = fragment['text']
            res = _parse_header_line(text)
            header = f'<h{res["level"]}>{res["text"]}</h{res["level"]}>\n'
            rendered_lines.append(header)
        elif fragment['kind'] == 'fragment':
            result = _process_md_text(fragment['lines'], section=section)
            rendered_lines.append(result['rendered_lines'])
            footnote_definitions.extend(result['footnote_definitions'])
            bibliography_entries_seen.update(result['bibliography_entries_seen'])
    result = {'rendered_lines': rendered_lines,
              'footnote_definitions': footnote_definitions,
              'bibliography_entries_seen': bibliography_entries_seen}
    return result


def _write_html_in_zip_file(epub_zip, fpath, html):
    #soup = BeautifulSoup(html, features='lxml')
    #pretty_html = soup.prettify(formatter=None)
    epub_zip.writestr(fpath, html)


def _create_chapter(chapter, epub_zip):

    res = _create_html_for_md_text_in_section(chapter)
    html = '\n'.join(res['rendered_lines'])
    footnote_definitions = res['footnote_definitions']
    bibliography_entries_seen = res['bibliography_entries_seen']

    for subchapter in chapter.subsections:
        html += CHAPTER_SECTION_LINE.format(epub_type='subchapter',
                                            section_id=subchapter.id)
        res = _create_html_for_md_text_in_section(subchapter)
        html += '\n'.join(res['rendered_lines'])
        html += '</section>\n'
        footnote_definitions.extend(res['footnote_definitions'])
        bibliography_entries_seen.update(res['bibliography_entries_seen'])

    _create_section_xhtml_file(title=chapter.title,
                               id_=chapter.id,
                               section_html=html,
                               fpath=_create_epub_fpath_for_section(chapter),
                               epub_type='chapter',
                               epub_zip=epub_zip)

    result = {'footnote_definitions': footnote_definitions,
              'bibliography_entries_seen': bibliography_entries_seen}
    return result


def _create_section_xhtml_file(title, id_, section_html, fpath, epub_type,
                               epub_zip):
    html = CHAPTER_HEADER_HTML.format(title=title)
    html += '<body>\n'
    html += CHAPTER_SECTION_LINE.format(epub_type=epub_type,
                                        section_id=id_)
    html += section_html
    html += '</section>\n'
    html += '</body>\n'
    html += '</html>\n'
    _write_html_in_zip_file(epub_zip, fpath, html)


def _create_part(part, epub_zip):
    title = part.title
    part_id = part.id
    fpath = _create_epub_fpath_for_section(part)

    result = _create_html_for_md_text_in_section(part)
    section_html = '\n'.join(result['rendered_lines'])
    footnote_definitions = result['footnote_definitions']
    bibliography_entries_seen = result['bibliography_entries_seen']

    _create_section_xhtml_file(title=title,
                               id_=part_id,
                               section_html=section_html,
                               fpath=fpath,
                               epub_type='part',
                               epub_zip=epub_zip)

    for chapter in part.subsections:
        if chapter.kind == CHAPTER:
            res = _create_chapter(chapter, epub_zip)
        else:
            raise RuntimeError('A part should only have chapters as subparts.')
        footnote_definitions.extend(res['footnote_definitions'])
        bibliography_entries_seen.update(res['bibliography_entries_seen'])

    result = {'footnote_definitions': footnote_definitions,
              'bibliography_entries_seen': bibliography_entries_seen}
    return result


def _create_endnotes_section_html(endnote_definitions):

    html = '<ol role="doc-endnotes">'
    for endnote_definition in endnote_definitions:
        html += endnote_definition['footnote_definition_li']
    html += '</ol>\n'
    return html


def _create_endnotes_chapter(chapter, endnote_definitions, header_level,
                             epub_zip):
    html = f'  <h{header_level}>{chapter.title}</h{header_level}>\n'
    html += _create_endnotes_section_html(endnote_definitions)

    _create_section_xhtml_file(title=chapter.title,
                               id_=chapter.id,
                               section_html=html,
                               fpath=_create_epub_fpath_for_section(chapter),
                               epub_type=chapter.kind,
                               epub_zip=epub_zip)


def _create_bibliography_section_html(bibliography_entries, book):
    htmls = []
    for bibliography_id in bibliography_entries:
        citation_html = create_bibliography_citation(book.bibliography_db,
                                                     bibliography_id)
        htmls.append(citation_html)
    htmls.sort()

    html = '<ul role="Bibliography">'
    for html_li in htmls:
        html += f'<li>{html_li}</li>'
    html += '</ul>\n'
    return html


def _create_bibliography_chapter(chapter, bibliography_entries, header_level,
                                 epub_zip):

    html = f'  <h{header_level}>{chapter.title}</h{header_level}>\n'
    html += _create_bibliography_section_html(bibliography_entries,
                                              chapter.book)

    _create_section_xhtml_file(title=chapter.title,
                               id_=chapter.id,
                               section_html=html,
                               fpath=_create_epub_fpath_for_section(chapter),
                               epub_type=chapter.kind,
                               epub_zip=epub_zip)


def _build_link(link, text, id_=None, for_nav=False):
    if id_ and not for_nav:
        li = f'<a href="{link}#nav_span_{id_}">{text}</a>'
        #li = f'<a href="{link}">{text}</a>'
    else:
        li = f'<a href="{link}">{text}</a>'
    return li


def _build_nav_li_to_section(section, for_nav):
    try:
        has_no_html = section.has_no_html
    except AttributeError:
        has_no_html = False

    if section.kind == PART and has_no_html:
        section_fpath = None
    else:
        section_fpath = os.path.join('..',  _create_epub_fpath_for_section(section))
        #section_fpath = os.path.join(_create_epub_fpath_for_section(section))
        section_fname = os.path.basename(_create_epub_fpath_for_section(section))

    if section_fpath:
        li = _build_link(section_fname,
                         text=section.title,
                         id_=section.id,
                         for_nav=for_nav)
    else:
        li = f'<span>{section.title}</span>'
    return li


def _build_nav_for_chapter(chapter, for_nav):
    li = _build_nav_li_to_section(chapter, for_nav=for_nav)
    subchapters = list(chapter.subsections)

    if subchapters:
        html = f'<li>{li}\n'
        html += '<ol>\n'
        for subchapter in subchapters:
            li = _build_nav_li_to_section(subchapter, for_nav=False)
            html += f'<li>{li}</li>\n'
        html += '</ol></li>\n'
    else:
        html = f'<li>{li}</li>\n'
    return html


def _create_toc_section_html(book, for_nav=False):

    html = '<nav epub:type="toc">\n'
    html += f'<h1>{TOC_CHAPTER_TITLE[book.lang]}</h1>\n'
    html += '<ol>\n'

    for section in book.subsections:
        if section.kind == PART:
            li = _build_nav_li_to_section(section, for_nav=for_nav)
            html += f'<li>{li}\n'
            html += '<ol>\n'
            for chapter in section.subsections:
                html += _build_nav_for_chapter(chapter, for_nav=for_nav)
            html += '</ol></li>\n'
        elif section.kind == CHAPTER:
            html += _build_nav_for_chapter(section, for_nav=for_nav)

    html += '</ol>\n'
    html += '</nav>\n'
    return html


def _create_toc_chapter(toc_chapter, header_level, epub_zip):

    _create_section_xhtml_file(title=toc_chapter.title,
                               id_=toc_chapter.id,
                               section_html=_create_toc_section_html(toc_chapter.book),
                               fpath=_get_epub_fpath_for_toc_chapter(),
                               epub_type=toc_chapter.kind,
                               epub_zip=epub_zip)


def _creata_nav(book, epub_zip):
    html = NAV_HEADER_XML.format(title=book.title)
    html += '<section>\n'

    html += _create_toc_section_html(book, for_nav=True)

    html += '</section>\n'
    html += '</body>\n'
    html += '</html>\n'
    _write_html_in_zip_file(epub_zip, NAV_FPATH, html)


def _build_nav_point_xml_for_section(section, play_order, level):

    fpath = _create_epub_fpath_for_section(section)
    fname = os.path.basename(fpath)
    span_id = f'nav_span_{section.id}'

    nbsps_for_nested = NBSP * (level - 1)
    if section.kind in [PART, CHAPTER]:
        return f'''<navPoint class="{section.kind}" id="{section.id}" playOrder="{play_order}">
  <navLabel>
    <text>{nbsps_for_nested}{section.title}</text>
  </navLabel>
  <content src="{fname}" />
</navPoint>'''
    else:
        return f'''<navPoint id="{section.id}" playOrder="{play_order}">
<navLabel>
<text>{nbsps_for_nested}{section.title}</text>
</navLabel>
<content src="{fname}#{span_id}" />
</navPoint>'''


def _create_ncx(book, epub_zip):
    html = NCX_HEADER_XML
    html += '<head>\n'
    html += f'<meta content="{book.metadata["uid"]}" name="dtb:uid"/>\n'
    html += '</head>\n'
    html += f'<docTitle> <text>{book.title}</text> </docTitle>\n'
    html += '<navMap>\n'

    # Do not use nested navPoints because some ebook do not support them
    # Use &nbsp; to simulate nesting

    play_order = 1
    for section in book.subsections:
        if section.kind == PART:
            if not section.has_no_html:
                html += _build_nav_point_xml_for_section(section, play_order, 1)
                play_order += 1
            for chapter in section.subsections:
                html += _build_nav_point_xml_for_section(chapter, play_order, 2)
                play_order += 1
                for subchapter in chapter.subsections:
                    html += _build_nav_point_xml_for_section(subchapter, play_order, 3)
                    play_order += 1
        elif section.kind == CHAPTER:
            html += _build_nav_point_xml_for_section(section, play_order, 1)
            play_order += 1
            for subchapter in section.subsections:
                html += _build_nav_point_xml_for_section(subchapter, play_order, 2)
                play_order += 1

    html += '</navMap>'
    html += '</ncx>'
    _write_html_in_zip_file(epub_zip, NCX_FPATH, html)


def _create_epub_backbone(epub_zip):
    epub_zip.writestr(CONTAINER_XML_FPATH, CONTAINER_XML)


def _create_mimetype_file(epub_zip):
    epub_zip.writestr('mimetype', b'application/epub+zip')


def _create_opf(book, epub_zip):
    xml = OPF_HEADER_XML

    now = datetime.datetime.utcnow().isoformat(timespec='seconds')
    xml += f'<meta property="dcterms:modified">{now}Z</meta>\n'
    xml += f'<dc:identifier id="id">{book.metadata["uid"]}</dc:identifier>\n'
    xml += f'<dc:title>{book.title}</dc:title>\n'
    xml += f'<dc:language>{book.lang}</dc:language>\n'
    for author in book.metadata['author']:
        xml += f'<dc:creator id="creator">{author}</dc:creator>\n'
    xml += '</metadata>\n'

    xml += '<manifest>\n'

    item_xml = '<item href="{fname}" id="{id}" media-type="application/xhtml+xml" />\n'

    spine = [TOC_CHAPTER_ID]
    xml += item_xml.format(fname=os.path.basename(_get_epub_fpath_for_toc_chapter()),
                           id='toc')

    for section in book.subsections:
        if section.kind == PART:
            if not section.has_no_html:
                spine.append(section.id)
                fname = os.path.basename(_create_epub_fpath_for_section(section))
                xml += item_xml.format(fname=fname, id=section.id)
            for chapter in section.subsections:
                spine.append(chapter.id)
                fname = os.path.basename(_create_epub_fpath_for_section(chapter))
                xml += item_xml.format(fname=fname, id=chapter.id)
        elif section.kind == CHAPTER:
            spine.append(section.id)
            fname = os.path.basename(_create_epub_fpath_for_section(section))
            xml += item_xml.format(fname=fname, id=section.id)

    fname = os.path.basename(NCX_FPATH)
    xml += f'<item href="{fname}" id="ncx" media-type="application/x-dtbncx+xml" />\n'
    fname = os.path.basename(NAV_FPATH)
    xml += f'<item href="{fname}" id="nav" media-type="application/xhtml+xml" properties="nav" />\n'

    xml += '</manifest>\n'

    xml += '<spine toc="ncx">\n'
    for chapter_id in spine:
        xml += f'<itemref idref="{chapter_id}"/>\n'
    xml += '</spine>\n'

    xml += '<guide>\n'
    title = TOC_CHAPTER_TITLE[book.lang]
    fname = os.path.basename(_get_epub_fpath_for_toc_chapter())
    xml += f'<reference type="toc" title="{title}" href="{fname}" />\n'
    xml += '</guide>\n'
    xml += '</package>\n'

    _write_html_in_zip_file(epub_zip, OPF_FPATH, xml)


def create_epub(book, epub_path):
    with zipfile.ZipFile(epub_path, 'w') as epub_zip:
        _create_mimetype_file(epub_zip)
        _create_epub_backbone(epub_zip)

        endnote_definitions = []
        bibliography_entries_seen = set()
        for section in book.subsections:
            if section.kind == CHAPTER:
                res = _create_chapter(section, epub_zip)
            elif section.kind == PART:
                res = _create_part(section, epub_zip)
            elif section.kind == BOOK:
                raise ValueError('A book should not include a subsection of kind BOOK')
            elif section.kind == SUBCHAPTER:
                raise ValueError('A book should not include a subsection of kind SUBCHAPTER')
            else:
                assert False
            endnote_definitions.extend(res['footnote_definitions'])
            bibliography_entries_seen.update(res['bibliography_entries_seen'])

        if (endnote_definitions or bibliography_entries_seen) and book.has_parts():
            back_matter_part = BookSectionWithNoFiles(parent=book,
                                                      id_=BACK_MATTER_PART_ID,
                                                      title=APPENDICES_PART_TITLE[book.lang],
                                                      kind=PART)
            back_matter_part.has_no_html = True
            book.subsections.append(back_matter_part)
            parent = back_matter_part
        else:
            back_matter_part = None
            parent = book

        toc_level_for_appendix_chapters = 2 if book.has_parts() else 1


        if endnote_definitions:
            endnotes_chapter = BookSectionWithNoFiles(parent=parent,
                                                      id_=ENDNOTE_CHAPTER_ID,
                                                      title=ENDNOTE_CHAPTER_TITLE[book.lang],
                                                      kind=CHAPTER)
            parent.subsections.append(endnotes_chapter)
            _create_endnotes_chapter(endnotes_chapter,
                                     endnote_definitions,
                                     header_level=toc_level_for_appendix_chapters,
                                     epub_zip=epub_zip)
        if bibliography_entries_seen:
            chapter = BookSectionWithNoFiles(parent=parent,
                                             id_=BIBLIOGRAPHY_CHAPTER_ID,
                                             title=BIBLIOGRAPHY_CHAPTER_TITLE[book.lang],
                                             kind=CHAPTER)
            parent.subsections.append(chapter)
            _create_bibliography_chapter(chapter,
                                         bibliography_entries_seen,
                                         header_level=toc_level_for_appendix_chapters,
                                         epub_zip=epub_zip)

        toc_chapter = BookSectionWithNoFiles(parent=book,
                                             id_=TOC_CHAPTER_ID,
                                             title=TOC_CHAPTER_TITLE[book.lang],
                                             kind=TOC)
        _create_toc_chapter(toc_chapter,
                            header_level=1,
                            epub_zip=epub_zip)
        book.subsections.insert(0, toc_chapter)

        _creata_nav(book, epub_zip=epub_zip)

        _create_ncx(book, epub_zip=epub_zip)

        _create_opf(book, epub_zip=epub_zip)

    check_epub(epub_path)


def unzip_epub(ebook_path, out_dir):

    if out_dir.exists():
        shutil.rmtree(out_dir)

    with zipfile.ZipFile(ebook_path) as epubzip:
        epubzip.extractall(path=out_dir)


def check_epub(ebook_path):
    cmd = ['java', '-jar', EPUBCHECK_JAR, str(ebook_path)]
    completed_process = subprocess.run(cmd, capture_output=True)

    if completed_process.returncode:
        sys.stdout.write(completed_process.stdout.decode())
        sys.stderr.write(completed_process.stderr.decode())
