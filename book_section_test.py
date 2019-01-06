
import unittest
import tempfile
from dataclasses import dataclass
from pathlib import Path
import io

from book_section import (BookSection, _parse_header_line, BOOK, CHAPTER, PART,
                          SUBCHAPTER)


class ParseHeadersTest(unittest.TestCase):
    def test_parse_header(self):
        res = _parse_header_line('#chapter {#capitulo1 $chapter}')
        assert res == {'id': 'capitulo1',
                       'level': 1,
                       'section_kind': CHAPTER,
                       'text': 'chapter'}

        res = _parse_header_line('##chapter {$chapter}')
        assert res == {'level': 2,
                       'section_kind': CHAPTER,
                       'text': 'chapter'}
        res = _parse_header_line('#chapter {#capitulo1}')
        assert res == {'level': 1,
                       'text': 'chapter',
                       'id': 'capitulo1'}

        res = _parse_header_line('### chapter')
        assert res == {'level': 3,
                       'text': 'chapter'}


@dataclass
class _MarkdownFile:
    path: 'typing.Any'
    content: str

@dataclass
class _Directory:
    path: 'typing.Any'
    content: 'typing.Any'


def _create_book_files(base_dir, file_or_directory):
    klass = file_or_directory.__class__.__name__
    if klass == '_MarkdownFile':
        file = file_or_directory
        path = base_dir / file.path
        fhand = path.open('wt')
        fhand.write(file.content)
        fhand.close()
    elif klass == '_Directory':
        directory = file_or_directory
        this_dir_base_dir = base_dir / directory.path
        this_dir_base_dir.mkdir(exist_ok=True)
        for item_in_directory in directory.content:
            _create_book_files(this_dir_base_dir, item_in_directory)
    else:
        raise ValueError('We expect a _MarkdownFile or a _Directory')


ONE_CHAPTER = '''### This is one chapter {#capitulo1 $chapter}
Chapter content.
'''

CHAPTER_WITH_NO_ID_AND_NO_KIND = '''# A chapter with no id
blah, blah, blah.
'''

ONE_SUBCHAPTER = '''# This is one subchapter
Some text in the subchapter
'''

PART1 = '''# Part1 Title {$part}
Some intro to the part.
'''

BOOK_METADATA = '''---
title:  'The book title'
---

%%%
This is a comment
%%%
'''

chapter1_md = _MarkdownFile(path=Path('chapter_one.md'),
                            content=ONE_CHAPTER)
chapter1 = _Directory(path=Path('chapter1'),
                      content=[chapter1_md])
chapter2_md = _MarkdownFile(path=Path('chapter_two.md'),
                            content=CHAPTER_WITH_NO_ID_AND_NO_KIND)
chapter2 = _Directory(path=Path('chapter2'),
                      content=[chapter2_md])
book_md = _MarkdownFile(path=Path('book.md'),
                        content=BOOK_METADATA)
BOOK1_STRUCTURE = _Directory(path='',
                             content=[book_md, chapter1, chapter2])

part_md = _MarkdownFile(path=Path('part.md'),
                        content=PART1)
part1 = _Directory(path=Path('00_part1'),
                   content=[part_md, chapter1])
subchapter_md = _MarkdownFile(path=Path('subchapter.md'),
                              content=ONE_SUBCHAPTER)
subchapter = _Directory(path=Path('subchapter'),
                        content=[subchapter_md])
chapter2 = _Directory(path=Path('chapter2'),
                      content=[chapter2_md, subchapter])
BOOK2_STRUCTURE = _Directory(path='',
                             content=[book_md, part1, chapter2])

class GetSectionsTest(unittest.TestCase):
    def _prepare_book_md_files(self, book_dir_structure):
        temp_dir = tempfile.TemporaryDirectory(prefix='book_')

        _create_book_files(base_dir=Path(temp_dir.name),
                           file_or_directory=book_dir_structure)
        return temp_dir

    def _assert_paths_equal_to_paths(self, abolute_paths1, relative_paths, relative_to_path):
        assert [str(path.relative_to(relative_to_path)) for path in abolute_paths1] == relative_paths

    def test_simple_main_md(self):

        with self._prepare_book_md_files(BOOK1_STRUCTURE) as book_dir:
            book = BookSection(Path(book_dir))
            self._assert_paths_equal_to_paths(book.md_files,
                                              ['book.md'],
                                              book_dir)
            assert book.kind == BOOK
            assert book.id == None
            assert book.title == 'The book title'
            assert ''.join(book.md_text) == '\n'
            assert book.is_within_a_part() is None

            chapter1, chapter2 = book.subsections

            section = chapter1
            assert section.idx == 1
            assert section.dir.relative_to(book_dir) == Path('chapter1')
            self._assert_paths_equal_to_paths(section.md_files,
                                              ['chapter1/chapter_one.md'],
                                              book_dir)
            assert section.kind == CHAPTER
            assert section.id == 'capitulo1'
            assert section.title == 'This is one chapter'
            assert not section.subsections
            assert not section.is_within_a_part()
            assert list(section.md_text) == ['# This is one chapter\n',
                                             '\n',
                                             'Chapter content.\n']

            section = chapter2
            assert section.kind == CHAPTER
            assert section.idx == 2
            assert section.dir.relative_to(book_dir) == Path('chapter2')
            self._assert_paths_equal_to_paths(section.md_files,
                                              ['chapter2/chapter_two.md'],
                                              book_dir)
            assert section.kind == CHAPTER
            assert section.id == 'chapter_2'
            assert section.title == 'A chapter with no id'
            assert not section.subsections
            assert not section.is_within_a_part()
            assert list(section.md_text) == ['# A chapter with no id\n',
                                             '\n',
                                             'blah, blah, blah.\n']

        with self._prepare_book_md_files(BOOK2_STRUCTURE) as book_dir:
            book = BookSection(Path(book_dir))
            self._assert_paths_equal_to_paths(book.md_files,
                                              ['book.md'],
                                              book_dir)

            part1, chapter2 = book.subsections

            section = part1
            assert section.idx == 1
            assert section.dir.relative_to(book_dir) == Path('00_part1')
            self._assert_paths_equal_to_paths(section.md_files,
                                              ['00_part1/part.md'],
                                              book_dir)
            assert section.kind == PART
            assert section.id == 'part_1'
            assert section.title == 'Part1 Title'
            assert section.is_within_a_part() is None
            assert list(section.md_text) == ['# Part1 Title\n',
                                             '\n',
                                             'Some intro to the part.\n']

            chapter1, = section.subsections
            section = chapter1
            assert section.idx == 1
            assert section.dir.relative_to(book_dir) == Path('00_part1/chapter1')
            assert section.kind == CHAPTER
            assert section.id == 'capitulo1'
            assert not section.subsections
            assert section.is_within_a_part()
            assert list(section.md_text) == ['## This is one chapter\n',
                                             '\n',
                                             'Chapter content.\n']

            section = chapter2
            self._assert_paths_equal_to_paths(section.md_files,
                                              ['chapter2/chapter_two.md'],
                                              book_dir)
            assert section.kind == CHAPTER
            assert section.idx == 2
            assert section.id == 'chapter_2'
            assert not section.is_within_a_part()
            assert list(section.md_text) == ['# A chapter with no id\n',
                                             '\n',
                                             'blah, blah, blah.\n']

if __name__ == '__main__':
    unittest.main()
