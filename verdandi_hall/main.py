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
        self.tabs.addTab(self._create_jack_tab(), "Local JACK")
        
        # Tab 3: Remote JACK Graph (empty initially, populated when node selected)
        self.remote_jack_canvas = None
        self.current_remote_node_id = None
        self.tabs.addTab(self._create_remote_jack_tab(), "Remote JACK")
        
        # Tab 4: Fabric Graph (will be created after database init)
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
    
    def _create_remote_jack_tab(self):
        """Create the remote JACK graph canvas tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Header with instructions and current node info
        header = QHBoxLayout()
        self.remote_node_label = QLabel("<i>Select a node from the list on the left to view its JACK graph</i>")
        header.addWidget(self.remote_node_label)
        header.addStretch()
        layout.addLayout(header)
        
        # Container for the remote canvas (will be created when node selected)
        self.remote_canvas_container = QWidget()
        remote_container_layout = QVBoxLayout(self.remote_canvas_container)
        remote_container_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.remote_canvas_container)
        
        return widget
        
    def _create_fabric_tab(self):
        """Create the Fabric graph canvas tab."""
        return FabricCanvasWidget(self.config, self.db, jack_manager=None, parent=self)
        
    def _init_fabric_tab(self):
        """Initialize fabric tab after database is ready."""
        if self.db:
            self.fabric_widget = self._create_fabric_tab()
            # Set JACK manager if already initialized
            if hasattr(self, 'jack_manager') and self.jack_manager:
                self.fabric_widget.jack_manager = self.jack_manager
                self.fabric_widget.sample_rate = self.jack_manager.get_sample_rate()
                self.fabric_widget.buffer_size = self.jack_manager.get_buffer_size()
                # Update the display labels
                self.fabric_widget.sample_rate_label.setText(f"Sample Rate: {self.fabric_widget.sample_rate} Hz")
                self.fabric_widget.buffer_size_label.setText(f"Buffer Size: {self.fabric_widget.buffer_size} frames")
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
            logger.error(f"database_connection_failed: {e}")
            
    def _init_jack(self):
        """Initialize JACK client connection."""
        try:
            self.jack_manager = JackClientManager("verdandi_hall")
            self.jack_canvas.set_jack_manager(self.jack_manager)
            # Update fabric widget with JACK settings if it exists
            if hasattr(self, 'fabric_widget') and self.fabric_widget:
                self.fabric_widget.jack_manager = self.jack_manager
                if hasattr(self.fabric_widget, 'sample_rate'):
                    self.fabric_widget.sample_rate = self.jack_manager.get_sample_rate()
                    self.fabric_widget.buffer_size = self.jack_manager.get_buffer_size()
            self.status_bar.showMessage("✓ JACK connected", 3000)
        except Exception as e:
            self.status_bar.showMessage(f"✗ JACK error: {e}")
            logger.error(f"jack_connection_failed: {e}")
            
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
        self.node_list.itemClicked.connect(self._on_node_clicked)  # Single click, not double
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
        """Handle node list item click - switch to Remote JACK tab and load that node's graph."""
        node_id = item.data(Qt.UserRole)
        
        # If local node, switch to Local JACK tab
        if node_id == self.config.node.node_id:
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "Local JACK":
                    self.tabs.setCurrentIndex(i)
                    break
            return
        
        # Switch to Remote JACK tab and load this node's graph
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Remote JACK":
                self.tabs.setCurrentIndex(i)
                break
        
        # Load the remote node's JACK graph
        self._load_remote_jack_graph(node_id)
    
    def _load_remote_jack_graph(self, node_id: str):
        """Load and display a remote node's JACK graph in the Remote JACK tab."""
        if node_id == self.current_remote_node_id and self.remote_jack_canvas:
            # Already showing this node
            return
        
        try:
            session = self.db.get_session()
            node = session.query(Node).filter_by(node_id=node_id).first()
            session.close()
            
            if not node:
                QMessageBox.warning(self, "Node Not Found", f"Node {node_id[:8]} not found in database.")
                return
            
            # Update header
            self.remote_node_label.setText(f"<b>Remote JACK Graph:</b> {node.hostname} ({node.ip_last_seen})")
            
            # Clear existing canvas if any
            if self.remote_jack_canvas:
                self.remote_canvas_container.layout().removeWidget(self.remote_jack_canvas)
                self.remote_jack_canvas.deleteLater()
                self.remote_jack_canvas = None
            
            # Query remote JACK graph via gRPC and create canvas
            from PySide6.QtWidgets import QLabel
            from PySide6.QtCore import Qt
            from verdandi_hall.grpc_client import VerdandiGrpcClient
            
            try:
                # Query remote JACK graph
                with VerdandiGrpcClient(node) as client:
                    jack_graph = client.get_jack_graph()
                
                # Create canvas with remote data
                self.remote_jack_canvas = JackCanvas(jack_manager=None, parent=self, node_id=node_id)
                
                # TODO: Populate canvas with remote data from jack_graph
                # For now, just show it works
                
                self.remote_canvas_container.layout().addWidget(self.remote_jack_canvas)
                self.current_remote_node_id = node_id
                
                self.status_bar.showMessage(f"Connected to {node.hostname} - {len(jack_graph.clients)} JACK clients found", 5000)
                
            except Exception as e:
                logger.error(f"Failed to query remote JACK graph: {e}", exc_info=True)
                
                # Show error placeholder
                placeholder = QLabel(
                    f"<h3>Remote JACK Graph: {node.hostname}</h3>\n\n"
                    f"<p style='color: #f88;'><b>Error:</b> Failed to connect to remote node</p>\n"
                    f"<p><i>{str(e)}</i></p>\n\n"
                    f"<p>Make sure the Verdandi daemon is running on {node.hostname}</p>"
                )
                placeholder.setTextFormat(Qt.RichText)
                placeholder.setAlignment(Qt.AlignCenter)
                placeholder.setStyleSheet("QLabel { padding: 40px; }")
                placeholder.setWordWrap(True)
                
                self.remote_jack_canvas = placeholder
                self.remote_canvas_container.layout().addWidget(self.remote_jack_canvas)
                self.current_remote_node_id = node_id
                self.remote_canvas_container.layout().addWidget(self.remote_jack_canvas)
                self.current_remote_node_id = node_id
            
        except Exception as e:
            logger.error("load_remote_jack_failed", error=str(e), node_id=node_id)
            QMessageBox.critical(self, "Error", f"Failed to load remote JACK graph: {e}")
    
    def _load_remote_canvas_state(self, node_id: str):
        """Load saved canvas state (positions, connections) for a remote node."""
        # TODO: Load from database or file
        # For now, this is a placeholder
        logger.info(f"Loading canvas state for remote node {node_id}")
        pass
    
    def _save_remote_canvas_state(self, node_id: str):
        """Save canvas state (positions, connections) for a remote node."""
        # TODO: Save to database or file
        # For now, this is a placeholder
        logger.info(f"Saving canvas state for remote node {node_id}")
        pass
    def _on_fabric_node_clicked(self, node_id: str):
        """Handle fabric canvas node double-click - load that node's JACK graph."""
        # Use same logic as node list click
        # Find the corresponding list item to trigger selection
        for i in range(self.node_list.count()):
            item = self.node_list.item(i)
            if item.data(Qt.UserRole) == node_id:
                self._on_node_clicked(item)
                return


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

