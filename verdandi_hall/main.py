"""
Verdandi Hall - GUI application for managing the Verdandi fabric.
"""

import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QStatusBar, QPushButton, QMessageBox, QDockWidget,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.models.identity import Node
from verdandi_hall.widgets import JackCanvas, JackClientManager, FabricCanvasWidget

logger = logging.getLogger(__name__)


class VerdandiHall(QMainWindow):
    """Main window for Verdandi Hall GUI."""
    
    def __init__(self):
        super().__init__()
        self.config = VerdandiConfig.load()
        self.db = None
        self.jack_manager = None
        self.remote_jack_tabs = {}  # Track open remote JACK tabs by node_id
        
        self.setWindowTitle(f"Verdandi Hall - {self.config.node.hostname}")
        self.setGeometry(100, 100, 1400, 900)
        
        self._init_ui()
        self._init_database()
        self._init_jack()
        self._init_fabric_tab()  # Initialize fabric tab after database
        self._init_node_list()  # Initialize node list dock
        
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
            self.fabric_widget = self._create_fabric_tab()
            # Connect signals
            self.fabric_widget.canvas.node_double_clicked.connect(self._on_fabric_node_clicked)
            # Replace placeholder with actual widget
            index = self.tabs.indexOf(self.fabric_tab_placeholder)
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, self.fabric_widget, "Fabric Graph")
        
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
    
    def _init_node_list(self):
        """Initialize the node list dock widget."""
        # Create dock widget
        dock = QDockWidget("Network Nodes", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create list widget
        self.node_list = QListWidget()
        self.node_list.itemDoubleClicked.connect(self._on_node_clicked)
        dock.setWidget(self.node_list)
        
        # Add dock to left side
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        
        # Initial population
        self._refresh_node_list()
        
        # Auto-refresh every 10 seconds
        self.node_list_timer = QTimer(self)
        self.node_list_timer.timeout.connect(self._refresh_node_list)
        self.node_list_timer.start(10000)
    
    def _refresh_node_list(self):
        """Refresh the list of discovered nodes."""
        if not self.db:
            return
            
        try:
            session = self.db.get_session()
            nodes = session.query(Node).order_by(Node.hostname).all()
            session.close()
            
            # Clear and repopulate list
            self.node_list.clear()
            
            for node in nodes:
                is_local = node.node_id == self.config.node.node_id
                status_icon = "🟢" if node.status == "online" else "🔴"
                local_marker = " (local)" if is_local else ""
                
                item_text = f"{status_icon} {node.hostname}{local_marker}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, str(node.node_id))  # Store node_id as data
                
                # Color local node differently
                if is_local:
                    item.setForeground(Qt.darkGreen)
                
                self.node_list.addItem(item)
                
        except Exception as e:
            logger.error("node_list_refresh_failed", error=str(e))
    
    def _on_node_clicked(self, item: QListWidgetItem):
        """Handle node list item click - open remote JACK graph tab."""
        node_id = item.data(Qt.UserRole)
        
        # Don't open remote tab for local node - already have JACK Graph tab
        if node_id == self.config.node.node_id:
            # Switch to existing JACK Graph tab
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "JACK Graph":
                    self.tabs.setCurrentIndex(i)
                    break
            return
        
        # Check if tab already exists
        if node_id in self.remote_jack_tabs:
            tab_widget = self.remote_jack_tabs[node_id]
            # Find and switch to existing tab
            for i in range(self.tabs.count()):
                if self.tabs.widget(i) == tab_widget:
                    self.tabs.setCurrentIndex(i)
                    return
        
        # Get node info from database
        try:
            session = self.db.get_session()
            node = session.query(Node).filter_by(node_id=node_id).first()
            session.close()
            
            if not node:
                QMessageBox.warning(self, "Node Not Found", f"Node {node_id[:8]} not found in database.")
                return
            
            # Create remote JACK tab
            remote_tab = self._create_remote_jack_tab(node)
            tab_name = f"{node.hostname} JACK"
            tab_index = self.tabs.addTab(remote_tab, tab_name)
            self.tabs.setCurrentIndex(tab_index)
            
            # Track the tab
            self.remote_jack_tabs[node_id] = remote_tab
            
            self.status_bar.showMessage(f"Opened remote JACK graph for {node.hostname}", 3000)
            
        except Exception as e:
            logger.error("open_remote_jack_failed", error=str(e), node_id=node_id)
            QMessageBox.critical(self, "Error", f"Failed to open remote JACK graph: {e}")
    
    def _create_remote_jack_tab(self, node: Node):
        """Create a tab for viewing remote node's JACK graph."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Header with node info
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<h3>Remote JACK Graph: {node.hostname}</h3>"))
        header.addWidget(QLabel(f"<code>{node.ip_last_seen}:{node.daemon_port}</code>"))
        header.addStretch()
        layout.addLayout(header)
        
        # Placeholder for actual remote JACK canvas
        # TODO: Implement RemoteJackCanvas that queries via gRPC
        placeholder = QLabel("Remote JACK graph visualization coming soon...\n\n"
                           f"This will display JACK ports and connections from {node.hostname}\n"
                           f"via gRPC connection to {node.ip_last_seen}:{node.daemon_port}")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("QLabel { color: gray; padding: 40px; }")
        layout.addWidget(placeholder)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(lambda: self.status_bar.showMessage(f"Refreshing {node.hostname}...", 2000))
        button_layout.addWidget(refresh_btn)
        
        close_btn = QPushButton("Close Tab")
        close_btn.clicked.connect(lambda: self._close_remote_jack_tab(node.node_id))
        button_layout.addWidget(close_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        return widget
    
    def _close_remote_jack_tab(self, node_id: str):
        """Close a remote JACK tab."""
        if node_id in self.remote_jack_tabs:
            tab_widget = self.remote_jack_tabs[node_id]
            
            # Find and remove tab
            for i in range(self.tabs.count()):
                if self.tabs.widget(i) == tab_widget:
                    self.tabs.removeTab(i)
                    break
            
            # Remove from tracking
            del self.remote_jack_tabs[node_id]
    
    def _on_fabric_node_clicked(self, node_id: str):
        """Handle fabric canvas node double-click."""
        # Find node info and open remote JACK tab
        try:
            session = self.db.get_session()
            node = session.query(Node).filter_by(node_id=node_id).first()
            session.close()
            
            if not node:
                return
            
            # Use same logic as node list click
            if node_id == self.config.node.node_id:
                # Switch to JACK Graph tab
                for i in range(self.tabs.count()):
                    if self.tabs.tabText(i) == "JACK Graph":
                        self.tabs.setCurrentIndex(i)
                        break
            else:
                # Open or switch to remote JACK tab
                if node_id in self.remote_jack_tabs:
                    tab_widget = self.remote_jack_tabs[node_id]
                    for i in range(self.tabs.count()):
                        if self.tabs.widget(i) == tab_widget:
                            self.tabs.setCurrentIndex(i)
                            return
                else:
                    remote_tab = self._create_remote_jack_tab(node)
                    tab_name = f"{node.hostname} JACK"
                    tab_index = self.tabs.addTab(remote_tab, tab_name)
                    self.tabs.setCurrentIndex(tab_index)
                    self.remote_jack_tabs[node_id] = remote_tab
                    self.status_bar.showMessage(f"Opened remote JACK graph for {node.hostname}", 3000)
                    
        except Exception as e:
            logger.error("fabric_node_click_failed", error=str(e), node_id=node_id)


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

