
import re
import weakref
from collections import Counter
import warnings
from pathlib import Path

import yaml

SYMBOLS_FOR_IDS = '(?:#|\$)'
_HEADER_RE = re.compile('^(?P<pounds>#+)(?P<text>[^{]+) *{?(?P<item1>' + SYMBOLS_FOR_IDS + '[^ }]+)? ?(?P<item2>' + SYMBOLS_FOR_IDS + '[^}]+)?}?$')

BOOK = 'book'
CHAPTER = 'chapter'
PART = 'part'
SUBCHAPTER = 'subchapter'
TOC = 'toc'
SECTION_KINDS = [BOOK, PART, CHAPTER, SUBCHAPTER]


def _look_for_first_header(lines):
    for line in lines:
        if line.startswith('#'):
            return line
    raise ValueError('No header line in text')


def _parse_header_line(line):
    match = _HEADER_RE.match(line)

    if not match:
        raise ValueError('Line is not a header line: {}'.format(line))

    result = {'level': len(match.group('pounds')),
              'text': match.group('text').strip()}

    for match_item in (match.group('item1'), match.group('item2')):
        if match_item is None:
            continue
        if match_item.startswith('#'):
            result['id'] = match_item[1:]
        if match_item.startswith('$'):
            section_kind = match_item[1:]
            if section_kind not in SECTION_KINDS:
                msg = f'Unknown section kind: {section_kind}'
                raise ValueError(msg)
            result['section_kind'] = section_kind
    return result


def _get_subdirs_in_dir(dir_path):
    subdirs = []
    for subdir in dir_path.iterdir():
        if str(subdir.name).startswith('.') or subdir.is_file():
            continue
        subdirs.append(subdir)
    subdirs.sort(key=lambda x: str(x))
    return subdirs


def _is_md_file(path):
    if not path.is_file():
        return False
    if str(path.name).startswith('.'):
        return False
    if path.suffix not in ('.md'):
        return False
    return True


def _get_md_files_in_dir(dir_path):

    files = []
    for path in dir_path.iterdir():
        if not _is_md_file(path):
            continue
        files.append(path)
    files.sort(key=lambda x: str(x))
    return files


def _get_md_files_in_dir_tree(path):
    assert path.is_dir()

    for path_in_dir in sorted(path.iterdir()):
        if path_in_dir.name.startswith('.'):
            continue
        if _is_md_file(path_in_dir):
            yield path_in_dir
        if path_in_dir.is_dir():
            for md_path in _get_md_files_in_dir_tree(path_in_dir):
                yield md_path


def _open_and_concat_text_paths(paths):
    for path in paths:
        with path.open('rt') as fpath:
            for line in fpath:
                yield line


class _BookSection:
    def _get_subsections_recursively(self, section, subsections,
                                     stop_in_me=True):
        subsections.append(section)

        if stop_in_me and section is self:
            return True

        section_subsections = section.subsections
        if not section_subsections:
            return False
        else:
            for section in section_subsections:
                stop = self._get_subsections_recursively(section, subsections,
                                                         stop_in_me=stop_in_me)
                if stop:
                    return stop
        return False

    def _walk_book_sections(self, stop_in_me=True):
        book = self.book
        subsections = []
        self._get_subsections_recursively(book, subsections, stop_in_me)
        return subsections

    @property
    def idx(self):
        if self.kind == BOOK:
            return 0

        parent = self.parent
        subsection_counts = Counter()
        for subsection in self._walk_book_sections(stop_in_me=True):
            subsection_counts[subsection.kind] += 1

        return subsection_counts[self.kind]

    @property
    def book(self):
        current_section = self
        while True:
            parent = current_section.parent
            if parent is None:
                return current_section
            current_section = parent

    @property
    def subsections(self):
        return self._subsections


class BookSection(_BookSection):
    def __init__(self, dir_, parent=None):
        self.dir = dir_
        self.parent = parent
        self._set_kind()
        if self.kind == BOOK:
            self._set_book_metadata()
        self._create_subsections()
        self._id = None
        self._title = None

    def _get_parent(self):
        if self._parent is None:
            return None
        return self._parent()

    def _set_parent(self, parent):
        if parent is None:
            self._parent = None
        else:
            self._parent = weakref.ref(parent)

    parent = property(_get_parent, _set_parent)

    @property
    def md_files(self):
        return _get_md_files_in_dir(self.dir)

    def _set_kind_with_header_info(self, section_kind_in_header):
        parent = self.parent
        if parent is None:
            admisible_kinds = [BOOK]
            default_kind = BOOK
        else:
            parent_kind = parent.kind
            if parent_kind == BOOK:
                admisible_kinds = [PART, CHAPTER]
                default_kind = CHAPTER
            elif parent_kind == PART:
                admisible_kinds = [CHAPTER]
                default_kind = CHAPTER
            elif parent_kind == CHAPTER:
                admisible_kinds = [SUBCHAPTER]
                default_kind = SUBCHAPTER
            else:
                msg = 'A section can only be created within a book, part, chapter or subchapter.'
                raise RuntimeError(msg)

        if section_kind_in_header:
            if section_kind_in_header not in admisible_kinds:
                msg = f'section_kind suggested in header {section_kind_in_header} wihtin a {parent_kind} should be: ' + ','.join(admisible_kinds)
                raise ValueError(msg)
            kind = section_kind_in_header
        else:
            kind = default_kind
        self._kind = kind

    def _set_kind(self):
        self._set_idx_kind_title(set_only_kind=True)

    def _set_id(self, suggested_id):
        if suggested_id:
            self._id = suggested_id
            return

        kind = self.kind
        idx = self.idx
        if kind == BOOK:
            id_ = None
        elif kind == PART:
            id_ = f'part_{idx}'
        elif kind == CHAPTER:
            id_ = f'chapter_{idx}'
        elif kind == SUBCHAPTER:
            parent_chapter_id = self.parent.id
            id_ = f'{parent_chapter_id}_{idx}'
        self._id = id_

    def _get_yaml_section(self, md_text):
        in_yaml = False
        for line in md_text:
            if line.startswith('---'):
                if in_yaml:
                    break
                else:
                    in_yaml = True
                    continue
            yield line

    def _set_book_metadata(self):
        md_text = _open_and_concat_text_paths(self.md_files)
        yaml_text = self._get_yaml_section(md_text)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore",category=DeprecationWarning)
            metadata = yaml.load('\n'.join(yaml_text))

        if 'title' not in metadata:
            msg = 'The book title should be set in the first book yaml section'
            raise ValueError(msg)
        self._metadata = metadata

    def _set_idx_kind_title(self, set_only_kind=False):
        md_text = _open_and_concat_text_paths(self.md_files)
        try:
            header_line = _look_for_first_header(md_text)
        except ValueError:
            header_line = None
        if header_line:
            res = _parse_header_line(header_line)
        else:
            res = {}

        self._set_kind_with_header_info(res.get('section_kind'))
        if set_only_kind:
            return

        self._set_id(res.get('id'))
        if self.kind != BOOK:
            self._title = res.get('text')

    @property
    def kind(self):
        return self._kind

    @property
    def id(self):
        if self._id is None and self.kind != BOOK:
            self._set_idx_kind_title()
        return self._id

    @property
    def title(self):
        if self.kind == BOOK:
            return self._metadata['title']
        else:
            if self._title is None:
                self._set_idx_kind_title()
            return self._title

    def _create_subsections(self):
        kind = self.kind
        if kind == SUBCHAPTER:
            self._subsections = []

        subdirs = _get_subdirs_in_dir(self.dir)
        subsections = []
        for subdir in subdirs:
            subsections.append(BookSection(subdir, parent=self))
        self._subsections = subsections

    def _get_parents_up_to_book(self):
        parents = []
        current_section = self
        while True:
            parent = current_section.parent
            if parent is None:
                break
            parents.append(parent)
            current_section = parent
        return parents

    def is_within_a_part(self):
        kind = self.kind
        if kind in (BOOK, PART):
            return None

        all_parents = self._get_parents_up_to_book()
        if any([parent.kind == PART for parent in all_parents]):
            return True
        else:
            return False

    @property
    def md_text(self):
        in_metadata_yaml = False
        metadata_yaml_done = False
        in_comment = False
        section_kind = self.kind

        if section_kind == PART:
            main_header_level = 1
        else:
            if self.is_within_a_part():
                if section_kind == CHAPTER:
                    main_header_level = 2
                elif section_kind == SUBCHAPTER:
                    main_header_level = 3
            else:
                if section_kind == CHAPTER:
                    main_header_level = 1
                elif section_kind == SUBCHAPTER:
                    main_header_level = 2

        has_subsections = bool(self.subsections)
        for path in self.md_files:
            with path.open('rt') as fhand:
                first_header_level_in_file = None
                last_line_was_blank = False
                for line in fhand:
                    if section_kind == BOOK and not metadata_yaml_done:
                        if line.startswith('---'):
                            if in_metadata_yaml:
                                in_metadata_yaml = False
                                metadata_yaml_done = True
                                continue
                            else:
                                in_metadata_yaml = True
                                continue

                    if line.startswith('%%%'):
                        if in_comment:
                            in_comment = False
                            continue
                        else:
                            in_comment = True
                            continue

                    if in_metadata_yaml or in_comment:
                        continue

                    if line.startswith('#'):
                        res = _parse_header_line(line)
                        if first_header_level_in_file is None:
                            first_header_level_in_file = res['level']
                        else:
                            if has_subsections and not section_kind == BOOK:
                                msg = f'In a section with subsections only one header is allowed: {line}'
                                raise ValueError(msg)
                        header_level = res['level'] - (first_header_level_in_file - main_header_level)
                        line = '#' * header_level + ' ' + res['text'] + '\n'
                        yield line
                        line = '\n'

                    if line == '\n':
                        if last_line_was_blank:
                            continue
                        else:
                            last_line_was_blank = True
                    else:
                        last_line_was_blank = False

                    yield line

    @property
    def metadata(self):
        return self.book._metadata

    @property
    def lang(self):
        return self.metadata['lang']

    @property
    def bibliography_path(self):
        if self.kind == BOOK:
            try:
                return self._bibliography_path
            except AttributeError:
                try:
                    bibliography_path = Path(self.metadata['bibliography'])
                except KeyError:
                    bibliography_path = None
                self._bibliography_path = bibliography_path
                return self._bibliography_path
        else:
            return self.book.bibliography_path

    def _get_section_index(self):
        try:
            return self._section_index
        except AttributeError:
            pass

        index = {}
        for section in self._walk_book_sections(stop_in_me=False):
            id_ = section.id
            if id_ in index:
                raise ValueError(f'Repeated section id: {id_}')
            index[id_] = section
        self._section_index = index
        return self._section_index

    def get_section_by_id(self, section_id):
        if self.kind == BOOK:
            index = self._get_section_index()
            return index[section_id]
        else:
            return self.book.get_section_by_id(section_id)

    def has_parts(self):
        if self.kind == BOOK:
            return any(section.kind == PART for section in self.subsections)
        else:
            return self.book.has_parts(section_id)

    @property
    def has_no_html(self):
        return not self.md_files

class BookSectionWithNoFiles(_BookSection):
    def __init__(self, parent, id_, title, kind):
        self.parent = parent
        self.id = id_
        self.title = title
        self.kind = kind
        self._subsections = []
