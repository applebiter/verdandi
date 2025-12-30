"""
Fabric Link Orchestrator - monitors FabricLink table and spawns/terminates JackTrip processes.
"""
import asyncio
import structlog
import json
from typing import Set

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database
from verdandi_codex.models.fabric import FabricLink, LinkStatus, LinkType
from verdandi_codex.models.identity import Node
from .jacktrip_manager import JackTripManager

logger = structlog.get_logger()


class FabricOrchestrator:
    """
    Monitors FabricLink entries in database and orchestrates JackTrip processes.
    
    Each node runs this orchestrator independently. For P2P links, the node
    with source_node_id (sending audio TO the link) spawns the JackTrip client
    that connects to the target node.
    """
    
    def __init__(
        self,
        config: VerdandiConfig,
        database: Database,
        jacktrip_manager: JackTripManager
    ):
        self.config = config
        self.database = database
        self.jacktrip_manager = jacktrip_manager
        self.running = False
        self.active_links: Set[str] = set()  # link_ids we're managing
        
    async def start(self):
        """Start the orchestration loop."""
        self.running = True
        logger.info("fabric_orchestrator_started")
        
        while self.running:
            try:
                await self._orchestrate_links()
            except Exception as e:
                logger.error("fabric_orchestration_error", error=str(e), exc_info=True)
            
            # Poll every 2 seconds
            await asyncio.sleep(2)
    
    async def stop(self):
        """Stop the orchestration loop."""
        self.running = False
        logger.info("fabric_orchestrator_stopped")
    
    async def _orchestrate_links(self):
        """Main orchestration logic - check links and spawn/terminate as needed."""
        with self.database.get_session() as session:
            # Query all links in the Home graph
            from verdandi_codex.models.fabric import FabricGraph
            
            graph = session.query(FabricGraph).filter_by(name="Home").first()
            if not graph:
                return
            
            # Get all links for this graph
            links = session.query(FabricLink).filter_by(graph_id=graph.graph_id).all()
            
            # Track which links should be active
            desired_links = set()
            
            for link in links:
                link_id = str(link.link_id)
                
                # Parse params
                if isinstance(link.params_json, str):
                    params = json.loads(link.params_json)
                else:
                    params = link.params_json or {}
                
                # Skip if marked as unconnected (not ready yet)
                if params.get('_unconnected'):
                    continue
                
                # Only handle AUDIO_JACKTRIP links
                if link.link_type != LinkType.AUDIO_JACKTRIP:
                    continue
                
                # Check if link should be active (DESIRED_UP)
                if link.status == LinkStatus.DESIRED_UP or link.status == "DESIRED_UP":
                    desired_links.add(link_id)
                    
                    # Determine if THIS node should spawn the process
                    should_spawn = await self._should_spawn_for_link(link, params, session)
                    
                    if should_spawn and link_id not in self.active_links:
                        # Spawn JackTrip process
                        success = await self._spawn_link(link, params, session)
                        if success:
                            self.active_links.add(link_id)
                            # Update status to OBSERVED_UP
                            link.status = LinkStatus.OBSERVED_UP
                            session.commit()
                
                # Check if link should be terminated (DESIRED_DOWN)
                elif link.status == LinkStatus.DESIRED_DOWN or link.status == "DESIRED_DOWN":
                    if link_id in self.active_links:
                        # Terminate JackTrip process
                        await self._terminate_link(link_id)
                        self.active_links.remove(link_id)
            
            # Clean up any links that are no longer in database
            removed_links = self.active_links - desired_links - set(str(l.link_id) for l in links)
            for link_id in removed_links:
                await self._terminate_link(link_id)
                self.active_links.discard(link_id)
    
    async def _should_spawn_for_link(self, link: FabricLink, params: dict, session) -> bool:
        """
        Determine if THIS node should spawn the JackTrip process for this link.
        
        P2P mode: The source node (node_a_id / source_node_id) spawns the client
        Hub mode: Client nodes spawn clients, hub node spawns server
        """
        local_node_id = str(self.config.node.node_id)
        mode = params.get('mode', 'P2P')
        
        if mode == 'P2P':
            # In P2P, the source node spawns the client that connects to target
            source_node_id = params.get('source_node_id') or str(link.node_a_id)
            return source_node_id == local_node_id
        
        elif mode == 'HUB':
            # In Hub mode, determine if we're the hub or a client
            hub_node_id = params.get('hub_node_id')
            
            if not hub_node_id:
                logger.error("hub_link_missing_hub_node_id", link_id=str(link.link_id))
                return False
            
            # For now, we're implementing client mode only
            # Hub server spawning would be more complex (one server, many clients)
            # Client nodes connect TO the hub
            return local_node_id != hub_node_id
        
        return False
    
    async def _spawn_link(self, link: FabricLink, params: dict, session) -> bool:
        """Spawn JackTrip process for a link."""
        link_id = str(link.link_id)
        mode = params.get('mode', 'P2P')
        
        # Get connection details
        if mode == 'P2P':
            # Connect to the target node
            target_node_id = params.get('target_node_id') or str(link.node_b_id)
            target_node = session.query(Node).filter_by(node_id=target_node_id).first()
            
            if not target_node:
                logger.error("target_node_not_found", link_id=link_id, target_node_id=target_node_id)
                return False
            
            if not target_node.ip_last_seen:
                logger.error("target_node_no_ip", link_id=link_id, hostname=target_node.hostname)
                return False
            
            remote_host = target_node.ip_last_seen
            remote_port = target_node.daemon_port or 4464  # Default JackTrip UDP port
            
        elif mode == 'HUB':
            # Connect to the hub node
            hub_node_id = params.get('hub_node_id')
            hub_node = session.query(Node).filter_by(node_id=hub_node_id).first()
            
            if not hub_node:
                logger.error("hub_node_not_found", link_id=link_id, hub_node_id=hub_node_id)
                return False
            
            if not hub_node.ip_last_seen:
                logger.error("hub_node_no_ip", link_id=link_id, hostname=hub_node.hostname)
                return False
            
            remote_host = hub_node.ip_last_seen
            remote_port = hub_node.daemon_port or 4464
        
        else:
            logger.error("unknown_link_mode", link_id=link_id, mode=mode)
            return False
        
        # Get audio parameters
        send_channels = params.get('send_channels', params.get('channels', 2))
        receive_channels = params.get('receive_channels', params.get('channels', 2))
        # For now, use send_channels (we're sending TO remote)
        channels = send_channels
        
        sample_rate = params.get('sample_rate', 48000)
        buffer_size = params.get('buffer_size', 128)
        
        logger.info(
            "spawning_jacktrip_for_link",
            link_id=link_id,
            mode=mode,
            remote_host=remote_host,
            remote_port=remote_port,
            channels=channels
        )
        
        # Spawn JackTrip client
        success = await self.jacktrip_manager.create_audio_link(
            link_id=link_id,
            remote_host=remote_host,
            remote_port=remote_port,
            channels=channels,
            mode=mode.lower(),
            sample_rate=sample_rate,
            buffer_size=buffer_size
        )
        
        return success
    
    async def _terminate_link(self, link_id: str):
        """Terminate JackTrip process for a link."""
        logger.info("terminating_jacktrip_for_link", link_id=link_id)
        await self.jacktrip_manager.remove_audio_link(link_id)
