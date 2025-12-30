# Canvas and Node GUI Implementation Notes

Reference: `/home/sysadmin/Programs/skeleton-crew/src/skeleton_app/gui/widgets/`

## Key Files to Reuse

### 1. `node_canvas_v3.py` (974 lines)
**Purpose:** Complete canvas-and-node system with Model-View separation

**Key Components:**
- `GraphModel` - Pure data model (QObject with signals)
  - Manages nodes, connections, aliases
  - Emits `changed` signal for updates
  - Batch mode for efficient bulk updates

- `NodeModel` - Data class for a JACK client
  - name, inputs, outputs, x, y position
  
- `PortModel` - Data class for ports
  - name, full_name, is_output, is_midi flags
  
- `ConnectionModel` - Data class for connections
  - output_port, input_port (full names)

- `NodeGraphicsItem` - QGraphicsItem for rendering nodes
  - Auto-sizing based on content
  - Color-coded by port type (audio=blue, MIDI=red, mixed=purple)
  - Draggable with `ItemIsMovable | ItemIsSelectable | ItemSendsScenePositionChanges`
  - Socket rendering for ports
  - Text rendering with aliases
  
- `ConnectionGraphicsItem` - QGraphicsItem for connections
  - Curved bezier paths between sockets
  - Different colors for audio vs MIDI
  
- `GraphCanvas` - QGraphicsView container
  - Pan/zoom support
  - Drag-to-connect functionality
  - Node auto-layout algorithms
  - JSON save/load of positions and aliases

**Features:**
- ✓ Drag nodes to reposition
- ✓ Drag from output port to input port to create connections
- ✓ Auto-layout with force-directed or grid algorithms
- ✓ Color-coding for audio/MIDI/mixed nodes
- ✓ Port aliasing (rename nodes)
- ✓ Save/load canvas state to JSON
- ✓ Proper bounding rect calculations (no rendering artifacts)

### 2. `patchbay_widget.py` (320 lines)
**Purpose:** Complete JACK patchbay widget integrating the canvas

**Key Components:**
- Integrates `GraphCanvas` with live JACK data
- Auto-refresh timer to poll JACK state
- Buttons for layout, save, load
- Connection creation/deletion via drag or button

### 3. `remote_node_canvas.py`
**Purpose:** Canvas for visualizing remote nodes in a cluster

**Use Case:** Similar to what we need for the Verdandi fabric graph

## Implementation Strategy for Verdandi

### Phase 1: Local JACK Graph Viewer
**Location:** `verdandi_hall/widgets/jack_canvas.py`

1. Adapt `GraphModel`, `NodeModel`, `PortModel` from skeleton-crew
2. Use `NodeGraphicsItem` and `ConnectionGraphicsItem` as-is
3. Integrate with `JackConnectionManager` to get real-time port data
4. Add to Verdandi Hall as a tab

### Phase 2: Fabric Graph Viewer  
**Location:** `verdandi_hall/widgets/fabric_canvas.py`

1. Create `FabricGraphModel` based on `GraphModel`
2. Create `FabricNodeItem` (similar to `NodeGraphicsItem` but for Verdandi nodes)
   - Show node hostname, capabilities, status
   - Show JackTrip/RTP-MIDI links as edges
3. Create `FabricLinkItem` (similar to `ConnectionGraphicsItem`)
   - Show audio vs MIDI links with different colors
   - Show link status (UP, DOWN, DESIRED_UP)
4. Real-time updates from database FabricLink/FabricGraph tables
5. Drag-to-create links (calls gRPC CreateAudioLink/CreateMidiLink)

### Phase 3: Integrated View
**Location:** `verdandi_hall/widgets/integrated_view.py`

- Multi-panel view:
  - Top: Fabric graph (nodes in LAN)
  - Bottom: Selected node's JACK graph
- Click a node in fabric graph → show its JACK ports below
- Drag from JACK port on node A to JACK port on node B → create JackTrip link

## Code Reuse Strategy

**Copy these files directly:**
```bash
cp skeleton-crew/src/skeleton_app/gui/widgets/node_canvas_v3.py \
   verdandi/verdandi_hall/widgets/
```

**Adapt for Verdandi:**
1. Change data source from `JackClientManager` to `JackConnectionManager`
2. Add gRPC calls for link creation
3. Add database integration for fabric graph
4. Keep all the rendering logic intact (it works!)

## Key Lessons from skeleton-crew

1. **Model-View Separation is Critical**
   - Pure data classes separate from Qt rendering
   - Makes testing and data persistence easy
   
2. **Bounding Rect Must Be Generous**
   - Include socket radius + margin in boundingRect
   - Prevents rendering artifacts during drag
   
3. **Use Correct Item Flags**
   ```python
   ItemIsMovable | ItemIsSelectable | ItemSendsScenePositionChanges
   ```
   
4. **Disable Caching During Drag**
   ```python
   setCacheMode(QGraphicsItem.NoCache)
   ```
   
5. **Color Coding is Essential**
   - Audio ports: Blue
   - MIDI ports: Purple/Magenta
   - Mixed nodes: Purple-gray
   
6. **Auto-Layout Algorithms**
   - Force-directed: organic, good for small graphs
   - Grid: clean, good for large graphs
   - Circular: good for star topologies

## Next Steps When Implementing GUI

1. Create `verdandi_hall/widgets/` directory
2. Copy `node_canvas_v3.py` as starting point
3. Create `jack_canvas.py` integrating with our JackConnectionManager
4. Test with single node first
5. Extend to fabric_canvas.py for multi-node view
6. Add to main Verdandi Hall window

## Dependencies
```python
# Already in pyproject.toml under gui extras
PySide6>=6.6.0
```

## Testing Strategy
See skeleton-crew test files:
- `test_drag.py` - Basic drag functionality
- `test_our_node.py` - Node rendering
- `test_thread_safety.py` - Concurrent updates

All the hard work of making canvas-and-node GUI work properly has been done in skeleton-crew. We can reuse 80%+ of the code!
