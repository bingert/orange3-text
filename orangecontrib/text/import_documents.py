import contextlib
import fnmatch
import logging
import os
import pathlib
import re
import yaml
from urllib.parse import quote, unquote
from requests.exceptions import ConnectionError

from collections import namedtuple
from tempfile import NamedTemporaryFile
from types import SimpleNamespace as namespace
from typing import List, Tuple, Callable
from unicodedata import normalize

import numpy as np
import pandas as pd

import docx2txt
from odf.opendocument import load
from odf import text, teletype

from pdfminer.pdfparser import PDFParser, PDFDocument
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTTextBox, LTTextLine
from bs4 import BeautifulSoup

import serverfiles

from Orange.data import DiscreteVariable, Domain, StringVariable
from Orange.data.io import detect_encoding, UrlReader as CoreUrlReader
from Orange.data.util import get_unique_names
from Orange.util import Registry

from orangecontrib.text.corpus import Corpus

DefaultFormats = ("docx", "odt", "txt", "pdf", "xml")

TextData = namedtuple(
    "Text",
    ["name", "path", "ext", "category", "content"]
)
TextData.isvalid = property(lambda self: True)

TextDataError = namedtuple(
    "TextDataError",
    ["path", "error", "error_str"]
)
TextDataError.isvalid = property(lambda self: False)

log = logging.getLogger(__name__)


class NoDocumentsException(Exception):
    pass


class Reader(metaclass=Registry):
    def __init__(self, path, replace_white_space=False):
        self.path = path
        self.replace_white_space = replace_white_space
        self.content = None

    @classmethod
    def get_reader(cls, path):
        ext = pathlib.Path(path).suffix
        for _reader in cls.registry:
            reader = eval(_reader)
            if ext in reader.ext:
                return reader(path)
        return Reader(path)

    def read(self, ):
        error = ""
        try:
            self.read_file()
        except Exception as ex:
            textdata = None
            error = "{}".format(pathlib.Path(self.path).name)
            log.exception('Error reading failed', exc_info=ex)
        else:
            textdata = self.make_text_data()
        return textdata, error

    def read_file(self):
        raise NotImplementedError("No reader for {}".format(pathlib.Path(self.path).suffix))

    def make_text_data(self):
        name = pathlib.Path(self.path).stem
        directory = pathlib.PurePath(self.path).parent
        category = directory.parts[-1] or "None"
        if self.replace_white_space:
            self.content = re.sub(r'\s+', ' ', self.content)
        return TextData(name, self.path, self.ext, category, self.content)


class TxtReader(Reader):
    ext = [".txt"]

    def read_file(self):
        encoding = detect_encoding(self.path)
        with open(self.path, 'r', encoding=encoding) as f:
            self.content = f.read()


class DocxReader(Reader):
    ext = [".docx"]

    def read_file(self):
        self.content = docx2txt.process(self.path)


class OdtReader(Reader):
    ext = [".odt"]

    def read_file(self):
        odtfile = load(self.path)
        texts = odtfile.getElementsByType(text.P)
        self.content = " ".join(teletype.extractText(t) for t in texts)


class PdfReader(Reader):
    """
    char_margin — two text chunks whose distance is closer than this value are considered
    contiguous and get grouped into one.
    word_margin — it may be required to insert blank characters (spaces) as necessary if
    the distance between two words is greater than this value, as a blank between words might
    not be represented as a space, but indicated by the positioning of each word.
    """
    ext = [".pdf"]

    def read_file(self):
        with open(self.path, 'rb') as f:
            parser = PDFParser(f)
        doc = PDFDocument()
        parser.set_document(doc)
        doc.set_parser(parser)
        doc.initialize('')
        rsrcmgr = PDFResourceManager()
        laparams = LAParams()
        laparams.char_margin = 0.1
        laparams.word_margin = 1.0
        device = PDFPageAggregator(rsrcmgr, laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        extracted_text = []

        for page in doc.get_pages():
            interpreter.process_page(page)
            layout = device.get_result()
            for lt_obj in layout:
                if isinstance(lt_obj, LTTextBox) or isinstance(lt_obj, LTTextLine):
                    extracted_text.append(lt_obj.get_text())
        self.content = ' '.join(extracted_text).replace('\x00', '')


class XmlReader(Reader):
    ext = [".xml"]

    def read_file(self):
        encoding = detect_encoding(self.path)
        with open(self.path, encoding=encoding, errors='ignore') as markup:
            soup = BeautifulSoup(markup.read(), "lxml")
        self.content = soup.get_text()


class CsvMetaReader(Reader):
    ext = [".csv"]

    def read_file(self):
        self.content = pd.read_csv(self.path)


class YamlMetaReader(Reader):
    ext = [".yaml"]

    def read_file(self):
        with open(self.path, "r") as f:
            self.content = yaml.safe_load(f)


class UrlReader(Reader, CoreUrlReader):
    ext = [".url"]

    def __init__(self, path, *args):
        CoreUrlReader.__init__(self, path)
        Reader.__init__(self, path, *args)

    def read_file(self):
        # unquote prevent double quoting when filename is already quoted
        # when not quoted it doesn't change url - it is required since Orange's
        # UrlReader quote urls in version 3.29 but not in older versions
        self.filename = quote(unquote(self.filename), safe="/:")
        self.filename = self._trim(self._resolve_redirects(self.filename))
        with contextlib.closing(self.urlopen(self.filename)) as response:
            name = self._suggest_filename(
                response.headers["content-disposition"])
            extension = "".join(pathlib.Path(name).suffixes)
            with NamedTemporaryFile(suffix=extension, delete=False) as f:
                f.write(response.read())
            reader = Reader.get_reader(f.name)
            reader.read_file()
            self.content = reader.content
            os.remove(f.name)

    def make_text_data(self):
        text_data = super().make_text_data()
        ext = pathlib.Path(self.path).suffix
        return TextData(text_data.name, text_data.path, [ext],
                        text_data.category, text_data.content)


class ImportDocuments:
    META_DATA_FILE_KEY = "Text file"

    def __init__(self, startdir: str,
                 is_url: bool = False,
                 formats: Tuple[str] = DefaultFormats,
                 report_progress: Callable = None):
        if is_url and not startdir.endswith("/"):
            startdir += "/"
        elif not is_url:
            startdir = os.path.join(startdir, "")
        self.startdir = startdir
        self.formats = formats
        self._report_progress = report_progress
        self.cancelled = False
        self._is_url = is_url
        self._text_data = []
        self._meta_data: pd.DataFrame = None

    def run(self) -> Tuple[Corpus, List]:
        self._text_data, errors_text = self._read_text_data()
        self._meta_data, errors_meta = self._read_meta_data()
        corpus = self._create_corpus()
        corpus = self._add_metadata(corpus)
        return corpus, errors_text + errors_meta

    def _read_text_data(self):
        text_data = []
        errors = []
        patterns = ["*.{}".format(fmt.lower()) for fmt in self.formats]
        scan = self.scan_url if self._is_url else self.scan
        paths = scan(self.startdir, include_patterns=patterns)
        n_paths = len(paths)
        batch = []

        if n_paths == 0:
            raise NoDocumentsException()

        for path in paths:
            if len(batch) == 1 and self._report_progress is not None:
                self._report_progress(
                    namespace(progress=len(text_data) / n_paths,
                              lastpath=path,
                              batch=batch))
                batch = []

            reader = Reader.get_reader(path) if not self._is_url \
                else UrlReader(path)
            text, error = reader.read()
            if text is not None:
                text_data.append(text)
                batch.append(text_data)
            else:
                errors.append(error)

            if self.cancelled:
                return

        return text_data, errors

    def _read_meta_data(self):
        scan = self.scan_url if self._is_url else self.scan
        patterns = ["*.csv", "*.yaml", "*.yml"]
        paths = scan(self.startdir, include_patterns=patterns)
        meta_dfs, errors = [], []
        for path in paths:
            reader = Reader.get_reader(path) if not self._is_url \
                else UrlReader(path)
            data, error = reader.read()
            if data is not None:
                content = data.content
                if isinstance(content, dict):
                    content = pd.DataFrame(content, index=[0])
                meta_dfs.append(content)
            else:
                errors.append(error)

            if self.cancelled:
                return

        return pd.concat(meta_dfs) if meta_dfs else None, errors

    def _create_corpus(self) -> Corpus:
        corpus = None
        names = ["name", "path", "content"]
        data = []
        category_data = []
        text_categories = list(set(t.category for t in self._text_data))
        values = list(set(text_categories))
        category_var = DiscreteVariable.make("category", values=values)
        for textdata in self._text_data:
            data.append(
                [
                    # some characters are written as decomposed (č is char c
                    # and separate char for caron), with NFC normalization we
                    # normalize them to be written as precomposed (č is one
                    # unicode char - 0x10D)
                    # https://docs.python.org/3/library/unicodedata.html#unicodedata.normalize
                    normalize('NFC', textdata.name),
                    normalize('NFC', textdata.path),
                    normalize('NFC', textdata.content)
                ]
            )
            category_data.append(category_var.to_val(textdata.category))
        if len(text_categories) > 1:
            category_data = np.array(category_data)
        else:
            category_var = []
            category_data = np.empty((len(data), 0))
        domain = Domain(
            [], category_var, [StringVariable.make(name) for name in names]
        )
        domain["name"].attributes["title"] = True
        data = np.array(data, dtype=object)
        if len(data):
            corpus = Corpus(domain,
                            Y=category_data,
                            metas=data,
                            text_features=[domain.metas[2]])

        return corpus

    def _add_metadata(self, corpus: Corpus) -> Corpus:
        if "path" not in corpus.domain or self._meta_data is None \
                or self.META_DATA_FILE_KEY not in self._meta_data.columns:
            return corpus

        df = self._meta_data.set_index(
            self.startdir + self._meta_data[self.META_DATA_FILE_KEY]
        )
        path_column = corpus.get_column_view("path")[0]
        if len(df.index.drop_duplicates()) != len(df.index):
            df = df[~df.index.duplicated(keep='first')]
        filtered = df.reindex(path_column)
        for column in filtered.columns:
            corpus = corpus.add_column(
                StringVariable(get_unique_names(corpus.domain, column)),
                filtered[column].to_numpy(),
                to_metas=True
            )

        return corpus

    @staticmethod
    def scan(topdir, include_patterns=("*",), exclude_patterns=(".*",)):
        """
        Yield file system paths under `topdir` that match include/exclude patterns

        Parameters
        ----------
        topdir: str
            Top level directory path for the search.
        include_patterns: List[str]
            `fnmatch.fnmatch` include patterns.
        exclude_patterns: List[str]
            `fnmatch.fnmatch` exclude patterns.

        Returns
        -------
        list of paths
        """
        if include_patterns is None:
            include_patterns = ["*"]

        paths = []

        for dirpath, dirnames, filenames in os.walk(topdir):
            for dirname in list(dirnames):
                # do not recurse into hidden dirs
                if fnmatch.fnmatch(dirname, ".*"):
                    dirnames.remove(dirname)

            filenames = [fname for fname in filenames
                         if matches_any(fname, include_patterns)
                            and not matches_any(fname, exclude_patterns)]
            paths = paths + [os.path.join(dirpath, fname) for fname in filenames]
        return paths

    @staticmethod
    def scan_url(topdir: str, include_patterns: Tuple[str] = ("*",),
                 exclude_patterns: Tuple[str] = (".*",)) -> List[str]:
        try:
            files = serverfiles.ServerFiles(topdir).listfiles()
        except ConnectionError:
            return []

        include_patterns = include_patterns or ("*",)
        paths = []
        for filename in files:
            path = topdir + "/".join(filename)
            if matches_any(path, include_patterns) and \
                    not matches_any(path, exclude_patterns):
                paths.append(path)
        return paths


def matches_any(fname: str, patterns: Tuple[str]) -> bool:
    return any(fnmatch.fnmatch(fname.lower(), pattern)
               for pattern in patterns)
