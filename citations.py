
from pathlib import Path
from pprint import pprint
import unittest

import bibtexparser
import dateparser
import locale


DEFAULT_LANG = 'es'

LOCALES = {'es': 'ES_ES',
           'en': 'EN_US'}

COPULATIVE_CONJUNTION = {'es': 'y', 'en': 'and'}


def load_bibliography_db(bibtex_path):

    with bibtex_path.open('rt') as bibtex_fhand:
        bibtex_db = bibtexparser.load(bibtex_fhand)
    return bibtex_db


def _parse_autors(authors):
    authors = [bibtexparser.customization.splitname(author.strip()) for author in authors.split(' and ')]
    return authors


def _join_items_with_copulative_conjuntion(text_items, lang):
    if len(text_items) == 1:
        return text_items[0]

    all_but_last_items = text_items[:-1]
    last_item = text_items[-1]
    text = ', '.join(all_but_last_items)

    if lang == 'en':
        text += ','

    text += ' ' + COPULATIVE_CONJUNTION[lang] + ' ' + last_item
    return text


def _strip_latex_parentheses(text):
    return text.lstrip('{').rstrip('}')


def _buil_locator_text(locator):
    if locator is None:
        return None

    locator_term =  locator.get('locator_term', None)

    if locator_term:
        locator_text = locator_term + ' '
    else:
         locator_text = ''

    position = locator.get('locator_positions', None)
    if position:
        if isinstance(position, (str, int)):
            raise ValueError('locator_position should be a list with one or two integers')
        elif len(position) == 1:
            locator_text += str(position[0])
        elif len(position) == 2:
            locator_text += str(position[0]) + '-' + str(position[1])
        else:
            raise RuntimeError('locator_position should be a list with one o two integers')

    return locator_text


_LAST_CITATION_CACHE = None


def create_citation_note(bibliography_db, entry_key, locator=None,
                         clear_last_cache_entry=False,
                         lang=DEFAULT_LANG):
    entry = bibliography_db.entries_dict[entry_key]
    #pprint(entry)

    global _LAST_CITATION_CACHE

    if clear_last_cache_entry:
        _LAST_CITATION_CACHE = None

    if (_LAST_CITATION_CACHE is not None and
        _LAST_CITATION_CACHE['entry']['ID'] == entry['ID']):
        entry_same_as_previous_one = True
    else:
        entry_same_as_previous_one = False

    if  _LAST_CITATION_CACHE:
        different_locator = _LAST_CITATION_CACHE['locator'] == locator
    else:
        same_locator_or_no_locator_in_cache = False

    if entry_same_as_previous_one:
        if locator is None and _LAST_CITATION_CACHE['locator'] is not None:
            ibid = False
        else:
            ibid = True
    else:
        ibid = False

    if ibid:
        surname_text = None
        title = None
    else:
        author = entry.get('author', None)
        authors = _parse_autors(author) if author else None

        editor = entry.get('editor', None)
        editors = _parse_autors(editor) if editor else None

        people = authors if authors else editors
        if people:
            surnames = [' '.join(author['last']) for author in people]
            surname_text = _join_items_with_copulative_conjuntion(surnames,
                                                                  lang=lang)
        else:
            surname_text = None

        title = _strip_latex_parentheses(entry['title'])

    if ibid and locator == _LAST_CITATION_CACHE['locator']:
        locator_text = None
    else:
        locator_text = _buil_locator_text(locator)

    if ibid:
        if locator_text:
            citation_html = f'Ibid, {locator_text}.'
        else:
            citation_html = f'Ibid.'
    else:
        if surname_text and locator_text:
            citation_html = f'{surname_text}, <i>{title}</i>, {locator_text}.'
        elif surname_text:
            citation_html = f'{surname_text}, <i>{title}</i>.'
        elif locator_text:
            citation_html = f'“{title}”, {locator_text}.'
        else:
            if lang == 'en':
                citation_html = f'“{title}.”'
            else:
                citation_html = f'“{title}”.'
    _LAST_CITATION_CACHE = {'entry': entry, 'locator': locator}

    return citation_html


def _get_first_and_last_author_strings(author):
    if 'first' in author:
        first = ' '.join(author['first'])
    else:
        first = None
    if 'last' in author:
        last = ' '.join(author['last'])
    else:
        last = None
    return {'first': first, 'last': last}


def _join_lastname_firstname(author):
    author = _get_first_and_last_author_strings(author)

    if author['last'] and author['first']:
        name = f'{author["last"]}, {author["first"]}'
    elif not author['last'] and author['first']:
        name = f'{author["first"]}'
    elif author['last'] and not author['first']:
        name = f'{author["last"]}'
    else:
        raise ValueError('Malformed author')
    return name


def _join_firstname_lastname(author):
    author = _get_first_and_last_author_strings(author)

    if author['last'] and author['first']:
        name = f"{author['first']} {author['last']}"
    elif not author['last'] and author['first']:
        name = f'{author["first"]}'
    elif author['last'] and not author['first']:
        name = f'{author["last"]}'
    else:
        raise ValueError('Malformed author')
    return name


def _create_authors_string(authors, lang):
    first_author = _join_lastname_firstname(authors[0])
    other_authors = [_join_firstname_lastname(author) for author in authors[1:]]
    return _join_items_with_copulative_conjuntion([first_author] + other_authors,
                                                  lang)


def create_bibliography_citation(bibliography_db, entry_key,
                                 lang=DEFAULT_LANG):
    locale.setlocale(locale.LC_ALL, LOCALES[lang])
    entry = bibliography_db.entries_dict[entry_key]
    author = entry.get('author', None)
    if author:
        authors_string = _create_authors_string(_parse_autors(author), lang)
    else:
        authors_string = None

    editor = entry.get('editor', None)
    if editor:
        editors_string = _create_authors_string(_parse_autors(editor), lang)
    else:
        editors_string = None

    title = _strip_latex_parentheses(entry['title'])

    publisher = entry.get('publisher', None)
    year = entry.get('year', None)

    url = entry.get('url', None)
    urldate = entry.get('urldate', None)
    if urldate:
        urldate = dateparser.parse(urldate)
        if lang == 'es':
            urldate = urldate.strftime('Consultado el %d de %B de %Y')
        else:
            urldate = urldate.strftime('Accessed %B %d, %Y')
    booktitle = entry.get('booktitle', None)

    if False:
        print(authors_string)
        print(title)
        print(publisher)
        pprint(year)

    if url:
        accessed_date = urldate
        result = f'{booktitle}. “{title}”. {accessed_date}. {url}.'
        #Yale University. “About Yale: Yale Facts.” Accessed May 1, 2017. https://www.yale.edu/about-yale/yale-facts.
    else:
        if authors_string and title and publisher and year:
            result = f'{authors_string}. <i>{title}</i>. {publisher}, {year}.'
        elif editors_string and title and publisher and year:
            result = f'{editors_string}, ed. <i>{title}</i>. {publisher}, {year}.'

    result = result.replace('..', '.')
    return result


class CitationNoteTest(unittest.TestCase):
    def test_citation_note(self):
        bibliography_db = load_bibliography_db(Path('bibliografia_arte.bibtex'))

        citation_html = create_citation_note(bibliography_db, 'shortintro')
        assert citation_html == 'Okasha, <i>Philosophy of science : a very short introduction</i>.'

        citation_html = create_citation_note(bibliography_db, 'pigli2013', {'locator_term': 'página',
                                                                            'locator_positions': [10]})
        assert citation_html == 'Pigliucci y Boudry, <i>Philosophy of Pseudoscience: Reconsidering the Demarcation Problem</i>, página 10.'
        citation_html = create_citation_note(bibliography_db, 'pigli2013', {'locator_term': 'página',
                                                                            'locator_positions': [10]})
        assert citation_html == 'Ibid.'
        citation_html = create_citation_note(bibliography_db, 'pigli2013', {'locator_term': 'página',
                                                                            'locator_positions': [11]})
        assert citation_html == 'Ibid, página 11.'
        citation_html = create_citation_note(bibliography_db, 'pigli2013', {'locator_term': 'página',
                                                                            'locator_positions': [11]},
                                            clear_last_cache_entry=True)
        assert citation_html == 'Pigliucci y Boudry, <i>Philosophy of Pseudoscience: Reconsidering the Demarcation Problem</i>, página 11.'
        citation_html = create_citation_note(bibliography_db, 'pigli2013')
        assert citation_html == 'Pigliucci y Boudry, <i>Philosophy of Pseudoscience: Reconsidering the Demarcation Problem</i>.'

        citation_html = create_citation_note(bibliography_db, 'pigli2013')
        assert citation_html == 'Ibid.'

        citation_html = create_citation_note(bibliography_db, 'hebb')
        assert citation_html == '“Hebbian theory”.'


class BibiliographyCitationTest(unittest.TestCase):
    def test_bibliography_citation(self):
        bibliography_db = load_bibliography_db(Path('bibliografia_arte.bibtex'))

        citation_html = create_bibliography_citation(bibliography_db, 'shortintro')
        assert citation_html == 'Okasha, Samir. <i>Philosophy of science : a very short introduction</i>. Oxford University Press, 2002.'

        citation_html = create_bibliography_citation(bibliography_db, 'pigli2013')
        assert citation_html == 'Pigliucci, Massimo y Maarten Boudry, ed. <i>Philosophy of Pseudoscience: Reconsidering the Demarcation Problem</i>. The University of Chicago Press, 2013.'

        citation_html = create_bibliography_citation(bibliography_db, 'deceptive')
        assert citation_html == 'The Great Courses. “Your Deceptive Mind: A Scientific Guide to Critical Thinking”. Consultado el 23 de septiembre de 2016. http://www.thegreatcourses.com/courses/your-deceptive-mind-a-scientific-guide-to-critical-thinking-skills.html.'

if __name__ == '__main__':

    unittest.main()
