import unittest

from Orange.data import Table
from Orange.distance import Euclidean
from Orange.widgets.tests.base import WidgetTest

from orangecontrib.text.widgets.owduplicates import OWDuplicates


class TestCorpusViewerWidget(WidgetTest):
    def setUp(self):
        self.widget = self.create_widget(OWDuplicates)
        self.data = Table.from_file('iris')
        self.distances = Euclidean(self.data)

    def test_duplicates(self):
        self.send_signal(self.widget.Inputs.distances, self.distances)
        self.widget.table_view.selectRow(0)
        out_corpus = self.get_output(self.widget.Outputs.duplicates)
        self.assertEqual(len(out_corpus), 2)
        self.widget.table_view.selectRow(3)
        out_corpus = self.get_output(self.widget.Outputs.duplicates)
        self.assertEqual(len(out_corpus), 1)


if __name__ == "__main__":
    unittest.main()