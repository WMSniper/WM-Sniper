import sys
import time
import requests
import warnings
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, QPushButton, 
                             QHBoxLayout, QScrollArea, QFrame, QDialog, QFormLayout, 
                             QLineEdit, QComboBox, QDialogButtonBox, QListWidget, 
                             QListWidgetItem, QAbstractItemView, QSizePolicy, QShortcut,
                             QTabWidget)
from PyQt5.QtCore import Qt, QTimer, QPoint, QSize, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QCursor, QPixmap, QKeySequence
import pyperclip
import threading
import json
from urllib.parse import urlencode
import os

# Ignora tutti i warning di deprecazione
warnings.filterwarnings("ignore", category=DeprecationWarning)

BACKEND_URL = "http://127.0.0.1:8080"
CHECK_INTERVAL = 5  # secondi

def to_item_url(display_name: str) -> str:
    # Same normalization used by the backend
    return display_name.replace(" ", "_").lower()

class ToggleIcon(QLabel):
    def __init__(self, overlay_window, parent=None):
        super().__init__(parent)
        self.overlay = overlay_window
        self.setFixedSize(32, 32)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Carica l'icona o usa un placeholder
        if os.path.exists("icon.jpg"):
            self.setPixmap(QPixmap("icon.jpg").scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.setStyleSheet("""
                background-color: #3498db;
                border-radius: 16px;
                border: 2px solid #2980b9;
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
                background-color: rgba(0,0,0,150); 
                border-radius: 5px; 
                margin: 2px;
            }
            QLabel { 
                color: white; 
                font-size: 9pt;
            }
            QPushButton { 
                color: white; 
                border: none; 
                border-radius: 3px; 
                padding: 2px 4px;
                font-size: 9pt;
            }
            #copyButton {
                background-color: #4CAF50; 
                min-width: 50px;
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
                background-color: #95a5a6;
                min-width: 60px;
            }
            #removeButton:hover {
                background-color: #7f8c8d;
            }
            #stopButton {
                background-color: #e67e22;
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
        self.label.setToolTip(f"Venditore: {offer.get('seller')}")
        layout.addWidget(self.label, 1)
        
        # Contenitore per i pulsanti
        btn_container = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        # Pulsanti con dimensioni ottimizzate
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("copyButton")
        copy_btn.setToolTip("Copia messaggio per il venditore")
        copy_btn.clicked.connect(self.copy_message)
        btn_layout.addWidget(copy_btn)

        fav_btn = QPushButton("❤️")
        fav_btn.setObjectName("favButton")
        fav_btn.setToolTip("Aggiungi ai preferiti")
        fav_btn.clicked.connect(self.add_to_favorites)
        btn_layout.addWidget(fav_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("removeButton")
        remove_btn.setToolTip("Rimuovi questa offerta")
        remove_btn.clicked.connect(self.remove_self)
        btn_layout.addWidget(remove_btn)
        
        stop_btn = QPushButton("Stop")
        stop_btn.setObjectName("stopButton")
        stop_btn.setToolTip("Ferma ricerca per questo item")
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
        
    def add_to_favorites(self):
        display_name = self.offer.get('display_name')
        try:
            response = requests.post(
                f"{BACKEND_URL}/favorites/add_item",
                data={'category': 'default', 'display_name': display_name},
                timeout=5
            )
            if response.status_code == 200:
                print(f"Aggiunto ai preferiti: {display_name}")
            else:
                print("Errore aggiunta preferiti:", response.text)
        except Exception as e:
            print("Errore richiesta preferiti:", e)
            
    def stop_search(self):
        item_url = self.offer.get('item')
        try:
            # 1. Ferma la ricerca
            response = requests.post(
                f"{BACKEND_URL}/stop_watch",
                data={'item_url': item_url},
                timeout=5
            )
            if response.status_code == 200:
                print(f"Ricerca fermata per: {item_url}")
                
                # 2. Rimuovi le offerte dal backend
                clear_response = requests.post(
                    f"{BACKEND_URL}/clear_matches",
                    data={'item_url': item_url},
                    timeout=5
                )
                if clear_response.status_code == 200:
                    print(f"Offerte rimosse per: {item_url}")
                else:
                    print("Errore rimozione offerte:", clear_response.text)
                
                # 3. Rimuovi tutti i widget per questo item (client-side) e sopprimi temporaneamente
                self.overlay.remove_item_widgets(item_url)
            else:
                print("Errore fermata ricerca:", response.text)
        except Exception as e:
            print("Errore richiesta fermata ricerca:", e)

class ManualOfferWidget(QFrame):
    def __init__(self, offer, parent=None):
        super().__init__(parent)
        self.offer = offer
        self.parent_tab = parent
        
        self.setStyleSheet("""
            QFrame { 
                background-color: rgba(0,0,0,150); 
                border-radius: 5px; 
                margin: 2px;
            }
            QLabel { 
                color: white; 
                font-size: 9pt;
            }
            QPushButton { 
                color: white; 
                border: none; 
                border-radius: 3px; 
                padding: 2px 4px;
                font-size: 9pt;
            }
            #copyButton {
                background-color: #4CAF50; 
                min-width: 50px;
            }
            #copyButton:hover {
                background-color: #45a049; 
            }
            #removeButton {
                background-color: #95a5a6;
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
        self.label.setToolTip(f"Venditore: {offer.get('seller')}")
        layout.addWidget(self.label, 1)
        
        # Contenitore per i pulsanti
        btn_container = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        
        # Pulsanti
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("copyButton")
        copy_btn.setToolTip("Copia messaggio per il venditore")
        copy_btn.clicked.connect(self.copy_message)
        btn_layout.addWidget(copy_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.setObjectName("removeButton")
        remove_btn.setToolTip("Rimuovi questa offerta")
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
        layout = QVBoxLayout()
        
        form = QFormLayout()
        
        # Campo per il nome dell'item con autocomplete
        self.item_input = QLineEdit()
        self.item_input.setPlaceholderText("Es: Ash Prime Set")
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
        self.max_rank_input.setPlaceholderText("Opzionale")
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
            
        try:
            params = {'q': query, 'limit': 10}
            response = requests.get(f"{BACKEND_URL}/autocomplete?{urlencode(params)}", timeout=5)
            if response.status_code == 200:
                items = response.json()
                self.update_autocomplete_list(items)
            else:
                self.autocomplete_list.clear()
                self.autocomplete_list.setVisible(False)
        except Exception as e:
            print("Errore autocomplete:", e)
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
            
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
        layout = QVBoxLayout()
        
        form = QFormLayout()
        
        # Campo per il nome dell'item con autocomplete
        self.item_input = QLineEdit()
        self.item_input.setPlaceholderText("Es: Ash Prime Set")
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
        self.max_rank_input.setPlaceholderText("Opzionale")
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
            
        try:
            params = {'q': query, 'limit': 10}
            response = requests.get(f"{BACKEND_URL}/autocomplete?{urlencode(params)}", timeout=5)
            if response.status_code == 200:
                items = response.json()
                self.update_autocomplete_list(items)
            else:
                self.autocomplete_list.clear()
                self.autocomplete_list.setVisible(False)
        except Exception as e:
            print("Errore autocomplete:", e)
            self.autocomplete_list.clear()
            self.autocomplete_list.setVisible(False)
            
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item = None
        self.current_rank = "All"
        self.displayed_offers = {}
        self.stopped_items = set()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Etichetta informazioni
        self.info_label = QLabel("Use the search button above to find items")
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
            self.info_label.setText("Inserisci un nome item valido")
            return
            
        self.current_item = item_name
        self.current_rank = rank_choice
        self.max_rank_override = max_rank_override
        self.info_label.setText(f"Ricerca in corso per: {item_name}...")
        
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
            
        try:
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
            
            # Effettua la richiesta al backend
            response = requests.get(
                f"{BACKEND_URL}/manual_offers",
                params={**params, **filters},
                timeout=10
            )
            
            if response.status_code == 200:
                offers = response.json()
                self.display_offers(offers)
            else:
                self.info_label.setText(f"Errore nella ricerca: {response.status_code}")
                
        except Exception as e:
            self.info_label.setText(f"Errore di connessione: {str(e)}")
    
    def display_offers(self, offers):
        # Pulisci i risultati precedenti
        for i in reversed(range(self.vbox.count())):
            widget = self.vbox.itemAt(i).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        
        if not offers:
            self.info_label.setText("Nessuna offerta trovata")
            return
            
        # Ordina le offerte per prezzo (crescente)
        sorted_offers = sorted(offers, key=lambda x: x.get('price', 999999))
        
        # Mostra le prime 10 offerte
        displayed_count = min(10, len(sorted_offers))
        self.info_label.setText(f"Trovate {len(offers)} offerte - Mostrate {displayed_count}")
        
        # Aggiungi i widget delle offerte
        for offer in sorted_offers[:displayed_count]:
            widget = ManualOfferWidget(offer, self)
            self.vbox.addWidget(widget)
            item_url = offer.get('item')
            if item_url not in self.displayed_offers:
                self.displayed_offers[item_url] = []
            self.displayed_offers[item_url].append(widget)

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(500, 350)  # Dimensioni aumentate per la nuova UI

        self.drag_position = None
        self.offers_by_item = {}  # Tieni traccia degli widget per item

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Barra superiore con pulsante nuova ricerca
        top_bar = QHBoxLayout()
        self.new_search_btn = QPushButton("WM Sniper")
        self.new_search_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db; 
                color: white; 
                font-weight: bold;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.new_search_btn.clicked.connect(self.open_search_dialog)
        top_bar.addWidget(self.new_search_btn)
        
        # Pulsante per chiudere l'overlay
        self.close_btn = QPushButton("✕")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c; 
                color: white; 
                font-weight: bold;
                padding: 5px;
                border-radius: 3px;
                min-width: 24px;
                max-width: 24px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        self.close_btn.clicked.connect(self.hide_overlay)
        top_bar.addWidget(self.close_btn)
        
        main_layout.addLayout(top_bar)
        
        # Sistema a tab
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444;
                background: rgba(30, 30, 30, 200);
            }
            QTabBar::tab {
                background: rgba(50, 50, 50, 200);
                color: white;
                padding: 8px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: rgba(70, 70, 70, 200);
                border-bottom: 2px solid #3498db;
            }
        """)
        
        # Tab Sniper
        self.sniper_tab = QWidget()
        sniper_layout = QVBoxLayout()
        sniper_layout.setContentsMargins(0, 0, 0, 0)
        
        # Area scroll per le offerte
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: rgba(30,30,30,150); border-radius: 5px;")
        
        self.content = QWidget()
        self.vbox = QVBoxLayout()
        self.vbox.setAlignment(Qt.AlignTop)
        self.content.setLayout(self.vbox)
        self.scroll.setWidget(self.content)
        
        sniper_layout.addWidget(self.scroll)
        self.sniper_tab.setLayout(sniper_layout)
        
        # Tab Ricerca Manuale
        self.manual_tab = ManualSearchTab()
        
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
            self.new_search_btn.setText("WM Sniper")
        else:  # Tab Warframe Market
            self.new_search_btn.setText("WM Market")

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
        try:
            response = requests.get(f"{BACKEND_URL}/matches", timeout=5)
            response.raise_for_status()
            matches = response.json()

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

        except Exception as e:
            print("Overlay error:", e)
            
    def open_search_dialog(self):
        # Apre la dialog in base alla tab selezionata
        if self.tabs.currentIndex() == 0:  # Tab Sniper
            dialog = SearchDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.get_data()
                if not data['item']:
                    return
                    
                try:
                    response = requests.post(
                        f"{BACKEND_URL}/start_watch",
                        data=data,
                        timeout=5
                    )
                    if response.status_code == 200:
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
                        print("Errore avvio ricerca:", response.text)
                except Exception as e:
                    print("Errore richiesta ricerca:", e)
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
        
        # Crea l'overlay principale
        self.overlay = Overlay()
        
        # Crea l'icona di toggle
        self.toggle_icon = ToggleIcon(self.overlay)
        
        # Posiziona l'icona in alto a destra
        screen_geom = self.app.primaryScreen().availableGeometry()
        self.toggle_icon.move(screen_geom.right() - 50, 20)
        self.toggle_icon.show()
        
        # Imposta la scorciatoia da tastiera (tasto Ins) sull'icona
        self.toggle_shortcut = QShortcut(QKeySequence(Qt.Key_Insert), self.toggle_icon)
        self.toggle_shortcut.activated.connect(self.toggle_system)
        
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