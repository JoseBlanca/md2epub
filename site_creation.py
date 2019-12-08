
from pprint import pprint
import re
from collections import OrderedDict, defaultdict
import zipfile
from pathlib import Path
import datetime
import subprocess
import sys
import os

import mistune

from references import process_citations
from book_section import (BOOK, CHAPTER, PART, SUBCHAPTER,
                          _parse_header_line,
                          SpecialSection)

this_module_dir = Path(os.path.dirname(os.path.abspath(__file__)))

EPUBCHECK_JAR = 'epubcheck-4.0.2/epubcheck.jar'
EPUBCHECK_JAR = 'epubcheck-4.2.2/epubcheck.jar'
EPUBCHECK_JAR = this_module_dir / EPUBCHECK_JAR

EPUB3 = 'epub3'
HTML = 'html'
SUPPORTED_SITE_KINDS = [EPUB3, HTML]

EPUB_META_DIR = Path('META-INF')

CONTAINER_XML_FPATH = EPUB_META_DIR / 'container.xml'
CONTAINER_XML = '''<?xml version='1.0' encoding='utf-8'?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile media-type="application/oebps-package+xml" full-path="EPUB/content.opf"/>
  </rootfiles>
</container>'''

NBSP = '&#160;'
BACK_ARROW = '&#8592;'

BLOCKQUOTE_RE = re.compile('^<blockquote>[\n ]*<p>[^<>]*</p>[\n ]*</blockquote>$')

XHTML_FILES_EXTENSION = 'xhtml'
HTML_FILES_EXTENSION = 'html'
EPUB_CHAPTER_DIR = Path('EPUB')
HTML_CHAPTER_DIR = Path('section')

ENDNOTE_CHAPTER_ID = 'endnotes'
ENDNOTE_CHAPTER_BASE_NAME = 'endnotes'
ENDNOTE_CHAPTER_TITLE = {'es': 'Notas',
                         'en': 'Notes'}

BIBLIOGRAPHY_CHAPTER_ID = 'bibliography'
BIBLIOGRAPHY_CHAPTER_BASE_NAME = 'bibliography'
BIBLIOGRAPHY_CHAPTER_TITLE = {'es': 'Bibliografía',
                              'en': 'Bibliography'}

TOC_CHAPTER_ID = 'toc'
TOC_CHAPTER_BASE_NAME = 'toc'
TOC_CHAPTER_TITLE = {'es': 'Índice',
                     'en': 'Table of contents'}

EPUB_CHAPTER_HEADER_HTML = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
<title>{title}</title>
</head>\n'''
EPUB_START_CHAPTER_SECTION = '''<section epub:type="{epub_type}" id="{section_id}" class="{epub_type}">
<span id="nav_span_{section_id}">&#160;</span>
'''
EPUB_END_CHAPTER_SECTION = '</section>\n'
HTML_CHAPTER_HEADER_HTML = '''<!DOCTYPE html>
<head>
<title>{title}</title>
</head>\n'''
HTML_START_CHAPTER_SECTION = '''<div id="{section_id}" class="{epub_type}">
<span id="nav_span_{section_id}">&#160;</span>
'''
HTML_END_CHAPTER_SECTION = '</div>\n'

NAV_BASE_NAME = 'nav'
NAV_HEADER_XML = '''<?xml version='1.0' encoding='utf-8'?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head>
<title>{title}</title>
</head>
<body>
'''
NCX_FNAME = 'toc.ncx'
NCX_HEADER_XML = '''<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'''
OPF_FNAME = 'content.opf'
OPF_HEADER_XML = '''<?xml version='1.0' encoding='utf-8'?>
<package unique-identifier="id" version="3.0" xmlns="http://www.idpf.org/2007/opf" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
'''


def _itemize_fragment(md_text):

    # This algorithm has one limitation, it does not allow to have trees
    # it can only yield a stream of items, but not items within an item

    footnote_re = re.compile(r' *\[\^(?P<id>[^\]]+)\]')
    footnote_definition_re = re.compile(r'\[\^(?P<id>[^\]]*)\]:(?P<content>[^\n]+)')
    citation_re = re.compile(r' *\[@(?P<id>[^ \],]+),? *(?P<locator_term>[\w]*):? *(?P<locator_positions>[0-9]*)\]', re.UNICODE)
    internal_link_re = re.compile(r'\[(?P<text>[^\]]+)\]\(#(?P<link_id>[^\)]+)\)')

    item_kinds = OrderedDict([('paragraph_limit', {'re': re.compile('\n{2,}')}),
                              ('footnote_definition', {'re': footnote_definition_re}),
                              ('footnote', {'re': footnote_re}),
                              ('citation', {'re': citation_re}),
                              ('internal_link', {'re': internal_link_re}),
                              ])
    re_idx = {item_kind: idx for idx, item_kind in enumerate(item_kinds.keys())}

    debug_text = '@CosmosSeEstreno2012'
    debug_text = None

    if debug_text and debug_text in md_text:
        print('md_text')
        pprint(md_text)
        debug = True
    else:
        debug = False

    start_pos_to_search = 0
    while True:
        matches = []
        text_in_which_to_search = md_text[start_pos_to_search:]
        if debug:
            print('text_in_which_to_search')
            print(text_in_which_to_search)
        for kind, item_def in item_kinds.items():
            match = item_def['re'].search(text_in_which_to_search)
            if match is None:
                continue
            matches.append({'kind': kind, 'match': match})
        if matches:
            matches.sort(key=lambda match: re_idx[match['kind']])
            matches.sort(key=lambda match: match['match'].start())
            next_match = matches[0]['match']
            kind = matches[0]['kind']
            if debug:
                print('matches')
                pprint(matches)
        else:
            yield {'kind': 'std_md',
                   'md_orig_main_text': md_text[start_pos_to_search:]}
            break

        next_match_start = next_match.start() + start_pos_to_search
        next_match_end = next_match.end() + start_pos_to_search
        if start_pos_to_search < next_match_start:
            res = {'kind': 'std_md',
                   'md_orig_main_text': md_text[start_pos_to_search:next_match_start]}
            if debug:
                print('start_pos_to_search < next_match_start', start_pos_to_search, next_match_start)
                print('yield result')
                pprint(res)
            yield res

        res = {'kind': kind,
               'md_orig_main_text': md_text[next_match_start:next_match_end],
               'match': next_match}
        if debug:
            print('yielding in last yield')
            pprint(res)
        yield res
        start_pos_to_search = next_match_end

        if start_pos_to_search >= len(md_text):
            break


def _join_fragment_lines(fragment_lines):
    fragment = ''.join(fragment_lines).strip()

    fragment = re.sub('\n>', '\n\n>', fragment)
    return fragment


def _itemize_md_text(md_text):

    fragment_lines = []
    for line in md_text:

        if line.startswith('#'):
            if fragment_lines:
                for item in _itemize_fragment(_join_fragment_lines(fragment_lines)):
                    if item['kind'] == 'std_md':
                        assert '\n\n' not in item['md_orig_main_text']
                    yield item
            fragment_lines = []
            yield {'kind': 'header',
                   'md_orig_main_text': line}
        else:
            fragment_lines.append(line)

    if fragment_lines:
        for item in _itemize_fragment(_join_fragment_lines(fragment_lines)):
            if item['kind'] == 'std_md':
                assert '\n\n' not in item['md_orig_main_text']
            yield item


def _add_p_tags(html_text):
    html_text = html_text.strip()

    if html_text.startswith('<ul>') and html_text.endswith('</ul>'):
        return html_text
    if html_text.startswith('<ol>') and html_text.endswith('</ol>'):
        return html_text

    first_close_p_position = None
    try:
        first_open_p_position = html_text.index('<p>')
    except ValueError:
        first_open_p_position = None
    try:
        first_close_p_position = html_text.index('</p>')
    except ValueError:
        first_close_p_position = None

    #print(first_open_p_position, first_close_p_position)
    #print(html_text)

    if first_close_p_position is None and first_open_p_position is None:
        return f'<p>{html_text}</p>\n'

    if first_close_p_position and (first_open_p_position is None or first_open_p_position > first_close_p_position):
        html_text = f'<p>{html_text}'

    last_p_open_position = html_text.rfind('<p>')
    if last_p_open_position < 0:
        last_p_open_position = None
    last_p_close_position = html_text.rfind('</p>')
    if last_p_close_position < 0:
        last_p_close_position = None
    if last_p_close_position and (last_p_close_position is None or last_p_close_position < last_p_open_position):
        html_text = f'{html_text}</p>\n'

    return html_text


class SiteRenderer:
    def __init__(self, md_book, site_kind, zip_path=None, out_dir=None):
        self.book = md_book

        if not(zip_path is not None or out_dir is not None):
            raise ValueError('Either site_path or out_dir should be given')

        if zip_path:
            zip_path = zip_path.resolve()
        self.out_zip_path = zip_path
        self._out_zip = None
        if out_dir:
            out_dir = out_dir.resolve()
        self.out_dir = out_dir

        if site_kind not in SUPPORTED_SITE_KINDS:
            msg = f'site_kind not supported'
            raise NotImplementedError(msg)
        self.site_kind = site_kind
        self._sections_info = defaultdict(dict)

        renderer = mistune.Renderer(use_xhtml=True)
        self._render_markdown = mistune.Markdown(renderer)
        self.citation_notes_should_be_endnotes = True
        self.note_lis = defaultdict(list)
        self.section_main_html = {}
        self._special_sections = {}
        self._references = {}
        self._sections_added = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_details):
        self._close_out_files()

    def _open_out_files(self):
        if self.out_zip_path:
            self._out_zip = zipfile.ZipFile(self.out_zip_path, 'w')
        if self.out_dir:
            self.out_dir.mkdir()

    def _close_out_files(self):
        if self._out_zip:
            self._out_zip.close()

    def _get_sections_and_items(self):
        sections_and_items = []
        for section in self.book.parts_and_chapters:
            section_and_items = {'section': section,
                                 'items': list(_itemize_md_text(section.md_text))}
            sections_and_items.append(section_and_items)
        return sections_and_items

    def _process_citations(self):
        citation_keys_not_found = self.citation_keys_not_found

        for section_and_items in self._sections_and_items:
            citations = [item for item in section_and_items['items'] if item['kind'] == 'citation']

            if citations:
                citation_texts = [citation['md_orig_main_text'] for citation in citations]
                processed_citations = process_citations(citation_texts,
                                                        libray_csl_json_path=self.book.bibliography_path)

                assert len(citations) == len(processed_citations['citation_items'])

                for citation, processed_citation in zip(citations, processed_citations['citation_items']):

                    citation['citation_keys'] = processed_citation['citation_keys']
                    if processed_citation['citations_found']:
                        citation['citations_found'] = True
                        #pprint(processed_citation)
                        if 'footnote_html_text' in processed_citation:
                            citation['footnote_html_text'] = processed_citation['footnote_html_text']
                        in_text_html_text = processed_citation['in_text_html_text'].strip()
                        #print(in_text_html_text)
                        #print(in_text_html_text.startswith('<sup>'), in_text_html_text.endswith('</sup>'))
                        if in_text_html_text.startswith('<sup>') and in_text_html_text.endswith('</sup>'):
                            citation['citation_text_is_note_number'] = True
                        else:
                            citation['html_main_text'] = processed_citation['in_text_html_text']
                        #pprint(citation)
                    else:
                        citation['citations_found'] = False
                        citation_keys_not_found.update(processed_citation['citation_keys'])
                self._references.update(dict(processed_citations['references']))

    @staticmethod
    def _make_dir_tree(path):
        dirs_to_check = list(reversed(path.parents)) + [path]
        for dir_ in dirs_to_check:
            if not dir_.exists():
                dir_.mkdir()
        
    def create_file(self, path, content):

        if self.out_zip_path:
            self._out_zip.writestr(str(path), content)
        if self.out_dir:
            full_path = self.out_dir / path
            self._make_dir_tree(full_path.parent)

            fhand = full_path.open('wt')
            fhand.write(content)
            fhand.close()

    def _create_mimetype_file(self):
        self.create_file('mimetype', 'application/epub+zip')

    def _create_epub_backbone(self):
        self.create_file(CONTAINER_XML_FPATH, CONTAINER_XML)

    def _get_base_path(self):
        if self.site_kind == EPUB3:
            base_path = EPUB_CHAPTER_DIR
        else:
            base_path = HTML_CHAPTER_DIR
        return base_path

    def _get_files_extension(self):
        if self.site_kind == EPUB3:
            extension = XHTML_FILES_EXTENSION
        else:
            extension = HTML_FILES_EXTENSION
        return extension

    def _get_fname_for_section(self, section):
        extension = self._get_files_extension()
        if section.id == ENDNOTE_CHAPTER_ID:
            fname =  f'{ENDNOTE_CHAPTER_BASE_NAME}.{extension}'
        elif section.id == BIBLIOGRAPHY_CHAPTER_ID:
            fname =  f'{BIBLIOGRAPHY_CHAPTER_BASE_NAME}.{extension}'
        elif section.id == TOC_CHAPTER_ID:
            fname =  f'{TOC_CHAPTER_BASE_NAME}.{extension}'
        elif section.kind == CHAPTER:
            fname =  f'chapter_{section.idx}.{extension}'
        elif section.kind == PART:
            fname = f'part_{section.idx}.{extension}'
        else:
            raise ValueError(f'No fpath defined for this kind of section: {section.kind}')
        return fname

    def _create_path_within_site_for_section(self, section):
        base_path = self._get_base_path()
        fname = self._get_fname_for_section(section)
        path_within_site = base_path / fname
        self._sections_info[section.id]['path_within_site'] = path_within_site

    def _get_path_within_site_for_section(self, section):
        if not 'path_within_site' in self._sections_info[section.id]:
            self. _create_path_within_site_for_section(section)
        return self._sections_info[section.id]['path_within_site']

    def get_url_to_section(self, section, id_=None):
        url = '../' + str(self._get_path_within_site_for_section(section))
        if id_:
            url = f'{url}#{id_}'
        return url

    def build_anchor_to_section(self, section, text=None, id_=None,
                                anchor_id=None,
                                is_note_to_ref=False):
        if not text:
            text = section.title
        url = self.get_url_to_section(section, id_=id_)

        if anchor_id:
            anchor_id_str = f'id="{anchor_id}"'
        else:
            anchor_id_str = ''

        if self.site_kind == EPUB3 and is_note_to_ref:
            anchor = f'<a {anchor_id_str} epub:type="noteref" href="{url}">{text}</a>'
        else:
            anchor = f'<a {anchor_id_str} href="{url}">{text}</a>'
        return anchor

    def _get_special_section(self, section_id):
        if section_id in self._special_sections:
            return self._special_sections[section_id]
        
        if section_id == ENDNOTE_CHAPTER_ID:
            section = SpecialSection(kind=CHAPTER,
                                     title=ENDNOTE_CHAPTER_TITLE[self.book.lang],
                                     id=section_id,
                                     parent=self.book
                                     )
        elif section_id == BIBLIOGRAPHY_CHAPTER_ID:
            section = SpecialSection(kind=CHAPTER,
                                     title=BIBLIOGRAPHY_CHAPTER_TITLE[self.book.lang],
                                     id=section_id,
                                     parent=self.book
                                     )
        elif section_id == TOC_CHAPTER_ID:
            section = SpecialSection(kind=CHAPTER,
                                     title=TOC_CHAPTER_TITLE[self.book.lang],
                                     id=section_id,
                                     parent=self.book
                                     )
        else:
            raise ValueError(f'Unknown special section {section_id}')
        self._special_sections[section_id] = section
        return section

    def _process_basic_markdown(self, md_text):
        html_text = self._render_markdown(md_text)
        html_text = html_text.strip()

        if html_text.startswith('<p>'):
            html_text = html_text[3:]
        if html_text.endswith('</p>'):
            html_text = html_text[:-4]

        assert '&lt;' not in html_text
        #print('html_text', html_text)
        assert '<h' not in html_text
        return html_text
    
    def _create_html_from_items(self, items, section=None):

        if self.citation_notes_should_be_endnotes:
            section_to_add_citation_notes = self._get_special_section(ENDNOTE_CHAPTER_ID)
            note_lis = self.note_lis[section_to_add_citation_notes.id]
        else:
            raise NotImplementedError('Implement notes at the end of chapter')

        citations_not_found = set()
        htmls = []
        paragraph = ''
        for item in items:
            #print('item')
            #pprint(item)
            if item['kind'] == 'header':
                paragraph = paragraph.strip()
                if paragraph:
                    htmls.append(_add_p_tags(paragraph))
                    paragraph = ''
                res = _parse_header_line(item['md_orig_main_text'])
                html_item_text = f'<h{res["level"]}>{res["text"]}</h{res["level"]}>\n'
                htmls.append(html_item_text)
            elif item['kind'] == 'std_md':
                paragraph += self._process_basic_markdown(item['md_orig_main_text'])
            elif item['kind'] == 'citation':
                note_id_in_text = f'citation_{len(note_lis) + 1}'
                if item['citations_found']:
                    if item.get('footnote_html_text'):
                        endnote_id = f'{section_to_add_citation_notes.id}_{len(note_lis) + 1}'
                        epub_type = 'epub:type="endnote" ' if self.site_kind == EPUB3 else ''
                        endnote_li = f'<span {epub_type}id="{endnote_id}">{item["footnote_html_text"]}</span>'
                        endnote_li += self.build_anchor_to_section(section, text=BACK_ARROW, id_=note_id_in_text)
                        note_lis.append(endnote_li)
                    else:
                        endnote_id = None

                    if item['citation_text_is_note_number']:
                        if self.citation_notes_should_be_endnotes:
                            html_item_text = f'<sup>{len(note_lis) + 1}</sup>'
                        else:
                            raise NotImplementedError('Implement notes at the end of chapter')
                    else:
                        html_item_text = item['html_main_text']

                    #html_item_text += f'<span id="{note_id_in_text}"></span>'

                    if endnote_id:
                        html_item_text = self.build_anchor_to_section(section=section_to_add_citation_notes,
                                                                      text=html_item_text,
                                                                      id_=endnote_id,
                                                                      is_note_to_ref=True,
                                                                      anchor_id=note_id_in_text)
                else:
                    html_item_text = item['md_orig_main_text']
                    citations_not_found.update(item['citation_keys'])
                paragraph += html_item_text
            elif item['kind'] == 'paragraph_limit':
                paragraph = paragraph.strip()
                if paragraph:
                    #print('paragraph:', paragraph)
                    htmls.append(_add_p_tags(paragraph))
                    paragraph = ''
            elif item['kind'] == 'html':
                htmls.append(item['html'])
            else:
                raise NotImplementedError()
        paragraph = paragraph.strip()
        if paragraph:
            #print('paragraph:', paragraph)
            htmls.append(_add_p_tags(paragraph))
        #pprint(htmls)
        return '\n'.join(htmls)

    def _create_section(self, section, items):
        if section.id == TOC_CHAPTER_ID:
            self._sections_added.insert(0, section)
        else:
            self._sections_added.append(section)

        title = section.title
        main_html = self._create_html_from_items(items, section)

        if self.site_kind == EPUB3:
            head_html_template = EPUB_CHAPTER_HEADER_HTML
            start_section_template = EPUB_START_CHAPTER_SECTION
            end_section = EPUB_END_CHAPTER_SECTION
        elif self.site_kind == HTML:
            head_html_template = HTML_CHAPTER_HEADER_HTML
            start_section_template = HTML_START_CHAPTER_SECTION
            end_section = HTML_END_CHAPTER_SECTION

        if section.kind == PART:
            section_kind = 'part'
        elif section.kind == CHAPTER:
            section_kind = 'chapter'

        html = head_html_template.format(title=title)
        html += '<body>\n'
        html += start_section_template.format(epub_type=section_kind,
                                              section_id=section.id)
        html += main_html
        html += end_section
        html += '</body>\n'
        html += '</html>\n'

        section_path = self._get_path_within_site_for_section(section)

        self.create_file(section_path, html)

    def _create_endnotes_section_items(self):
        lis = self.note_lis[ENDNOTE_CHAPTER_ID]
        if not lis:
            return []
        
        htmls = [f'<h1>{ENDNOTE_CHAPTER_TITLE[self.book.lang]}</h1>\n']

        if self.site_kind == EPUB3:
            htmls.append('<section epub:type="endnotes">\n')
        elif self.site_kind == HTML:
            htmls.append('<div id="doc-endnotes">\n')

        if self.site_kind == EPUB3:
            for li in lis:
                html = ''
                html += '<aside class="endnote" epub:type="endnote">'
                html += li
                html += '</aside>'
                htmls.append(html)
        elif self.site_kind == HTML:
            htmls.append('<ol>\n')
            htmls.extend((f'<li>{li}</li>' for li in lis))
            htmls.append('</ol>\n')

        if self.site_kind == EPUB3:
            htmls.append('</section>\n')
        elif self.site_kind == HTML:
            htmls.append('</div>\n')

        items = [{'kind': 'html', 'html': html} for html in htmls]
        return items

    def _create_reference_items(self):

        if not self._references:
            return []

        htmls = [f'<h1>{BIBLIOGRAPHY_CHAPTER_TITLE[self.book.lang]}</h1>\n']

        if self.site_kind == EPUB3:
            htmls.append('<section role="doc-bibliography">\n')
        elif self.site_kind == HTML:
            htmls.append('<div id="doc-bibliography">\n')

        htmls.append('<ul>\n')

        if self.site_kind == EPUB3:
            role = ' role="doc-endnote"'
        elif self.site_kind == HTML:
            role = ''
    
        htmls.extend((f'<li>{li}{role}</li>' for li in sorted(self._references.values())))
        htmls.append('</ul>\n')

        if self.site_kind == EPUB3:
            htmls.append('</section>\n')
        elif self.site_kind == HTML:
            htmls.append('</div>\n')

        items = [{'kind': 'html', 'html': html} for html in htmls]
        return items

    def _build_nav_for_chapter(self, chapter):
        htmls = []
        chapter_anchor = self.build_anchor_to_section(chapter)

        subchapters = list(chapter.subsections)
        if subchapters:
            htmls.append(f'<li>{chapter_anchor}\n')
            htmls.append('<ol>\n')
            for subchapter in subchapters:
                anchor = self.build_anchor_to_section(subchapter)
                htmls.append(f'<li>{anchor}</li>\n')
            htmls.append('</ol></li>\n')
        else:
            htmls.append(f'<li>{chapter_anchor}</li>\n')
        return htmls

    def _create_toc_section_items(self):

        if self.site_kind == EPUB3:
            html = '<nav epub:type="toc">\n'
        else:
            html = '<nav class="toc">\n'
        htmls = [html]

        htmls.append(f'<h1>{TOC_CHAPTER_TITLE[self.book.lang]}</h1>\n')
        htmls.append('<ol>\n')

        for section in self.book.subsections:
            if section.kind == PART:
                anchor = self.build_anchor_to_section(section)
                htmls.append(f'<li>{anchor}\n')
                htmls.append('<ol>\n')
                for chapter in section.subsections:
                    htmls.extend(self._build_nav_for_chapter(chapter))
                htmls.append('</ol></li>\n')
            elif section.kind == CHAPTER:
                htmls.extend(self._build_nav_for_chapter(section))
        for section in self._backmater_sections:
            htmls.extend(self._build_nav_for_chapter(section))

        htmls.append('</ol>\n')
        htmls.append('</nav>\n')
        items = [{'kind': 'html', 'html': html} for html in htmls]
        return items

    def _get_nav_fname(self):
        extension = self._get_files_extension()
        return f'{NAV_BASE_NAME}.{extension}'

    def _create_nav(self, items):
        main_html = self._create_html_from_items(items)

        html = NAV_HEADER_XML.format(title=self.book.title)
        html += '<section>\n'

        html += main_html

        html += '</section>\n'
        html += '</body>\n'
        html += '</html>\n'

        base_path = self._get_base_path()

        path = base_path / self._get_nav_fname()
        self.create_file(path, html)

    def _build_nav_point_xml_for_section(self, section, play_order, level):

        fname = self._get_fname_for_section(section)
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

    def _create_ncx_xml(self):

        book = self.book
        html = NCX_HEADER_XML
        html += '<head>\n'
        html += f'<meta content="{book.metadata["uid"]}" name="dtb:uid"/>\n'
        html += '</head>\n'
        html += f'<docTitle> <text>{book.title}</text> </docTitle>\n'
        html += '<navMap>\n'

        # Do not use nested navPoints because some ebook do not support them
        # Use &nbsp; to simulate nesting

        play_order = 1
        toc_chapter = self._get_special_section(TOC_CHAPTER_ID)
        html += self._build_nav_point_xml_for_section(toc_chapter, play_order, 1)
        play_order += 1

        for section in self.book.subsections:
            if section.kind == PART:
                if not section.has_no_html:
                    html += self._build_nav_point_xml_for_section(section, play_order, 1)
                    play_order += 1
                for chapter in section.subsections:
                    html += self._build_nav_point_xml_for_section(chapter, play_order, 2)
                    play_order += 1
                    for subchapter in chapter.subsections:
                        html += self._build_nav_point_xml_for_section(subchapter, play_order, 3)
                        play_order += 1
            elif section.kind == CHAPTER:
                html += self._build_nav_point_xml_for_section(section, play_order, 1)
                play_order += 1
                for subchapter in section.subsections:
                    html += self._build_nav_point_xml_for_section(subchapter, play_order, 2)
                    play_order += 1
        for section in self._backmater_sections:
            html += self._build_nav_point_xml_for_section(section, play_order, 1)
            play_order += 1

        html += '</navMap>'
        html += '</ncx>'
        return html

    def _create_ncx(self):
        xml = self._create_ncx_xml()
        base_path = self._get_base_path()
        path = base_path / NCX_FNAME
        self.create_file(path, xml)

    def _create_opf_xml(self):
        xml = OPF_HEADER_XML

        now = datetime.datetime.utcnow().isoformat(timespec='seconds')

        book = self.book
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
        toc_chapter = self._sections_added[0]
        toc_fname = self._get_fname_for_section(toc_chapter)
        xml += item_xml.format(fname=toc_fname,
                               id='toc')

        for section in self.book.subsections:
            if section.kind == PART:
                if not section.has_no_html:
                    spine.append(section.id)
                    fname = self._get_fname_for_section(section)
                    xml += item_xml.format(fname=fname, id=section.id)
                for chapter in section.subsections:
                    spine.append(chapter.id)
                    fname = self._get_fname_for_section(chapter)
                    xml += item_xml.format(fname=fname, id=chapter.id)
            elif section.kind == CHAPTER:
                spine.append(section.id)
                fname = self._get_fname_for_section(section)
                xml += item_xml.format(fname=fname, id=section.id)
        for section in self._backmater_sections:
            spine.append(section.id)
            fname = self._get_fname_for_section(section)
            xml += item_xml.format(fname=fname, id=section.id)

        xml += f'<item href="{NCX_FNAME}" id="ncx" media-type="application/x-dtbncx+xml" />\n'
        fname = self._get_nav_fname()
        xml += f'<item href="{fname}" id="nav" media-type="application/xhtml+xml" properties="nav" />\n'

        xml += '</manifest>\n'

        xml += '<spine toc="ncx">\n'
        for chapter_id in spine:
            xml += f'<itemref idref="{chapter_id}"/>\n'
        xml += '</spine>\n'

        xml += '<guide>\n'
        title = TOC_CHAPTER_TITLE[book.lang]
        xml += f'<reference type="toc" title="{title}" href="{toc_fname}" />\n'
        xml += '</guide>\n'
        xml += '</package>\n'
        return xml

    def _create_opf(self):
        xml = self._create_opf_xml()
        base_path = self._get_base_path()
        path = base_path / OPF_FNAME
        self.create_file(path, xml)

    def _create_navigation_files(self):

        items = self._create_toc_section_items()
        section = self._get_special_section(TOC_CHAPTER_ID)
        self._create_section(section, items)

        if self.site_kind == EPUB3:
            items = self._create_toc_section_items()
            self._create_nav(items)
            self._create_ncx()
            self._create_opf()

    def render(self):
        print(self.site_kind)
        self.citation_keys_not_found= set()

        self._sections_and_items = self._get_sections_and_items()
        self._process_citations()

        # self._process_notes()

        self._open_out_files()

        if self.site_kind == EPUB3:
            self._create_mimetype_file()
            self._create_epub_backbone()

        for section_and_items in self._sections_and_items:
            section = section_and_items['section']
            items = section_and_items['items']
            self._create_section(section, items)

        self._backmater_sections = []
        endnotes_items = self._create_endnotes_section_items()
        if endnotes_items:
            section = self._get_special_section(ENDNOTE_CHAPTER_ID)
            self._create_section(section, endnotes_items)
            self._backmater_sections.append(section)

        reference_items = self._create_reference_items()
        if reference_items:
            section = self._get_special_section(BIBLIOGRAPHY_CHAPTER_ID)
            self._create_section(section, reference_items)
            self._backmater_sections.append(section)

        self._create_navigation_files()

        self._close_out_files()

def check_epub(ebook_path):
    cmd = ['java', '-jar', str(EPUBCHECK_JAR), str(ebook_path)]
    completed_process = subprocess.run(cmd, capture_output=True)

    if completed_process.returncode:
        sys.stdout.write(completed_process.stdout.decode())
        sys.stderr.write(completed_process.stderr.decode())
