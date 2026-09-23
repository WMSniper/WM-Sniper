import sys
import time
import requests
import warnings
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, QPushButton, 
                             QHBoxLayout, QScrollArea, QFrame, QDialog, QFormLayout, 
                             QLineEdit, QComboBox, QDialogButtonBox, QListWidget, 
                             QListWidgetItem, QAbstractItemView, QSizePolicy, QShortcut,
                             QTabWidget, QMessageBox, QStyle)
from PyQt5.QtCore import Qt, QTimer, QPoint, QSize, QPropertyAnimation, QEasingCurve, pyqtSignal, QObject
from PyQt5.QtGui import QCursor, QPixmap, QKeySequence
import pyperclip
import threading
import json
from urllib.parse import urlencode
import os
import uuid

def resource_path(relative_path):
    """Ottieni il percorso assoluto per le risorse, funziona sia in dev che in .exe"""
    try:
        # PyInstaller crea una cartella temporanea e memorizza il percorso in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Ignora tutti i warning di deprecazione
warnings.filterwarnings("ignore", category=DeprecationWarning)

BACKEND_URL = "https://wmsniper.onrender.com"
CHECK_INTERVAL = 5  # secondi

def get_persistent_user_id():
    """Restituisce un UUID stabile, nel formato richiesto dal backend."""
    app_data_dir = os.environ.get("APPDATA") or os.path.expanduser("~")
    user_id_path = os.path.join(app_data_dir, "WM-Sniper", "user_id.txt")

    try:
        with open(user_id_path, "r", encoding="utf-8") as user_id_file:
            saved_user_id = user_id_file.read().strip()
        return str(uuid.UUID(saved_user_id))
    except (OSError, ValueError, AttributeError):
        pass

    user_id = str(uuid.uuid4())
    try:
        os.makedirs(os.path.dirname(user_id_path), exist_ok=True)
        with open(user_id_path, "w", encoding="utf-8") as user_id_file:
            user_id_file.write(user_id)
    except OSError:
        # Anche senza poter salvare il file, l'UUID resta valido per questa sessione.
        pass
    return user_id

# Worker semplice per eseguire richieste HTTP fuori dal thread UI
class HttpWorker(QObject):
    success = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    def run(self, func):
        def _target():
            try:
                result = func()
                self.success.emit(result)
            except Exception as e:
                self.error.emit(e)
        t = threading.Thread(target=_target, daemon=True)
        self._thread = t
        t.start()


def to_item_url(display_name: str) -> str:
    # Same normalization used by the backend
    return display_name.replace(" ", "_").lower()

class ToggleIcon(QLabel):
    def __init__(self, overlay_window, parent=None):
        super().__init__(parent)
        self.overlay = overlay_window
        self.setFixedSize(38, 38)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setToolTip("WM Sniper — double-click to show or hide")
        
        # Carica l'icona o usa un placeholder
        icon_path = resource_path("icon.jpg")
        if os.path.exists(icon_path):
            self.setPixmap(QPixmap(icon_path).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.setStyleSheet("""
                background-color: #111b27;
                border-radius: 19px;
                border: 2px solid #e6c676;
                color: #e6c676;
            """)
            self.setText("⚙️")
            self.setAlignment(Qt.AlignCenter)
        
        self.drag_position = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
            
    def mouseReleaseEvent(self, event):
        self.drag_position = None
        
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.overlay.toggle_overlay()
            event.accept()

class OfferWidget(QFrame):
    def __init__(self, offer, overlay_instance):
        super().__init__()
        self.offer = offer
        self.overlay = overlay_instance
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(7,13,20,220);
                border: 1px solid rgba(126,230,231,55);
                border-left: 3px solid #7ee6e7;
                border-radius: 7px;
                margin: 3px 1px;
            }
            QFrame:hover { background-color: rgba(21,43,52,235); border-color: rgba(126,230,231,135); }
            QLabel {
                color: #edf5f5;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton { 
                color: white; 
                border: none; 
                border-radius: 3px; 
                padding: 2px 4px;
                font-size: 9pt;
            }
            #copyButton {
                background-color: #69d6a1;
                color: #07120e;
                min-width: 54px;
            }
            #copyButton:hover {
                background-color: #45a049; 
            }
            #favButton {
                background-color: #e74c3c;
                min-width: 30px;
            }
            #favButton:hover {
                background-color: #c0392b;
            }
            #removeButton {
                background-color: rgba(156,171,183,35);
                border: 1px solid rgba(156,171,183,100);
                min-width: 60px;
            }
            #removeButton:hover {
                background-color: #7f8c8d;
            }
            #stopButton {
                background-color: #e6c676;
                color: #151006;
                min-width: 50px;
            }
            #stopButton:hover {
                background-color: #d35400;
            }
        """)
        
        layout = QHBoxLayout()
        
        # Etichetta principale con testo ridotto
        main_text = f"{offer.get('display_name')} - {offer.get('price')}p"
        self.label = QLabel(main_text)
        self.label.setToolTip(f"Seller: {offer.get('seller')}")
        layout.addWidget(self.label, 1)
        
        # Contenitore per i pulsanti
        btn_container = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        # Pulsanti con dimensioni ottimizzate
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("copyButton")
        copy_btn.setToolTip("Copy message to seller")
        copy_btn.clicked.connect(self.copy_message)
        btn_layout.addWidget(copy_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("removeButton")
        remove_btn.setToolTip("Remove this offer")
        remove_btn.clicked.connect(self.remove_self)
        btn_layout.addWidget(remove_btn)
        
        stop_btn = QPushButton("Stop")
        stop_btn.setObjectName("stopButton")
        stop_btn.setToolTip("Stop watching this item")
        stop_btn.clicked.connect(self.stop_search)
        btn_layout.addWidget(stop_btn)
        
        btn_container.setLayout(btn_layout)
        layout.addWidget(btn_container, 0)
        
        self.setLayout(layout)

    def copy_message(self):
        seller = self.offer.get('seller') or ""
        msg = f"/w {seller} Hi! I want to buy: \"{self.offer.get('display_name')}\" for {self.offer.get('price')} platinum. (warframe.market)"
        pyperclip.copy(msg)

    def remove_self(self):
        # Sopprimi temporaneamente questa notifica (riapparirà al prossimo start_watch)
        try:
            msg_id = f"{self.offer.get('item')}_{self.offer.get('seller')}_{self.offer.get('price')}"
            self.overlay.suppressed_items.add(msg_id)
            if msg_id in self.overlay.notified_items:
                self.overlay.notified_items.remove(msg_id)
            # Rimuovi anche il widget dalla mappa offers_by_item se presente
            item_url = self.offer.get('item')
            if item_url and item_url in self.overlay.offers_by_item:
                try:
                    self.overlay.offers_by_item[item_url].remove(self)
                except ValueError:
                    pass
                if not self.overlay.offers_by_item[item_url]:
                    del self.overlay.offers_by_item[item_url]
        except Exception:
            pass

        self.setParent(None)
        self.deleteLater()
            
    def stop_search(self):
        item_url = self.offer.get('item')
        headers = {'X-User-ID': self.overlay.user_id} if self.overlay.user_id else {}
        self._stop_worker = HttpWorker(self)
        def _task():
            # 1. Ferma la ricerca
            response = requests.post(
                f"{BACKEND_URL}/stop_watch",
                data={'item_url': item_url},
                headers=headers,
                timeout=5
            )
            if response.status_code != 200:
                raise Exception(f"Search Stop Error: {response.text}")
            # 2. Rimuovi le offerte dal backend
            clear_response = requests.post(
                f"{BACKEND_URL}/clear_matches",
                data={'item_url': item_url},
                headers=headers,
                timeout=5
            )
            return (response.status_code, clear_response.status_code, clear_response.text, item_url)
        def _on_success(result):
            stop_code, clear_code, clear_text, it = result
            if stop_code == 200:
                print(f"Ricerca fermata per: {it}")
                if clear_code == 200:
                    print(f"Offerte rimosse per: {it}")
                else:
                    print("Offer Removal Error:", clear_text)
                self.overlay.remove_item_widgets(it)
        def _on_error(e):
            print("Stop search request error:", e)
        self._stop_worker.success.connect(_on_success)
        self._stop_worker.error.connect(_on_error)
        self._stop_worker.run(_task)

class ManualOfferWidget(QFrame):
    def __init__(self, offer, parent=None):
        super().__init__(parent)
        self.offer = offer
        self.parent_tab = parent
        
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(7,13,20,220);
                border: 1px solid rgba(126,230,231,55);
                border-left: 3px solid #e6c676;
                border-radius: 7px;
                margin: 3px 1px;
            }
            QFrame:hover { background-color: rgba(32,37,37,235); border-color: rgba(230,198,118,135); }
            QLabel {
                color: #edf5f5;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton { 
                color: white; 
                border: none; 
                border-radius: 3px; 
                padding: 2px 4px;
                font-size: 9pt;
            }
            #copyButton {
                background-color: #69d6a1;
                color: #07120e;
                min-width: 54px;
            }
            #copyButton:hover {
                background-color: #45a049; 
            }
            #removeButton {
                background-color: rgba(156,171,183,35);
                border: 1px solid rgba(156,171,183,100);
                min-width: 60px;
            }
            #removeButton:hover {
                background-color: #7f8c8d;
            }
        """)
        
        layout = QHBoxLayout()
        
        # Etichetta principale
        main_text = f"{offer.get('display_name')} - {offer.get('price')}p"
        self.label = QLabel(main_text)
        self.label.setToolTip(f"Seller: {offer.get('seller')}")
        layout.addWidget(self.label, 1)
        
        # Contenitore per i pulsanti
        btn_container = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        # Pulsanti
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("copyButton")
        copy_btn.setToolTip("Copy message to seller")
        copy_btn.clicked.connect(self.copy_message)
        btn_layout.addWidget(copy_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("removeButton")
        remove_btn.setToolTip("Remove this offer")
        remove_btn.clicked.connect(self.remove_self)
        btn_layout.addWidget(remove_btn)
        
        btn_container.setLayout(btn_layout)
        layout.addWidget(btn_container, 0)
        
        self.setLayout(layout)

    def copy_message(self):
        seller = self.offer.get('seller') or ""
        msg = f"/w {seller} Hi! I want to buy: \"{self.offer.get('display_name')}\" for {self.offer.get('price')} platinum. (warframe.market)"
        pyperclip.copy(msg)

    def remove_self(self):
        self.setParent(None)
        self.deleteLater()

class ManualSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WM Search")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(550, 400)
        self.setStyleSheet("""
            QDialog { background: #0d141e; color: #edf5f5; }
            QLabel { color: #ccd7d8; font-weight: 600; }
            QLineEdit, QComboBox { min-height: 34px; padding: 0 9px; color: #edf5f5; background: #070b12; border: 1px solid rgba(167,200,221,55); border-radius: 4px; }
            QLineEdit:focus, QComboBox:focus { border-color: #7ee6e7; }
            QPushButton { min-height: 34px; padding: 0 14px; border: 1px solid #e6c676; border-radius: 4px; color: #11120f; font-weight: 700; background: #e6c676; }
            QPushButton:hover { background: #ffe4a0; }
        """)
        layout = QVBoxLayout()
        
        form = QFormLayout()
        
        # Campo per il nome dell'item con autocomplete
        self.item_input = QLineEdit()
        self.item_input.setPlaceholderText("Ex: Ash Prime Set")
        self.item_input.setMinimumWidth(300)
        self.item_input.textChanged.connect(self.on_text_changed)
        form.addRow("Item:", self.item_input)
        
        # Lista per i risultati dell'autocomplete
        self.autocomplete_list = QListWidget()
        self.autocomplete_list.setVisible(False)
        self.autocomplete_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.autocomplete_list.setStyleSheet("""
            QListWidget { 
                background-color: #222; 
                color: white; 
                border: 1px solid #444;
                border-radius: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 0px;
                border-bottom: 1px solid #333;
            }
            QListWidget::item:selected {
                background-color: #2a82da;
            }
        """)
        self.autocomplete_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.autocomplete_list.itemClicked.connect(self.select_autocomplete_item)
        self.autocomplete_list.itemDoubleClicked.connect(self.accept_autocomplete_item)
        
        # Selezione per il rank
        self.rank_combo = QComboBox()
        self.rank_combo.addItems(["All", "Maxed"])
        form.addRow("Rank:", self.rank_combo)
        
        # Campo per l'override del max rank
        self.max_rank_input = QLineEdit()
        self.max_rank_input.setPlaceholderText("3/5/10")
        form.addRow("Max Rank Override:", self.max_rank_input)
        
        layout.addLayout(form)
        layout.addWidget(self.autocomplete_list)
        
        # Pulsanti OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fetch_autocomplete)
        
    def on_text_changed(self, text):
        self.timer.stop()
        if text.strip():
            self.timer.start(300)  # Ritardo di 300ms per evitare troppe richieste
        else:
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
            
    def fetch_autocomplete(self):
        query = self.item_input.text().strip()
        if not query:
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
            return
            
        params = {'q': query, 'limit': 10}
        url = f"{BACKEND_URL}/autocomplete?{urlencode(params)}"
        self._autocomplete_worker = HttpWorker(self)
        def _task():
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                raise Exception(f"Status {resp.status_code}")
            return resp.json()
        self._autocomplete_worker.success.connect(lambda items: self.update_autocomplete_list(items))
        def _on_err(e):
            print("Error autocomplete:", e)
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
        self._autocomplete_worker.error.connect(_on_err)
        self._autocomplete_worker.run(_task)
            
    def update_autocomplete_list(self, items):
        self.autocomplete_list.clear()
        if not items:
            self.autocomplete_list.setVisible(False)
            return
            
        for item in items:
            list_item = QListWidgetItem()
            self.autocomplete_list.addItem(list_item)
            
            # Crea widget semplificato senza icona
            widget = QWidget()
            layout = QHBoxLayout()
            name_label = QLabel(item['display_name'])
            name_label.setStyleSheet("color: white; font-size: 12px; padding: 4px;")
            layout.addWidget(name_label)
            widget.setLayout(layout)
            
            list_item.setSizeHint(widget.sizeHint())
            
            # Salva i dati completi dell'item
            list_item.setData(Qt.UserRole, item)
            
            self.autocomplete_list.setItemWidget(list_item, widget)
            
        self.autocomplete_list.setVisible(True)
        
        # Calcola l'altezza ottimale
        max_height = 300
        item_height = 0
        for i in range(self.autocomplete_list.count()):
            item_height += self.autocomplete_list.sizeHintForRow(i)
        
        # Aggiungi spazio pour il bordo e la barra di scorrimento
        total_height = min(item_height + 10, max_height)
        self.autocomplete_list.setFixedHeight(total_height)
        
    def select_autocomplete_item(self, item):
        item_data = item.data(Qt.UserRole)
        if item_data:
            self.item_input.setText(item_data['display_name'])
            
    def accept_autocomplete_item(self, item):
        self.select_autocomplete_item(item)
        self.autocomplete_list.setVisible(False)
    
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.autocomplete_list.isVisible():
            selected_items = self.autocomplete_list.selectedItems()
            if selected_items:
                self.accept_autocomplete_item(selected_items[0])
                return
        elif event.key() == Qt.Key_Escape and self.autocomplete_list.isVisible():
            self.autocomplete_list.setVisible(False)
            return
            
        super().keyPressEvent(event)
    
    def get_data(self):
        return {
            'item': self.item_input.text().strip(),
            'rank_choice': self.rank_combo.currentText(),
            'max_rank_override': self.max_rank_input.text().strip() or ""
        }

class SearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WM Sniper")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(550, 400)  # Aumentato per più spazio
        self.setStyleSheet("""
            QDialog { background: #0d141e; color: #edf5f5; }
            QLabel { color: #ccd7d8; font-weight: 600; }
            QLineEdit, QComboBox { min-height: 34px; padding: 0 9px; color: #edf5f5; background: #070b12; border: 1px solid rgba(167,200,221,55); border-radius: 4px; }
            QLineEdit:focus, QComboBox:focus { border-color: #7ee6e7; }
            QPushButton { min-height: 34px; padding: 0 14px; border: 1px solid #e6c676; border-radius: 4px; color: #11120f; font-weight: 700; background: #e6c676; }
            QPushButton:hover { background: #ffe4a0; }
        """)
        layout = QVBoxLayout()
        
        form = QFormLayout()
        
        # Campo per il nome dell'item con autocomplete
        self.item_input = QLineEdit()
        self.item_input.setPlaceholderText("Ex: Ash Prime Set")
        self.item_input.setMinimumWidth(300)
        self.item_input.textChanged.connect(self.on_text_changed)
        form.addRow("Item:", self.item_input)
        
        # Lista per i risultati dell'autocomplete
        self.autocomplete_list = QListWidget()
        self.autocomplete_list.setVisible(False)
        self.autocomplete_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.autocomplete_list.setStyleSheet("""
            QListWidget { 
                background-color: #222; 
                color: white; 
                border: 1px solid #444;
                border-radius: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 0px;
                border-bottom: 1px solid #333;
            }
            QListWidget::item:selected {
                background-color: #2a82da;
            }
        """)
        self.autocomplete_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.autocomplete_list.itemClicked.connect(self.select_autocomplete_item)
        self.autocomplete_list.itemDoubleClicked.connect(self.accept_autocomplete_item)
        
        # Campo per il prezzo massimo
        self.max_price_input = QLineEdit()
        self.max_price_input.setPlaceholderText("999999")
        form.addRow("Higher Price:", self.max_price_input)
        
        # Selezione per il rank
        self.rank_combo = QComboBox()
        self.rank_combo.addItems(["All", "Maxed"])
        form.addRow("Rank:", self.rank_combo)
        
        # Campo per l'override del max rank
        self.max_rank_input = QLineEdit()
        self.max_rank_input.setPlaceholderText("3/5/10")
        form.addRow("Max Rank Override:", self.max_rank_input)
        
        layout.addLayout(form)
        layout.addWidget(self.autocomplete_list)
        
        # Pulsanti OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fetch_autocomplete)
        
    def on_text_changed(self, text):
        self.timer.stop()
        if text.strip():
            self.timer.start(300)  # Ritardo di 300ms per evitare troppe richieste
        else:
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
            
    def fetch_autocomplete(self):
        query = self.item_input.text().strip()
        if not query:
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
            return
            
        params = {'q': query, 'limit': 10}
        url = f"{BACKEND_URL}/autocomplete?{urlencode(params)}"
        self._autocomplete_worker = HttpWorker(self)
        def _task():
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                raise Exception(f"Status {resp.status_code}")
            return resp.json()
        self._autocomplete_worker.success.connect(lambda items: self.update_autocomplete_list(items))
        def _on_err(e):
            print("Error autocomplete:", e)
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
        self._autocomplete_worker.error.connect(_on_err)
        self._autocomplete_worker.run(_task)
            
    def update_autocomplete_list(self, items):
        self.autocomplete_list.clear()
        if not items:
            self.autocomplete_list.setVisible(False)
            return
            
        for item in items:
            list_item = QListWidgetItem()
            self.autocomplete_list.addItem(list_item)
            
            # Crea widget semplificato senza icona
            widget = QWidget()
            layout = QHBoxLayout()
            name_label = QLabel(item['display_name'])
            name_label.setStyleSheet("color: white; font-size: 12px; padding: 4px;")
            layout.addWidget(name_label)
            widget.setLayout(layout)
            
            list_item.setSizeHint(widget.sizeHint())
            
            # Salva i dati completi dell'item
            list_item.setData(Qt.UserRole, item)
            
            self.autocomplete_list.setItemWidget(list_item, widget)
            
        self.autocomplete_list.setVisible(True)
        
        # Calcola l'altezza ottimale
        max_height = 300
        item_height = 0
        for i in range(self.autocomplete_list.count()):
            item_height += self.autocomplete_list.sizeHintForRow(i)
        
        # Aggiungi spazio pour il bordo e la barra di scorrimento
        total_height = min(item_height + 10, max_height)
        self.autocomplete_list.setFixedHeight(total_height)
        
    def select_autocomplete_item(self, item):
        item_data = item.data(Qt.UserRole)
        if item_data:
            self.item_input.setText(item_data['display_name'])
            
    def accept_autocomplete_item(self, item):
        self.select_autocomplete_item(item)
        self.autocomplete_list.setVisible(False)
    
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.autocomplete_list.isVisible():
            selected_items = self.autocomplete_list.selectedItems()
            if selected_items:
                self.accept_autocomplete_item(selected_items[0])
                return
        elif event.key() == Qt.Key_Escape and self.autocomplete_list.isVisible():
            self.autocomplete_list.setVisible(False)
            return
            
        super().keyPressEvent(event)
    
    def get_data(self):
        return {
            'item': self.item_input.text().strip(),
            'max_price': self.max_price_input.text().strip() or "999999",
            'rank_choice': self.rank_combo.currentText(),
            'max_rank_override': self.max_rank_input.text().strip() or ""
        }

class ManualSearchTab(QWidget):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.current_item = None
        self.current_rank = "All"
        self.displayed_offers = {}
        self.stopped_items = set()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Etichetta informazioni
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: white; font-size: 10pt; padding: 5px;")
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)
        
        # Area scroll per i risultati
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: rgba(30,30,30,150); border-radius: 5px;")
        
        self.content = QWidget()
        self.vbox = QVBoxLayout()
        self.vbox.setAlignment(Qt.AlignTop)
        self.content.setLayout(self.vbox)
        self.scroll.setWidget(self.content)
        
        layout.addWidget(self.scroll)
        self.setLayout(layout)
        
        # Timer per aggiornamento periodico
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_offers)
        self.timer.start(10000)  # Aggiorna ogni 10 secondi
    
    def search_offers(self, item_name, rank_choice, max_rank_override=""):
        if not item_name:
            self.info_label.setText("Please enter a valid item name")
            return
            
        self.current_item = item_name
        self.current_rank = rank_choice
        self.max_rank_override = max_rank_override
        self.info_label.setText(f"Research in progress for: {item_name}...")
        
        # Reset stopped items se è un nuovo item
        item_url = to_item_url(item_name)
        if item_url not in self.stopped_items:
            self.stopped_items.discard(item_url)
        
        self.refresh_offers()
    
    def refresh_offers(self):
        if not self.current_item:
            return
        
        item_url = to_item_url(self.current_item)
        
        # Se l'item è stato stoppato, non aggiornare
        if item_url in self.stopped_items:
            return
        
        # Prepara i parametri della richiesta
        params = {
            'item_url': item_url,
            'rank': self.current_rank.lower(),
            'limit': 10  # Limita a 10 offerte
        }
        # Aggiungi max_rank_override se specificato e se il rank è Maxed
        if self.current_rank == "Maxed" and self.max_rank_override.strip():
            params['max_rank_override'] = self.max_rank_override.strip()
        # Aggiungi filtri preimpostati
        filters = {
            'seller_status': 'ingame',
            'online_only': 'true'
        }
        headers = {'X-User-ID': self.user_id} if self.user_id else {}
        self._offers_worker = HttpWorker(self)
        def _task():
            resp = requests.get(
                f"{BACKEND_URL}/manual_offers",
                params={**params, **filters},
                headers=headers,
                timeout=10
            )
            if resp.status_code != 200:
                raise Exception(f"Search Error: {resp.status_code}")
            return resp.json()
        self._offers_worker.success.connect(lambda offers: self.display_offers(offers))
        self._offers_worker.error.connect(lambda e: self.info_label.setText(f"Connection Error: {str(e)}"))
        self._offers_worker.run(_task)
    
    def display_offers(self, offers):
        # Pulisci i risultati precedenti
        for i in reversed(range(self.vbox.count())):
            widget = self.vbox.itemAt(i).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        
        if not offers:
            self.info_label.setText("No offers found")
            return
            
        # Ordina le offerte per prezzo (crescente)
        sorted_offers = sorted(offers, key=lambda x: x.get('price', 999999))
        
        # Mostra le prime 10 offerte
        displayed_count = min(10, len(sorted_offers))
        self.info_label.setText(f"Found {len(offers)} Offers - Show {displayed_count}")
        
        # Aggiungi i widget delle offerte
        for offer in sorted_offers[:displayed_count]:
            widget = ManualOfferWidget(offer, self)
            self.vbox.addWidget(widget)
            item_url = offer.get('item')
            if item_url not in self.displayed_offers:
                self.displayed_offers[item_url] = []
            self.displayed_offers[item_url].append(widget)

class Overlay(QWidget):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.setObjectName("overlayRoot")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(540, 390)
        self.setStyleSheet("""
            QWidget#overlayRoot { background: #0d141e; border: 1px solid rgba(126,230,231,110); border-radius: 12px; }
            QLabel#brand { color: #edf5f5; font-size: 14pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#brandAccent { color: #e6c676; }
            QLabel#connectionStatus { color: #9cabb7; font-size: 8pt; font-weight: 600; }
            QLabel#connectionDot { color: #69d6a1; font-size: 12pt; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 8px; background: transparent; }
            QScrollBar::handle:vertical { min-height: 24px; border-radius: 4px; background: rgba(126,230,231,100); }
            QTabWidget::pane { border: 1px solid rgba(167,200,221,40); border-radius: 8px; background: rgba(7,11,18,185); }
            QTabBar::tab { min-width: 128px; padding: 8px 13px; color: #9cabb7; background: rgba(17,27,39,180); border: 1px solid transparent; border-bottom: 2px solid transparent; font-weight: 700; }
            QTabBar::tab:selected { color: #edf5f5; border-bottom-color: #e6c676; background: rgba(30,48,61,210); }
            QTabBar::tab:hover:!selected { color: #7ee6e7; }
        """)

        self.drag_position = None
        self.offers_by_item = {}  # Tieni traccia degli widget per item

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 12, 14, 14)
        main_layout.setSpacing(10)
        
        # Barra superiore: identità del prodotto, stato e azione principale.
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        brand = QLabel("WM <span style='color:#e6c676'>SNIPER</span>")
        brand.setObjectName("brand")
        top_bar.addWidget(brand)
        top_bar.addSpacing(10)
        self.new_search_btn = QPushButton("Create Sniper Watch")
        self.new_search_btn.setMinimumWidth(270)
        self.new_search_btn.setToolTip("Create a new search in the current tab")
        self.new_search_btn.setStyleSheet("""
            QPushButton {
                background-color: #e6c676;
                color: #11120f;
                border: 1px solid #ffe4a0;
                font-weight: 800;
                padding: 7px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #ffe4a0;
            }
        """)
        self.new_search_btn.clicked.connect(self.open_search_dialog)
        top_bar.addWidget(self.new_search_btn)
        top_bar.addStretch(1)
        
        # Pulsante Chiudi Applicazione
        self.close_app_button = QPushButton("✕")
        self.close_app_button.setToolTip("Close")
        self.close_app_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid rgba(239,115,120,130);
                color: #ef7378;
                font-weight: bold;
                font-size: 12px;
                border-radius: 3px;
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
            }
            QPushButton:hover {
                background-color: rgba(239,115,120,35);
            }
        """)
        self.close_app_button.clicked.connect(QApplication.instance().quit)
        top_bar.addWidget(self.close_app_button)
        
        main_layout.addLayout(top_bar)
        
        # Sistema a tab
        self.tabs = QTabWidget()
        
        # Tab Sniper
        self.sniper_tab = QWidget()
        sniper_layout = QVBoxLayout()
        sniper_layout.setContentsMargins(0, 0, 0, 0)
        
        # Area scroll per le offerte
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: transparent;")
        
        self.content = QWidget()
        self.vbox = QVBoxLayout()
        self.vbox.setAlignment(Qt.AlignTop)
        self.content.setLayout(self.vbox)
        self.scroll.setWidget(self.content)
        
        sniper_layout.addWidget(self.scroll)
        self.sniper_tab.setLayout(sniper_layout)
        
        # Tab Ricerca Manuale
        self.manual_tab = ManualSearchTab(self.user_id)
        
        # Aggiungi i tab
        self.tabs.addTab(self.sniper_tab, "Sniper")
        self.tabs.addTab(self.manual_tab, "Warframe Market")
        
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        self.notified_items = set()
        self.suppressed_items = set()  # ids temporaneamente soppressi fino al restart
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_notifications)
        self.timer.start(CHECK_INTERVAL * 1000)
        
        # Cambia il testo del pulsante in base alla tab selezionata
        self.tabs.currentChanged.connect(self.update_button_text)
        
        # Nascondi inizialmente l'overlay
        self.hide()

    def update_button_text(self, index):
        if index == 0:  # Tab Sniper
            self.new_search_btn.setText("Create Sniper Watch")
        else:  # Tab Warframe Market
            self.new_search_btn.setText("Search Warframe Market")

    # Rendila finestra trascinabile
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def _remove_widget_by_msg_id(self, msg_id):
        """
        Rimuove il widget corrispondente al msg_id (se esiste) da UI, from offers_by_item,
        e dai set di tracking.
        """
        # Cerca in offers_by_item
        for item_url in list(self.offers_by_item.keys()):
            widgets = list(self.offers_by_item.get(item_url, []))
            for w in widgets:
                try:
                    wid_msg = f"{w.offer.get('item')}_{w.offer.get('seller')}_{w.offer.get('price')}"
                except Exception:
                    wid_msg = None
                if wid_msg == msg_id:
                    try:
                        if w in self.offers_by_item.get(item_url, []):
                            self.offers_by_item[item_url].remove(w)
                        w.setParent(None)
                        w.deleteLater()
                    except Exception:
                        pass
            # se la lista è vuota, rimuovila
            if not self.offers_by_item.get(item_url):
                try:
                    del self.offers_by_item[item_url]
                except KeyError:
                    pass
        # Pulizia set
        if msg_id in self.notified_items:
            self.notified_items.remove(msg_id)
        if msg_id in self.suppressed_items:
            try:
                self.suppressed_items.remove(msg_id)
            except KeyError:
                pass

    def check_notifications(self):
        headers = {'X-User-ID': self.user_id} if self.user_id else {}
        self._matches_worker = HttpWorker(self)
        def _task():
            resp = requests.get(f"{BACKEND_URL}/matches", headers=headers, timeout=5)
            resp.raise_for_status()
            return resp.json()
        def _on_success(matches):
            # Costruisci set di msg_id attuali riportati dal backend
            current_msg_ids = set()
            for m in matches:
                msg_id = f"{m.get('item')}_{m.get('seller')}_{m.get('price')}"
                current_msg_ids.add(msg_id)

            # Rimuovi dalle UI le notifiche che sono presenti localmente ma non più nel backend
            to_remove_local = [mid for mid in list(self.notified_items) if mid not in current_msg_ids]
            for mid in to_remove_local:
                self._remove_widget_by_msg_id(mid)
                # Non aggiungerlo a suppressed: sparisce permanentemente finché backend non lo riporta di nuovo

            # Aggiungi le nuove notifiche (ignorando quelle soppresse o già viste)
            for m in matches:
                msg_id = f"{m.get('item')}_{m.get('seller')}_{m.get('price')}"
                if msg_id in self.notified_items or msg_id in self.suppressed_items:
                    continue

                # nuovo: aggiungi e crea widget
                self.notified_items.add(msg_id)
                offer_widget = OfferWidget(m, self)  # Passa l'istanza dell'overlay
                self.vbox.addWidget(offer_widget)

                # Registra il widget per l'item
                item_url = m.get('item')
                if item_url not in self.offers_by_item:
                    self.offers_by_item[item_url] = []
                self.offers_by_item[item_url].append(offer_widget)
        def _on_error(e):
            print("Overlay error:", e)
        self._matches_worker.success.connect(_on_success)
        self._matches_worker.error.connect(_on_error)
        self._matches_worker.run(_task)
            
    def open_search_dialog(self):
        # Apre la dialog in base alla tab selezionata
        if self.tabs.currentIndex() == 0:  # Tab Sniper
            dialog = SearchDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.get_data()
                if not data['item']:
                    return
                headers = {'X-User-ID': self.user_id} if self.user_id else {}
                self._start_worker = HttpWorker(self)
                def _task():
                    resp = requests.post(
                        f"{BACKEND_URL}/start_watch",
                        data=data,
                        headers=headers,
                        timeout=5
                    )
                    return (resp.status_code, resp.text)
                def _on_success(result):
                    status_code, text = result
                    if status_code == 200:
                        print(f"Ricerca avviata per: {data['item']}")
                        # Calcola item_url dalla display name (stesso comportamento del backend)
                        item_url = to_item_url(data['item'])
                        # Rimuovi dalle soppressioni tutti gli id relativi a questo item
                        to_remove = [sid for sid in list(self.suppressed_items) if sid.startswith(f"{item_url}_")]
                        for sid in to_remove:
                            try:
                                self.suppressed_items.remove(sid)
                            except KeyError:
                                pass
                        # Forza un refresh immediato
                        self.check_notifications()
                    else:
                        print("Error starting Search:", text)
                def _on_error(e):
                    print("Search Request Error:", e)
                self._start_worker.success.connect(_on_success)
                self._start_worker.error.connect(_on_error)
                self._start_worker.run(_task)
        else:  # Tab Warframe Market
            dialog = ManualSearchDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.get_data()
                if not data['item']:
                    return
                
                # Avvia la ricerca manuale
                self.manual_tab.search_offers(data['item'], data['rank_choice'], data['max_rank_override'])
                
    def remove_item_widgets(self, item_url):
        """Rimuovi tutti i widget per un item specifico e sopprimi temporaneamente i loro msg_id"""
        if item_url in self.offers_by_item:
            for widget in list(self.offers_by_item[item_url]):
                try:
                    msg_id = f"{widget.offer.get('item')}_{widget.offer.get('seller')}_{widget.offer.get('price')}"
                except Exception:
                    msg_id = None

                if msg_id:
                    # Sopprimi temporaneamente finché l'utente non riavvia la ricerca per questo item
                    self.suppressed_items.add(msg_id)
                    # Rimuovi anche dall'insieme di notifiche viste (se presente)
                    if msg_id in self.notified_items:
                        self.notified_items.remove(msg_id)

                # rimozione widget
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except Exception:
                    pass

            # cancella dalla mappa
            try:
                del self.offers_by_item[item_url]
            except KeyError:
                pass

            print(f"Rimossi tutti i widget per: {item_url}")
            
    def toggle_overlay(self):
        """Attiva/disattiva la visibilità dell'overlay"""
        if self.isVisible():
            self.hide_overlay()
        else:
            self.show_overlay()
            
    def show_overlay(self):
        """Mostra l'overlay con animazione"""
        self.show()
        self.raise_()
        self.activateWindow()
        
    def hide_overlay(self):
        """Nasconde l'overlay"""
        self.hide()


class OverlaySystem:
    def __init__(self):
        self.app = QApplication(sys.argv)
        
        # Il backend accetta esclusivamente UUID nel campo X-User-ID.
        # Manteniamo lo stesso UUID tra tutte le chiamate e i riavvii dell'overlay.
        user_id = get_persistent_user_id()
        print(f"Using persistent user ID: {user_id}")
        
        # Crea l'overlay principale
        self.overlay = Overlay(user_id)
        
        # Crea l'icona di toggle
        self.toggle_icon = ToggleIcon(self.overlay)
        
        # Posiziona l'icona in alto a destra
        screen_geom = self.app.primaryScreen().availableGeometry()
        self.toggle_icon.move(screen_geom.right() - 50, 20)
        self.toggle_icon.show()
        
        # Stato iniziale
        self.system_visible = True
        self.overlay_was_visible = False

        
    def toggle_system(self):
        """Attiva/disattiva l'intero sistema (icona + overlay)"""
        if self.system_visible:
            # Salva lo stato corrente dell'overlay
            self.overlay_was_visible = self.overlay.isVisible()
            
            # Nascondi entrambi i componenti
            self.toggle_icon.hide()
            self.overlay.hide()
            self.system_visible = False
        else:
            # Mostra l'icona
            self.toggle_icon.show()
            
            # Ripristina lo stato dell'overlay
            if self.overlay_was_visible:
                self.overlay.show_overlay()
                
            self.system_visible = True
            
    def run(self):
        sys.exit(self.app.exec_())

def run_overlay():
    system = OverlaySystem()
    system.run()

if __name__ == "__main__":
    run_overlay()

