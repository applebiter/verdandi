# Fabric Link Orchestration

## Architecture Overview

The Verdandi fabric network uses a **desired state** architecture:

1. **GUI (verdandi-hall)**: User creates link nodes and connects wires → Writes desired state to database
2. **Daemon (verdandi-engine)**: Monitors database → Spawns/terminates JackTrip processes to match desired state
3. **Database**: Central source of truth shared across all nodes

## Workflow Example: Creating a P2P Audio Link

### Step 1: User Creates Link Node (GUI)
- User clicks "Add Link Node" → Dialog appears
- Selects P2P mode, 2 send channels, 2 receive channels
- Link created in database:
  ```
  status = DESIRED_DOWN
  _unconnected = true
  source_node_id = None
  target_node_id = None
  ```

### Step 2: User Connects Source (GUI)
- User drags wire from fabric node (e.g., "onyx") output → Link node input
- GUI updates database:
  ```
  source_node_id = "onyx-node-id"
  ```
  - Still `status = DESIRED_DOWN` (not ready yet)

### Step 3: User Connects Target (GUI)
- User drags wire from link node output → Another fabric node (e.g., "karate") input
- GUI updates database:
  ```
  target_node_id = "karate-node-id"
  _unconnected = false  (removed)
  status = DESIRED_UP   (ready to activate!)
  ```

### Step 4: Daemon Spawns JackTrip (Both Nodes)
**On source node (onyx):**
- Fabric orchestrator polls database every 2 seconds
- Sees link with `status=DESIRED_UP`, `source_node_id=<our node>`
- Determines: "We should spawn the client"
- Looks up target node IP from database
- Spawns: `jacktrip -c <karate-ip> -n 2 --clientname verdandi_jacktrip_81981485`
- Updates database: `status = OBSERVED_UP`

**On target node (karate):**
- Fabric orchestrator polls database
- Sees same link but `source_node_id != <our node>`
- Determines: "Not our link to spawn"
- Waits for incoming connection (JackTrip server should be running separately)

### Step 5: Audio Flows
- JackTrip client on onyx connects to JackTrip server on karate
- JACK ports appear: `verdandi_jacktrip_81981485:send_1`, `send_2`, `receive_1`, `receive_2`
- Jack Connection Manager (separate component) wires these to fabric nodes
- Audio flows: onyx JACK output → JackTrip → Network → JackTrip → karate JACK input

### Step 6: User Disconnects (GUI)
- User right-clicks wire or presses Delete
- GUI updates database:
  ```
  source_node_id = None (or target_node_id = None)
  _unconnected = true
  status = DESIRED_DOWN
  ```

### Step 7: Daemon Terminates JackTrip
- Orchestrator sees `status=DESIRED_DOWN`
- Terminates JackTrip process
- JACK ports disappear
- Audio stops

## Hub Mode

### Hub Node Selection
When creating Hub mode link:
- User selects which node should be the hub from dropdown
- Stored as `hub_node_id` in params_json

### Client Spawning Logic
- All non-hub nodes spawn JackTrip clients that connect TO hub
- Hub node would spawn JackTrip server (not yet implemented)

## P2P Mode Details

### Who Spawns?
In P2P mode, the **source node** spawns the JackTrip client:
- Source = node sending audio TO the link
- Target = node receiving audio FROM the link
- Rationale: Source initiates connection, target accepts

### Network Topology
```
[Onyx JACK output] → [JackTrip client] → Network → [JackTrip server] → [Karate JACK input]
```

The target node needs a JackTrip server running separately (or qjacktrip in server mode).

## Database Schema

### FabricLink Table
```sql
link_id         UUID PRIMARY KEY
graph_id        UUID NOT NULL  -- FK to fabric_graphs
link_type       ENUM ('audio', 'midi')
node_a_id       UUID NOT NULL  -- Source node
node_b_id       UUID NOT NULL  -- Target node
status          ENUM ('DESIRED_UP', 'DESIRED_DOWN', 'OBSERVED_UP', 'OBSERVED_DOWN')
params_json     JSONB
```

### params_json Structure (P2P)
```json
{
  "mode": "P2P",
  "send_channels": 2,
  "receive_channels": 2,
  "sample_rate": 44100,
  "buffer_size": 256,
  "source_node_id": "e845a741-...",
  "target_node_id": "a1b2c3d4-...",
  "_unconnected": false,
  "x": 100,
  "y": 150
}
```

## Node Discovery

Nodes discover each other via:
1. **mDNS**: Automatic local network discovery (verdandi._tcp)
2. **Database**: Central registry of all known nodes
3. **IP persistence**: Last seen IP stored in `Node.ip_last_seen`

When spawning JackTrip, orchestrator looks up target node's IP from database.

## Fault Tolerance

### JackTrip Crashes
- Daemon monitors process via `_monitor_session()`
- If process exits unexpectedly → Updates `status = OBSERVED_DOWN`
- Orchestrator on next poll sees `DESIRED_UP != OBSERVED_DOWN` → Respawns

### Network Partition
- If nodes can't reach each other, JackTrip client fails to connect
- Process exits, marked OBSERVED_DOWN
- Orchestrator keeps retrying every 2 seconds until connection succeeds

### Database Down
- Daemon continues running in degraded mode
- Existing JackTrip processes keep running
- No new links can be created/modified

## Testing Workflow

1. **Start daemons on all nodes:**
   ```bash
   verdandi-engine  # Or systemd service
   ```

2. **Open GUI on any node:**
   ```bash
   verdandi-hall
   ```

3. **Create link node, connect wires**
4. **Check logs to see orchestration:**
   ```
   fabric_orchestrator_started
   spawning_jacktrip_for_link link_id=81981485 mode=P2P remote_host=192.168.1.50
   jacktrip_session_started link_id=81981485 pid=12345
   ```

5. **Verify JACK ports:**
   ```bash
   jack_lsp | grep verdandi
   ```

6. **Check database:**
   ```sql
   SELECT link_id, status, params_json->>'mode' FROM fabric_links;
   ```

## Future Enhancements

- **Hub server spawning**: Hub node spawns `jacktrip -s` server
- **Multi-client hub**: Support multiple clients connecting to one hub
- **Automatic port allocation**: Dynamic port assignment for multiple links
- **Quality monitoring**: Track latency, packet loss, buffer underruns
- **Auto-reconnect**: Exponential backoff for failed connections
- **Link health status**: Visual indicators in GUI
