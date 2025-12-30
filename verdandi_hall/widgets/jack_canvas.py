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
            # Get parent widget to access jack_manager
            if self.scene() and self.scene().views():
                view = self.scene().views()[0]
                parent = view.parent()
                while parent and not hasattr(parent, 'jack_manager'):
                    parent = parent.parent()
                
                if parent and parent.jack_manager:
                    try:
                        parent.jack_manager.disconnect_ports(self.conn.output_port, self.conn.input_port)
                        # Refresh to show removed connection
                        parent.refresh_from_jack()
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
        # Get parent widget to access jack_manager
        parent = self.parent()
        while parent and not hasattr(parent, 'jack_manager'):
            parent = parent.parent()
        
        if parent and parent.jack_manager:
            try:
                parent.jack_manager.connect_ports(output_port, input_port)
                # Refresh to show new connection
                parent.refresh_from_jack()
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
    
    def __init__(self, jack_manager: Optional[JackClientManager] = None, parent=None):
        super().__init__(parent)
        self.jack_manager = jack_manager
        self.presets_dir = Path.home() / ".config" / "skeleton-app" / "jack-presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        self.last_preset_file = self.presets_dir / ".last_preset"
        
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
        
        # Auto-refresh - DISABLED (interferes with dragging)
        # Use manual Refresh button instead
        # self._timer = QTimer(self)
        # self._timer.timeout.connect(self.refresh_from_jack)
        # self._timer.start(2000)
        
        self.refresh_from_jack()
        
        # Auto-load last used preset
        self._load_last_preset()
        self._refresh_preset_list()
    
    def set_jack_manager(self, jack_manager: Optional[JackClientManager]):
        """Set or update the JACK manager."""
        self.jack_manager = jack_manager
        if jack_manager:
            self.refresh_from_jack()
    
    def refresh_from_jack(self):
        """Update model from JACK state."""
        if not self.jack_manager:
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
            
            # Mark as current and last used preset
            self.current_preset_name = name
            with open(self.last_preset_file, 'w') as f:
                f.write(name)
            
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
        
        # Apply connections
        for out_port, in_ports in data.get("connections", {}).items():
            for in_port in in_ports:
                try:
                    self.jack_manager.connect_ports(out_port, in_port)
                except:
                    pass
        
        # Mark as current and last used preset
        self.current_preset_name = name
        with open(self.last_preset_file, 'w') as f:
            f.write(name)
        
        # Refresh will apply positions
        self.refresh_from_jack()
        
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
        """Automatically load the last used preset."""
        if not self.last_preset_file.exists():
            return
        
        try:
            with open(self.last_preset_file, 'r') as f:
                last_preset_name = f.read().strip()
            
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
            
            # Apply connections
            for out_port, in_ports in data.get("connections", {}).items():
                for in_port in in_ports:
                    try:
                        self.jack_manager.connect_ports(out_port, in_port)
                    except:
                        pass
            
            # Mark as current preset
            self.current_preset_name = name
            
            # Refresh will apply positions
            self.refresh_from_jack()
            
            logger.info(f"Auto-loaded preset '{name}'")
        except Exception as e:
            logger.error(f"Error loading preset: {e}")


# Alias for Verdandi integration
JackCanvas = NodeCanvasWidget
