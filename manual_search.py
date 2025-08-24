import sys
import requests
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QComboBox, QPushButton, QScrollArea, QFrame, QLabel,
                             QFormLayout)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import pyqtSignal
import pyperclip

BACKEND_URL = "http://127.0.0.1:8080"

def to_item_url(display_name: str) -> str:
    return display_name.replace(" ", "_").lower()

class ManualOfferWidget(QFrame):
    def __init__(self, offer, parent=None):
        super().__init__(parent)
        self.offer = offer
        self.parent = parent
        
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

class ManualSearchTab(QWidget):
    stopItemDisplay = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item = None
        self.current_rank = "All"
        self.displayed_offers = {}
        self.stopped_items = set()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Form di ricerca
        search_form = QFormLayout()
        
        self.item_input = QLineEdit()
        self.item_input.setPlaceholderText("Item Name (es: Ash Prime Set)")
        self.item_input.returnPressed.connect(self.search_offers)
        search_form.addRow("Item:", self.item_input)
        
        # Selezione per il rank
        self.rank_combo = QComboBox()
        self.rank_combo.addItems(["All", "Maxed"])
        self.rank_combo.currentTextChanged.connect(self.rank_changed)
        search_form.addRow("Rank:", self.rank_combo)
        
        # Campo per l'override del max rank (visibile solo quando si seleziona Maxed)
        self.max_rank_input = QLineEdit()
        self.max_rank_input.setPlaceholderText("Opzionale (default: 10)")
        self.max_rank_input.setVisible(False)
        search_form.addRow("Max Rank Override:", self.max_rank_input)
        
        layout.addLayout(search_form)
        
        # Pulsante di ricerca
        self.search_btn = QPushButton("Search")
        self.search_btn.setStyleSheet("""
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
        self.search_btn.clicked.connect(self.search_offers)
        layout.addWidget(self.search_btn)
        
        # Etichetta informazioni
        self.info_label = QLabel("Enter the name of an item and press Search")
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
        
        self.stopItemDisplay.connect(self.handle_stop_item)
    
    def rank_changed(self, rank):
        self.current_rank = rank
        # Mostra/nascondi il campo max rank in base alla selezione
        self.max_rank_input.setVisible(rank == "Maxed")
        
        if self.current_item:
            self.search_offers()
    
    def search_offers(self):
        item_name = self.item_input.text().strip()
        if not item_name:
            self.info_label.setText("Inserisci un nome item valido")
            return
            
        self.current_item = item_name
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
            }
            
            # Aggiungi max_rank_override se specificato e se il rank è Maxed
            if self.current_rank == "Maxed" and self.max_rank_input.text().strip():
                params['max_rank_override'] = self.max_rank_input.text().strip()
            
            # Effettua la richiesta al backend
            response = requests.get(
                f"{BACKEND_URL}/manual_offers",
                params=params,
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
    
    def handle_stop_item(self, item_url):
        self.stopped_items.add(item_url)
        # Rimuovi tutti i widget per questo item
        if item_url in self.displayed_offers:
            for widget in self.displayed_offers[item_url]:
                widget.setParent(None)
                widget.deleteLater()
            del self.displayed_offers[item_url]
        
        self.info_label.setText(f"Visualizzazione interrotta per: {item_url}")
    
    def stop_item_display(self, item_url):
        self.stopItemDisplay.emit(item_url)