"""
Verdandi Hall - GUI application for managing the Verdandi fabric.
"""

import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QStatusBar, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_hall.widgets import JackCanvas, JackClientManager, FabricCanvasWidget

logger = logging.getLogger(__name__)


class VerdandiHall(QMainWindow):
    """Main window for Verdandi Hall GUI."""
    
    def __init__(self):
        super().__init__()
        self.config = VerdandiConfig.load()
        self.db = None
        self.jack_manager = None
        
        self.setWindowTitle(f"Verdandi Hall - {self.config.node.hostname}")
        self.setGeometry(100, 100, 1400, 900)
        
        self._init_ui()
        self._init_database()
        self._init_jack()
        self._init_fabric_tab()  # Initialize fabric tab after database
        
    def _init_ui(self):
        """Initialize the user interface."""
        # Central widget with tab system
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Header with node info
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<h2>Verdandi Hall</h2>"))
        header.addStretch()
        header.addWidget(QLabel(f"Node: <b>{self.config.node.hostname}</b>"))
        header.addWidget(QLabel(f"ID: <code>{self.config.node.node_id[:8]}...</code>"))
        layout.addLayout(header)
        
        # Tab widget for different views
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Tab 1: Status/Overview
        self.tabs.addTab(self._create_status_tab(), "Status")
        
        # Tab 2: Local JACK Graph
        self.tabs.addTab(self._create_jack_tab(), "JACK Graph")
        
        # Tab 3: Fabric Graph (will be created after database init)
        self.fabric_tab_placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.fabric_tab_placeholder)
        placeholder_layout.addWidget(QLabel("Loading fabric graph..."))
        self.tabs.addTab(self.fabric_tab_placeholder, "Fabric Graph")
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
    def _create_status_tab(self):
        """Create the status/overview tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        layout.addWidget(QLabel("<h3>Node Information</h3>"))
        
        info_text = f"""
        <table>
        <tr><td><b>Hostname:</b></td><td>{self.config.node.hostname}</td></tr>
        <tr><td><b>Node ID:</b></td><td><code>{self.config.node.node_id}</code></td></tr>
        <tr><td><b>Display Name:</b></td><td>{self.config.node.display_name or '(not set)'}</td></tr>
        </table>
        
        <h3>Daemon Configuration</h3>
        <table>
        <tr><td><b>gRPC Port:</b></td><td>{self.config.daemon.grpc_port}</td></tr>
        <tr><td><b>mDNS:</b></td><td>{'Enabled' if self.config.daemon.enable_mdns else 'Disabled'}</td></tr>
        <tr><td><b>TLS:</b></td><td>{'Enabled' if self.config.daemon.tls_enabled else 'Disabled'}</td></tr>
        </table>
        
        <h3>Database</h3>
        <table>
        <tr><td><b>Host:</b></td><td>{self.config.database.host}:{self.config.database.port}</td></tr>
        <tr><td><b>Database:</b></td><td>{self.config.database.database}</td></tr>
        </table>
        """
        
        info_label = QLabel(info_text)
        info_label.setTextFormat(Qt.RichText)
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.clicked.connect(self._refresh_status)
        button_layout.addWidget(refresh_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        return widget
        
    def _create_jack_tab(self):
        """Create the JACK graph canvas tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Create canvas (jack_manager will be set after initialization)
        self.jack_canvas = JackCanvas(jack_manager=None, parent=self)
        layout.addWidget(self.jack_canvas)
        
        return widget
        
    def _create_fabric_tab(self):
        """Create the Fabric graph canvas tab."""
        return FabricCanvasWidget(self.config, self.db, parent=self)
        
    def _init_fabric_tab(self):
        """Initialize fabric tab after database is ready."""
        if self.db:
            fabric_widget = self._create_fabric_tab()
            # Replace placeholder with actual widget
            index = self.tabs.indexOf(self.fabric_tab_placeholder)
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, fabric_widget, "Fabric Graph")
        
    def _init_database(self):
        """Initialize database connection."""
        try:
            self.db = Database(self.config.database)
            self.status_bar.showMessage("✓ Database connected", 3000)
        except Exception as e:
            self.status_bar.showMessage(f"✗ Database error: {e}")
            logger.error("database_connection_failed", error=str(e))
            
    def _init_jack(self):
        """Initialize JACK client connection."""
        try:
            self.jack_manager = JackClientManager("verdandi_hall")
            self.jack_canvas.set_jack_manager(self.jack_manager)
            self.status_bar.showMessage("✓ JACK connected", 3000)
        except Exception as e:
            self.status_bar.showMessage(f"✗ JACK error: {e}")
            logger.error("jack_connection_failed", error=str(e))
            
    def _refresh_status(self):
        """Refresh the status information."""
        self.status_bar.showMessage("Refreshing...", 1000)
        # TODO: Query daemon status, update UI
        QTimer.singleShot(500, lambda: self.status_bar.showMessage("✓ Refreshed", 2000))


def main():
    """Entry point for Verdandi Hall."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Verdandi Hall")
    
    window = VerdandiHall()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

