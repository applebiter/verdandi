"""
Verdandi Hall - GUI application for Verdandi.
"""

import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QStatusBar, QPushButton, QMessageBox, QDockWidget,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtGui import QIcon, QAction

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.models.identity import Node
from verdandi_hall.widgets import JackCanvas, JackCanvasWithControls, JackClientManager
from verdandi_hall.widgets.jack_canvas import PortModel

logger = logging.getLogger(__name__)


class VerdandiHall(QMainWindow):
    """Main window for Verdandi Hall GUI."""
    
    def __init__(self):
        super().__init__()
        self.config = VerdandiConfig.load()
        self.db = None
        self.jack_manager = None
        
        self.setWindowTitle(f"Verdandi Hall - {self.config.node.hostname}")
        
        # Restore window geometry from settings
        self.settings = QSettings("Verdandi", "VerdandiHall")
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # Default size if no saved geometry
            self.setGeometry(100, 100, 1400, 900)
        
        self._init_ui()
        self._init_database()
        self._init_jack()
        self._init_node_list()  # Initialize node list dock
        
    def _init_ui(self):
        """Initialize the user interface."""
        # Create menu bar
        self._create_menu_bar()
        
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
        
        # Database maintenance buttons
        db_button_layout = QHBoxLayout()
        clear_db_btn = QPushButton("🗑️ Clear Database State")
        clear_db_btn.setToolTip("Clear all data from the database (useful for troubleshooting state issues)")
        clear_db_btn.clicked.connect(self._clear_database_state)
        db_button_layout.addWidget(clear_db_btn)
        db_button_layout.addStretch()
        layout.addLayout(db_button_layout)
        
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
        # Use wrapped canvas with JackTrip controls
        self.jack_canvas_widget = JackCanvasWithControls(
            jack_manager=None, 
            parent=self,
            is_remote=False
        )
        # Keep reference to inner canvas for compatibility
        self.jack_canvas = self.jack_canvas_widget.canvas
        # Connect hub coordination signal
        self.jack_canvas_widget.hub_started.connect(self._on_any_hub_started)
        return self.jack_canvas_widget
    
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
            self.jack_canvas_widget.set_jack_manager(self.jack_manager)
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
            
            logger.info(f"Local node_id: {self.config.node.node_id}")
            
            for node in nodes:
                # Convert both to strings for comparison to handle UUID vs string
                is_local = str(node.node_id) == str(self.config.node.node_id)
                
                logger.info(f"Checking node {node.hostname} (id: {node.node_id}), is_local: {is_local}")
                
                # Skip local node - it should not be shown in the network nodes list
                # to avoid confusion (clicking it would load local graph into remote graph)
                if is_local:
                    continue
                
                status_icon = "🟢" if node.status == "online" else "🔴"
                
                item_text = f"{status_icon} {node.hostname}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, str(node.node_id))  # Store node_id as data
                
                self.node_list.addItem(item)
                
        except Exception as e:
            logger.error("node_list_refresh_failed", error=str(e))
    
    def _on_any_hub_started(self):
        """Coordinate hub state across all control panels when any hub starts."""
        # Disable Start Hub buttons on all control panels
        if hasattr(self, 'jack_canvas_widget') and self.jack_canvas_widget:
            self.jack_canvas_widget.start_hub_btn.setEnabled(False)
        
        if hasattr(self, 'remote_jack_canvas') and self.remote_jack_canvas:
            if hasattr(self.remote_jack_canvas, 'start_hub_btn'):
                self.remote_jack_canvas.start_hub_btn.setEnabled(False)
    
    def _is_any_hub_running(self):
        """Check if any hub is currently running on any panel."""
        if hasattr(self, 'jack_canvas_widget') and self.jack_canvas_widget:
            if self.jack_canvas_widget.hub_running:
                return True
        
        if hasattr(self, 'remote_jack_canvas') and self.remote_jack_canvas:
            if hasattr(self.remote_jack_canvas, 'hub_running') and self.remote_jack_canvas.hub_running:
                return True
        
        return False
    
    def _sync_all_hub_states(self):
        """Sync all hub button states by checking the database for any running hub."""
        from verdandi_codex.models.jacktrip import JackTripHub
        
        # Check database for running hub
        hub_is_running = False
        hub_hostname = None
        try:
            session = self.db.get_session()
            hub_record = session.query(JackTripHub).first()
            if hub_record and hub_record.hub_hostname:
                hub_is_running = True
                hub_hostname = hub_record.hub_hostname
            session.close()
        except Exception as e:
            logger.error(f"Failed to check hub state from database: {e}")
        
        # Update all hub buttons based on database state
        if hub_is_running:
            logger.info(f"Hub is running on {hub_hostname}, disabling all Start Hub buttons")
            # Disable all Start Hub buttons
            if hasattr(self, 'jack_canvas_widget') and self.jack_canvas_widget:
                self.jack_canvas_widget.start_hub_btn.setEnabled(False)
            
            if hasattr(self, 'remote_jack_canvas') and self.remote_jack_canvas:
                if hasattr(self.remote_jack_canvas, 'start_hub_btn'):
                    self.remote_jack_canvas.start_hub_btn.setEnabled(False)
        else:
            logger.info("No hub running, enabling all Start Hub buttons")
            # Enable all Start Hub buttons (unless local hub is running on that specific node)
            if hasattr(self, 'jack_canvas_widget') and self.jack_canvas_widget:
                if not self.jack_canvas_widget.hub_running:
                    self.jack_canvas_widget.start_hub_btn.setEnabled(True)
            
            if hasattr(self, 'remote_jack_canvas') and self.remote_jack_canvas:
                if hasattr(self.remote_jack_canvas, 'start_hub_btn'):
                    if not (hasattr(self.remote_jack_canvas, 'hub_running') and self.remote_jack_canvas.hub_running):
                        self.remote_jack_canvas.start_hub_btn.setEnabled(True)
    
    def _on_node_clicked(self, item: QListWidgetItem):
        """Handle node list item click - switch to Remote JACK tab and load that node's graph."""
        node_id = item.data(Qt.UserRole)
        
        # Switch to Remote JACK tab and load this node's graph
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Remote JACK":
                self.tabs.setCurrentIndex(i)
                break
        
        # Load the remote node's JACK graph
        self._load_remote_jack_graph(node_id)
    
    def _load_remote_jack_graph(self, node_id: str, force_refresh: bool = False):
        """Load and display a remote node's JACK graph in the Remote JACK tab."""
        # Always reload to capture any changes (like new JackTrip instances)
        
        try:
            session = self.db.get_session()
            node = session.query(Node).filter_by(node_id=node_id).first()
            session.close()
            
            if not node:
                QMessageBox.warning(self, "Node Not Found", f"Node {node_id[:8]} not found in database.")
                return
            
            # Update header
            self.remote_node_label.setText(f"<b>Remote JACK Graph:</b> {node.hostname} ({node.ip_last_seen})")
            
            # Clear existing canvas if any (or if force refresh)
            if self.remote_jack_canvas and (force_refresh or self.current_remote_node_id != node_id):
                self.remote_canvas_container.layout().removeWidget(self.remote_jack_canvas)
                self.remote_jack_canvas.deleteLater()
                self.remote_jack_canvas = None
            
            # Query remote JACK graph via gRPC and create canvas
            from PySide6.QtWidgets import QLabel
            from PySide6.QtCore import Qt
            from verdandi_hall.grpc_client import VerdandiGrpcClient
            
            try:
                # Query remote JACK graph
                logger.info(f"Querying JACK graph from {node.hostname} ({node.ip_last_seen})")
                with VerdandiGrpcClient(node) as client:
                    jack_graph = client.get_jack_graph()
                
                logger.info(f"Received JACK graph with {len(jack_graph.clients)} clients from {node.hostname}")
                logger.info(f"Client names in response: {[c.name for c in jack_graph.clients]}")
                
                # Create canvas with remote data and controls if not exists
                if not self.remote_jack_canvas:
                    self.remote_jack_canvas = JackCanvasWithControls(
                        jack_manager=None, 
                        parent=self, 
                        node_id=node_id,
                        is_remote=True,
                        remote_node=node
                    )
                    
                    # Connect refresh signal to reload remote graph
                    self.remote_jack_canvas.canvas.remote_refresh_requested.connect(
                        lambda: self._load_remote_jack_graph(node_id, force_refresh=True)
                    )
                    
                    # Connect hub coordination signal
                    self.remote_jack_canvas.hub_started.connect(self._on_any_hub_started)
                    
                    self.remote_canvas_container.layout().addWidget(self.remote_jack_canvas)
                    self.current_remote_node_id = node_id
                
                # Always populate canvas with latest remote data from jack_graph
                self._populate_remote_jack_canvas(jack_graph)
                
                # Always detect JackTrip state from JACK graph (handles restarts)
                self._detect_jacktrip_state(jack_graph)
                
                # Always sync hub state after detecting state (this ensures button states are correct)
                self._sync_all_hub_states()
                
                # Always load the last saved preset to restore positions
                self.remote_jack_canvas.canvas._load_last_preset()
                
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
    
    def _populate_remote_jack_canvas(self, jack_graph):
        """Populate the remote JACK canvas with data from a JackGraphResponse."""
        if not hasattr(self, 'remote_jack_canvas') or self.remote_jack_canvas is None:
            logger.warning("No remote canvas to populate")
            return
        
        # Get the inner canvas
        canvas = self.remote_jack_canvas.canvas
        
        # Clear existing data BEFORE batch mode so view is properly cleared
        canvas.model.clear()
        
        # Begin batch mode to prevent multiple refreshes
        canvas.model.begin_batch()
        
        # Get hub info from database to determine naming
        from verdandi_codex.models.jacktrip import JackTripHub
        hub_hostname = None
        session = self.db.get_session()
        try:
            hub_record = session.query(JackTripHub).first()
            if hub_record and hub_record.hub_hostname:
                hub_hostname = hub_record.hub_hostname
                logger.info(f"Hub is running on: {hub_hostname}")
        except Exception as e:
            logger.error(f"Failed to get hub info: {e}")
        
        # Add clients and ports
        x, y = 50, 50  # Starting position for auto-layout
        for client in jack_graph.clients:
            client_name = client.name  # Keep original name for node creation
            hostname_alias = None  # Track if we need to set an alias
            
            # Check if this is a JackTrip client - map to hostname for display
            import re
            ip_pattern = re.compile(r'__ffff_(\d+\.\d+\.\d+\.\d+)')
            if ip_pattern.match(client_name):
                # This is a JackTrip client connection
                # Map to hostname for display, but keep original name for node
                ip_address = ip_pattern.match(client_name).group(1)
                try:
                    node = session.query(Node).filter_by(ip_last_seen=ip_address).first()
                    if node:
                        hostname_alias = node.hostname
                        logger.info(f"Will map JackTrip client {ip_address} to display as {hostname_alias}")
                except:
                    pass
            
            # Split system and a2j clients into capture/playback nodes
            if client_name == "system":
                # Separate into capture (sources) and playback (sinks)
                if client.output_ports:
                    node_name = "system (capture)"
                    node = canvas.model.add_node(node_name, x, y)
                    for jack_port in client.output_ports:
                        node.outputs.append(
                            PortModel(
                                name=jack_port.name,
                                full_name=jack_port.full_name,
                                is_output=True,
                                is_midi=jack_port.is_midi
                            )
                        )
                    y += 150
                
                if client.input_ports:
                    node_name = "system (playback)"
                    node = canvas.model.add_node(node_name, x, y)
                    for jack_port in client.input_ports:
                        node.inputs.append(
                            PortModel(
                                name=jack_port.name,
                                full_name=jack_port.full_name,
                                is_output=False,
                                is_midi=jack_port.is_midi
                            )
                        )
                    y += 150
            
            elif client_name.startswith("a2j"):
                # Split a2j (MIDI bridge) clients into capture (sources) and playback (sinks)
                if client.output_ports:
                    node_name = f"{client_name} (capture)"
                    node = canvas.model.add_node(node_name, x, y)
                    for jack_port in client.output_ports:
                        node.outputs.append(
                            PortModel(
                                name=jack_port.name,
                                full_name=jack_port.full_name,
                                is_output=True,
                                is_midi=jack_port.is_midi
                            )
                        )
                    y += 150
                
                if client.input_ports:
                    node_name = f"{client_name} (playback)"
                    node = canvas.model.add_node(node_name, x, y)
                    for jack_port in client.input_ports:
                        node.inputs.append(
                            PortModel(
                                name=jack_port.name,
                                full_name=jack_port.full_name,
                                is_output=False,
                                is_midi=jack_port.is_midi
                            )
                        )
                    y += 150
            
            else:
                # Normal client - keep inputs and outputs together
                node = canvas.model.add_node(client_name, x, y)
                
                # Set hostname alias if this is a JackTrip client
                if hostname_alias:
                    canvas.model.set_alias(client_name, hostname_alias)
                    logger.info(f"Set alias for JackTrip client '{client_name}' -> '{hostname_alias}'")
                
                # Add input ports
                for jack_port in client.input_ports:
                    node.inputs.append(
                        PortModel(
                            name=jack_port.name,
                            full_name=jack_port.full_name,
                            is_output=False,
                            is_midi=jack_port.is_midi
                        )
                    )
                
                # Add output ports
                for jack_port in client.output_ports:
                    node.outputs.append(
                        PortModel(
                            name=jack_port.name,
                            full_name=jack_port.full_name,
                            is_output=True,
                            is_midi=jack_port.is_midi
                        )
                    )
                
                # Update position for next node
                x += 200
                if x > 800:
                    x = 50
                    y += 150
        
        # Close session
        session.close()
        
        # Add connections
        for conn in jack_graph.connections:
            try:
                canvas.model.add_connection(
                    output_port=conn.output_port,
                    input_port=conn.input_port
                )
            except Exception as e:
                logger.warning(f"Failed to add connection {conn.output_port} -> {conn.input_port}: {e}")
        
        # End batch mode - this triggers a single rebuild
        canvas.model.end_batch()
        
        logger.info(f"Populated remote canvas with {len(jack_graph.clients)} clients and {len(jack_graph.connections)} connections")
        logger.info(f"Canvas now has {len(canvas.model.nodes)} nodes: {list(canvas.model.nodes.keys())}")

    
    def _detect_jacktrip_state(self, jack_graph):
        """Detect if JackTrip is running by querying the daemon."""
        if not hasattr(self, 'remote_jack_canvas') or self.remote_jack_canvas is None:
            logger.warning("_detect_jacktrip_state called but remote_jack_canvas is None")
            return
        
        # Query the daemon for actual JackTrip status
        try:
            from verdandi_hall.grpc_client import VerdandiGrpcClient
            session = self.db.get_session()
            node = session.query(Node).filter_by(node_id=self.current_remote_node_id).first()
            session.close()
            
            if not node:
                logger.warning(f"Node {self.current_remote_node_id} not found")
                return
            
            with VerdandiGrpcClient(node) as client:
                status = client.get_jacktrip_status()
                
                logger.info(f"JackTrip status from {node.hostname}: hub_running={status.hub_running}, client_running={status.client_running}")
                
                # Extract client names for hostname mapping
                client_names = [c.name for c in jack_graph.clients]
                
                # Update remote canvas state based on daemon response
                if hasattr(self.remote_jack_canvas, '_on_jacktrip_state_detected'):
                    self.remote_jack_canvas._on_jacktrip_state_detected(
                        status.hub_running,
                        status.client_running,
                        client_names
                    )
                    logger.info(f"Updated remote canvas state: hub={status.hub_running}, client={status.client_running}")
                else:
                    logger.warning("remote_jack_canvas doesn't have _on_jacktrip_state_detected method")
                        
        except Exception as e:
            logger.error(f"Failed to query JackTrip status: {e}", exc_info=True)
    
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
    
    def closeEvent(self, event):
        """Save window geometry before closing."""
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()
    
    def _create_menu_bar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        # Clear Database State action
        clear_db_action = QAction("🗑️ Clear Database State", self)
        clear_db_action.setToolTip("Clear all data from the database")
        clear_db_action.triggered.connect(self._clear_database_state)
        tools_menu.addAction(clear_db_action)
        
        tools_menu.addSeparator()
        
        # Exit action
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        tools_menu.addAction(exit_action)
    
    def _clear_database_state(self):
        """Clear all database state - useful for troubleshooting."""
        reply = QMessageBox.question(
            self,
            "Clear Database State",
            "This will delete all data from the database including:\n\n"
            "• Node registrations\n"
            "• JackTrip sessions\n"
            "• All other state\n\n"
            "Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                logger.info("Clearing database state...")
                self.db.drop_all_tables()
                self.db.create_all_tables()
                logger.info("Database state cleared successfully")
                
                QMessageBox.information(
                    self,
                    "Database Cleared",
                    "Database state has been cleared successfully.\n\n"
                    "You may want to restart the application for a clean state."
                )
                
                self.status_bar.showMessage("Database state cleared", 5000)
                
                # Refresh any displayed data
                self._refresh_status()
                
            except Exception as e:
                logger.error(f"Error clearing database: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to clear database state:\n\n{str(e)}"
                )


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

