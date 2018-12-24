
from pathlib import Path
import operator
import re
from functools import partial
from collections import OrderedDict, Counter
from pprint import pprint
import zipfile
import shutil

import mistune
from ebooklib import epub

from citations import (load_bibliography_db, create_citation_note,
                       create_bibliography_citation)

EPUB_VERSION = 'old'

ENDNOTES_EPUB_TYPE = {'old': 'rearnotes',
                      '3.1': 'endnotes'}

_HEADER_RE = re.compile('^(?P<pounds>#+)(?P<text>[^{]+)')
_HEADER_WITH_ID_RE = re.compile('^(?P<pounds>#+)(?P<text>[^{]+) *{#(?P<id>[^}]+)}$')


BACK_ENDNOTE_TEXT = {'en': 'Go to note reference',
                     'es': 'Volver a la nota'}

HTML_FILES_EXTENSION = 'xhtml'
HTML_DIR = '.'


_NUM_FOOTNOTES_AND_CITATIONS_SEEN = 0
_FOOTNOTE_IDS_SEEN = set()
_CITATION_COUNTS = Counter()
_FOOTNOTE_DEFINITION_ID_COUNTS = Counter()

CHAPTER_HEADER_HTML = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="css/epub.css" />
</head>\n'''

CHAPTER_SECTION_LINE = '  <section epub:type="{epub_type}" id="{chapter_id}" class="chapter">\n'

ENDNOTE_CHAPTER_TITLE = {'es': 'Notas',
                         'en': 'Notes'}

BIBLIOGRAPHY_CHAPTER_TITLE = {'es': 'Bibliografía',
                              'en': 'Bibliography'}

TOC_CHAPTER_TITLE = {'es': 'Índice',
                     'en': 'Table of contents'}

APPENDICES_PART_TITLE = {'es': 'Apéndices',
                         'en': 'Appendices'}


def _footnote_processor(footnote, footnote_chapter_fpath):
    footnote_id = footnote['match'].group('id')

    if footnote_id in _FOOTNOTE_IDS_SEEN:
        raise RuntimeError('Repeated footnote ID: ' + footnote_id)
    _FOOTNOTE_IDS_SEEN.add(footnote_id)
    global _NUM_FOOTNOTES_AND_CITATIONS_SEEN
    _NUM_FOOTNOTES_AND_CITATIONS_SEEN += 1

    href_to_footnote_definition = f'{footnote_chapter_fpath}#ftd_{footnote_id}'
    a_id = f'ft_{footnote_id}'

    text = f'<a id="{a_id}" href="{href_to_footnote_definition}" role="doc-noteref" epub:type="noteref">{_NUM_FOOTNOTES_AND_CITATIONS_SEEN}</a>'
    return {'processed_text': text,
            'match_location': footnote['match'].span()[0],
            'footnote_id': footnote_id}


def _footnote_definition_processor(footnote_definition,
                                   chapter_path, lang):
    footnote_id = footnote_definition['match'].group('id')

    _FOOTNOTE_DEFINITION_ID_COUNTS[footnote_id] += 1
    if _FOOTNOTE_DEFINITION_ID_COUNTS[footnote_id] > 1:
        raise RuntimeError('More than one footnote definition for footnote ID: ' + footnote_id)

    li_id = f'ftd_{footnote_id}'
    content = footnote_definition['match'].group('content').strip()
    text = f'<li id= "{li_id}" role="doc-endnote"><p>{content}</p></li>'

    return {'footnote_definition_li': text,
            'footnote_id': footnote_id}


def _citation_processor(citation, bibliography_chapter_fpath,
                        chapter_path,
                        footnote_chapter_fpath,
                        bibliography_db,
                        bibliography_entries_seen,
                        lang):
    citation_id = citation['match'].group('id')
    _CITATION_COUNTS[citation_id] += 1
    footnote_id = f'{citation_id}_{_CITATION_COUNTS[citation_id]}'
    global _NUM_FOOTNOTES_AND_CITATIONS_SEEN
    _NUM_FOOTNOTES_AND_CITATIONS_SEEN += 1

    href_to_footnote_definition = f'{footnote_chapter_fpath}#ftd_{footnote_id}'
    a_id = f'ft_{footnote_id}'

    text = f'<a id="{a_id}" href="{href_to_footnote_definition}" role="doc-noteref" epub:type="noteref">{_NUM_FOOTNOTES_AND_CITATIONS_SEEN}</a>'

    footnote_definition_content = create_citation_note(bibliography_db,
                                                       citation_id)
    li_id = f'ftd_{footnote_id}'
    chapter_fpath = str(chapter_path)
    back_href_to_footnote = f'{chapter_fpath}#ft_{footnote_id}'
    footnote_definition_text = f'<li id= "{li_id}" role="doc-endnote"><p>{footnote_definition_content}</p><p><a href="{back_href_to_footnote}" role="doc-backlink">{BACK_ENDNOTE_TEXT[lang]}</a>.</p></li>'

    bibliography_entries_seen.add(citation_id)

    return {'footnote_definition_li': footnote_definition_text,
            'processed_text': text,
            'match_location': citation['match'].span()[0]}


def _split_md_text_in_items(md_text):

    # This algorithm has one limitation, it does not allow to have trees
    # it can only yield a stream of items, but not items within an item

    footnote_re = re.compile(r'\[\^(?P<id>[^\]]+)\]')
    footnote_definition_re = re.compile(r'\[\^(?P<id>[^\]]*)\]:(?P<content>[^\n]+)')
    citation_re = re.compile(r'\[@(?P<id>[^\],]+),? *(?P<locator_term>[\w]*) *(?P<locator_positions>[0-9]*)\]', re.UNICODE)
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


def _get_citation_location_in_text(footnote_definition, footnote_locations):
    if 'match_location' in footnote_definition:
        return footnote_definition['match_location']
    else:
        return footnote_locations[footnote_definition['footnote_id']]


def _build_internal_link(text, anchor_section):
    path = anchor_section['path']
    fname = path.name
    id_ = anchor_section['id']
    link = f'<a href="{fname}#{id_}">{text}</a>'
    return link


def _internal_link_processor(internal_link, sections_by_id):
    text = internal_link['match'].group('text')
    link_id = internal_link['match'].group('link_id')

    link = _build_internal_link(text, sections_by_id[link_id])
    return {'processed_text': link}


def _process_citations_and_footnotes(md_text, chapter_path,
                                     footnote_chapter_fpath,
                                     bibliography_chapter_fpath,
                                     bibliography_db,
                                     sections_by_id,
                                     lang):
    items = _split_md_text_in_items(md_text)

    bibliography_entries_seen = set()
    footnote_definitions = []

    #split_text_in_items, item kinds: std_markdown, citation, footnote, footnote_definition,
    item_processors = {'footnote': partial(_footnote_processor,
                                           footnote_chapter_fpath=footnote_chapter_fpath),
                       'footnote_definition': partial(_footnote_definition_processor,
                                                      chapter_path=chapter_path,
                                                      lang=lang),
                       'citation': partial(_citation_processor,
                                           chapter_path=chapter_path,
                                           footnote_chapter_fpath=footnote_chapter_fpath,
                                           bibliography_chapter_fpath=bibliography_chapter_fpath,
                                           bibliography_db=bibliography_db,
                                           bibliography_entries_seen=bibliography_entries_seen,
                                           lang=lang),
                        'internal_link': partial(_internal_link_processor,
                                                 sections_by_id=sections_by_id)
                      }
    processed_text = []
    debug_item = 'internal_link'
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


def _process_md_text(lines_iterator, chapter_path,
                     footnote_chapter_fpath,
                     bibliography_chapter_fpath,
                     bibliography_db,
                     sections_by_id,
                     lang):
    md_text = '\n'.join(lines_iterator)

    result = _process_citations_and_footnotes(md_text=md_text,
                                              chapter_path=chapter_path,
                                              footnote_chapter_fpath=footnote_chapter_fpath,
                                              bibliography_chapter_fpath=bibliography_chapter_fpath,
                                              bibliography_db=bibliography_db,
                                              sections_by_id=sections_by_id,
                                              lang=lang)
    result['rendered_text'] = _process_basic_markdown(result['rendered_text'])
    result['bibliography_entries_seen'] = result['bibliography_entries_seen']
    return result


def _parse_header_line(line):
    match = _HEADER_WITH_ID_RE.match(line)
    if not match:
        match = _HEADER_RE.match(line)

    if not match:
        raise ValueError('Line is not a header line: {}'.format(line))

    result = {'level': len(match.group('pounds')),
              'text': match.group('text').strip()}
    try:
        result['id'] = match.group('id')
    except IndexError:
        pass
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


def _get_lines_in_files(md_files):
    for file in md_files:
        for line in file.open('rt'):
            line = line.strip()
            yield line


def render_section(section, base_header_level, path,
                   footnote_chapter_fpath,
                   bibliography_chapter_fpath,
                   bibliography_db,
                   sections_by_id,
                   lang):
    md_files = section['md_files']

    rendered_text = ''
    footnote_definitions = []
    bibliography_entries_seen = set()

    lines = _get_lines_in_files(md_files)

    lowest_header_level_in_md = None
    for fragment in _split_section_in_fragments(lines):
        if fragment['kind'] == 'header':
            text = fragment['text']
            res = _parse_header_line(text)
            if lowest_header_level_in_md is None:
                lowest_header_level_in_md = res['level']
            header_level = (res['level'] - lowest_header_level_in_md) + base_header_level
            header = f'    <h{header_level}>{res["text"]}</h{header_level}>\n'
            rendered_text += header
        elif fragment['kind'] == 'fragment':
            result = _process_md_text(fragment['lines'],
                                      chapter_path=path,
                                      footnote_chapter_fpath=footnote_chapter_fpath,
                                      bibliography_chapter_fpath=bibliography_chapter_fpath,
                                      bibliography_db=bibliography_db,
                                      sections_by_id=sections_by_id,
                                      lang=lang)
            rendered_text += result['rendered_text']
            footnote_definitions.extend(result['footnote_definitions'])
            bibliography_entries_seen.update(result['bibliography_entries_seen'])

    if not rendered_text:
        raise ValueError('A chapter should have at least one line: {}'.format(', '.join(md_files)))

    result = {'rendered_text': rendered_text,
              'footnote_definitions': footnote_definitions,
              'bibliography_entries_seen': bibliography_entries_seen}
    return result


def render_chapter(chapter, base_header_level,
                   footnote_chapter_fpath, bibliography_chapter_fpath,
                   bibliography_db, sections_by_id, lang):

    sections = chapter['subsections']
    footnote_definitions = []
    bibliography_entries_seen = set()

    first_section = sections[0]

    result = render_section(first_section,
                            base_header_level,
                            path=chapter['path'],
                            footnote_chapter_fpath=footnote_chapter_fpath,
                            bibliography_chapter_fpath=bibliography_chapter_fpath,
                            bibliography_db=bibliography_db,
                            sections_by_id=sections_by_id,
                            lang=lang)

    rendered_text = CHAPTER_SECTION_LINE.format(epub_type='chapter',
                                                chapter_id=chapter['id'])

    rendered_text += result['rendered_text']
    footnote_definitions.extend(result['footnote_definitions'])
    bibliography_entries_seen.update(result['bibliography_entries_seen'])
    title = result.get('title', None)

    subchapter_ids_and_titles = {}
    for idx, subchapter_section in enumerate(sections[1:]):
        subchapter_idx = idx + 1
        chapter_id = chapter['id']
        subchapter_id = f'{chapter_id}_sub{subchapter_idx}'
        rendered_text += f'    <section epub:type="chapter" id="{subchapter_id}" class="subchapter">\n'

        result = render_section(subchapter_section,
                                base_header_level + 1,
                                path=chapter['path'],
                                footnote_chapter_fpath=footnote_chapter_fpath,
                                bibliography_chapter_fpath=bibliography_chapter_fpath,
                                bibliography_db=bibliography_db,
                                sections_by_id=sections_by_id,
                                lang=lang)
        rendered_text += result['rendered_text']
        footnote_definitions.extend(result['footnote_definitions'])
        bibliography_entries_seen.union(result['bibliography_entries_seen'])

        # end subchapter
        rendered_text += '    </section>\n'
        subchapter_ids_and_titles[subchapter_id] = result.get('title', None)

    # end chapter
    rendered_text += '  </section>'
    result = {'rendered_text': rendered_text,
              'footnote_definitions': footnote_definitions,
              'bibliography_entries_seen': bibliography_entries_seen}
    if subchapter_ids_and_titles:
        result['subchapter_titles'] = subchapter_ids_and_titles
    return result


def _render_part(part_id, header, sections_by_id):
    rendered_text = f'<section epub:type="part" id="{part_id}" class="part">\n'
    if header:
        rendered_text += f'  <h1>{header}</h1>\n'
        title = header
    else:
        title = None

    rendered_text += '</section>\n'
    return {'rendered_text': rendered_text}


def _get_subdirs_in_dir(dir_path):
    subdirs = []
    for subdir in dir_path.iterdir():
        if str(subdir.name).startswith('.') or subdir.is_file():
            continue
        subdirs.append(subdir)
    subdirs.sort(key=lambda x: str(x))
    return subdirs


def _get_md_files_in_dir(dir_path):

    files = []
    for file in dir_path.iterdir():
        if not file.is_file():
            continue
        if str(file.name).startswith('.') or not str(file.name).endswith('.md'):
            continue
        files.append(file)
    files.sort(key=lambda x: str(x))
    return files


def _get_section_files_in_chapter(chaper_dir_path):

    sections = []

    md_files = _get_md_files_in_dir(chaper_dir_path)
    if md_files:
        sections.append({'md_files': md_files, 'is_subchapter': False})

    subchapter_dirs = _get_subdirs_in_dir(chaper_dir_path)
    for subchapter_dir in subchapter_dirs:
        md_files = _get_md_files_in_dir(subchapter_dir)
        sections.append({'md_files': md_files, 'is_subchapter': True})

    return sections


def _get_chapters(book_base_dir):
    chapters = []
    for chapter_dir in book_base_dir.iterdir():
        if chapter_dir.name.startswith('.'):
            continue
        if not chapter_dir.is_dir():
            continue
        chapters.append({'dir_path': chapter_dir})
    chapters.sort(key=operator.itemgetter('dir_path'))
    return chapters


def _get_dir_kind(dir_path):
    dir_fname = dir_path.name
    first_letter = dir_fname.lstrip('0123456789_-')[0]
    if first_letter.lower() == 'c':
        return 'chapter'
    elif first_letter.lower() == 'p':
        return 'part'
    else:
        msg = f'first letter for a part or chapter directory should be p or c: {dir_fname}'
        raise ValueError(msg)


def _create_chapter_path(idx, out_dir):
    fname = f'chapter_{idx}.{HTML_FILES_EXTENSION}'
    path = out_dir / HTML_DIR / fname
    return path


def _create_part_path(idx, out_dir):
    fname = f'part_{idx}.{HTML_FILES_EXTENSION}'
    path = out_dir / HTML_DIR / fname
    return path


def _check_first_subsection_in_chapter_is_not_subchapter(chapter):
    sections = chapter['subsections']
    first_section = sections[0]
    if first_section['is_subchapter']:
        msg = 'The chapter has no file before first subchapter: {}\n'.format(' ,'.join(first_section['md_files']))
        raise ValueError(msg)


def _get_first_header_line(lines):
    for line in lines:
        if line.startswith('#'):
            return line


def _get_chapter_id(chapter, idx):
    lines = _get_lines_in_files(chapter['subsections'][0]['md_files'])
    first_header = _get_first_header_line(lines)
    if not first_header:
        raise ValueError('First chapter subsection has no header line: ' + str(chapter))
    res = _parse_header_line(first_header)
    title = res['text']
    id_ = res.get('id', f'chapter_{idx}')
    return title, id_


def _get_part_id(part, idx):
    if 'md_file' in part['part']:
        header_lines = [line for line in part['part']['md_file'].open('rt') if line.startswith('#')]
    else:
        header_lines = []

    if len(header_lines) > 1:
        raise ValueError(f'Only one header line is allowed in part markdown file {md_file}')

    if header_lines:
        res = _parse_header_line(header_lines[0])
        id_ = res.get('id')
        title = res['text']
    else:
        id_ = None
        title = None

    if id_ is None:
        id_ = f'chapter_{idx}'

    return title, id_


def _get_parts_and_chapters(book_base_dir, out_dir):
    chapters = []
    parts = []
    for dir_ in sorted(book_base_dir.iterdir(), key=lambda path: path.name):
        if dir_.name.startswith('.'):
            continue

        dir_kind = _get_dir_kind(dir_)

        if dir_kind == 'part':
            part_chapters = _get_chapters(dir_)
            chapters.extend(part_chapters)

            part = {'part_dir': dir_,
                    'chapters': part_chapters}

            md_files = _get_md_files_in_dir(dir_)
            if md_files:
                if len(md_files) > 1:
                    msg = 'Only one markdown file is allowed in part directory: {}'.format(' ,'.join(md_files))
                    raise ValueError(msg)

                part['md_file'] = md_files[0]
            parts.append(part)
        elif dir_kind == 'chapter':
            chapters.append({'dir_path': dir_})
        else:
            raise RuntimeError('We should not be here. Fixme')

    sections = []
    chapters_iter = iter(chapters)
    parts_iter = iter(parts)
    next_part = None
    next_chapter_in_chapters = None
    parts_used = False
    while True:
        if next_chapter_in_chapters is None:
            try:
                next_chapter_in_chapters = next(chapters_iter)
            except StopIteration:
                break
        if next_part is None:
            try:
                next_part = next(parts_iter)
                part_section = {'kind': 'part',
                                'chapters': [],
                                'part': next_part}
                next_part_is_constructed = False
            except StopIteration:
                next_part = None

        if next_part is None:
            # we are here if we do not use parts or if there are no more parts
            if parts_used:
                # if we have used parts, but we don't have one right now
                # we create a part
                part_section = {'kind': 'part',
                                'chapters': [next_chapter_in_chapters]}
                sections.append(part_section)
                next_chapter_in_chapters = None
            else:
                section = {'kind': 'chapter',
                           'chapter': next_chapter_in_chapters}
                sections.append(section)
                next_chapter_in_chapters = None
        else:
            # we have parts, although we might not use one yet
            chapter_is_in_next_part = any(next_chapter_in_chapters is chapter for chapter in next_part.get('chapters', None))

            if chapter_is_in_next_part:
                parts_used = True
                part_section['chapters'].append(next_chapter_in_chapters)
                next_chapter_in_chapters = None
            else:
                # chapter is not in the current part
                if part_section['chapters']:
                    # we had a valid part, but this chapter is not in it anymore
                    sections.append(part_section)
                    next_part = None
                    # the chapter might belong to the next section and it will
                    # be evaluated in the next while iteration
                else:
                    section = {'kind': 'chapter',
                               'chapter': next_chapter_in_chapters}
                    sections.append(section)
                    next_chapter_in_chapters = None
    if part_section['chapters']:
        sections.append(part_section)

    for section in sections:
        if section['kind'] == 'part':
            if 'part' not in section:
                raise RuntimeError(f'Malformed part section: {section}')

    # add ids
    part_idx = 0
    chapter_idx = 0
    sections_by_id = {}
    for section in sections:
        if section['kind'] == 'part':
            part_idx += 1
            section['idx'] = part_idx
            section['path'] = _create_part_path(part_idx, out_dir)
            title, section['id'] = _get_part_id(section, part_idx)
            if title:
                section['title'] = title
            sections_by_id[section['id']] = section

            for chapter in section['chapters']:
                chapter_idx += 1
                chapter['idx'] = chapter_idx
                chapter['path'] = _create_chapter_path(chapter_idx, out_dir)
                chapter['subsections'] = _get_section_files_in_chapter(chapter['dir_path'])
                _check_first_subsection_in_chapter_is_not_subchapter(chapter)
                chapter['title'], chapter['id'] = _get_chapter_id(chapter,
                                                                  chapter_idx)
                sections_by_id[chapter['id']] = chapter

        if section['kind'] == 'chapter':
            chapter_idx += 1
            section['idx'] = chapter_idx
            section['path'] = _create_chapter_path(chapter_idx, out_dir)
            section['subsections'] = _get_section_files_in_chapter(section['chapter']['dir_path'])
            _check_first_subsection_in_chapter_is_not_subchapter(section)
            section['title'], section['id'] = _get_chapter_id(section,
                                                              chapter_idx)
            sections_by_id[section['id']] = section

    #pprint(sections)
    return {'chapters': chapters,
            'parts': parts,
            'parts_and_chapters': sections,
            'sections_by_id': sections_by_id}


def _add_endnotes_chapter(chapter_title, chapter_id, header_level,
                          footnote_definitions, lang):
    html = CHAPTER_SECTION_LINE.format(chapter_id=chapter_id,
                                       epub_type=ENDNOTES_EPUB_TYPE[EPUB_VERSION])

    header = f'  <h{header_level}>{chapter_title}</h{header_level}>\n'
    html += header

    html += '<ol role="doc-endnotes">'
    for footnote_definition in footnote_definitions:
        html += footnote_definition['footnote_definition_li']
    html += '</ol>\n'

    html += '</section>\n'
    return {'html': html}


def _add_bibliography_chapter(chapter_title, chapter_id, header_level,
                             bibliography_entries_seen,
                             bibliography_db, lang):
    html = CHAPTER_SECTION_LINE.format(chapter_id=chapter_id,
                                       epub_type='bibliography')

    header = f'  <h{header_level}>{chapter_title}</h{header_level}>\n'
    html += header

    htmls = []
    for bibliography_id in bibliography_entries_seen:
        citation_html = create_bibliography_citation(bibliography_db, bibliography_id)
        htmls.append(citation_html)
    htmls.sort()

    html += '<ul role="Bibliography">'
    for html_li in htmls:
        html += f'<li>{html_li}</li>'
    html += '</ul>\n'

    html += '</section>\n'
    html += '\n</body>\n</html>\n'
    return {'html': html}


def _add_toc_chapter(chapter_title, chapter_id,
                     header_level, toc_info, lang):

    html = CHAPTER_SECTION_LINE.format(chapter_id=chapter_id,
                                       epub_type='toc')

    html += '<nav epub:type="toc">\n'
    html += f'<h1>{TOC_CHAPTER_TITLE[lang]}</h1>'
    html += '<ol>\n'
    current_level = 1
    for toc_entry in toc_info:
        toc_level = toc_entry['level']
        if toc_level > current_level:
            html += '<ol>\n'
            current_level = toc_level
        if toc_level < current_level:
            html += '</ol>\n'
            current_level = toc_level
        if 'path' not in toc_entry:
            if 'title' in toc_entry and toc_entry["title"]:
                li = f'<li>{toc_entry["title"]}</li>\n'
            else:
                li = ''
        else:
            fname = toc_entry['path'].name
            li = f'<li><a href="{fname}#{toc_entry["id"]}">{toc_entry["title"]}</a></li>\n'
        html += li

    for _ in range(current_level, 1, -1):
        html += '</ol>\n'

    html += '</ol>'
    html += '</nav>\n'
    html += '</section>\n'
    html += '\n</body>\n</html>\n'
    return {'html': html}


def _compile_chapter(chapter,
                     base_header_level,
                     endnote_chapter_fname,
                     bibliography_chapter_fpath,
                     bibliography_db,
                     sections_by_id,
                     lang):

    result = render_chapter(chapter,
                            base_header_level=base_header_level,
                            footnote_chapter_fpath=endnote_chapter_fname,
                            bibliography_chapter_fpath=bibliography_chapter_fpath,
                            bibliography_db=bibliography_db,
                            sections_by_id=sections_by_id,
                            lang=lang)

    return {'footnote_definitions': result['footnote_definitions'],
            'bibliography_entries_seen': result['bibliography_entries_seen'],
            'html': result['rendered_text']}


def _compile_part(chapter,
                  endnote_chapter_fname, bibliography_chapter_fpath,
                  bibliography_db, sections_by_id, lang):

    header = chapter.get('title', None)
    result = _render_part(part_id=chapter['id'],
                          header=header,
                          sections_by_id=sections_by_id)

    return {'html': result['rendered_text']}


def create_epub(book_base_dir, out_path, bibliography_path, metadata):
    book = epub.EpubBook()

    book.set_identifier(metadata['id'])
    book.set_title(metadata['title'])
    lang = metadata['lang']
    book.set_language(lang)
    book.add_author(metadata['author'])

    bibliography_db = load_bibliography_db(bibliography_path)
    endnote_chapter_fname = f'endnotes.{HTML_FILES_EXTENSION}'
    bibliography_chapter_fpath = f'bibliography.{HTML_FILES_EXTENSION}'
    toc_chapter_fpath = f'toc.{HTML_FILES_EXTENSION}'

    sections = _get_parts_and_chapters(book_base_dir, out_dir)

    footnote_definitions = []
    bibliography_entries_seen = set()
    toc_info = []
    parts_are_used = False

    spine = []
    for section in sections['parts_and_chapters']:
        if section['kind'] == 'chapter':
            result = _compile_chapter(section,
                                      base_header_level=1,
                                      endnote_chapter_fname=endnote_chapter_fname,
                                      bibliography_chapter_fpath=bibliography_chapter_fpath,
                                      bibliography_db=bibliography_db,
                                      sections_by_id=sections['sections_by_id'],
                                      lang=lang)
            footnote_definitions.extend(result['footnote_definitions'])
            bibliography_entries_seen.update(result['bibliography_entries_seen'])

            epub_chapter = epub.EpubHtml(title=section['title'],
                                         file_name=section['path'].name,
                                         lang=lang)
            epub_chapter.set_content(result['html'])
            book.add_item(epub_chapter)
            spine.append(epub_chapter)

            toc_entry = {'id': section['id'],
                         'path': section['path'],
                         'title': section['title'],
                         'level': 1}
            toc_info.append(toc_entry)

        elif section['kind'] == 'part':
            parts_are_used = True
            result = _compile_part(section,
                                   endnote_chapter_fname=endnote_chapter_fname,
                                   bibliography_chapter_fpath=bibliography_chapter_fpath,
                                   bibliography_db=bibliography_db,
                                   sections_by_id=sections['sections_by_id'],
                                   lang=lang)
            epub_chapter = epub.EpubHtml(title=section['title'],
                                         file_name=section['path'].name,
                                         lang=lang)
            epub_chapter.set_content(result['html'])
            book.add_item(epub_chapter)
            spine.append(epub_chapter)

            toc_entry = {'id': section['id'],
                         'path': section['path'],
                         'title': section['title'],
                         'level': 1}
            toc_info.append(toc_entry)

            for chapter in section['chapters']:
                result = _compile_chapter(chapter,
                                          base_header_level=2,
                                          endnote_chapter_fname=endnote_chapter_fname,
                                          bibliography_chapter_fpath=bibliography_chapter_fpath,
                                          bibliography_db=bibliography_db,
                                          sections_by_id=sections['sections_by_id'],
                                          lang=lang)
                footnote_definitions.extend(result['footnote_definitions'])
                bibliography_entries_seen.update(result['bibliography_entries_seen'])

                epub_chapter = epub.EpubHtml(title=chapter['title'],
                                             file_name=chapter['path'].name,
                                             lang=lang)
                epub_chapter.set_content(result['html'])
                book.add_item(epub_chapter)
                spine.append(epub_chapter)

                toc_entry = {'id': chapter['id'],
                             'path': chapter['path'],
                             'title': chapter['title'],
                             'level': 2}
                toc_info.append(toc_entry)


    if (footnote_definitions or bibliography_entries_seen) and parts_are_used:
        part_id = 'part_back_matter'
        part_title = APPENDICES_PART_TITLE[lang]
        toc_entry = {'id': part_id,
                     'title': part_title,
                     'level': 1}
        toc_info.append(toc_entry)

    toc_level_for_appendix_chapters = 2 if parts_are_used else 1

    if footnote_definitions:
        chapter_path = out_dir / HTML_DIR / endnote_chapter_fname
        chapter_id = f'chapter_endnotes'
        chapter_title = ENDNOTE_CHAPTER_TITLE[lang]
        base_header_level = 2 if parts_are_used else 1
        result = _add_endnotes_chapter(chapter_title,
                                       chapter_id=chapter_id,
                                       header_level=base_header_level,
                                       footnote_definitions=footnote_definitions,
                                       lang=lang)

        epub_chapter = epub.EpubHtml(title=chapter_title,
                                     file_name=chapter_path.name,
                                     lang=lang)
        epub_chapter.set_content(result['html'])
        book.add_item(epub_chapter)
        spine.append(epub_chapter)

        toc_entry = {'id': chapter_id,
                     'path': chapter_path,
                     'fname': endnote_chapter_fname,
                     'title': ENDNOTE_CHAPTER_TITLE[lang],
                     'level': toc_level_for_appendix_chapters}
        toc_info.append(toc_entry)

    if bibliography_entries_seen:
        chapter_path = out_dir / HTML_DIR / bibliography_chapter_fpath
        chapter_id = f'chapter_bibliography'
        chapter_title = BIBLIOGRAPHY_CHAPTER_TITLE[lang]
        base_header_level = 2 if parts_are_used else 1
        result = _add_bibliography_chapter(chapter_title,
                                           chapter_id=chapter_id,
                                           header_level=base_header_level,
                                           bibliography_entries_seen=bibliography_entries_seen,
                                           bibliography_db=bibliography_db,
                                           lang=lang)
        epub_chapter = epub.EpubHtml(title=chapter_title,
                                     file_name=chapter_path.name,
                                     lang=lang)
        epub_chapter.set_content(result['html'])
        book.add_item(epub_chapter)
        spine.append(epub_chapter)

        toc_entry = {'id': chapter_id,
                     'path': chapter_path,
                     'fname': bibliography_chapter_fpath,
                     'title': BIBLIOGRAPHY_CHAPTER_TITLE[lang],
                     'level': toc_level_for_appendix_chapters}
        toc_info.append(toc_entry)

    if toc_info:
        chapter_path = out_dir / HTML_DIR / toc_chapter_fpath
        chapter_id = 'toc'
        chapter_title = TOC_CHAPTER_TITLE[lang]
        result = _add_toc_chapter(chapter_title,
                         chapter_id=chapter_id,
                         header_level=1,
                         toc_info=toc_info,
                         lang=lang)
        epub_chapter = epub.EpubHtml(title=chapter_title,
                                     file_name=chapter_path.name,
                                     lang=lang)
        epub_chapter.set_content(result['html'])
        book.add_item(epub_chapter)
        spine.insert(0, epub_chapter)

    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(out_path), book)


def unzip_epub(ebook_path, out_dir):

    if out_dir.exists():
        shutil.rmtree(out_dir)

    with zipfile.ZipFile(ebook_path) as epubzip:
        epubzip.extractall(path=out_dir)


if __name__ == '__main__':
    out_dir = Path('rendered_book')
    out_dir.mkdir(exist_ok=True)

    metadata = {'id': 'arteDudaIntroduccionFilosoficaCiencia',
                'title': 'El arte de la duda',
                'author': 'Jose Blanca',
                'lang': 'es'}

    ebook_path = Path('book_test.epub')
    create_epub(book_base_dir=Path('book_test'),
                out_path=ebook_path,
                bibliography_path=Path('bibliografia_arte.bibtex'),
                metadata=metadata)

    unzip_epub(ebook_path, Path('rendered_book'))

# TODO:
# - index
# - comentarios
# - epubchecker, google libros
