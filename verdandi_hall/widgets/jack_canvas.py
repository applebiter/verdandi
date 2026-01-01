"""
JACK Canvas for Verdandi Hall.
Adapted from skeleton-crew node_canvas_v3.py with Verdandi integration.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Dict, List, Set, Tuple, TYPE_CHECKING
from pathlib import Path
from dataclasses import dataclass, field

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QPushButton, QComboBox, QLabel,
    QInputDialog, QMessageBox
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal, QObject
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QBrush, QFont

if TYPE_CHECKING:
    from .jack_client_manager import JackClientManager

logger = logging.getLogger(__name__)

# Startup confirmation
print("=" * 60)
print("VERDANDI JACK CANVAS LOADED - Color scheme:")
print("  Audio nodes: Blue-gray (50, 60, 80)")
print("  MIDI nodes: Red-gray (80, 50, 50)")
print("  Mixed nodes: Purple-gray (70, 60, 80)")
print("=" * 60)


# ============================================================================
# PURE DATA MODEL (No Qt, No UI)
# ============================================================================

@dataclass
class PortModel:
    """Pure data: a port on a node."""
    name: str
    full_name: str
    is_output: bool
    is_midi: bool = False  # Track if this is a MIDI port

@dataclass
class NodeModel:
    """Pure data: a JACK client with ports."""
    name: str
    inputs: List[PortModel] = field(default_factory=list)
    outputs: List[PortModel] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0

@dataclass
class ConnectionModel:
    """Pure data: connection between two ports."""
    output_port: str  # full name
    input_port: str   # full name

class GraphModel(QObject):
    """Pure data model of the JACK graph. No rendering logic."""
    
    changed = Signal()  # Emitted when model changes
    
    def __init__(self):
        super().__init__()
        self.nodes: Dict[str, NodeModel] = {}
        self.connections: List[ConnectionModel] = []
        self.aliases: Dict[str, str] = {}  # Map original name -> alias
        self._batch_mode = False  # Suppress signals during batch updates
    
    def add_node(self, name: str, x: float = 0, y: float = 0) -> NodeModel:
        if name not in self.nodes:
            self.nodes[name] = NodeModel(name=name, x=x, y=y)
            if not self._batch_mode:
                self.changed.emit()
        return self.nodes[name]
    
    def set_alias(self, original_name: str, alias: str):
        """Set an alias for a node."""
        if alias and alias != original_name:
            self.aliases[original_name] = alias
        elif original_name in self.aliases:
            del self.aliases[original_name]
        self.changed.emit()
    
    def get_display_name(self, original_name: str) -> str:
        """Get display name (alias if set, otherwise original)."""
        return self.aliases.get(original_name, original_name)
    
    def move_node(self, name: str, x: float, y: float):
        if name in self.nodes:
            self.nodes[name].x = x
            self.nodes[name].y = y
            self.changed.emit()
    
    def add_connection(self, output_port: str, input_port: str):
        conn = ConnectionModel(output_port, input_port)
        if conn not in self.connections:
            self.connections.append(conn)
            if not self._batch_mode:
                self.changed.emit()
    
    def clear(self):
        self.nodes.clear()
        self.connections.clear()
        # Don't clear aliases - they persist across refreshes
        if not self._batch_mode:
            self.changed.emit()
    
    def begin_batch(self):
        """Start batch mode - suppress changed signals."""
        self._batch_mode = True
    
    def end_batch(self):
        """End batch mode - emit one changed signal."""
        self._batch_mode = False
        self.changed.emit()


# ============================================================================
# VIEW LAYER (Qt Graphics Items - render the model)
# ============================================================================

class NodeGraphicsItem(QGraphicsItem):
    """Visual representation of a NodeModel. Pure rendering, no data."""
    
    def __init__(self, model: NodeModel, graph_model: GraphModel):
        super().__init__()
        self.model = model
        self.graph_model = graph_model
        self._dragging_connection = False
        self._drag_start_port = None
        self._drag_is_output = False
        
        # CRITICAL: Use exact flags from working test
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsScenePositionChanges
        )
        
        # Disable caching to prevent artifacts during drag
        self.setCacheMode(QGraphicsItem.NoCache)
        
        self.setPos(model.x, model.y)
        self.socket_radius = 5
        self._calculate_size()
    
    def _calculate_size(self):
        """Calculate node size based on content."""
        from PySide6.QtGui import QFontMetrics
        
        # Measure text widths
        font_title = QFont("Sans", 9, QFont.Bold)
        font_port = QFont("Sans", 8)
        metrics_title = QFontMetrics(font_title)
        metrics_port = QFontMetrics(font_port)
        
        # Calculate minimum width based on title
        title_width = metrics_title.horizontalAdvance(self.model.name) + 20  # padding
        
        # If node has both inputs and outputs, need space for both side-by-side
        if self.model.inputs and self.model.outputs:
            # Find longest input and output names
            max_input_width = 0
            for port in self.model.inputs:
                width = metrics_port.horizontalAdvance(port.name)
                max_input_width = max(max_input_width, width)
            
            max_output_width = 0
            for port in self.model.outputs:
                width = metrics_port.horizontalAdvance(port.name)
                max_output_width = max(max_output_width, width)
            
            # Total width = left port text + spacing + right port text + margins
            port_width = max_input_width + max_output_width + 60  # 60 for sockets, padding, gap
        else:
            # Only inputs or only outputs - calculate normally
            max_port_width = 100
            for port in self.model.inputs + self.model.outputs:
                port_width_calc = metrics_port.horizontalAdvance(port.name) + 24
                max_port_width = max(max_port_width, port_width_calc)
            port_width = max_port_width
        
        # Width is the maximum of title and port requirements
        self.width = max(150, title_width, port_width)
    
    def _calculate_height(self):
        """Calculate node height based on port count."""
        max_ports = max(len(self.model.inputs), len(self.model.outputs), 1)
        return max(100, 30 + max_ports * 18 + 10)
    
    def boundingRect(self):
        # Expand bounds generously to include sockets AND any anti-aliasing
        height = self._calculate_height()
        margin = 10  # Extra margin to prevent artifacts
        return QRectF(-margin, -margin, 
                      self.width + 2 * self.socket_radius + 2 * margin, 
                      height + 2 * margin)
    
    def paint(self, painter, option, widget):
        # Get current height from boundingRect
        height = self._calculate_height()
        
        # Background (offset to center within margin)
        # Three-way color scheme based on port types
        margin = 10
        all_ports = self.model.inputs + self.model.outputs
        
        # TEMPORARY DEBUG - Print port info
        if not hasattr(self, '_debug_printed'):
            if all_ports:
                print(f"NODE '{self.model.name}': {len(all_ports)} ports")
                print(f"  Sample port: {all_ports[0].name}, is_midi={all_ports[0].is_midi}")
            self._debug_printed = True
        
        if len(all_ports) > 0:
            has_audio = any(not p.is_midi for p in all_ports)
            has_midi = any(p.is_midi for p in all_ports)
            
            if has_audio and has_midi:
                # Mixed node: purple-gray
                painter.setBrush(QColor(70, 60, 80))
            elif has_midi:
                # MIDI-only node: red-gray
                painter.setBrush(QColor(80, 50, 50))
            else:
                # Audio-only node: blue-gray
                painter.setBrush(QColor(50, 60, 80))
        else:
            painter.setBrush(QColor(50, 50, 50))  # Default gray for nodes with no ports
        
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.drawRoundedRect(margin + self.socket_radius, margin, self.width, height, 5, 5)
        
        # Title (use display name from graph model - may be aliased)
        display_name = self.graph_model.get_display_name(self.model.name)
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Sans", 9, QFont.Bold)
        painter.setFont(font)
        painter.drawText(QRectF(margin + self.socket_radius + 5, margin + 5, self.width - 10, 20), Qt.AlignLeft, display_name)
        
        # Input ports (left side)
        y = margin + 30
        painter.setFont(QFont("Sans", 8))
        for port in self.model.inputs:
            # Use different color for MIDI ports (purple/magenta)
            if port.is_midi:
                painter.setBrush(QColor(200, 100, 255))  # Purple for MIDI inputs
            else:
                painter.setBrush(QColor(100, 100, 255))  # Blue for audio inputs
            painter.drawEllipse(QPointF(margin + self.socket_radius, y), self.socket_radius, self.socket_radius)
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(QRectF(margin + self.socket_radius + 12, y - 8, self.width - 24, 16), Qt.AlignLeft, port.name)
            y += 18
        
        # Output ports (right side)
        y = margin + 30
        for port in self.model.outputs:
            # Use different color for MIDI ports (orange/yellow)
            if port.is_midi:
                painter.setBrush(QColor(255, 200, 100))  # Orange for MIDI outputs
            else:
                painter.setBrush(QColor(100, 255, 100))  # Green for audio outputs
            painter.drawEllipse(QPointF(margin + self.socket_radius + self.width, y), self.socket_radius, self.socket_radius)
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(QRectF(margin + self.socket_radius + 12, y - 8, self.width - 24, 16), Qt.AlignRight, port.name)
            y += 18
    
    def itemChange(self, change, value):
        # Update model when position changes - but DON'T emit changed signal during drag
        if change == QGraphicsItem.ItemPositionHasChanged:
            pos = value.toPointF() if hasattr(value, 'toPointF') else self.pos()
            # Update model silently (no signal emission)
            self.model.x = pos.x()
            self.model.y = pos.y()
            # Update ALL connections - more reliable than searching
            scene = self.scene()
            if scene and scene.views():
                view = scene.views()[0]
                if hasattr(view, 'connection_items'):
                    for conn_item in view.connection_items:
                        # Extract client name from port names for matching
                        out_client = conn_item.conn.output_port.split(':')[0]
                        in_client = conn_item.conn.input_port.split(':')[0]
                        
                        # Check if this node is involved (handle system split)
                        node_matches = False
                        if self.model.name == out_client or self.model.name == in_client:
                            node_matches = True
                        elif "system" in self.model.name and (out_client == "system" or in_client == "system"):
                            # Handle system (capture) and system (playback) nodes
                            node_matches = True
                        
                        if node_matches:
                            conn_item.update_path()
        return super().itemChange(change, value)
    
    def get_port_scene_pos(self, port_name: str, is_output: bool) -> QPointF:
        """Get scene position of a port."""
        ports = self.model.outputs if is_output else self.model.inputs
        margin = 10
        for i, port in enumerate(ports):
            if port.name == port_name:
                y = margin + 30 + i * 18
                # Account for margin and socket_radius offset in boundingRect
                x = (margin + self.socket_radius + self.width) if is_output else (margin + self.socket_radius)
                return self.mapToScene(QPointF(x, y))
        return self.scenePos()
    
    def get_port_at_pos(self, pos: QPointF) -> tuple[Optional[PortModel], bool]:
        """Check if position is over a port. Returns (port, is_output) or (None, False)."""
        margin = 10
        socket_radius = self.socket_radius
        
        # Check input ports (left side)
        y = margin + 30
        for port in self.model.inputs:
            port_center = QPointF(margin + socket_radius, y)
            distance = (pos - port_center).manhattanLength()
            if distance < socket_radius * 2:  # Click area slightly larger than socket
                return (port, False)
            y += 18
        
        # Check output ports (right side)
        y = margin + 30
        for port in self.model.outputs:
            port_center = QPointF(margin + socket_radius + self.width, y)
            distance = (pos - port_center).manhattanLength()
            if distance < socket_radius * 2:
                return (port, True)
            y += 18
        
        return (None, False)
    
    def mousePressEvent(self, event):
        """Check if clicking on a port to start connection drag."""
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            port, is_output = self.get_port_at_pos(pos)
            if port:
                # Start dragging a connection from this port
                self._dragging_connection = True
                self._drag_start_port = port
                self._drag_is_output = is_output
                event.accept()
                # Notify view to start drawing temp connection
                if self.scene() and self.scene().views():
                    view = self.scene().views()[0]
                    if hasattr(view, 'start_connection_drag'):
                        start_pos = self.get_port_scene_pos(port.name, is_output)
                        view.start_connection_drag(start_pos, port.full_name, is_output)
                return
        elif event.button() == Qt.RightButton:
            # Show context menu for renaming
            self._show_context_menu(event.screenPos())
            event.accept()
            return
        
        # Not clicking on port, allow normal drag
        super().mousePressEvent(event)
    
    def _show_context_menu(self, pos):
        """Show context menu for node operations."""
        from PySide6.QtWidgets import QMenu
        
        menu = QMenu()
        
        current_display = self.graph_model.get_display_name(self.model.name)
        is_aliased = current_display != self.model.name
        
        rename_action = menu.addAction("Rename Client...")
        if is_aliased:
            reset_action = menu.addAction(f"Reset to '{self.model.name}'")
        else:
            reset_action = None
        
        action = menu.exec(pos)
        
        if action == rename_action:
            new_name, ok = QInputDialog.getText(
                None,
                "Rename Client",
                f"Enter new name for '{current_display}':",
                text=current_display
            )
            if ok and new_name and new_name != current_display:
                self.graph_model.set_alias(self.model.name, new_name)
        elif reset_action and action == reset_action:
            self.graph_model.set_alias(self.model.name, "")  # Clear alias
    
    def mouseMoveEvent(self, event):
        """Update temp connection line if dragging."""
        if self._dragging_connection:
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                if hasattr(view, 'update_connection_drag'):
                    view.update_connection_drag(self.mapToScene(event.pos()))
            event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Complete connection if released over valid port."""
        if self._dragging_connection:
            # Check if released over a port
            items = self.scene().items(self.mapToScene(event.pos()))
            target_port = None
            target_is_output = False
            
            for item in items:
                if isinstance(item, NodeGraphicsItem) and item != self:
                    port, is_output = item.get_port_at_pos(item.mapFromScene(self.mapToScene(event.pos())))
                    if port:
                        target_port = port
                        target_is_output = is_output
                        break
            
            # Notify view to complete or cancel
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                if hasattr(view, 'end_connection_drag'):
                    view.end_connection_drag(target_port.full_name if target_port else None, target_is_output)
            
            self._dragging_connection = False
            self._drag_start_port = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ConnectionGraphicsItem(QGraphicsItem):
    """Visual representation of a ConnectionModel."""
    
    def __init__(self, conn: ConnectionModel, graph_model: GraphModel, node_items: Dict[str, NodeGraphicsItem]):
        super().__init__()
        self.conn = conn
        self.graph_model = graph_model
        self.node_items = node_items
        self.setZValue(-1)  # Behind nodes
        self.path = QPainterPath()
        self.setAcceptHoverEvents(True)  # Enable hover for highlighting
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)  # Make selectable
        self._hovered = False
        self.update_path()
    
    def boundingRect(self):
        return self.path.boundingRect().adjusted(-5, -5, 5, 5)  # Add padding for click area
    
    def paint(self, painter, option, widget):
        # Highlight on hover or selection
        if self._hovered or self.isSelected():
            painter.setPen(QPen(QColor(255, 100, 100), 4))
        else:
            painter.setPen(QPen(QColor(255, 200, 100), 2))
        painter.drawPath(self.path)
    
    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):
        """Right-click to delete connection."""
        if event.button() == Qt.RightButton:
            # Get parent widget to access jack_manager or remote_node
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                parent = view.parent()
                while parent and not hasattr(parent, 'jack_manager') and not hasattr(parent, 'remote_node'):
                    parent = parent.parent()
                
                if parent:
                    try:
                        if parent.jack_manager:
                            # Local disconnection
                            parent.jack_manager.disconnect_ports(self.conn.output_port, self.conn.input_port)
                            parent.refresh_from_jack()
                        elif parent.remote_node:
                            # Remote disconnection via gRPC
                            from verdandi_hall.grpc_client import VerdandiGrpcClient
                            with VerdandiGrpcClient(parent.remote_node, timeout=10) as client:
                                response = client.disconnect_jack_ports(self.conn.output_port, self.conn.input_port)
                                if response.success:
                                    logger.info(f"Remote disconnection: {response.message}")
                                    # Trigger remote refresh
                                    if hasattr(parent, 'remote_refresh_requested'):
                                        parent.remote_refresh_requested.emit()
                                else:
                                    logger.error(f"Failed to disconnect remotely: {response.message}")
                    except Exception as e:
                        logger.error(f"Failed to disconnect: {e}", exc_info=True)
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def update_path(self):
        # Find start and end positions
        start_pos = self._get_port_pos(self.conn.output_port, is_output=True)
        end_pos = self._get_port_pos(self.conn.input_port, is_output=False)
        
        if start_pos and end_pos:
            # MUST call prepareGeometryChange BEFORE modifying geometry
            self.prepareGeometryChange()
            
            self.path = QPainterPath()
            self.path.moveTo(start_pos)
            
            # Bezier curve
            dist = abs(end_pos.x() - start_pos.x()) * 0.5
            self.path.cubicTo(
                start_pos.x() + dist, start_pos.y(),
                end_pos.x() - dist, end_pos.y(),
                end_pos.x(), end_pos.y()
            )
            
            # Force redraw
            self.update()
    
    def _get_port_pos(self, full_port_name: str, is_output: bool) -> Optional[QPointF]:
        if ':' not in full_port_name:
            return None
        
        client_name = full_port_name.split(':')[0]
        port_name = ':'.join(full_port_name.split(':')[1:])
        
        # Handle system split
        if client_name == "system":
            if "capture" in port_name:
                client_name = "system (capture)"
            elif "playback" in port_name:
                client_name = "system (playback)"
        
        node_item = self.node_items.get(client_name)
        if node_item:
            return node_item.get_port_scene_pos(port_name, is_output)
        return None


class GraphCanvas(QGraphicsView):
    """View layer - renders the GraphModel."""
    
    def __init__(self, model: GraphModel):
        super().__init__()
        self.model = model
        self.scene = QGraphicsScene(-2000, -2000, 4000, 4000)
        self.setScene(self.scene)
        
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        
        # Enable panning with middle mouse button
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        
        self.node_items: Dict[str, NodeGraphicsItem] = {}
        self.connection_items: List[ConnectionGraphicsItem] = []
        
        # Temporary connection for drag-to-connect
        self._temp_connection_item = None
        self._temp_start_pos = None
        self._temp_start_port = None
        self._temp_start_is_output = False
        
        # Rebuild view when model changes
        self.model.changed.connect(self.rebuild_view)
    
    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        self.scale(factor, factor)
    
    def start_connection_drag(self, start_pos: QPointF, start_port: str, is_output: bool):
        """Start dragging a temporary connection line."""
        from PySide6.QtWidgets import QGraphicsLineItem
        self._temp_start_pos = start_pos
        self._temp_start_port = start_port
        self._temp_start_is_output = is_output
        
        # Set crosshair cursor during drag
        self.setCursor(Qt.CrossCursor)
        
        # Create temp line
        self._temp_connection_item = QGraphicsLineItem()
        self._temp_connection_item.setPen(QPen(QColor(255, 255, 0, 180), 3, Qt.DashLine))
        self._temp_connection_item.setLine(start_pos.x(), start_pos.y(), start_pos.x(), start_pos.y())
        self._temp_connection_item.setZValue(-2)
        self.scene.addItem(self._temp_connection_item)
    
    def update_connection_drag(self, current_pos: QPointF):
        """Update the temporary connection line."""
        if self._temp_connection_item and self._temp_start_pos:
            self._temp_connection_item.setLine(
                self._temp_start_pos.x(), self._temp_start_pos.y(),
                current_pos.x(), current_pos.y()
            )
    
    def end_connection_drag(self, end_port: Optional[str], end_is_output: bool):
        """Complete or cancel the connection drag."""
        # Restore arrow cursor
        self.setCursor(Qt.ArrowCursor)
        
        # Remove temp line
        if self._temp_connection_item:
            self.scene.removeItem(self._temp_connection_item)
            self._temp_connection_item = None
        
        # Create connection if valid
        if end_port and self._temp_start_port:
            # Validate: must connect output to input
            if self._temp_start_is_output and not end_is_output:
                # Output -> Input (correct)
                self._create_jack_connection(self._temp_start_port, end_port)
            elif not self._temp_start_is_output and end_is_output:
                # Input <- Output (reverse it)
                self._create_jack_connection(end_port, self._temp_start_port)
            # else: invalid connection (output to output or input to input)
        
        self._temp_start_pos = None
        self._temp_start_port = None
    
    def _create_jack_connection(self, output_port: str, input_port: str):
        """Create a JACK connection between two ports."""
        # Get parent widget to access jack_manager or remote_node
        parent = self.parent()
        while parent and not hasattr(parent, 'jack_manager') and not hasattr(parent, 'remote_node'):
            parent = parent.parent()
        
        if parent:
            try:
                if parent.jack_manager:
                    # Local connection
                    parent.jack_manager.connect_ports(output_port, input_port)
                    parent.refresh_from_jack()
                elif parent.remote_node:
                    # Remote connection via gRPC
                    from verdandi_hall.grpc_client import VerdandiGrpcClient
                    with VerdandiGrpcClient(parent.remote_node, timeout=10) as client:
                        response = client.connect_jack_ports(output_port, input_port)
                        if response.success:
                            logger.info(f"Remote connection created: {response.message}")
                            # Trigger remote refresh
                            if hasattr(parent, 'remote_refresh_requested'):
                                parent.remote_refresh_requested.emit()
                        else:
                            logger.error(f"Failed to create remote connection: {response.message}")
            except Exception as e:
                logger.error(f"Failed to create connection: {e}", exc_info=True)
    
    def rebuild_view(self):
        """Rebuild all graphics items from model."""
        # Clear existing items
        for item in self.connection_items:
            self.scene.removeItem(item)
        for item in self.node_items.values():
            self.scene.removeItem(item)
        
        self.node_items.clear()
        self.connection_items.clear()
        
        # Create node items
        for node_model in self.model.nodes.values():
            item = NodeGraphicsItem(node_model, self.model)
            self.scene.addItem(item)
            self.node_items[node_model.name] = item
        
        # Create connection items
        for conn in self.model.connections:
            item = ConnectionGraphicsItem(conn, self.model, self.node_items)
            self.scene.addItem(item)
            self.connection_items.append(item)
        
        # Update connection paths
        for item in self.connection_items:
            item.update_path()


# ============================================================================
# CONTROLLER WIDGET
# ============================================================================

class NodeCanvasWidget(QWidget):
    """Controller - bridges JACK manager and GraphModel."""
    
    # Signal for remote canvases to request refresh
    remote_refresh_requested = Signal()
    
    def __init__(self, jack_manager: Optional[JackClientManager] = None, parent=None, node_id: str = None, remote_node=None):
        super().__init__(parent)
        self.jack_manager = jack_manager
        self.node_id = node_id or "local"  # Default to "local" for local canvas
        self.remote_node = remote_node  # Node object for remote gRPC operations
        
        # Determine presets directory based on node_id
        if node_id:
            # Remote node - store state separately per node
            self.presets_dir = Path.home() / ".config" / "verdandi" / "remote-jack-presets" / node_id[:8]
        else:
            # Local node
            self.presets_dir = Path.home() / ".config" / "skeleton-app" / "jack-presets"
        
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        
        # Per-node last preset tracking
        self.last_preset_map_file = Path.home() / ".config" / "verdandi" / "jack_last_presets.json"
        self.last_preset_map_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Model
        self.model = GraphModel()
        
        # Preset positions to apply
        self._preset_positions = {}
        self.current_preset_name = None  # Track currently loaded preset
        
        # View
        layout = QVBoxLayout(self)
        
        # Controls
        controls = QHBoxLayout()
        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self.refresh_from_jack)
        controls.addWidget(btn_refresh)
        
        controls.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        controls.addWidget(self.preset_combo)
        
        btn_save = QPushButton("💾 Save")
        btn_save.clicked.connect(self._save_preset)
        controls.addWidget(btn_save)
        
        btn_load = QPushButton("📁 Load")
        btn_load.clicked.connect(self._load_preset)
        controls.addWidget(btn_load)
        
        controls.addStretch()
        layout.addLayout(controls)
        
        # Canvas
        self.canvas = GraphCanvas(self.model)
        layout.addWidget(self.canvas)
        
        # Add keyboard shortcut for Ctrl+S to save preset
        from PySide6.QtGui import QShortcut, QKeySequence
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self._save_preset)
        
        # Auto-refresh - DISABLED (interferes with dragging)
        # Use manual Refresh button instead
        # self._timer = QTimer(self)
        # self._timer.timeout.connect(self.refresh_from_jack)
        # self._timer.start(2000)
        
        # Only auto-refresh and load preset if we have a jack_manager (local canvas)
        # Remote canvases will be populated manually and then load preset
        if jack_manager:
            self.refresh_from_jack()
            self._load_last_preset()
        
        self._refresh_preset_list()
    
    def set_jack_manager(self, jack_manager: Optional[JackClientManager]):
        """Set or update the JACK manager."""
        self.jack_manager = jack_manager
        if jack_manager:
            self.refresh_from_jack()
            # Load last preset now that we have data
            self._load_last_preset()
    
    def refresh_from_jack(self):
        """Update model from JACK state."""
        if not self.jack_manager:
            # For remote canvases, emit signal to trigger remote refresh
            if hasattr(self, 'remote_refresh_requested'):
                self.remote_refresh_requested.emit()
            return
        try:
            # Get JACK data - include both audio and MIDI ports
            all_ports = self.jack_manager.get_ports()  # Get all ports (audio + MIDI)
            output_ports = set(self.jack_manager.get_ports(is_output=True))  # All outputs
            connections_dict = self.jack_manager.get_all_connections()
            
            # Preserve existing node positions (prefer preset positions if available)
            old_positions = {name: (node.x, node.y) for name, node in self.model.nodes.items()}
            # Merge with preset positions (preset takes priority)
            if self._preset_positions:
                old_positions.update(self._preset_positions)
                self._preset_positions = {}  # Clear after use
            
            # Batch update - only emit changed once at the end
            self.model.begin_batch()
            
            # Clear model
            self.model.clear()
            
            # Group ports by client and detect MIDI ports
            clients = {}
            
            # Detect MIDI ports by checking each port's type
            midi_ports = set()
            for port_name in all_ports:
                try:
                    port_obj = self.jack_manager.client.get_port_by_name(port_name)
                    if port_obj.is_midi:
                        midi_ports.add(port_name)
                except Exception as e:
                    logger.warning(f"Error checking port type for {port_name}: {e}")
            
            print(f"DEBUG: Total ports: {len(all_ports)}, MIDI ports: {len(midi_ports)}")
            if midi_ports:
                print(f"DEBUG: Sample MIDI ports: {list(midi_ports)[:3]}")
            
            for port_name in all_ports:
                if ':' not in port_name:
                    continue
                client_name = port_name.split(':')[0]
                port_short = ':'.join(port_name.split(':')[1:])
                if client_name not in clients:
                    clients[client_name] = []
                is_output = port_name in output_ports
                is_midi = port_name in midi_ports
                clients[client_name].append((port_short, port_name, is_output, is_midi))
            
            # Create nodes with auto-layout (but restore old positions if available)
            x, y = 50, 50
            for client_name, ports in clients.items():
                if client_name == "system":
                    # Split system
                    capture_ports = [(s, f, m) for s, f, _, m in ports if "capture" in s]
                    playback_ports = [(s, f, m) for s, f, _, m in ports if "playback" in s]
                    
                    if capture_ports:
                        node_name = "system (capture)"
                        saved_x, saved_y = old_positions.get(node_name, (x, y))
                        node = self.model.add_node(node_name, saved_x, saved_y)
                        for port_short, port_full, is_midi in capture_ports:
                            node.outputs.append(PortModel(port_short, port_full, True, is_midi))
                        y += 150
                    
                    if playback_ports:
                        node_name = "system (playback)"
                        saved_x, saved_y = old_positions.get(node_name, (x, y))
                        node = self.model.add_node(node_name, saved_x, saved_y)
                        for port_short, port_full, is_midi in playback_ports:
                            node.inputs.append(PortModel(port_short, port_full, False, is_midi))
                        y += 150
                
                elif client_name.startswith("a2j"):
                    # Split a2j (MIDI bridge) clients into capture (sources) and playback (sinks)
                    capture_ports = [(s, f, m) for s, f, is_out, m in ports if is_out]
                    playback_ports = [(s, f, m) for s, f, is_out, m in ports if not is_out]
                    
                    if capture_ports:
                        node_name = f"{client_name} (capture)"
                        saved_x, saved_y = old_positions.get(node_name, (x, y))
                        node = self.model.add_node(node_name, saved_x, saved_y)
                        for port_short, port_full, is_midi in capture_ports:
                            node.outputs.append(PortModel(port_short, port_full, True, is_midi))
                        y += 150
                    
                    if playback_ports:
                        node_name = f"{client_name} (playback)"
                        saved_x, saved_y = old_positions.get(node_name, (x, y))
                        node = self.model.add_node(node_name, saved_x, saved_y)
                        for port_short, port_full, is_midi in playback_ports:
                            node.inputs.append(PortModel(port_short, port_full, False, is_midi))
                        y += 150
                
                else:
                    saved_x, saved_y = old_positions.get(client_name, (x, y))
                    node = self.model.add_node(client_name, saved_x, saved_y)
                    for port_short, port_full, is_output, is_midi in ports:
                        if is_output:
                            node.outputs.append(PortModel(port_short, port_full, True, is_midi))
                        else:
                            node.inputs.append(PortModel(port_short, port_full, False, is_midi))
                    
                    x += 200
                    if x > 800:
                        x = 50
                        y += 150
            
            # Add connections
            for out_port, in_ports in connections_dict.items():
                for in_port in in_ports:
                    self.model.add_connection(out_port, in_port)
            
            # End batch - trigger single rebuild
            self.model.end_batch()
        
        except Exception as e:
            logger.error(f"Error refreshing from JACK: {e}", exc_info=True)
    
    def _get_last_preset_for_node(self) -> Optional[str]:
        """Get the last used preset name for this node."""
        try:
            if self.last_preset_map_file.exists():
                with open(self.last_preset_map_file, 'r') as f:
                    preset_map = json.load(f)
                    return preset_map.get(self.node_id)
        except Exception as e:
            logger.error(f"Failed to read last preset map: {e}")
        return None
    
    def _set_last_preset_for_node(self, preset_name: str):
        """Store the last used preset name for this node."""
        try:
            preset_map = {}
            if self.last_preset_map_file.exists():
                with open(self.last_preset_map_file, 'r') as f:
                    preset_map = json.load(f)
            
            preset_map[self.node_id] = preset_name
            
            with open(self.last_preset_map_file, 'w') as f:
                json.dump(preset_map, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write last preset map: {e}")
    
    def _save_preset(self):
        # Prepopulate with current preset name if available
        default_name = self.current_preset_name or ""
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", text=default_name)
        if ok and name:
            data = {
                "name": name,
                "connections": {c.output_port: [c.input_port] for c in self.model.connections},
                "positions": {n.name: (n.x, n.y) for n in self.model.nodes.values()},
                "aliases": self.model.aliases.copy()  # Save client aliases
            }
            
            path = self.presets_dir / f"{name}.json"
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Mark as current and last used preset for this node
            self.current_preset_name = name
            self._set_last_preset_for_node(name)
            
            self._refresh_preset_list()
            # Update combo box to show current preset
            idx = self.preset_combo.findText(name)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
            QMessageBox.information(self, "Success", f"Preset '{name}' saved!")
    
    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        
        path = self.presets_dir / f"{name}.json"
        if not path.exists():
            return
        
        with open(path, 'r') as f:
            data = json.load(f)
        
        # Store positions to be applied during next refresh
        self._preset_positions = data.get("positions", {})
        
        # Load aliases
        self.model.aliases = data.get("aliases", {})
        
        # Apply positions immediately to existing nodes
        for node_name, (x, y) in self._preset_positions.items():
            if node_name in self.model.nodes:
                self.model.move_node(node_name, x, y)
        
        # Apply connections (only if jack_manager available)
        if self.jack_manager:
            for out_port, in_ports in data.get("connections", {}).items():
                for in_port in in_ports:
                    try:
                        self.jack_manager.connect_ports(out_port, in_port)
                    except:
                        pass
        
        # Mark as current and last used preset for this node
        self.current_preset_name = name
        self._set_last_preset_for_node(name)
        
        # Refresh if jack_manager available, otherwise trigger view rebuild
        if self.jack_manager:
            self.refresh_from_jack()
        else:
            # For remote canvases without jack_manager, just rebuild the view
            self.model.changed.emit()
        
        QMessageBox.information(self, "Success", f"Preset '{name}' loaded!")
    
    def _refresh_preset_list(self):
        current = self.preset_combo.currentText()
        self.preset_combo.clear()
        
        presets = [p.stem for p in self.presets_dir.glob("*.json")]
        presets.sort()
        self.preset_combo.addItems(presets)
        
        idx = self.preset_combo.findText(current)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
    
    def _load_last_preset(self):
        """Automatically load the last used preset for this node."""
        try:
            # Get last preset name for this specific node
            last_preset_name = self._get_last_preset_for_node()
            
            if not last_preset_name:
                return
            
            # Check if preset still exists
            preset_path = self.presets_dir / f"{last_preset_name}.json"
            if not preset_path.exists():
                return
            
            # Select it in combo box
            idx = self.preset_combo.findText(last_preset_name)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
                # Load it silently (no message box)
                self._load_preset_silent(last_preset_name)
        except Exception as e:
            logger.debug(f"Could not load last preset: {e}")
    
    def _load_preset_silent(self, name: str):
        """Load preset without showing message box."""
        path = self.presets_dir / f"{name}.json"
        if not path.exists():
            return
        
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            
            # Store positions to be applied during next refresh
            self._preset_positions = data.get("positions", {})
            
            # Load aliases
            self.model.aliases = data.get("aliases", {})
            
            # Apply positions immediately to existing nodes
            for node_name, (x, y) in self._preset_positions.items():
                if node_name in self.model.nodes:
                    self.model.move_node(node_name, x, y)
            
            # Apply connections (only if jack_manager available)
            if self.jack_manager:
                for out_port, in_ports in data.get("connections", {}).items():
                    for in_port in in_ports:
                        try:
                            self.jack_manager.connect_ports(out_port, in_port)
                        except:
                            pass
            
            # Mark as current preset
            self.current_preset_name = name
            
            # Refresh if jack_manager available, otherwise trigger view rebuild
            if self.jack_manager:
                self.refresh_from_jack()
            else:
                # For remote canvases without jack_manager, just rebuild the view
                self.model.changed.emit()
            
            logger.info(f"Auto-loaded preset '{name}' for node {self.node_id}")
        except Exception as e:
            logger.error(f"Error loading preset: {e}")


# Alias for Verdandi integration
JackCanvas = NodeCanvasWidget


# ============================================================================
# JackCanvasWidget - Wrapper with JackTrip controls
# ============================================================================

class JackCanvasWithControls(QWidget):
    """Wrapper for JackCanvas with JackTrip hub/client controls."""
    
    hub_started = Signal()  # Emitted when hub starts (for coordination)
    
    def __init__(self, jack_manager=None, parent=None, node_id=None, is_remote=False, remote_node=None):
        super().__init__(parent)
        self.jack_manager = jack_manager
        self.node_id = node_id
        self.is_remote = is_remote
        self.remote_node = remote_node  # Node object for remote operations
        
        # State tracking
        self.hub_running = False
        self.client_connected = False
        self.hub_host = None
        self.hub_port = 4464
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Control panel
        controls = self._create_control_panel()
        layout.addWidget(controls)
        
        # Canvas - pass node_id and remote_node for remote connections
        self.canvas = NodeCanvasWidget(
            jack_manager=jack_manager, 
            parent=self, 
            node_id=node_id,
            remote_node=remote_node
        )
        layout.addWidget(self.canvas)
    
    def sync_hub_state(self):
        """Sync hub button state with current global hub state."""
        # Check if any hub is running by looking at parent's state
        if self.parent() and hasattr(self.parent(), '_is_any_hub_running'):
            if self.parent()._is_any_hub_running():
                self.start_hub_btn.setEnabled(False)
        
    def _create_control_panel(self):
        """Create JackTrip control panel."""
        panel = QWidget()
        panel.setStyleSheet("QWidget { background: #2a2a2a; padding: 5px; }")
        layout = QHBoxLayout(panel)
        
        # Title
        title = "Local JackTrip Controls" if not self.is_remote else f"Remote JackTrip Controls"
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        
        # Hub controls
        layout.addWidget(QLabel("Hub:"))
        self.start_hub_btn = QPushButton("▶️ Start Hub")
        self.start_hub_btn.clicked.connect(self._on_start_hub)
        layout.addWidget(self.start_hub_btn)
        
        self.stop_hub_btn = QPushButton("⏹️ Stop Hub")
        self.stop_hub_btn.clicked.connect(self._on_stop_hub)
        self.stop_hub_btn.setEnabled(False)
        layout.addWidget(self.stop_hub_btn)
        
        layout.addWidget(QLabel("|"))
        
        # Client controls
        layout.addWidget(QLabel("Client:"))
        self.connect_client_btn = QPushButton("🔌 Connect to Hub")
        self.connect_client_btn.clicked.connect(self._on_connect_client)
        layout.addWidget(self.connect_client_btn)
        
        self.disconnect_client_btn = QPushButton("❌ Disconnect")
        self.disconnect_client_btn.clicked.connect(self._on_disconnect_client)
        self.disconnect_client_btn.setEnabled(False)
        layout.addWidget(self.disconnect_client_btn)
        
        layout.addWidget(QLabel("|"))
        
        # Status
        self.status_label = QLabel("Status: <i>Idle</i>")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        return panel
    
    def _on_start_hub(self):
        """Start JackTrip hub server."""
        from PySide6.QtWidgets import QDialog, QFormLayout, QSpinBox, QDialogButtonBox
        
        # Configuration dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Start JackTrip Hub")
        layout = QFormLayout(dialog)
        
        layout.addRow(QLabel("<b>Hub Server Configuration</b>"))
        layout.addRow(QLabel("Clients will connect to this hub to share audio."))
        layout.addRow(QLabel("Each client will specify their own send/receive channels."))
        
        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        port_spin.setValue(4464)
        layout.addRow("Port:", port_spin)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() != QDialog.Accepted:
            return
        
        port = port_spin.value()
        
        try:
            if self.is_remote:
                # Start hub on remote node via gRPC
                from verdandi_hall.grpc_client import VerdandiGrpcClient
                with VerdandiGrpcClient(self.remote_node, timeout=30) as client:
                    response = client.start_jacktrip_hub(
                        send_channels=2,  # Default, clients will specify their own
                        receive_channels=2,
                        sample_rate=48000,
                        buffer_size=256,
                        port=port
                    )
                location = f"on {self.remote_node.hostname}"
            else:
                # Start hub locally via subprocess
                import subprocess
                cmd = [
                    "jacktrip", "-S",
                    "--bindport", str(port)
                ]
                try:
                    # Start process and capture output for error checking
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    # Give it a moment to fail if there's an immediate error
                    import time
                    time.sleep(0.5)
                    poll = proc.poll()
                    if poll is not None:
                        # Process died, get error
                        _, stderr = proc.communicate()
                        raise Exception(f"JackTrip hub failed to start: {stderr.decode()}")
                    location = "locally"
                except Exception as e:
                    raise Exception(f"Failed to start local hub: {e}")
            
            self.hub_running = True
            self.hub_port = port
            self.start_hub_btn.setEnabled(False)
            self.stop_hub_btn.setEnabled(True)
            self.status_label.setText(f"Status: <b style='color: #6f6'>Hub Running</b> (port {port})")
            
            # Emit signal to coordinate with other control panels
            self.hub_started.emit()
            
            QMessageBox.information(self, "Hub Started", 
                                  f"JackTrip hub server started {location} on port {port}.\n"
                                  f"Clients can now connect.")
            
            # Refresh canvas after a moment to show new JACK client
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, self.canvas.refresh_from_jack)
            
        except Exception as e:
            logger.error(f"Failed to start hub: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to start hub: {e}")
    
    def _on_stop_hub(self):
        """Stop JackTrip hub server."""
        try:
            if self.is_remote:
                # Stop hub on remote node via gRPC
                from verdandi_hall.grpc_client import VerdandiGrpcClient
                with VerdandiGrpcClient(self.remote_node, timeout=30) as client:
                    response = client.stop_jacktrip_hub()
                location = f"on {self.remote_node.hostname}"
            else:
                # Stop hub locally
                import subprocess
                subprocess.run(["pkill", "-f", "jacktrip.*-S"], check=False)
                location = "locally"
            
            self.hub_running = False
            self.start_hub_btn.setEnabled(True)
            self.stop_hub_btn.setEnabled(False)
            self.status_label.setText("Status: <i>Idle</i>")
            
            QMessageBox.information(self, "Hub Stopped", f"JackTrip hub server stopped {location}.")
            
            # Refresh canvas
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, self.canvas.refresh_from_jack)
            
        except Exception as e:
            logger.error(f"Failed to stop hub: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to stop hub: {e}")
    
    def _on_connect_client(self):
        """Connect as client to a hub."""
        from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox
        from verdandi_codex.database import Database
        from verdandi_codex.models.identity import Node
        
        # Configuration dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Connect to JackTrip Hub")
        layout = QFormLayout(dialog)
        
        layout.addRow(QLabel("<b>Client Configuration</b>"))
        layout.addRow(QLabel("Connect to a running JackTrip hub server."))
        
        # Get list of nodes from database
        host_combo = QComboBox()
        try:
            db = Database()
            session = db.get_session()
            nodes = session.query(Node).order_by(Node.hostname).all()
            session.close()
            
            # Populate combo box with nodes
            for node in nodes:
                display_text = f"{node.hostname} ({node.ip_last_seen})"
                host_combo.addItem(display_text, node.ip_last_seen)  # Store IP as user data
            
            if host_combo.count() == 0:
                host_combo.addItem("No nodes registered", None)
        except Exception as e:
            logger.error(f"Failed to load nodes: {e}")
            host_combo.addItem("Error loading nodes", None)
        
        layout.addRow("Hub Host:", host_combo)
        
        port_spin = QSpinBox()
        port_spin.setRange(1024, 65535)
        port_spin.setValue(4464)
        layout.addRow("Hub Port:", port_spin)
        
        send_channels_spin = QSpinBox()
        send_channels_spin.setRange(1, 8)
        send_channels_spin.setValue(2)
        layout.addRow("Send Channels (to hub):", send_channels_spin)
        
        receive_channels_spin = QSpinBox()
        receive_channels_spin.setRange(1, 8)
        receive_channels_spin.setValue(2)
        layout.addRow("Receive Channels (from hub):", receive_channels_spin)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() != QDialog.Accepted:
            return
        
        host = host_combo.currentData()  # Get IP from selected node
        if not host:
            QMessageBox.warning(self, "Invalid Input", "Please enter a hub host address.")
            return
        
        port = port_spin.value()
        send_channels = send_channels_spin.value()
        receive_channels = receive_channels_spin.value()
        
        try:
            if self.is_remote:
                # Start client on remote node via gRPC
                from verdandi_hall.grpc_client import VerdandiGrpcClient
                with VerdandiGrpcClient(self.remote_node, timeout=30) as client:
                    response = client.start_jacktrip_client(
                        hub_address=host,
                        hub_port=port,
                        send_channels=send_channels,
                        receive_channels=receive_channels,
                        sample_rate=48000,
                        buffer_size=256
                    )
                location = f"on {self.remote_node.hostname}"
            else:
                # Start client locally via subprocess
                import subprocess
                import socket
                
                # Try to resolve hostname from IP, fallback to hostname portion
                try:
                    # If host is IP, try reverse DNS lookup
                    if host.replace('.', '').replace(':', '').isdigit() or ':' in host:
                        client_name = socket.gethostbyaddr(host)[0].split('.')[0]
                    else:
                        client_name = host.split('.')[0]
                except:
                    # Fallback: just use first part
                    client_name = host.split('.')[0] if '.' in host else host
                
                # Get local hostname to tell the hub who we are
                local_hostname = socket.gethostname().split('.')[0]
                
                cmd = [
                    "jacktrip", "-C", host,
                    "--bindport", str(port),
                    "--sendchannels", str(send_channels),
                    "--receivechannels", str(receive_channels),
                    "--clientname", client_name,
                    "--remotename", local_hostname  # Tell hub to name us by our hostname
                ]
                try:
                    # Start process and capture output for error checking
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    # Give it a moment to fail if there's an immediate error
                    import time
                    time.sleep(0.5)
                    poll = proc.poll()
                    if poll is not None:
                        # Process died, get error
                        _, stderr = proc.communicate()
                        raise Exception(f"JackTrip client failed to connect: {stderr.decode()}")
                    location = "locally"
                except Exception as e:
                    raise Exception(f"Failed to start local client: {e}")
            
            self.client_connected = True
            self.hub_host = host
            self.hub_port = port
            self.connect_client_btn.setEnabled(False)
            self.disconnect_client_btn.setEnabled(True)
            self.status_label.setText(f"Status: <b style='color: #6f6'>Connected</b> to {host}:{port}")
            
            QMessageBox.information(self, "Client Connected", 
                                  f"JackTrip client {location} connected to {host}:{port}.")
            
            # Refresh canvas after a moment to show new JACK client
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, self.canvas.refresh_from_jack)
            
        except Exception as e:
            logger.error(f"Failed to connect client: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to connect client: {e}")
    
    def _on_disconnect_client(self):
        """Disconnect client from hub."""
        try:
            if self.is_remote:
                # Stop client on remote node via gRPC
                from verdandi_hall.grpc_client import VerdandiGrpcClient
                with VerdandiGrpcClient(self.remote_node, timeout=30) as client:
                    response = client.stop_jacktrip_client()
                location = f"on {self.remote_node.hostname}"
            else:
                # Stop client locally
                import subprocess
                subprocess.run(["pkill", "-f", "jacktrip.*-C"], check=False)
                location = "locally"
            
            self.client_connected = False
            self.hub_host = None
            self.connect_client_btn.setEnabled(True)
            self.disconnect_client_btn.setEnabled(False)
            self.status_label.setText("Status: <i>Idle</i>")
            
            QMessageBox.information(self, "Client Disconnected", 
                                  f"JackTrip client {location} disconnected.")
            
            # Refresh canvas
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, self.canvas.refresh_from_jack)
            
        except Exception as e:
            logger.error(f"Failed to disconnect client: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to disconnect client: {e}")
    
    def set_jack_manager(self, jack_manager):
        """Set the JACK manager for the canvas."""
        self.jack_manager = jack_manager
        self.canvas.set_jack_manager(jack_manager)
