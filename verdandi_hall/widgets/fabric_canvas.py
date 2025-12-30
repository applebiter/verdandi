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
    QGraphicsLineItem, QPushButton, QLabel, QMenu, QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPolygonF, QAction

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
    # Connections
    source_node_id: Optional[str] = None  # For P2P: client node
    target_node_id: Optional[str] = None  # For P2P: server node
    hub_node_id: Optional[str] = None     # For HUB: hub node
    client_ids: Optional[List[str]] = None  # For HUB: client nodes


class ConnectionPort(QGraphicsEllipseItem):
    """Visual connection port on a node."""
    
    def __init__(self, parent_item, port_type: str, angle: float = 0):
        super().__init__(-8, -8, 16, 16)
        self.parent_item = parent_item
        self.port_type = port_type  # "input" or "output"
        self.angle = angle
        
        self.setBrush(QBrush(QColor(200, 200, 200)))
        self.setPen(QPen(QColor(100, 100, 100), 2))
        
        self.setParentItem(parent_item)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)
        
        # Position based on angle
        radius = 45 if isinstance(parent_item, FabricNodeItem) else 35
        import math
        x = radius * math.cos(math.radians(angle))
        y = radius * math.sin(math.radians(angle))
        self.setPos(x, y)
    
    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255, 200, 100)))
        self.setPen(QPen(QColor(255, 150, 0), 3))
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(200, 200, 200)))
        self.setPen(QPen(QColor(100, 100, 100), 2))
        super().hoverLeaveEvent(event)


class ConnectionWire(QGraphicsLineItem):
    """Visual wire connecting nodes via their ports."""
    
    def __init__(self, from_item, to_item, from_port=None, to_port=None):
        super().__init__()
        self.from_item = from_item
        self.to_item = to_item
        self.from_port = from_port
        self.to_port = to_port
        
        pen = QPen(QColor(150, 150, 150), 3)
        self.setPen(pen)
        self.update_position()
    
    def update_position(self):
        """Update line position based on connected items and ports."""
        if self.from_port and self.to_port:
            # Connect port to port
            p1 = self.from_port.sceneBoundingRect().center()
            p2 = self.to_port.sceneBoundingRect().center()
        elif self.from_port:
            # Connect port to item center
            p1 = self.from_port.sceneBoundingRect().center()
            p2 = self.to_item.sceneBoundingRect().center()
        elif self.to_port:
            # Connect item center to port
            p1 = self.from_item.sceneBoundingRect().center()
            p2 = self.to_port.sceneBoundingRect().center()
        else:
            # Connect item centers (fallback)
            p1 = self.from_item.sceneBoundingRect().center()
            p2 = self.to_item.sceneBoundingRect().center()
        
        self.setLine(p1.x(), p1.y(), p2.x(), p2.y())


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
        
        # Add connection ports at cardinal points
        self.input_port_left = ConnectionPort(self, "input", 180)   # Left
        self.input_port_top = ConnectionPort(self, "input", 270)    # Top
        self.output_port_right = ConnectionPort(self, "output", 0)  # Right
        self.output_port_bottom = ConnectionPort(self, "output", 90) # Bottom
    
    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        
        # Draw mode text
        painter.setFont(QFont("Sans", 8, QFont.Bold))
        painter.setPen(QPen(QColor(255, 255, 255)))
        text_rect = QRectF(-25, -8, 50, 16)
        painter.drawText(text_rect, Qt.AlignCenter, self.link_data.mode)
        
        # Draw channel count below
        painter.setFont(QFont("Sans", 7))
        text_rect2 = QRectF(-25, 5, 50, 12)
        painter.drawText(text_rect2, Qt.AlignCenter, f"{self.link_data.channels}ch")
    
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
        
        # Add connection ports around the perimeter
        self.output_port_right = ConnectionPort(self, "output", 0)    # Right
        self.output_port_bottom = ConnectionPort(self, "output", 90)  # Bottom
        self.input_port_left = ConnectionPort(self, "input", 180)     # Left
        self.input_port_top = ConnectionPort(self, "input", 270)      # Top
    
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
        
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        # Configure view
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        
        # Storage
        self.fabric_nodes: Dict[str, FabricNodeItem] = {}
        self.link_nodes: Dict[str, LinkNodeItem] = {}
        self.wires: List[ConnectionWire] = []
        
        # Auto-refresh
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(5000)
        
        self.refresh()
    
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
                    
                    link_data = LinkNodeData(
                        link_id=link_id,
                        mode=mode,
                        channels=params.get('channels', 2),
                        sample_rate=params.get('sample_rate', 48000),
                        buffer_size=params.get('buffer_size', 128),
                        status=str(link.status),
                        source_node_id=str(link.node_a_id) if mode == 'P2P' else None,
                        target_node_id=str(link.node_b_id) if mode == 'P2P' else None
                    )
                    
                    # Position between connected nodes
                    if link_data.source_node_id in self.fabric_nodes and link_data.target_node_id in self.fabric_nodes:
                        n1 = self.fabric_nodes[link_data.source_node_id]
                        n2 = self.fabric_nodes[link_data.target_node_id]
                        x = (n1.pos().x() + n2.pos().x()) / 2
                        y = (n1.pos().y() + n2.pos().y()) / 2
                    else:
                        x = 400
                        y = 300
                    
                    item = LinkNodeItem(link_data, x, y, parent_canvas=self)
                    self.scene.addItem(item)
                    self.link_nodes[link_id] = item
            
            # Update wires - clear and recreate
            for wire in self.wires:
                self.scene.removeItem(wire)
            self.wires.clear()
            
            # Create wires for P2P links
            for link_node in self.link_nodes.values():
                if link_node.link_data.mode == 'P2P':
                    src_id = link_node.link_data.source_node_id
                    tgt_id = link_node.link_data.target_node_id
                    
                    if src_id in self.fabric_nodes and tgt_id in self.fabric_nodes:
                        src_node = self.fabric_nodes[src_id]
                        tgt_node = self.fabric_nodes[tgt_id]
                        
                        # Source node output port to Link node input port
                        wire1 = ConnectionWire(
                            src_node, link_node,
                            from_port=src_node.output_port_right,
                            to_port=link_node.input_port_left
                        )
                        self.scene.addItem(wire1)
                        self.wires.append(wire1)
                        
                        # Link node output port to Target node input port
                        wire2 = ConnectionWire(
                            link_node, tgt_node,
                            from_port=link_node.output_port_right,
                            to_port=tgt_node.input_port_left
                        )
                        self.scene.addItem(wire2)
                        self.wires.append(wire2)
            
        except Exception as e:
            logger.error(f"Error refreshing fabric canvas: {e}", exc_info=True)
    
    def add_link_node(self, x: float, y: float):
        """Add a new link node at position."""
        link_id = str(uuid.uuid4())
        
        link_data = LinkNodeData(
            link_id=link_id,
            mode="P2P",
            channels=2,
            sample_rate=48000,
            buffer_size=256,
            status="UNCONFIGURED"
        )
        
        item = LinkNodeItem(link_data, x, y, parent_canvas=self)
        self.scene.addItem(item)
        self.link_nodes[link_id] = item
        
        logger.info(f"Added new link node: {link_id[:8]}")
    
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
        
        # Channels
        channels_spin = QSpinBox()
        channels_spin.setRange(1, 8)
        channels_spin.setValue(link_node.link_data.channels)
        layout.addRow("Channels:", channels_spin)
        
        # Sample Rate
        sample_rate_combo = QComboBox()
        sample_rate_combo.addItems(["44100", "48000", "96000"])
        sample_rate_combo.setCurrentText(str(link_node.link_data.sample_rate))
        layout.addRow("Sample Rate:", sample_rate_combo)
        
        # Buffer Size
        buffer_size_combo = QComboBox()
        buffer_size_combo.addItems(["64", "128", "256", "512", "1024"])
        buffer_size_combo.setCurrentText(str(link_node.link_data.buffer_size))
        layout.addRow("Buffer Size:", buffer_size_combo)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            # Update link node
            link_node.link_data.mode = mode_combo.currentText()
            link_node.link_data.channels = channels_spin.value()
            link_node.link_data.sample_rate = int(sample_rate_combo.currentText())
            link_node.link_data.buffer_size = int(buffer_size_combo.currentText())
            link_node.update()
            
            logger.info(f"Configured link: {link_node.link_data.link_id[:8]}, "
                       f"{link_node.link_data.mode}, {link_node.link_data.channels}ch")
    
    def delete_link_node(self, link_node: LinkNodeItem):
        """Delete a link node."""
        reply = QMessageBox.question(
            None, "Delete Link",
            f"Delete link {link_node.link_data.link_id[:8]}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            link_id = link_node.link_data.link_id
            self.scene.removeItem(link_node)
            if link_id in self.link_nodes:
                del self.link_nodes[link_id]
            logger.info(f"Deleted link node: {link_id[:8]}")


class FabricCanvasWidget(QWidget):
    """Widget containing the fabric canvas with controls."""
    
    def __init__(self, config: VerdandiConfig, database: Database, parent=None):
        super().__init__(parent)
        self.config = config
        self.database = database
        
        layout = QVBoxLayout(self)
        
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
    
    def _on_refresh(self):
        """Manual refresh."""
        self.canvas.refresh()
        self._update_status()
    
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
        self.status_label.setText(f"{fabric_count} nodes, {link_count} links")
