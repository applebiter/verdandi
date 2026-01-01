"""
Fabric Canvas V2 for Verdandi Hall - Link Node Architecture
Visualizes the multi-node fabric network with:
- Fabric Nodes (circles) = Physical machines
- Link Nodes (diamonds) = JackTrip sessions
- Connections (lines) = Wires between nodes
"""

from __future__ import annotations

import logging
import json
import uuid
from typing import Optional, Dict, List
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsEllipseItem, QGraphicsPolygonItem,
    QGraphicsLineItem, QPushButton, QLabel, QMenu, QInputDialog, QMessageBox,
    QComboBox
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPolygonF, QAction, QPainterPath

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.models.identity import Node
from verdandi_codex.models.fabric import FabricLink

logger = logging.getLogger(__name__)


@dataclass
class NodeGraphics:
    """Graphics data for a fabric node (physical machine)."""
    node_id: str
    hostname: str
    ip_address: str
    x: float
    y: float
    is_local: bool = False


@dataclass
class LinkNodeData:
    """Data for a link node (JackTrip session)."""
    link_id: str
    mode: str  # "P2P" or "HUB"
    channels: int
    sample_rate: int
    buffer_size: int
    status: str
    send_channels: int = 2  # Channels to send
    receive_channels: int = 2  # Channels to receive
    # Connections
    source_node_id: Optional[str] = None  # For P2P: client node
    target_node_id: Optional[str] = None  # For P2P: server node
    hub_node_id: Optional[str] = None     # For HUB: hub node
    client_ids: Optional[List[str]] = None  # For HUB: client nodes


class ConnectionPort(QGraphicsEllipseItem):
    """Visual connection port on a node."""
    
    def __init__(self, parent_item, is_output: bool):
        super().__init__(-8, -8, 16, 16)
        self.parent_item = parent_item
        self.is_output = is_output
        
        self.setBrush(QBrush(QColor(200, 200, 200)))
        self.setPen(QPen(QColor(100, 100, 100), 2))
        
        self.setParentItem(parent_item)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)
        
        # Position: output on right, input on left
        radius = 45 if isinstance(parent_item, FabricNodeItem) else 35
        if is_output:
            self.setPos(radius, 0)  # Right side
        else:
            self.setPos(-radius, 0)  # Left side
    
    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255, 200, 100)))
        self.setPen(QPen(QColor(255, 150, 0), 3))
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(200, 200, 200)))
        self.setPen(QPen(QColor(100, 100, 100), 2))
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        """Start dragging a connection from this port."""
        if event.button() == Qt.LeftButton:
            # Get the canvas view
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                if hasattr(view, 'start_connection_drag'):
                    start_pos = self.sceneBoundingRect().center()
                    view.start_connection_drag(start_pos, self.parent_item, self.is_output)
                    event.accept()
                    return
        super().mousePressEvent(event)


class ConnectionWire(QGraphicsItem):
    """Curved wire connecting nodes via their ports."""
    
    def __init__(self, from_item, to_item, from_port=None, to_port=None, parent_canvas=None):
        super().__init__()
        self.from_item = from_item
        self.to_item = to_item
        self.from_port = from_port
        self.to_port = to_port
        self.parent_canvas = parent_canvas
        self.path = QPainterPath()
        self.is_hovered = False
        self.setZValue(-1)  # Behind nodes
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.update_path()
    
    def boundingRect(self):
        return self.path.boundingRect().adjusted(-5, -5, 5, 5)
    
    def paint(self, painter, option, widget):
        # Different colors for different states
        if self.isSelected():
            color = QColor(255, 100, 100)  # Red when selected
            width = 3
        elif self.is_hovered:
            color = QColor(255, 255, 100)  # Bright yellow on hover
            width = 3
        else:
            color = QColor(255, 200, 100)  # Orange normally
            width = 2
        painter.setPen(QPen(color, width))
        painter.drawPath(self.path)
    
    def hoverEnterEvent(self, event):
        """Change color when mouse hovers over wire."""
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Restore color when mouse leaves wire."""
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)
    
    def keyPressEvent(self, event):
        """Handle Delete key to remove wire."""
        if event.key() == Qt.Key_Delete and self.parent_canvas:
            self.parent_canvas.delete_wire(self)
            event.accept()
        else:
            super().keyPressEvent(event)
    
    def mousePressEvent(self, event):
        """Right-click to delete connection (matches JACK graph behavior)."""
        if event.button() == Qt.RightButton:
            if self.parent_canvas:
                self.parent_canvas.delete_wire(self)
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def update_path(self):
        """Update curved path based on connected items and ports."""
        # Get start and end positions
        if self.from_port and self.to_port:
            start_pos = self.from_port.sceneBoundingRect().center()
            end_pos = self.to_port.sceneBoundingRect().center()
        elif self.from_port:
            start_pos = self.from_port.sceneBoundingRect().center()
            end_pos = self.to_item.sceneBoundingRect().center()
        elif self.to_port:
            start_pos = self.from_item.sceneBoundingRect().center()
            end_pos = self.to_port.sceneBoundingRect().center()
        else:
            start_pos = self.from_item.sceneBoundingRect().center()
            end_pos = self.to_item.sceneBoundingRect().center()
        
        # MUST call prepareGeometryChange BEFORE modifying geometry
        self.prepareGeometryChange()
        
        self.path = QPainterPath()
        self.path.moveTo(start_pos)
        
        # Bezier curve for smooth connection
        dist = abs(end_pos.x() - start_pos.x()) * 0.5
        self.path.cubicTo(
            start_pos.x() + dist, start_pos.y(),
            end_pos.x() - dist, end_pos.y(),
            end_pos.x(), end_pos.y()
        )
        
        # Force redraw
        self.update()


class LinkNodeItem(QGraphicsPolygonItem):
    """Diamond-shaped node representing a JackTrip session."""
    
    def __init__(self, link_data: LinkNodeData, x: float, y: float, parent_canvas=None):
        # Create larger diamond shape
        size = 40
        diamond = QPolygonF([
            QPointF(0, -size),      # Top
            QPointF(size, 0),       # Right
            QPointF(0, size),       # Bottom
            QPointF(-size, 0)       # Left
        ])
        super().__init__(diamond)
        
        self.link_data = link_data
        self.parent_canvas = parent_canvas
        
        # Style based on status
        if "UP" in link_data.status:
            color = QColor(100, 200, 100, 180)
        elif "DESIRED" in link_data.status:
            color = QColor(200, 200, 100, 180)
        else:
            color = QColor(200, 100, 100, 180)
        
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(200, 200, 200), 2))
        
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        
        tooltip = (f"Link: {link_data.link_id[:8]}\n"
                  f"Mode: {link_data.mode}\n"
                  f"Channels: {link_data.channels}\n"
                  f"Sample Rate: {link_data.sample_rate} Hz\n"
                  f"Buffer: {link_data.buffer_size} frames\n"
                  f"Status: {link_data.status}\n\n"
                  f"Right-click to configure")
        self.setToolTip(tooltip)
        
        self.setAcceptHoverEvents(True)
        
        # Add connection ports: input on left, output on right
        self.input_port = ConnectionPort(self, is_output=False)
        self.output_port = ConnectionPort(self, is_output=True)
    
    def itemChange(self, change, value):
        """Update wire positions when node moves and save position to database."""
        if change == QGraphicsItem.ItemPositionHasChanged and self.parent_canvas:
            # Update all wires connected to this node
            for wire in self.parent_canvas.wires:
                if wire.from_item == self or wire.to_item == self:
                    wire.update_path()
            
            # Save position to database
            if self.parent_canvas.database:
                try:
                    with self.parent_canvas.database.get_session() as session:
                        from verdandi_codex.models.fabric import FabricLink
                        import json
                        
                        link = session.query(FabricLink).filter_by(link_id=self.link_data.link_id).first()
                        if link:
                            params = json.loads(link.params_json) if isinstance(link.params_json, str) else link.params_json or {}
                            params['x'] = value.x()
                            params['y'] = value.y()
                            link.params_json = json.dumps(params)
                            session.commit()
                except Exception:
                    # Don't log every move, too noisy
                    pass
        return super().itemChange(change, value)
    
    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        
        # Draw mode text
        painter.setFont(QFont("Sans", 8, QFont.Bold))
        painter.setPen(QPen(QColor(255, 255, 255)))
        text_rect = QRectF(-25, -8, 50, 16)
        painter.drawText(text_rect, Qt.AlignCenter, self.link_data.mode)
        
        # Draw send→receive channel count below
        painter.setFont(QFont("Sans", 7))
        text_rect2 = QRectF(-30, 5, 60, 12)
        send_ch = getattr(self.link_data, 'send_channels', self.link_data.channels)
        recv_ch = getattr(self.link_data, 'receive_channels', self.link_data.channels)
        painter.drawText(text_rect2, Qt.AlignCenter, f"{send_ch}→{recv_ch}ch")
    
    def contextMenuEvent(self, event):
        """Show context menu for configuration."""
        if self.parent_canvas:
            menu = QMenu()
            
            configure_action = QAction("Configure Link...", menu)
            configure_action.triggered.connect(lambda: self.parent_canvas.configure_link_node(self))
            menu.addAction(configure_action)
            
            menu.addSeparator()
            
            delete_action = QAction("Delete Link", menu)
            delete_action.triggered.connect(lambda: self.parent_canvas.delete_link_node(self))
            menu.addAction(delete_action)
            
            menu.exec(event.screenPos())


class FabricNodeItem(QGraphicsEllipseItem):
    """Circular node representing a physical machine."""
    
    def __init__(self, node: NodeGraphics, parent_canvas=None):
        # Larger circle
        radius = 45
        super().__init__(-radius, -radius, radius*2, radius*2)
        self.node = node
        self.parent_canvas = parent_canvas
        
        # Color based on local/remote
        if node.is_local:
            color = QColor(100, 180, 100, 200)
        else:
            color = QColor(80, 120, 180, 200)
        
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(200, 200, 200), 2))
        
        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        
        tooltip = (f"{node.hostname}\n"
                  f"{node.ip_address}\n"
                  f"ID: {node.node_id[:8]}\n\n"
                  f"Double-click: Open JACK graph")
        self.setToolTip(tooltip)
        
        # Add connection ports: input on left, output on right
        self.input_port = ConnectionPort(self, is_output=False)
        self.output_port = ConnectionPort(self, is_output=True)
    
    def itemChange(self, change, value):
        """Update wire positions when node moves."""
        if change == QGraphicsItem.ItemPositionHasChanged and self.parent_canvas:
            # Update all wires connected to this node
            for wire in self.parent_canvas.wires:
                if wire.from_item == self or wire.to_item == self:
                    wire.update_path()
        return super().itemChange(change, value)
    
    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        
        # Draw hostname
        painter.setFont(QFont("Sans", 10, QFont.Bold))
        painter.setPen(QPen(QColor(255, 255, 255)))
        text_rect = QRectF(-40, -10, 80, 20)
        painter.drawText(text_rect, Qt.AlignCenter, self.node.hostname)
    
    def mouseDoubleClickEvent(self, event):
        """Handle double-click to open JACK graph."""
        if self.parent_canvas:
            self.parent_canvas.node_double_clicked.emit(self.node.node_id)
        super().mouseDoubleClickEvent(event)


class FabricCanvas(QGraphicsView):
    """Canvas for visualizing the fabric network with Link Nodes."""
    
    node_double_clicked = Signal(str)
    
    def __init__(self, config: VerdandiConfig, database: Database, parent=None):
        super().__init__(parent)
        self.config = config
        self.database = database
        
        self.scene = QGraphicsScene(-2000, -2000, 4000, 4000)
        self.setScene(self.scene)
        
        # Configure view
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        
        # Storage
        self.fabric_nodes: Dict[str, FabricNodeItem] = {}
        self.link_nodes: Dict[str, LinkNodeItem] = {}
        self.wires: List[ConnectionWire] = []
        
        # Store direct hub-client connections (not in database, just for visualization)
        # Format: {(client_node_id, hub_node_id): {send_channels, receive_channels}}
        self.hub_client_connections: Dict[tuple, Dict] = {}
        
        # Load saved connections
        self._load_hub_connections()
        
        # Auto-refresh
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(5000)
        
        # Connection dragging state
        self._temp_connection_item = None
        self._temp_start_pos = None
        self._temp_start_item = None
        self._temp_start_is_output = False
        
        self.refresh()
    
    def wheelEvent(self, event):
        """Zoom in/out with mouse wheel."""
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
    
    def start_connection_drag(self, start_pos: QPointF, start_item, is_output: bool):
        """Start dragging a temporary connection line."""
        from PySide6.QtWidgets import QGraphicsLineItem
        self._temp_start_pos = start_pos
        self._temp_start_item = start_item
        self._temp_start_is_output = is_output
        
        # Set crosshair cursor during drag
        self.setCursor(Qt.CrossCursor)
        
        # Create temp line
        self._temp_connection_item = QGraphicsLineItem()
        self._temp_connection_item.setPen(QPen(QColor(255, 255, 0, 180), 3, Qt.DashLine))
        self._temp_connection_item.setLine(start_pos.x(), start_pos.y(), start_pos.x(), start_pos.y())
        self._temp_connection_item.setZValue(-2)
        self.scene.addItem(self._temp_connection_item)
    
    def mouseMoveEvent(self, event):
        """Update the temporary connection line."""
        if self._temp_connection_item and self._temp_start_pos:
            current_pos = self.mapToScene(event.pos())
            self._temp_connection_item.setLine(
                self._temp_start_pos.x(), self._temp_start_pos.y(),
                current_pos.x(), current_pos.y()
            )
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Complete or cancel the connection drag."""
        if self._temp_connection_item:
            # Restore arrow cursor
            self.setCursor(Qt.ArrowCursor)
            
            # Remove temp line
            self.scene.removeItem(self._temp_connection_item)
            self._temp_connection_item = None
            
            # Find what we released over
            release_pos = self.mapToScene(event.pos())
            items = self.scene.items(release_pos)
            
            target_item = None
            target_is_output = False
            
            for item in items:
                if isinstance(item, ConnectionPort) and item.parent_item != self._temp_start_item:
                    target_item = item.parent_item
                    target_is_output = item.is_output
                    break
            
            # Create connection if valid (output to input or input to output)
            if target_item and self._temp_start_is_output != target_is_output:
                if self._temp_start_is_output:
                    # Dragged from output to input
                    self._create_wire(self._temp_start_item, target_item)
                else:
                    # Dragged from input to output
                    self._create_wire(target_item, self._temp_start_item)
            
            # Clear temp state AFTER using it
            self._temp_start_pos = None
            self._temp_start_item = None
            event.accept()
            return
        
        super().mouseReleaseEvent(event)
    
    def _create_wire(self, from_item, to_item):
        """Create a wire between two items."""
        # Check if wire already exists
        for wire in self.wires:
            if ((wire.from_item == from_item and wire.to_item == to_item) or
                (wire.from_item == to_item and wire.to_item == from_item)):
                logger.info("Wire already exists between these items")
                return
        
        # Create new wire
        wire = ConnectionWire(
            from_item, to_item,
            from_port=from_item.output_port if hasattr(from_item, 'output_port') else None,
            to_port=to_item.input_port if hasattr(to_item, 'input_port') else None,
            parent_canvas=self
        )
        self.scene.addItem(wire)
        self.wires.append(wire)
        logger.info(f"Created wire between nodes")
        
        # Update connection in the database
        self._update_link_connections(from_item, to_item)
    
    def _update_link_connections(self, from_item, to_item):
        """Update link node connections in database when wires are created."""
        link_node = None
        fabric_node = None
        hub_node = None
        client_node = None
        
        # Check if this is a link-fabric connection (old style with diamond nodes)
        if isinstance(from_item, LinkNodeItem) and isinstance(to_item, FabricNodeItem):
            link_node = from_item
            fabric_node = to_item
        elif isinstance(from_item, FabricNodeItem) and isinstance(to_item, LinkNodeItem):
            link_node = to_item
            fabric_node = from_item
        # Check if this is a direct fabric-to-fabric connection (client to hub)
        elif isinstance(from_item, FabricNodeItem) and isinstance(to_item, FabricNodeItem):
            # Determine which is hub and which is client
            parent = self.parentWidget()
            if parent and hasattr(parent, 'hub_node_combo'):
                selected_hub_id = parent.hub_node_combo.currentData()
                if str(from_item.node.node_id) == selected_hub_id:
                    hub_node = from_item
                    client_node = to_item
                elif str(to_item.node.node_id) == selected_hub_id:
                    hub_node = to_item
                    client_node = from_item
        
        # If neither link node nor hub/client pair found, return
        if not link_node and not hub_node:
            return
        
        # For HUB mode, show client configuration dialog
        from PySide6.QtWidgets import QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QLabel
        
        dialog = QDialog()
        dialog.setWindowTitle(f"Configure Client Connection")
        layout = QFormLayout(dialog)
        
        if link_node and fabric_node:
            # Old style with link nodes
            layout.addRow(QLabel(f"<b>Client:</b> {fabric_node.node.hostname}"))
            layout.addRow(QLabel(f"<b>Hub:</b> {link_node.link_data.link_id[:8]}"))
        elif hub_node and client_node:
            # Direct hub-to-client connection
            layout.addRow(QLabel(f"<b>Client:</b> {client_node.node.hostname}"))
            layout.addRow(QLabel(f"<b>Hub:</b> {hub_node.node.hostname}"))
        
        layout.addRow(QLabel("<i>Configure how many channels this client will send/receive</i>"))
        
        # Send Channels
        send_channels_spin = QSpinBox()
        send_channels_spin.setRange(1, 8)
        send_channels_spin.setValue(2)
        layout.addRow("Send Channels (to hub):", send_channels_spin)
        
        # Receive Channels
        receive_channels_spin = QSpinBox()
        receive_channels_spin.setRange(1, 8)
        receive_channels_spin.setValue(2)
        layout.addRow("Receive Channels (from hub):", receive_channels_spin)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() != QDialog.Accepted:
            # User cancelled - remove the wire
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.delete_wire(self.wires[-1]))
            return
        
        send_channels = send_channels_spin.value()
        receive_channels = receive_channels_spin.value()
        
        # Update the connection in the database
        try:
            with self.database.get_session() as session:
                from verdandi_codex.models.fabric import FabricLink, FabricGraph, LinkType
                import json
                
                if link_node and fabric_node:
                    # Old style with link nodes
                    link = session.query(FabricLink).filter_by(link_id=link_node.link_data.link_id).first()
                    if not link:
                        logger.error(f"Link {link_node.link_data.link_id} not found in database")
                        return
                    
                    # Load params
                    params = json.loads(link.params_json) if isinstance(link.params_json, str) else (link.params_json or {})
                    
                    # Add client to clients dict
                    client_node_id = str(fabric_node.node.node_id)
                    if 'clients' not in params:
                        params['clients'] = {}
                    
                    params['clients'][client_node_id] = {
                        "send_channels": send_channels,
                        "receive_channels": receive_channels,
                        "hostname": fabric_node.node.hostname
                    }
                    
                    link.params_json = json.dumps(params)
                    session.commit()
                    logger.info(f"Added client {fabric_node.node.hostname} to hub {link_node.link_data.link_id[:8]}: {send_channels}→{receive_channels}ch")
                    
                elif hub_node and client_node:
                    # Direct hub-to-client connection - store in memory and start JackTrip client
                    hub_node_id = str(hub_node.node.node_id)
                    client_node_id = str(client_node.node.node_id)
                    
                    connection_key = (client_node_id, hub_node_id)
                    self.hub_client_connections[connection_key] = {
                        "send_channels": send_channels,
                        "receive_channels": receive_channels,
                        "client_hostname": client_node.node.hostname,
                        "hub_hostname": hub_node.node.hostname
                    }
                    
                    logger.info(f"Stored direct hub connection: {client_node.node.hostname} ({send_channels}→{receive_channels}ch) -> hub {hub_node.node.hostname}")
                    
                    # Save connections to file for persistence
                    self._save_hub_connections()
                    
                    # Call gRPC to start JackTrip client on the client node
                    try:
                        from verdandi_codex.models.identity import Node
                        from verdandi_hall.grpc_client import VerdandiGrpcClient
                        
                        with self.database.get_session() as session:
                            client_node_db = session.query(Node).filter_by(node_id=client_node_id).first()
                            hub_node_db = session.query(Node).filter_by(node_id=hub_node_id).first()
                            
                            if client_node_db and hub_node_db:
                                session.expunge_all()
                                
                                # Start JackTrip client on client node, connecting to hub node
                                with VerdandiGrpcClient(client_node_db, timeout=30) as client_grpc:
                                    parent = self.parentWidget()
                                    sample_rate = getattr(parent, 'sample_rate', 48000)
                                    buffer_size = getattr(parent, 'buffer_size', 128)
                                    
                                    response = client_grpc.start_jacktrip_client(
                                        hub_address=hub_node_db.ip_last_seen,
                                        hub_port=4464,
                                        send_channels=send_channels,
                                        receive_channels=receive_channels,
                                        sample_rate=sample_rate,
                                        buffer_size=buffer_size
                                    )
                                    
                                    if response.success:
                                        logger.info(f"JackTrip client started on {client_node.node.hostname}")
                                    else:
                                        logger.error(f"Failed to start JackTrip client: {response.message}")
                    except Exception as e:
                        logger.error(f"Failed to start JackTrip client via gRPC: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to update link connections: {e}", exc_info=True)
    
    def delete_wire(self, wire: ConnectionWire):
        """Delete a wire and update link status in database."""
        # Determine if this involves a link node or direct hub-client connection
        link_node = None
        fabric_node = None
        
        if isinstance(wire.from_item, LinkNodeItem) and isinstance(wire.to_item, FabricNodeItem):
            link_node = wire.from_item
            fabric_node = wire.to_item
        elif isinstance(wire.from_item, FabricNodeItem) and isinstance(wire.to_item, LinkNodeItem):
            link_node = wire.to_item
            fabric_node = wire.from_item
        elif isinstance(wire.from_item, FabricNodeItem) and isinstance(wire.to_item, FabricNodeItem):
            # Direct hub-client connection
            client_node = wire.from_item
            hub_node = wire.to_item
            
            # Check both directions
            key1 = (str(client_node.node.node_id), str(hub_node.node.node_id))
            key2 = (str(hub_node.node.node_id), str(client_node.node.node_id))
            
            removed_key = None
            if key1 in self.hub_client_connections:
                del self.hub_client_connections[key1]
                removed_key = key1
                logger.info(f"Removed direct hub connection: {client_node.node.hostname} -> {hub_node.node.hostname}")
            elif key2 in self.hub_client_connections:
                del self.hub_client_connections[key2]
                removed_key = key2
                logger.info(f"Removed direct hub connection: {hub_node.node.hostname} -> {client_node.node.hostname}")
            
            # Stop JackTrip client on the client node
            if removed_key:
                try:
                    from verdandi_codex.models.identity import Node
                    from verdandi_hall.grpc_client import VerdandiGrpcClient
                    
                    client_id = removed_key[0]
                    with self.database.get_session() as session:
                        client_node_db = session.query(Node).filter_by(node_id=client_id).first()
                        if client_node_db:
                            session.expunge(client_node_db)
                            with VerdandiGrpcClient(client_node_db, timeout=30) as client_grpc:
                                client_grpc.stop_jacktrip_client()
                                logger.info(f"Stopped JackTrip client on {client_node_db.hostname}")
                except Exception as e:
                    logger.error(f"Failed to stop JackTrip client: {e}", exc_info=True)
                
                # Save updated connections
                self._save_hub_connections()
        
        # Remove wire from scene
        self.scene.removeItem(wire)
        if wire in self.wires:
            self.wires.remove(wire)
        
        # Update link if this was a client connection
        if link_node and fabric_node:
            try:
                with self.database.get_session() as session:
                    from verdandi_codex.models.fabric import FabricLink
                    import json
                    
                    link = session.query(FabricLink).filter_by(link_id=link_node.link_data.link_id).first()
                    if not link:
                        logger.error(f"Link {link_node.link_data.link_id} not found in database")
                        return
                    
                    # Load params
                    params = json.loads(link.params_json) if isinstance(link.params_json, str) else (link.params_json or {})
                    
                    # Remove client from clients dict
                    client_node_id = str(fabric_node.node.node_id)
                    if 'clients' in params and client_node_id in params['clients']:
                        del params['clients'][client_node_id]
                        logger.info(f"Removed client {fabric_node.node.hostname} from hub {link_node.link_data.link_id[:8]}")
                    
                    # Hub server stays DESIRED_UP even with no clients (ready for connections)
                    link.params_json = json.dumps(params)
                    session.commit()
            except Exception as e:
                logger.error(f"Failed to update link after wire deletion: {e}", exc_info=True)
    
    def _save_hub_connections(self):
        """Save hub-client connections to file for persistence."""
        from pathlib import Path
        import json
        
        config_dir = Path.home() / ".config" / "verdandi" / "fabric"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "hub_connections.json"
        
        try:
            # Convert tuple keys to strings for JSON serialization
            serializable = {}
            for (client_id, hub_id), conn_info in self.hub_client_connections.items():
                key = f"{client_id}:{hub_id}"
                serializable[key] = conn_info
            
            with open(config_file, 'w') as f:
                json.dump(serializable, f, indent=2)
            
            logger.info(f"Saved {len(serializable)} hub connections to {config_file}")
        except Exception as e:
            logger.error(f"Failed to save hub connections: {e}", exc_info=True)
    
    def _load_hub_connections(self):
        """Load hub-client connections from file."""
        from pathlib import Path
        import json
        
        config_file = Path.home() / ".config" / "verdandi" / "fabric" / "hub_connections.json"
        
        if not config_file.exists():
            return
        
        try:
            with open(config_file, 'r') as f:
                serializable = json.load(f)
            
            # Convert string keys back to tuples
            for key, conn_info in serializable.items():
                if ':' in key:
                    client_id, hub_id = key.split(':', 1)
                    tuple_key = (client_id, hub_id)
                    self.hub_client_connections[tuple_key] = conn_info
            
            logger.info(f"Loaded {len(self.hub_client_connections)} hub connections from {config_file}")
        except Exception as e:
            logger.error(f"Failed to load hub connections: {e}", exc_info=True)
    
    def refresh(self):
        """Refresh from database."""
        try:
            session = self.database.get_session()
            
            # Load fabric nodes
            nodes = session.query(Node).all()
            node_map = {str(n.node_id): n for n in nodes}
            
            # Load links
            links = session.query(FabricLink).all()
            
            session.close()
            
            # Update fabric nodes
            current_ids = set(node_map.keys())
            existing_ids = set(self.fabric_nodes.keys())
            
            # Remove deleted
            for node_id in existing_ids - current_ids:
                self.scene.removeItem(self.fabric_nodes[node_id])
                del self.fabric_nodes[node_id]
            
            # Add new
            for node_id, node in node_map.items():
                if node_id not in self.fabric_nodes:
                    x = (len(self.fabric_nodes) % 4) * 200 + 100
                    y = (len(self.fabric_nodes) // 4) * 150 + 100
                    
                    node_graphics = NodeGraphics(
                        node_id=str(node.node_id),
                        hostname=node.hostname,
                        ip_address=node.ip_last_seen or "unknown",
                        x=x,
                        y=y,
                        is_local=(str(node.node_id) == str(self.config.node.node_id))
                    )
                    
                    item = FabricNodeItem(node_graphics, parent_canvas=self)
                    self.scene.addItem(item)
                    self.fabric_nodes[node_id] = item
            
            # Update link nodes
            current_link_ids = set(str(link.link_id) for link in links)
            existing_link_ids = set(self.link_nodes.keys())
            
            # Remove deleted links
            for link_id in existing_link_ids - current_link_ids:
                self.scene.removeItem(self.link_nodes[link_id])
                del self.link_nodes[link_id]
            
            # Add new links
            for link in links:
                link_id = str(link.link_id)
                if link_id not in self.link_nodes:
                    # params_json is already a dict if stored as JSON type
                    if isinstance(link.params_json, str):
                        params = json.loads(link.params_json)
                    else:
                        params = link.params_json or {}
                    
                    # Determine mode (default P2P for now)
                    mode = params.get('mode', 'P2P')
                    
                    # Get send/receive channels, fallback to symmetric 'channels' for backwards compat
                    channels = params.get('channels', 2)
                    send_channels = params.get('send_channels', channels)
                    receive_channels = params.get('receive_channels', channels)
                    
                    link_data = LinkNodeData(
                        link_id=link_id,
                        mode=mode,
                        channels=channels,
                        send_channels=send_channels,
                        receive_channels=receive_channels,
                        sample_rate=params.get('sample_rate', 48000),
                        buffer_size=params.get('buffer_size', 128),
                        status=str(link.status),
                        source_node_id=str(link.node_a_id) if mode == 'P2P' else None,
                        target_node_id=str(link.node_b_id) if mode == 'P2P' else None
                    )
                    
                    # Position between connected nodes or use saved position
                    if link_data.source_node_id in self.fabric_nodes and link_data.target_node_id in self.fabric_nodes:
                        n1 = self.fabric_nodes[link_data.source_node_id]
                        n2 = self.fabric_nodes[link_data.target_node_id]
                        x = (n1.pos().x() + n2.pos().x()) / 2
                        y = (n1.pos().y() + n2.pos().y()) / 2
                    else:
                        # Use saved position from params, or place to the right with vertical stagger
                        # Fabric nodes are typically at 100-600 on x-axis, so place links at 800+
                        num_links = len(self.link_nodes)
                        x = params.get('x', 800 + (num_links % 3) * 200)  # 3 columns
                        y = params.get('y', 100 + (num_links // 3) * 200)  # Rows of 200px
                    
                    item = LinkNodeItem(link_data, x, y, parent_canvas=self)
                    self.scene.addItem(item)
                    self.link_nodes[link_id] = item
            
            # Update wires - clear and recreate
            for wire in self.wires:
                self.scene.removeItem(wire)
            self.wires.clear()
            
            # Create wires based on link mode
            for link_node in self.link_nodes.values():
                # Get connection info from database
                with self.database.get_session() as session:
                    link = session.query(FabricLink).filter_by(link_id=link_node.link_data.link_id).first()
                    if not link:
                        continue
                    
                    params = json.loads(link.params_json) if isinstance(link.params_json, str) else (link.params_json or {})
                    mode = params.get('mode', 'P2P')
                    
                    if mode == 'HUB':
                        # Hub mode: create wire from link to hub node, and from each client to link
                        hub_node_id = params.get('hub_node_id')
                        if hub_node_id and hub_node_id in self.fabric_nodes:
                            hub_node = self.fabric_nodes[hub_node_id]
                            # Wire from link output to hub input (hub is receiving)
                            wire_hub = ConnectionWire(
                                link_node, hub_node,
                                from_port=link_node.output_port,
                                to_port=hub_node.input_port,
                                parent_canvas=self
                            )
                            self.scene.addItem(wire_hub)
                            self.wires.append(wire_hub)
                        
                        # Wire from each client to link input
                        clients = params.get('clients', {})
                        for client_node_id in clients.keys():
                            if client_node_id in self.fabric_nodes:
                                client_node = self.fabric_nodes[client_node_id]
                                wire_client = ConnectionWire(
                                    client_node, link_node,
                                    from_port=client_node.output_port,
                                    to_port=link_node.input_port,
                                    parent_canvas=self
                                )
                                self.scene.addItem(wire_client)
                                self.wires.append(wire_client)
                    
                    elif mode == 'P2P':
                        # P2P mode: wire from source to link, link to target
                        src_id = params.get('source_node_id')
                        tgt_id = params.get('target_node_id')
                        
                        # Create wire from source to link input (if source is connected)
                        if src_id and src_id in self.fabric_nodes:
                            src_node = self.fabric_nodes[src_id]
                            wire1 = ConnectionWire(
                                src_node, link_node,
                                from_port=src_node.output_port,
                                to_port=link_node.input_port,
                                parent_canvas=self
                            )
                            self.scene.addItem(wire1)
                            self.wires.append(wire1)
                            
                            # Create wire from link output to target (if target is connected)
                            if tgt_id and tgt_id in self.fabric_nodes:
                                tgt_node = self.fabric_nodes[tgt_id]
                                wire2 = ConnectionWire(
                                    link_node, tgt_node,
                                    from_port=link_node.output_port,
                                    to_port=tgt_node.input_port,
                            parent_canvas=self
                        )
                        self.scene.addItem(wire2)
                        self.wires.append(wire2)
            
            # Create wires for direct hub-client connections (stored in memory)
            for (client_id, hub_id), conn_info in self.hub_client_connections.items():
                if client_id in self.fabric_nodes and hub_id in self.fabric_nodes:
                    client_node = self.fabric_nodes[client_id]
                    hub_node = self.fabric_nodes[hub_id]
                    
                    # Wire from client to hub
                    wire = ConnectionWire(
                        client_node, hub_node,
                        from_port=client_node.output_port,
                        to_port=hub_node.input_port,
                        parent_canvas=self
                    )
                    self.scene.addItem(wire)
                    self.wires.append(wire)
            
        except Exception as e:
            logger.error(f"Error refreshing fabric canvas: {e}", exc_info=True)
    
    def add_link_node(self, x: float, y: float):
        """Add a new link node at position."""
        from PySide6.QtWidgets import QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QMessageBox
        
        # Get selected hub node from parent widget
        hub_node_id = None
        hub_node_name = "unknown"
        parent = self.parentWidget()
        if parent and hasattr(parent, 'hub_node_combo'):
            hub_node_id = parent.hub_node_combo.currentData()
            hub_node_name = parent.hub_node_combo.currentText()
        
        if not hub_node_id:
            QMessageBox.warning(None, "No Hub Selected", "Please select a hub node from the dropdown above the canvas.")
            return
        
        # Show configuration dialog
        dialog = QDialog()
        dialog.setWindowTitle("Add Client Link")
        layout = QFormLayout(dialog)
        
        # Display selected hub (read-only)
        layout.addRow(QLabel(f"<b>Hub Server Node</b>"))
        layout.addRow(QLabel(f"Hub: {hub_node_name}"))
        layout.addRow(QLabel("<i>This creates a hub server. Connect clients by dragging wires from other nodes.</i>"))
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Get JACK audio settings from parent widget
        sample_rate = 48000
        buffer_size = 256
        parent = self.parentWidget()
        if parent and hasattr(parent, 'sample_rate'):
            sample_rate = parent.sample_rate
        if parent and hasattr(parent, 'buffer_size'):
            buffer_size = parent.buffer_size
        
        # Generate link ID
        link_id = str(uuid.uuid4())
        mode = "HUB"  # Always HUB mode now
        
        # Store in database
        try:
            with self.database.get_session() as session:
                from verdandi_codex.models.fabric import FabricLink, FabricGraph, LinkType
                import json
                
                # Get or create default graph
                graph = session.query(FabricGraph).filter_by(name="Home").first()
                if not graph:
                    graph = FabricGraph(name="Home", version=1)
                    session.add(graph)
                    session.flush()  # Get graph_id
                
                # Get hub node from database
                from verdandi_codex.models.identity import Node
                hub_node = session.query(Node).filter_by(node_id=hub_node_id).first()
                if not hub_node:
                    logger.error("Hub node not found in database")
                    return
                
                # Create hub server link - node_a is the hub, node_b unused
                # Clients will be stored in params_json["clients"] dict
                link = FabricLink(
                    link_id=link_id,
                    graph_id=graph.graph_id,
                    link_type=LinkType.AUDIO_JACKTRIP,
                    node_a_id=hub_node.node_id,  # Hub node
                    node_b_id=hub_node.node_id,  # Unused
                    status="DESIRED_UP",  # Hub server should start immediately
                    params_json=json.dumps({
                        "mode": mode,
                        "sample_rate": sample_rate,
                        "buffer_size": buffer_size,
                        "x": x,
                        "y": y,
                        "hub_node_id": hub_node_id,
                        "clients": {}  # Will store {"client_node_id": {"send_channels": 2, "receive_channels": 2}}
                    })
                )
                session.add(link)
                session.commit()
                logger.info(f"Created hub server link in database: {link_id[:8]}")
        except Exception as e:
            logger.error(f"Failed to create link: {e}", exc_info=True)
            return
        
        # Refresh to show new link with wire to hub
        self.refresh()
    
    def configure_link_node(self, link_node: LinkNodeItem):
        """Show configuration dialog for link node."""
        from PySide6.QtWidgets import QDialog, QFormLayout, QSpinBox, QComboBox, QDialogButtonBox
        
        dialog = QDialog()
        dialog.setWindowTitle(f"Configure Link: {link_node.link_data.link_id[:8]}")
        layout = QFormLayout(dialog)
        
        # Mode
        mode_combo = QComboBox()
        mode_combo.addItems(["P2P", "HUB"])
        mode_combo.setCurrentText(link_node.link_data.mode)
        layout.addRow("Mode:", mode_combo)
        
        # Send Channels
        send_channels_spin = QSpinBox()
        send_channels_spin.setRange(1, 8)
        send_channels_spin.setValue(getattr(link_node.link_data, 'send_channels', link_node.link_data.channels))
        layout.addRow("Send Channels:", send_channels_spin)
        
        # Receive Channels
        receive_channels_spin = QSpinBox()
        receive_channels_spin.setRange(1, 8)
        receive_channels_spin.setValue(getattr(link_node.link_data, 'receive_channels', link_node.link_data.channels))
        layout.addRow("Receive Channels:", receive_channels_spin)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            # Get JACK audio settings from parent
            sample_rate = link_node.link_data.sample_rate
            buffer_size = link_node.link_data.buffer_size
            if hasattr(self.parent(), 'sample_rate'):
                sample_rate = self.parent().sample_rate
            if hasattr(self.parent(), 'buffer_size'):
                buffer_size = self.parent().buffer_size
            
            # Update link node
            link_node.link_data.mode = mode_combo.currentText()
            link_node.link_data.send_channels = send_channels_spin.value()
            link_node.link_data.receive_channels = receive_channels_spin.value()
            link_node.link_data.channels = send_channels_spin.value()  # Keep for backwards compat
            link_node.link_data.sample_rate = sample_rate
            link_node.link_data.buffer_size = buffer_size
            link_node.update()
            
            # Update database
            try:
                with self.database.get_session() as session:
                    from verdandi_codex.models.fabric import FabricLink
                    import json
                    
                    link = session.query(FabricLink).filter_by(link_id=link_node.link_data.link_id).first()
                    if link:
                        params = json.loads(link.params_json) if isinstance(link.params_json, str) else link.params_json or {}
                        params.update({
                            "mode": link_node.link_data.mode,
                            "send_channels": link_node.link_data.send_channels,
                            "receive_channels": link_node.link_data.receive_channels,
                            "sample_rate": link_node.link_data.sample_rate,
                            "buffer_size": link_node.link_data.buffer_size,
                            "x": link_node.pos().x(),
                            "y": link_node.pos().y()
                        })
                        link.params_json = json.dumps(params)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed to update link: {e}", exc_info=True)
            
            logger.info(f"Configured link: {link_node.link_data.link_id[:8]}, "
                       f"{link_node.link_data.mode}, {link_node.link_data.send_channels}→{link_node.link_data.receive_channels}ch")
    
    def delete_link_node(self, link_node: LinkNodeItem):
        """Delete a link node."""
        reply = QMessageBox.question(
            None, "Delete Link",
            f"Delete link {link_node.link_data.link_id[:8]}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            link_id = link_node.link_data.link_id
            
            # Remove connected wires
            wires_to_remove = []
            for wire in self.wires:
                if wire.from_item == link_node or wire.to_item == link_node:
                    wires_to_remove.append(wire)
            
            for wire in wires_to_remove:
                self.scene.removeItem(wire)
                self.wires.remove(wire)
            
            # Remove from scene and memory
            self.scene.removeItem(link_node)
            if link_id in self.link_nodes:
                del self.link_nodes[link_id]
            
            # Delete from database
            try:
                with self.database.get_session() as session:
                    from verdandi_codex.models.fabric import FabricLink
                    link = session.query(FabricLink).filter_by(link_id=link_id).first()
                    if link:
                        session.delete(link)
                        session.commit()
                        logger.info(f"Deleted link from database: {link_id[:8]}")
            except Exception as e:
                logger.error(f"Failed to delete link from database: {e}", exc_info=True)
            
            logger.info(f"Deleted link node: {link_id[:8]}")


class FabricCanvasWidget(QWidget):
    """Widget containing the fabric canvas with controls."""
    
    def __init__(self, config: VerdandiConfig, database: Database, jack_manager=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.database = database
        self.jack_manager = jack_manager
        
        layout = QVBoxLayout(self)
        
        # Audio Settings Display - read-only, shows current JACK settings
        settings_group = QHBoxLayout()
        settings_group.addWidget(QLabel("<b>JACK Audio Settings:</b>"))
        
        # Get current JACK settings
        sample_rate = 48000
        buffer_size = 256
        if jack_manager:
            sample_rate = jack_manager.get_sample_rate()
            buffer_size = jack_manager.get_buffer_size()
        
        # Create labels that can be updated later
        self.sample_rate_label = QLabel(f"Sample Rate: {sample_rate} Hz")
        self.buffer_size_label = QLabel(f"Buffer Size: {buffer_size} frames")
        settings_group.addWidget(self.sample_rate_label)
        settings_group.addWidget(self.buffer_size_label)
        settings_group.addWidget(QLabel("<i>(Configure JACK server to change)</i>"))
        settings_group.addStretch()
        
        layout.addLayout(settings_group)
        
        # Store for link nodes to use
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        
        # Hub Node Selection (global for all links)
        hub_layout = QHBoxLayout()
        hub_layout.addWidget(QLabel("<b>Hub Node:</b>"))
        
        self.hub_node_combo = QComboBox()
        self._populate_hub_nodes()
        hub_layout.addWidget(self.hub_node_combo)
        
        self.start_hub_btn = QPushButton("▶️ Start Hub")
        self.start_hub_btn.clicked.connect(self._on_start_hub)
        hub_layout.addWidget(self.start_hub_btn)
        
        self.stop_hub_btn = QPushButton("⏹️ Stop Hub")
        self.stop_hub_btn.clicked.connect(self._on_stop_hub)
        self.stop_hub_btn.setEnabled(False)
        hub_layout.addWidget(self.stop_hub_btn)
        
        hub_config_btn = QPushButton("⚙️ Settings")
        hub_config_btn.clicked.connect(self._on_configure_hub)
        hub_layout.addWidget(hub_config_btn)
        
        hub_layout.addStretch()
        
        layout.addLayout(hub_layout)
        
        # Track hub state
        self.hub_running = False
        self.hub_node_id = None
        self.hub_inactivity_timer = QTimer(self)
        self.hub_inactivity_timer.timeout.connect(self._on_hub_inactivity)
        self.hub_inactivity_timeout = 300000  # 5 minutes in ms
        
        # Store hub configuration
        self.hub_autopatch_mode = 1  # Default: full mix
        self.hub_include_server = True
        
        # Controls
        controls = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._on_refresh)
        controls.addWidget(refresh_btn)
        
        add_link_btn = QPushButton("➕ Add Link Node")
        add_link_btn.clicked.connect(self._on_add_link)
        controls.addWidget(add_link_btn)
        
        self.status_label = QLabel("Loading...")
        controls.addWidget(self.status_label)
        
        controls.addStretch()
        layout.addLayout(controls)
        
        # Canvas
        self.canvas = FabricCanvas(config, database, self)
        layout.addWidget(self.canvas)
        
        self._update_status()
    
    def _populate_hub_nodes(self):
        """Load available nodes into hub selector."""
        self.hub_node_combo.clear()
        try:
            with self.database.get_session() as session:
                from verdandi_codex.models.identity import Node
                nodes = session.query(Node).all()
                for node in nodes:
                    display = f"{node.hostname} ({node.display_name or 'unnamed'})"
                    self.hub_node_combo.addItem(display, str(node.node_id))
        except Exception as e:
            logger.error(f"Failed to load hub nodes: {e}", exc_info=True)
    
    def _on_refresh(self):
        """Manual refresh."""
        self.canvas.refresh()
        self._populate_hub_nodes()
        self._update_status()
    
    def _on_configure_hub(self):
        """Show hub server configuration dialog."""
        from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QCheckBox, QDialogButtonBox, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Hub Server Configuration")
        layout = QFormLayout(dialog)
        
        layout.addRow(QLabel("<b>JackTrip Hub Server Settings</b>"))
        layout.addRow(QLabel("These settings apply to the hub server that all clients connect to."))
        layout.addRow(QLabel(""))
        
        # Autopatch mode
        autopatch_combo = QComboBox()
        autopatch_combo.addItem("Full Mix (all clients hear everyone)", 1)
        autopatch_combo.addItem("Client-based (client controls patching)", 0)
        autopatch_combo.addItem("No Auto-patch (manual patching only)", 2)
        autopatch_combo.setCurrentIndex(0)  # Default to full mix
        for i in range(autopatch_combo.count()):
            if autopatch_combo.itemData(i) == self.hub_autopatch_mode:
                autopatch_combo.setCurrentIndex(i)
                break
        layout.addRow("Autopatch Mode:", autopatch_combo)
        
        # Include server checkbox
        include_server_check = QCheckBox("Include hub server in audio mix")
        include_server_check.setChecked(self.hub_include_server)
        layout.addRow(include_server_check)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            self.hub_autopatch_mode = autopatch_combo.currentData()
            self.hub_include_server = include_server_check.isChecked()
            logger.info(f"Hub config updated: autopatch={self.hub_autopatch_mode}, include_server={self.hub_include_server}")
    
    def _on_add_link(self):
        """Add a new link node to center of view."""
        center = self.canvas.viewport().rect().center()
        scene_pos = self.canvas.mapToScene(center)
        self.canvas.add_link_node(scene_pos.x(), scene_pos.y())
        self._update_status()
    
    def _update_status(self):
        """Update status label."""
        fabric_count = len(self.canvas.fabric_nodes)
        link_count = len(self.canvas.link_nodes)
        wire_count = len(self.canvas.wires)
        hub_status = "HUB RUNNING" if self.hub_running else "hub idle"
        self.status_label.setText(f"{fabric_count} nodes, {link_count} links, {wire_count} connections | {hub_status}")
    
    def _on_start_hub(self):
        """Start JackTrip hub server on selected node."""
        selected_idx = self.hub_node_combo.currentIndex()
        if selected_idx < 0:
            QMessageBox.warning(self, "No Hub Selected", "Please select a node to run as hub.")
            return
        
        self.hub_node_id = self.hub_node_combo.itemData(selected_idx)
        
        logger.info(f"Starting JackTrip hub on node {self.hub_node_id}")
        
        try:
            # Get node info
            with self.database.get_session() as session:
                from verdandi_codex.models.identity import Node
                node = session.query(Node).filter_by(node_id=self.hub_node_id).first()
                if not node:
                    QMessageBox.critical(self, "Error", "Selected node not found in database.")
                    return
                
                hostname = node.hostname
                session.expunge(node)  # Detach for use outside session
            
            # Call gRPC to start hub
            from verdandi_hall.grpc_client import VerdandiGrpcClient
            
            with VerdandiGrpcClient(node, timeout=30) as client:
                response = client.start_jacktrip_hub(
                    send_channels=2,
                    receive_channels=2,
                    sample_rate=self.sample_rate,
                    buffer_size=self.buffer_size
                )
                
                if not response.success:
                    QMessageBox.critical(self, "Error", f"Failed to start hub: {response.message}")
                    return
            
            # Update UI
            self.hub_running = True
            self.start_hub_btn.setEnabled(False)
            self.stop_hub_btn.setEnabled(True)
            self.hub_node_combo.setEnabled(False)
            
            # Start inactivity timer
            self.hub_inactivity_timer.start(self.hub_inactivity_timeout)
            
            self._update_status()
            QMessageBox.information(self, "Hub Started", 
                                  f"JackTrip hub server started on {hostname}.\n\n"
                                  f"Clients can now connect to this node.")
            
        except Exception as e:
            logger.error(f"Failed to start hub: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to start hub: {e}")
    
    def _on_stop_hub(self):
        """Stop JackTrip hub server."""
        if not self.hub_running:
            return
        
        logger.info(f"Stopping JackTrip hub on node {self.hub_node_id}")
        
        try:
            # Get node info
            with self.database.get_session() as session:
                from verdandi_codex.models.identity import Node
                node = session.query(Node).filter_by(node_id=self.hub_node_id).first()
                if node:
                    session.expunge(node)
                    
                    # Call gRPC to stop hub
                    from verdandi_hall.grpc_client import VerdandiGrpcClient
                    with VerdandiGrpcClient(node, timeout=30) as client:
                        client.stop_jacktrip_hub()
        except Exception as e:
            logger.error(f"Failed to stop hub: {e}", exc_info=True)
        
        # Update UI
        self.hub_running = False
        self.hub_node_id = None
        self.start_hub_btn.setEnabled(True)
        self.stop_hub_btn.setEnabled(False)
        self.hub_node_combo.setEnabled(True)
        self.hub_inactivity_timer.stop()
        
        self._update_status()
        QMessageBox.information(self, "Hub Stopped", "JackTrip hub server has been stopped.")
    
    def _on_hub_inactivity(self):
        """Auto-stop hub after inactivity timeout."""
        if self.hub_running and len(self.canvas.wires) == 0:
            logger.info("Auto-stopping hub due to inactivity")
            self._on_stop_hub()
    
    def closeEvent(self, event):
        """Handle widget close - stop hub if running."""
        if self.hub_running:
            self._on_stop_hub()
        super().closeEvent(event)
