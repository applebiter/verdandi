"""
Fabric Canvas for Verdandi Hall.
Visualizes the multi-node fabric network with nodes and links.
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, List, Set, TYPE_CHECKING
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsEllipseItem, QGraphicsLineItem, 
    QPushButton, QLabel
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.models.fabric import FabricNode, FabricLink, LinkStatus

logger = logging.getLogger(__name__)


@dataclass
class NodeGraphics:
    """Graphics data for a fabric node."""
    node_id: str
    hostname: str
    ip_address: str
    x: float
    y: float
    is_local: bool = False


@dataclass
class LinkGraphics:
    """Graphics data for a fabric link."""
    link_id: str
    node_a_id: str
    node_b_id: str
    link_type: str
    status: str
    channels: int = 2
    sample_rate: int = 48000
    buffer_size: int = 128


class FabricNodeItem(QGraphicsEllipseItem):
    """Graphics item for a fabric node."""
    
    def __init__(self, node: NodeGraphics):
        super().__init__(-30, -30, 60, 60)
        self.node = node
        
        # Set colors
        if node.is_local:
            color = QColor(100, 180, 100)  # Green for local node
        else:
            color = QColor(80, 120, 180)  # Blue for remote nodes
            
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(200, 200, 200), 2))
        
        # Make it movable and selectable
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        
        self.setPos(node.x, node.y)
        self.setToolTip(f"{node.hostname}\n{node.ip_address}\nID: {node.node_id[:8]}")
        
    def paint(self, painter, option, widget):
        # Draw the circle
        super().paint(painter, option, widget)
        
        # Draw hostname text
        painter.setFont(QFont("Sans", 10, QFont.Bold))
        painter.setPen(QPen(QColor(255, 255, 255)))
        text_rect = QRectF(-30, -10, 60, 20)
        painter.drawText(text_rect, Qt.AlignCenter, self.node.hostname)


class FabricLinkItem(QGraphicsLineItem):
    """Graphics item for a fabric link."""
    
    def __init__(self, link: LinkGraphics, node_a_item: FabricNodeItem, node_b_item: FabricNodeItem):
        super().__init__()
        self.link = link
        self.node_a_item = node_a_item
        self.node_b_item = node_b_item
        
        # Set line color based on status
        if "UP" in link.status:
            color = QColor(100, 200, 100)  # Green for UP
        elif "DOWN" in link.status:
            color = QColor(200, 100, 100)  # Red for DOWN
        else:
            color = QColor(150, 150, 150)  # Gray for unknown
            
        pen = QPen(color, 3)
        if link.link_type == "AUDIO_JACKTRIP":
            pen.setStyle(Qt.SolidLine)
        elif link.link_type == "MIDI_RTPMIDI":
            pen.setStyle(Qt.DashLine)
        else:
            pen.setStyle(Qt.DotLine)
            
        self.setPen(pen)
        
        # Create tooltip with full info
        tooltip_lines = [
            f"Type: {link.link_type}",
            f"Status: {link.status}",
            f"Channels: {link.channels}",
            f"Sample Rate: {link.sample_rate} Hz",
            f"Buffer Size: {link.buffer_size} frames",
            f"Link ID: {link.link_id[:8]}"
        ]
        self.setToolTip("\n".join(tooltip_lines))
        
        self.update_position()
        
    def update_position(self):
        """Update line position based on node positions."""
        p1 = self.node_a_item.pos()
        p2 = self.node_b_item.pos()
        self.setLine(p1.x(), p1.y(), p2.x(), p2.y())
        
    def paint(self, painter, option, widget):
        """Custom paint to show channel count label."""
        super().paint(painter, option, widget)
        
        # Draw channel count in the middle of the line
        p1 = self.node_a_item.pos()
        p2 = self.node_b_item.pos()
        mid_x = (p1.x() + p2.x()) / 2
        mid_y = (p1.y() + p2.y()) / 2
        
        # Draw background rectangle for text
        painter.setBrush(QBrush(QColor(40, 40, 40, 200)))
        painter.setPen(QPen(QColor(150, 150, 150)))
        text_rect = QRectF(mid_x - 20, mid_y - 10, 40, 20)
        painter.drawRect(text_rect)
        
        # Draw channel count text
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setFont(QFont("Sans", 8, QFont.Bold))
        painter.drawText(text_rect, Qt.AlignCenter, f"{self.link.channels}ch")


class FabricCanvas(QGraphicsView):
    """Canvas for visualizing the fabric network."""
    
    def __init__(self, config: VerdandiConfig, database: Database, parent=None):
        super().__init__(parent)
        self.config = config
        self.database = database
        
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        # Configure view
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        
        # Storage
        self.node_items: Dict[str, FabricNodeItem] = {}
        self.link_items: Dict[str, FabricLinkItem] = {}
        
        # Auto-refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(5000)  # Refresh every 5 seconds
        
        # Initial load
        self.refresh()
        
    def refresh(self):
        """Refresh the fabric graph from database."""
        try:
            session = self.database.get_session()
            
            # Get all nodes
            nodes = session.query(FabricNode).all()
            node_map = {str(n.node_id): n for n in nodes}
            
            # Get all links
            links = session.query(FabricLink).all()
            
            session.close()
            
            # Update nodes
            current_node_ids = set(node_map.keys())
            existing_node_ids = set(self.node_items.keys())
            
            # Remove deleted nodes
            for node_id in existing_node_ids - current_node_ids:
                if node_id in self.node_items:
                    self.scene.removeItem(self.node_items[node_id])
                    del self.node_items[node_id]
            
            # Add or update nodes
            for node_id, node in node_map.items():
                if node_id not in self.node_items:
                    # New node - add it with auto-layout
                    x = (len(self.node_items) % 4) * 150
                    y = (len(self.node_items) // 4) * 150
                    
                    node_graphics = NodeGraphics(
                        node_id=str(node.node_id),
                        hostname=node.hostname,
                        ip_address=node.ip_address or "unknown",
                        x=x,
                        y=y,
                        is_local=(str(node.node_id) == str(self.config.node.node_id))
                    )
                    
                    item = FabricNodeItem(node_graphics)
                    self.scene.addItem(item)
                    self.node_items[node_id] = item
            
            # Update links
            current_link_ids = {str(link.link_id): link for link in links}
            existing_link_ids = set(self.link_items.keys())
            
            # Remove deleted links
            for link_id in existing_link_ids - set(current_link_ids.keys()):
                if link_id in self.link_items:
                    self.scene.removeItem(self.link_items[link_id])
                    del self.link_items[link_id]
            
            # Add new links
            for link_id, link in current_link_ids.items():
                node_a_id = str(link.node_a_id)
                node_b_id = str(link.node_b_id)
                
                if node_a_id in self.node_items and node_b_id in self.node_items:
                    if link_id not in self.link_items:
                        # Extract params from JSON
                        import json
                        params = json.loads(link.params_json) if link.params_json else {}
                        
                        link_graphics = LinkGraphics(
                            link_id=str(link.link_id),
                            node_a_id=node_a_id,
                            node_b_id=node_b_id,
                            link_type=str(link.link_type),
                            status=str(link.status),
                            channels=params.get('channels', 2),
                            sample_rate=params.get('sample_rate', 48000),
                            buffer_size=params.get('buffer_size', 128)
                        )
                        
                        item = FabricLinkItem(
                            link_graphics,
                            self.node_items[node_a_id],
                            self.node_items[node_b_id]
                        )
                        self.scene.addItem(item)
                        self.link_items[link_id] = item
                    else:
                        # Update existing link
                        self.link_items[link_id].update_position()
            
            # Update link positions when nodes move
            for link_item in self.link_items.values():
                link_item.update_position()
                
        except Exception as e:
            logger.error(f"Error refreshing fabric canvas: {e}")


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
        
        self.status_label = QLabel("Loading fabric graph...")
        controls.addWidget(self.status_label)
        
        controls.addStretch()
        layout.addLayout(controls)
        
        # Canvas
        self.canvas = FabricCanvas(config, database, self)
        layout.addWidget(self.canvas)
        
        # Update status
        self._update_status()
        
    def _on_refresh(self):
        """Manual refresh triggered."""
        self.canvas.refresh()
        self._update_status()
        
    def _update_status(self):
        """Update status label."""
        node_count = len(self.canvas.node_items)
        link_count = len(self.canvas.link_items)
        self.status_label.setText(f"{node_count} nodes, {link_count} links")
