from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QApplication, QGridLayout, QLabel, QFormLayout
from Orange.widgets import gui
from Orange.widgets import settings
from Orange.widgets.widget import OWWidget, Msg, Output
from Orange.widgets.credentials import CredentialManager

from Orange import data
from orangecontrib.text.corpus import Corpus
from orangecontrib.text.language_codes import lang2code, code2lang
from orangecontrib.text.widgets.utils import ComboBox, ListEdit, CheckListLayout, asynchronous

from orangecontrib.text.mine import MineAPI, MineCredentials
#from orangecontrib.text.mine im



class OWMine(OWWidget):
    class MineDialog(OWWidget):
        name = 'The Mine Credentials'
        want_main_area = False
        resizing_enabled = False
        cm_key = CredentialManager('The Mine API Key')
        key_input = 'test'

        class Error(OWWidget.Error):
            invalid_credentials = Msg('These credentials are invalid.')

        def __init__(self, parent):
            super().__init__()
            self.parent = parent
            self.api = None

            form = QFormLayout()
            form.setContentsMargins(5, 5, 5, 5)
            self.key_edit = gui.lineEdit(self, self, 'key_input', controlWidth=350)
            form.addRow('Key:', self.key_edit)
            self.controlArea.layout().addLayout(form)
            self.submit_button = gui.button(self.controlArea, self, 'OK', self.accept)
                    
            self.load_credentials()

        def load_credentials(self):
            if self.cm_key.key:
                self.key_edit.setText(self.cm_key.key)

        def save_credentials(self):
            self.cm_key.key = self.key_input
            print('WWWWWWWWWWWW77')
            print(self.cm_key.key)
            print('FFFFFFFFFFFF77')
            print(' ')

        def check_credentials(self):
            api = MineCredentials(self.key_input)
            if api.valid:
                self.save_credentials()
            else:
                api = None
            self.api = api
           
        def accept(self, silent=False):
            if not silent: self.Error.invalid_credentials.clear()
            self.check_credentials()
            if self.api:
                self.parent.update_api(self.api)
                super().accept()
            elif not silent:
                self.Error.invalid_credentials()
    """ Get articles from Mine. """
    name = 'Mine'
    priority = 160
    icon = 'icons/MINE-Logo-orange.svg'
    
   
    class Outputs:
        corpus = Output("Corpus", Corpus)
        
    want_main_area = False
    resizing_enabled = False

    label_width = 1
    widgets_width = 2

    attributes = [feat.name for feat in MineAPI.string_attributes]
    text_includes = settings.Setting([feat.name for feat in MineAPI.string_attributes])

    query_list = settings.Setting([])
    language = settings.Setting('en')
    articles_per_query = settings.Setting(10)

    info_label = 'Articles count {:d}'

   #class Error(OWWidget.Error):
    #    api_error = Msg('API error: {}')

    class Warning(OWWidget.Warning):
        no_text_fields = Msg('Text features are inferred when none are selected.')
        
    class Error(OWWidget.Error):
        no_api = Msg('Please provide a valid API key.')
        no_query = Msg('Please provide a query.')
        limit_exceeded = Msg('Requests limit reached.')
        api_error = Msg('API error: {}')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.api = MineAPI(on_error=self.Error.api_error)
        self.corpus = None
        
        query_box = gui.hBox(self.controlArea, 'Query')

        # Queries configuration
        layout = QGridLayout()
        layout.setSpacing(7)
        
        
        self.api_dlg = self.MineDialog(self)
        #self.api_dlg.accept(silent=True)
        gui.button(self.controlArea, self, 'The Mine API Key',
                   callback=self.api_dlg.exec_, focusPolicy=Qt.NoFocus)
                    
        #row = 0
        #self.query_edit = ListEdit(self, 'query_list', "Each line represents a "
        #                                               "separate query.", 100, self)
        row = 0
        self.query_edit2 = ListEdit(self, 'query_list', "Each line represents a separate query.", 30, self)
        #layout.addWidget(QLabel('Query word list:'), row, 0, 1, self.label_width)
        #layout.addWidget(self.query_edit, row, self.label_width, 1,
        #                self.widgets_width)
        
        layout.addWidget(QLabel('Query:'), row, 0, 1, self.label_width)
        layout.addWidget(self.query_edit2, row, self.label_width, 1, self.widgets_width)

        # Language
      #  row += 1
       # language_edit = ComboBox(self, 'language', tuple(sorted(lang2code.items())))
      #  layout.addWidget(QLabel('Language:'), row, 0, 1, self.label_width)
       # layout.addWidget(language_edit, row, self.label_width, 1, self.widgets_width)

        # Articles per query
        row += 1
        layout.addWidget(QLabel('Articles per query:'), row, 0, 1, self.label_width)
        slider = gui.valueSlider(query_box, self, 'articles_per_query', box='',
                                 values=[1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100])
        layout.addWidget(slider.box, row, 1, 1, self.widgets_width)

        query_box.layout().addLayout(layout)
        self.controlArea.layout().addWidget(query_box)

        self.controlArea.layout().addWidget(
        CheckListLayout('Text includes', self, 'text_includes', self.attributes, cols=2, callback=self.set_text_features))

        self.info_box = gui.hBox(self.controlArea, 'Info')
        self.result_label = gui.label(self.info_box, self, self.info_label.format(0))
        
        #self.info_box2 = gui.hBox(self.controlArea, 'Info')
        #self.result_label2 = gui.label(self.info_box, self, self.info_label.format(0))

        self.button_box = gui.hBox(self.controlArea)

        self.search_button = gui.button(self.button_box, self, 'Search', self.start_stop)
        self.search_button.setFocusPolicy(Qt.NoFocus)

        self.button_box = gui.hBox(self.controlArea)

        #self.search_button2 = gui.button(self.button_box, self, 'mineApiTest', self.mine_request)
        #self.search_button2.setFocusPolicy(Qt.NoFocus)

        
    
    #def mine_request(self):
    #    try:
     #       self.search_button2.setText('response-Code' + '200')
     #   except:
     #       self.search_button2.setText('mineApi-ConnectionTimeout')
     #   return mc.mine_request()
    
    def token(self):
        token = MineCredentials.key
        print('WWWWWWWWWWWW88')
        print(token)
        print('FFFFFFFFFFFF88')
        print(' ')
        return token
    
    def update_api(self, api):
        self.Error.no_api.clear()
        self.api = MineAPI(api)
                                  

    
    def start_stop(self):
        if self.search.running:
            self.search.stop()
        else:
            self.search()

    @asynchronous
    def search(self):
        #print('WWWWWWWWWWWW2')t
        #print(self)
        #print('FFFFFFFFFFFF2')
        tempd = self.api.search(token=self.token, lang=self.language, queries=self.query_list,
                                articles_per_query=self.articles_per_query,
                                on_progress=self.progress_with_info,
                                should_break=self.search.should_break)
        return tempd
       

    @search.callback(should_raise=False)
    def progress_with_info(self, progress, n_retrieved):
        self.progressBarSet(100 * progress)
        self.result_label.setText(self.info_label.format(n_retrieved))

    @search.on_start
    def on_start(self):
        self.Error.api_error.clear()
        self.progressBarInit()
        self.search_button.setText('Stop')
        self.result_label.setText(self.info_label.format(0))
        self.Outputs.corpus.send(None)

    @search.on_result
    def on_result(self, result):
        self.result = result
        self.result_label.setText(self.info_label.format(len(result) if result else 0))
        #self.search_button2.setText('mineApiTest')
        self.search_button.setText('Search')
        self.set_text_features()
        self.progressBarFinished()

    def set_text_features(self):
        self.Warning.no_text_fields.clear()
        if not self.text_includes:
            self.Warning.no_text_fields()

        if self.result is not None:
            print('WWWWWWWWWWWW44')
            print(self.result)
            print('FFFFFFFFFFFF44')
            print(' ')
            vars_ = [var for var in self.result.domain.metas if var.name in self.text_includes]
            self.result.set_text_features(vars_ or None)
            self.Outputs.corpus.send(self.result)
            #print('TTTTTTTT')
            #print(self.result)
            
    def send_report(self):
        if self.result:
            items = (('Language', code2lang[self.language]),
                     ('Query', self.query_edit.toPlainText()),
                     ('Articles count', len(self.result)))
            self.report_items('Query', items)


if __name__ == '__main__':
    #key = os.getenv('THE_GUARDIAN_API_KEY', 'test')
    credentials = MineCredentials(key)
    api = MineAPI(credentials=credentials)
    app = QApplication([])
    widget = OWMine()
    widget.show()
    app.exec()
    widget.saveSettings()
